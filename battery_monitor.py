"""
電池監測工具 Battery Monitor
============================
功能：
1. 每隔指定秒數記錄電池狀態 + 鍵盤滑鼠活動量 + 網路流量到 CSV
2. 啟動本機 Web Server，開瀏覽器看即時圖表
3. 定時 git push CSV 到 GitHub，GitHub Pages 儀表板可遠端查看

用法：
  python battery_monitor.py                  # 預設每 60 秒記錄，每 5 分鐘推一次 GitHub
  python battery_monitor.py --interval 30    # 每 30 秒記錄一次
  python battery_monitor.py --push-interval 10  # 每 10 分鐘推一次 GitHub
  python battery_monitor.py --no-push        # 不推 GitHub

啟動後：
  本機：http://localhost:5678
  遠端：https://TJC-KM.github.io/battery-monitor/

需要安裝：pip install psutil pynput
"""

import psutil
import csv
import os
import sys
import json
import time
import argparse
import threading
import subprocess
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

# ============================================================
# 設定
# ============================================================
SCRIPT_DIR = Path(__file__).parent
CSV_FILE = SCRIPT_DIR / "battery_log.csv"
CSV_HEADERS = ["timestamp", "percent", "status", "plugged_in", "seconds_left", "power_watts",
               "kb_count", "mouse_count", "net_sent_mb", "net_recv_mb"]

# ============================================================
# 鍵盤滑鼠活動計數器
# ============================================================
kb_counter = 0
mouse_counter = 0
input_lock = threading.Lock()

def start_input_listeners():
    global kb_counter, mouse_counter
    try:
        from pynput import keyboard, mouse

        def on_key_press(key):
            global kb_counter
            with input_lock:
                kb_counter += 1

        def on_click(x, y, button, pressed):
            global mouse_counter
            if pressed:
                with input_lock:
                    mouse_counter += 1

        def on_scroll(x, y, dx, dy):
            global mouse_counter
            with input_lock:
                mouse_counter += 1

        def on_move(x, y):
            global mouse_counter
            with input_lock:
                mouse_counter += 1

        kb_listener = keyboard.Listener(on_press=on_key_press)
        kb_listener.daemon = True
        kb_listener.start()

        mouse_listener = mouse.Listener(on_click=on_click, on_scroll=on_scroll, on_move=on_move)
        mouse_listener.daemon = True
        mouse_listener.start()

        print("⌨️  鍵盤/滑鼠活動監聽已啟動")
        return True
    except ImportError:
        print("⚠️  pynput 未安裝，活動監測停用（pip install pynput）")
        return False

def get_and_reset_input_counts():
    global kb_counter, mouse_counter
    with input_lock:
        kb = kb_counter
        ms = mouse_counter
        kb_counter = 0
        mouse_counter = 0
    return kb, ms

# ============================================================
# 網路流量追蹤
# ============================================================
_last_net = psutil.net_io_counters()
_last_net_time = time.time()

def get_and_reset_net_usage():
    global _last_net, _last_net_time
    current = psutil.net_io_counters()
    sent_mb = round((current.bytes_sent - _last_net.bytes_sent) / 1024 / 1024, 2)
    recv_mb = round((current.bytes_recv - _last_net.bytes_recv) / 1024 / 1024, 2)
    _last_net = current
    _last_net_time = time.time()
    return sent_mb, recv_mb

# ============================================================
# 電池資料讀取
# ============================================================
def get_battery_info() -> dict:
    battery = psutil.sensors_battery()
    kb, ms = get_and_reset_input_counts()
    net_sent, net_recv = get_and_reset_net_usage()

    if battery is None:
        return {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "percent": -1, "status": "no_battery", "plugged_in": False,
            "seconds_left": -1, "power_watts": 0,
            "kb_count": kb, "mouse_count": ms,
            "net_sent_mb": net_sent, "net_recv_mb": net_recv
        }

    if battery.power_plugged:
        status = "charging" if battery.percent < 100 else "full"
    else:
        status = "discharging"

    secs = battery.secsleft
    if secs == psutil.POWER_TIME_UNLIMITED:
        secs = -1
    elif secs == psutil.POWER_TIME_UNKNOWN:
        secs = -2

    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "percent": battery.percent, "status": status,
        "plugged_in": battery.power_plugged, "seconds_left": secs,
        "power_watts": 0, "kb_count": kb, "mouse_count": ms,
        "net_sent_mb": net_sent, "net_recv_mb": net_recv
    }

# ============================================================
# CSV 記錄
# ============================================================
def init_csv():
    if not CSV_FILE.exists():
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()
    else:
        with open(CSV_FILE, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader, [])
        missing = [h for h in CSV_HEADERS if h not in headers]
        if missing:
            rows = []
            with open(CSV_FILE, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    for h in missing:
                        row.setdefault(h, "0")
                    rows.append(row)
            with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
                writer.writeheader()
                writer.writerows(rows)
            print(f"📄 已升級 CSV 格式（新增欄位：{', '.join(missing)}）")

def append_csv(info: dict):
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writerow(info)

# ============================================================
# Git Push
# ============================================================
def git_push():
    """把 CSV 推到 GitHub"""
    try:
        cwd = str(SCRIPT_DIR)
        # git add
        subprocess.run(["git", "add", "battery_log.csv"], cwd=cwd,
                       capture_output=True, text=True, timeout=30)
        # git commit
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        result = subprocess.run(
            ["git", "commit", "-m", f"📊 Battery data update {now}"],
            cwd=cwd, capture_output=True, text=True, timeout=30
        )
        if "nothing to commit" in result.stdout:
            return "skip"
        # git push
        result = subprocess.run(
            ["git", "push"],
            cwd=cwd, capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            return "ok"
        else:
            return f"error: {result.stderr[:200]}"
    except Exception as e:
        return f"error: {str(e)[:200]}"

def push_loop(interval_minutes: int):
    """定時推送到 GitHub"""
    print(f"🔄 每 {interval_minutes} 分鐘推送一次到 GitHub")
    while True:
        time.sleep(interval_minutes * 60)
        result = git_push()
        ts = datetime.now().strftime("%H:%M:%S")
        if result == "ok":
            print(f"  ☁️  {ts} Git push 成功")
        elif result == "skip":
            print(f"  ⏭️  {ts} 無新資料，跳過")
        else:
            print(f"  ❌ {ts} Git push 失敗：{result}")

# ============================================================
# Web Server
# ============================================================
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🔋 電池監測儀表板</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600;700&family=Noto+Sans+TC:wght@300;400;600;700&display=swap');
  * { margin: 0; padding: 0; box-sizing: border-box; }
  :root {
    --bg-primary: #0a0e17; --bg-card: #111827; --bg-card-hover: #1a2332;
    --border: #1e293b; --text-primary: #e2e8f0; --text-secondary: #94a3b8; --text-dim: #475569;
    --green: #22c55e; --green-dim: rgba(34,197,94,0.15);
    --yellow: #eab308; --yellow-dim: rgba(234,179,8,0.15);
    --red: #ef4444; --red-dim: rgba(239,68,68,0.15);
    --blue: #3b82f6; --blue-dim: rgba(59,130,246,0.15);
    --cyan: #06b6d4; --purple: #a855f7;
    --orange: #f97316; --pink: #ec4899;
  }
  body { font-family: 'Noto Sans TC','JetBrains Mono',sans-serif; background: var(--bg-primary); color: var(--text-primary); min-height: 100vh; }
  body::before { content:''; position:fixed; top:-50%; left:-50%; width:200%; height:200%; background: radial-gradient(circle at 30% 40%, rgba(34,197,94,0.03) 0%, transparent 50%), radial-gradient(circle at 70% 60%, rgba(59,130,246,0.03) 0%, transparent 50%); z-index:-1; animation: bgShift 20s ease-in-out infinite alternate; }
  @keyframes bgShift { to { transform: translate(5%, 3%); } }
  .container { max-width: 1200px; margin: 0 auto; padding: 24px; }
  .header { display:flex; justify-content:space-between; align-items:center; margin-bottom:28px; padding-bottom:20px; border-bottom:1px solid var(--border); }
  .header h1 { font-size:1.6rem; font-weight:700; }
  .header h1 span { color: var(--green); }
  .header-meta { font-family:'JetBrains Mono',monospace; font-size:0.8rem; color:var(--text-dim); }
  .live-dot { display:inline-block; width:8px; height:8px; background:var(--green); border-radius:50%; margin-right:6px; animation: pulse 2s ease-in-out infinite; }
  @keyframes pulse { 0%,100%{ opacity:1; box-shadow:0 0 0 0 rgba(34,197,94,0.4); } 50%{ opacity:0.7; box-shadow:0 0 0 6px rgba(34,197,94,0); } }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:14px; margin-bottom:28px; }
  .card { background:var(--bg-card); border:1px solid var(--border); border-radius:12px; padding:18px; transition:all .3s; }
  .card:hover { background:var(--bg-card-hover); transform:translateY(-2px); }
  .card-label { font-size:.7rem; color:var(--text-dim); text-transform:uppercase; letter-spacing:1px; margin-bottom:6px; }
  .card-value { font-family:'JetBrains Mono',monospace; font-size:1.6rem; font-weight:700; line-height:1; }
  .card-sub { font-size:.75rem; color:var(--text-secondary); margin-top:5px; }
  .battery-bar-container { background:var(--bg-card); border:1px solid var(--border); border-radius:12px; padding:20px; margin-bottom:28px; }
  .battery-bar-header { display:flex; justify-content:space-between; margin-bottom:12px; }
  .battery-bar-track { height:28px; background:#1e293b; border-radius:14px; overflow:hidden; }
  .battery-bar-fill { height:100%; border-radius:14px; transition: width 1s ease, background 1s ease; position:relative; overflow:hidden; }
  .battery-bar-fill::after { content:''; position:absolute; top:0; left:-100%; width:200%; height:100%; background:linear-gradient(90deg,transparent,rgba(255,255,255,0.1),transparent); animation:shimmer 3s infinite; }
  @keyframes shimmer { to { left:100%; } }
  .chart-container { background:var(--bg-card); border:1px solid var(--border); border-radius:12px; padding:20px; position:relative; margin-bottom:20px; }
  .chart-wrapper { position:relative; height:260px; }
  .chart-wrapper canvas { width:100%!important; height:100%!important; }
  .chart-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; flex-wrap:wrap; gap:8px; }
  .chart-title { font-size:1rem; font-weight:600; }
  .chart-legend { display:flex; gap:14px; font-size:.72rem; color:var(--text-secondary); margin-bottom:6px; }
  .chart-legend span::before { content:''; display:inline-block; width:12px; height:3px; border-radius:2px; margin-right:5px; vertical-align:middle; }
  .legend-battery::before { background:var(--blue); } .legend-keyboard::before { background:var(--cyan); }
  .legend-mouse::before { background:var(--purple); } .legend-download::before { background:var(--orange); }
  .legend-upload::before { background:var(--pink); }
  .chart-range-btns button { font-family:'JetBrains Mono',monospace; font-size:.7rem; padding:4px 12px; border:1px solid var(--border); background:transparent; color:var(--text-secondary); border-radius:6px; cursor:pointer; margin-left:6px; transition:all .2s; }
  .chart-range-btns button.active,.chart-range-btns button:hover { background:var(--blue-dim); border-color:var(--blue); color:var(--blue); }
  .chart-range-btns input[type="date"] { font-family:'JetBrains Mono',monospace; font-size:.7rem; padding:3px 8px; border:1px solid var(--border); background:var(--bg-card); color:var(--text-secondary); border-radius:6px; outline:none; }
  .chart-range-btns input[type="date"]:focus { border-color:var(--blue); }
  .chart-range-btns input[type="date"]::-webkit-calendar-picker-indicator { filter:invert(0.6); cursor:pointer; }
  .log-container { background:var(--bg-card); border:1px solid var(--border); border-radius:12px; padding:20px; max-height:350px; overflow-y:auto; }
  .log-container::-webkit-scrollbar { width:6px; } .log-container::-webkit-scrollbar-thumb { background:var(--border); border-radius:3px; }
  table { width:100%; border-collapse:collapse; font-family:'JetBrains Mono',monospace; font-size:.75rem; }
  th { text-align:left; color:var(--text-dim); font-weight:400; text-transform:uppercase; letter-spacing:1px; font-size:.65rem; padding:7px 10px; border-bottom:1px solid var(--border); position:sticky; top:0; background:var(--bg-card); }
  td { padding:7px 10px; border-bottom:1px solid rgba(30,41,59,0.5); color:var(--text-secondary); }
  tr:hover td { color:var(--text-primary); background:rgba(255,255,255,0.02); }
  .status-badge { display:inline-block; padding:2px 8px; border-radius:4px; font-size:.7rem; font-weight:600; }
  .status-charging { background:var(--green-dim); color:var(--green); }
  .status-discharging { background:var(--yellow-dim); color:var(--yellow); }
  .status-full { background:var(--blue-dim); color:var(--blue); }
  .activity-bar { display:inline-block; height:6px; border-radius:3px; min-width:2px; vertical-align:middle; margin-right:4px; }
  .footer { text-align:center; padding:20px; color:var(--text-dim); font-size:.75rem; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>🔋 電池<span>監測</span>儀表板</h1>
    <div class="header-meta">
      <span class="live-dot"></span><span id="sourceLabel">即時更新中</span>
      <span id="lastUpdate" style="margin-left:12px;">--</span>
    </div>
  </div>
  <div class="cards">
    <div class="card"><div class="card-label">電量</div><div class="card-value" id="cardPercent">--%</div><div class="card-sub" id="cardPercentSub"></div></div>
    <div class="card"><div class="card-label">狀態</div><div class="card-value" id="cardStatus">--</div><div class="card-sub" id="cardStatusSub"></div></div>
    <div class="card"><div class="card-label">剩餘時間</div><div class="card-value" id="cardTimeLeft">--</div><div class="card-sub" id="cardTimeSub"></div></div>
    <div class="card"><div class="card-label">⌨️ 鍵盤</div><div class="card-value" style="color:var(--cyan)" id="cardKeyboard">--</div><div class="card-sub">次/分鐘</div></div>
    <div class="card"><div class="card-label">🖱️ 滑鼠</div><div class="card-value" style="color:var(--purple)" id="cardMouse">--</div><div class="card-sub">次/分鐘</div></div>
    <div class="card"><div class="card-label">⬇️ 下載</div><div class="card-value" style="color:var(--orange)" id="cardDownload">--</div><div class="card-sub">MB/分鐘</div></div>
    <div class="card"><div class="card-label">⬆️ 上傳</div><div class="card-value" style="color:var(--pink)" id="cardUpload">--</div><div class="card-sub">MB/分鐘</div></div>
    <div class="card"><div class="card-label">📊 記錄</div><div class="card-value" id="cardCount">--</div><div class="card-sub">筆</div></div>
  </div>
  <div class="battery-bar-container">
    <div class="battery-bar-header">
      <span style="font-size:.85rem;font-weight:600;">電池電量</span>
      <span id="barLabel" style="font-family:'JetBrains Mono',monospace;font-size:.85rem;color:var(--text-secondary);">--%</span>
    </div>
    <div class="battery-bar-track"><div class="battery-bar-fill" id="batteryFill" style="width:0%;background:var(--green);"></div></div>
  </div>
  <div class="chart-container" style="padding:12px 20px;margin-bottom:16px;">
    <div class="chart-range-btns" style="display:flex;align-items:center;justify-content:center;flex-wrap:wrap;gap:4px;">
      <button onclick="setRange('1d')" id="btn1d" class="active">1天</button>
      <button onclick="setRange('3d')" id="btn3d">3天</button>
      <button onclick="setRange('7d')" id="btn7d">7天</button>
      <button onclick="setRange('30d')" id="btn30d">30天</button>
      <span style="color:var(--text-dim);margin:0 8px;">|</span>
      <input type="date" id="dateFrom" title="起始日期" />
      <span style="color:var(--text-dim);margin:0 4px;">~</span>
      <input type="date" id="dateTo" title="結束日期" />
      <button onclick="applyDateRange()" id="btnCustom">套用</button>
    </div>
  </div>
  <div class="chart-container">
    <div class="chart-header"><div><span class="chart-title">📈 電量 & 活動趨勢</span>
      <div class="chart-legend"><span class="legend-battery">電量%</span><span class="legend-keyboard">⌨️鍵盤</span><span class="legend-mouse">🖱️滑鼠</span></div>
    </div></div>
    <div class="chart-wrapper"><canvas id="chartActivity"></canvas></div>
  </div>
  <div class="chart-container">
    <div class="chart-header"><div><span class="chart-title">🌐 網路流量</span>
      <div class="chart-legend"><span class="legend-download">⬇️下載MB</span><span class="legend-upload">⬆️上傳MB</span></div>
    </div></div>
    <div class="chart-wrapper"><canvas id="chartNetwork"></canvas></div>
  </div>
  <div class="log-container">
    <table><thead><tr><th>時間</th><th>電量</th><th>狀態</th><th>⌨️鍵盤</th><th>🖱️滑鼠</th><th>⬇️下載</th><th>⬆️上傳</th></tr></thead>
    <tbody id="logBody"></tbody></table>
  </div>
  <div class="footer">Battery Monitor · <a href="https://github.com/TJC-KM/battery-monitor" style="color:var(--blue);text-decoration:none;">GitHub</a></div>
</div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/papaparse@5/papaparse.min.js"></script>
<script>
  let allData = [];
  let currentRange = '1d';
  let customFrom = null, customTo = null;
  let chartActivity = null, chartNetwork = null;
  const isLocal = location.hostname === 'localhost' || location.hostname === '127.0.0.1';
  const CSV_URL = isLocal ? '/api/battery' : 'https://raw.githubusercontent.com/TJC-KM/battery-monitor/main/battery_log.csv';

  const statusMap = {
    charging:{text:'充電中',cls:'status-charging'},
    discharging:{text:'放電中',cls:'status-discharging'},
    full:{text:'已充滿',cls:'status-full'},
    no_battery:{text:'無電池',cls:''}
  };
  function getColor(p){return p>60?'var(--green)':p>30?'var(--yellow)':'var(--red)';}
  function fmtSec(s){if(s===-1)return'∞ 充電中';if(s===-2)return'計算中…';if(s<=0)return'--';const h=Math.floor(s/3600),m=Math.floor((s%3600)/60);return h>0?h+'h '+m+'m':m+'m';}
  function filterByRange(data){
    if(currentRange==='custom'&&customFrom&&customTo){const f=new Date(customFrom+'T00:00:00'),t=new Date(customTo+'T23:59:59');return data.filter(d=>{const x=new Date(d.timestamp);return x>=f&&x<=t;});}
    const now=new Date(),days={'1d':1,'3d':3,'7d':7,'30d':30}[currentRange]||1;
    const cutoff=new Date(now.getTime()-days*24*3600000);return data.filter(d=>new Date(d.timestamp)>=cutoff);
  }

  function updateCards(latest){
    const p=latest.percent;
    document.getElementById('cardPercent').textContent=p+'%';
    document.getElementById('cardPercent').style.color=getColor(p);
    const st=statusMap[latest.status]||{text:latest.status};
    document.getElementById('cardStatus').textContent=st.text;
    document.getElementById('cardStatus').style.color=latest.status==='charging'?'var(--green)':latest.status==='discharging'?'var(--yellow)':'var(--blue)';
    document.getElementById('cardStatusSub').textContent=latest.plugged_in?'已接電源':'使用電池';
    document.getElementById('cardTimeLeft').textContent=fmtSec(latest.seconds_left);
    document.getElementById('cardCount').textContent=allData.length;
    document.getElementById('lastUpdate').textContent=latest.timestamp;
    document.getElementById('cardKeyboard').textContent=latest.kb_count||0;
    document.getElementById('cardMouse').textContent=latest.mouse_count||0;
    document.getElementById('cardDownload').textContent=(latest.net_recv_mb||0).toFixed(1);
    document.getElementById('cardUpload').textContent=(latest.net_sent_mb||0).toFixed(1);
    document.getElementById('batteryFill').style.width=p+'%';
    document.getElementById('batteryFill').style.background=p>60?'linear-gradient(90deg,#22c55e,#4ade80)':p>30?'linear-gradient(90deg,#eab308,#facc15)':'linear-gradient(90deg,#ef4444,#f87171)';
    document.getElementById('barLabel').textContent=p+'%';
    document.getElementById('sourceLabel').textContent=isLocal?'即時更新中':'GitHub 資料（約5分鐘延遲）';
  }

  const chartOpts={responsive:true,maintainAspectRatio:false,animation:{duration:500},interaction:{mode:'index',intersect:false},plugins:{legend:{display:false},tooltip:{backgroundColor:'#1e293b',titleColor:'#e2e8f0',bodyColor:'#94a3b8',borderColor:'#334155',borderWidth:1}}};
  const xScale={type:'time',time:{tooltipFormat:'MM/dd HH:mm:ss',displayFormats:{minute:'HH:mm',hour:'HH:mm',day:'MM/dd'}},grid:{color:'rgba(30,41,59,0.5)'},ticks:{color:'#475569',font:{family:'JetBrains Mono',size:10}}};

  function updateCharts(){
    const f=filterByRange(allData),labels=f.map(d=>new Date(d.timestamp)),pcts=f.map(d=>d.percent),kb=f.map(d=>d.kb_count||0),ms=f.map(d=>d.mouse_count||0),nr=f.map(d=>d.net_recv_mb||0),ns=f.map(d=>d.net_sent_mb||0),chg=f.map(d=>d.plugged_in),pc=chg.map(c=>c?'#22c55e':'#eab308');
    if(!chartActivity){
      chartActivity=new Chart(document.getElementById('chartActivity').getContext('2d'),{type:'line',data:{labels,datasets:[
        {label:'電量%',data:pcts,borderColor:'#3b82f6',backgroundColor:'rgba(59,130,246,0.08)',borderWidth:2,pointBackgroundColor:pc,pointBorderColor:pc,pointRadius:2,pointHoverRadius:5,fill:true,tension:.3,yAxisID:'y'},
        {label:'⌨️鍵盤',data:kb,borderColor:'#06b6d4',backgroundColor:'rgba(6,182,212,0.08)',borderWidth:1.5,pointRadius:0,pointHoverRadius:4,fill:true,tension:.3,yAxisID:'y1'},
        {label:'🖱️滑鼠',data:ms,borderColor:'#a855f7',backgroundColor:'rgba(168,85,247,0.08)',borderWidth:1.5,pointRadius:0,pointHoverRadius:4,fill:true,tension:.3,yAxisID:'y1'}
      ]},options:{...chartOpts,scales:{x:xScale,y:{position:'left',min:0,max:100,grid:{color:'rgba(30,41,59,0.5)'},ticks:{color:'#3b82f6',font:{family:'JetBrains Mono',size:10},callback:v=>v+'%'}},y1:{position:'right',min:0,grid:{display:false},ticks:{color:'#06b6d4',font:{family:'JetBrains Mono',size:10}}}}}});
    } else { chartActivity.data.labels=labels;chartActivity.data.datasets[0].data=pcts;chartActivity.data.datasets[0].pointBackgroundColor=pc;chartActivity.data.datasets[0].pointBorderColor=pc;chartActivity.data.datasets[1].data=kb;chartActivity.data.datasets[2].data=ms;chartActivity.update('none'); }
    if(!chartNetwork){
      chartNetwork=new Chart(document.getElementById('chartNetwork').getContext('2d'),{type:'bar',data:{labels,datasets:[
        {label:'⬇️下載MB',data:nr,backgroundColor:'rgba(249,115,22,0.6)',borderColor:'#f97316',borderWidth:1,borderRadius:2},
        {label:'⬆️上傳MB',data:ns,backgroundColor:'rgba(236,72,153,0.6)',borderColor:'#ec4899',borderWidth:1,borderRadius:2}
      ]},options:{...chartOpts,scales:{x:xScale,y:{position:'left',min:0,grid:{color:'rgba(30,41,59,0.5)'},ticks:{color:'#f97316',font:{family:'JetBrains Mono',size:10},callback:v=>v+' MB'}}}}});
    } else { chartNetwork.data.labels=labels;chartNetwork.data.datasets[0].data=nr;chartNetwork.data.datasets[1].data=ns;chartNetwork.update('none'); }
  }

  function updateLog(data){
    const tbody=document.getElementById('logBody'),recent=data.slice(-50).reverse();
    const maxKb=Math.max(...data.slice(-50).map(d=>d.kb_count||0),1),maxMs=Math.max(...data.slice(-50).map(d=>d.mouse_count||0),1);
    tbody.innerHTML=recent.map(d=>{const st=statusMap[d.status]||{text:d.status,cls:''};const kb=d.kb_count||0,ms=d.mouse_count||0;
      return`<tr><td>${d.timestamp}</td><td style="color:${getColor(d.percent)}">${d.percent}%</td><td><span class="status-badge ${st.cls}">${st.text}</span></td><td><span class="activity-bar" style="width:${Math.max(2,(kb/maxKb)*50)}px;background:var(--cyan)"></span>${kb}</td><td><span class="activity-bar" style="width:${Math.max(2,(ms/maxMs)*50)}px;background:var(--purple)"></span>${ms}</td><td style="color:var(--orange)">${(d.net_recv_mb||0).toFixed(2)}</td><td style="color:var(--pink)">${(d.net_sent_mb||0).toFixed(2)}</td></tr>`;
    }).join('');
  }

  function setRange(r){currentRange=r;customFrom=null;customTo=null;document.getElementById('dateFrom').value='';document.getElementById('dateTo').value='';document.querySelectorAll('.chart-range-btns button').forEach(b=>b.classList.remove('active'));const el=document.getElementById('btn'+r);if(el)el.classList.add('active');updateCharts();}
  function applyDateRange(){const f=document.getElementById('dateFrom').value,t=document.getElementById('dateTo').value;if(!f||!t){alert('請選擇起始和結束日期');return;}if(f>t){alert('起始日期不能大於結束日期');return;}currentRange='custom';customFrom=f;customTo=t;document.querySelectorAll('.chart-range-btns button').forEach(b=>b.classList.remove('active'));document.getElementById('btnCustom').classList.add('active');updateCharts();}

  function parseRow(r){
    return {timestamp:r.timestamp,percent:parseInt(r.percent),status:r.status,
      plugged_in:r.plugged_in==='True'||r.plugged_in===true,
      seconds_left:parseInt(r.seconds_left),power_watts:parseFloat(r.power_watts||0),
      kb_count:parseInt(r.kb_count||0),mouse_count:parseInt(r.mouse_count||0),
      net_sent_mb:parseFloat(r.net_sent_mb||0),net_recv_mb:parseFloat(r.net_recv_mb||0)};
  }

  async function fetchData(){
    try {
      if(isLocal){
        const resp=await fetch('/api/battery');
        allData=(await resp.json()).map(parseRow);
      } else {
        const resp=await fetch(CSV_URL+'?t='+Date.now());
        const text=await resp.text();
        const parsed=Papa.parse(text.trim(),{header:true,skipEmptyLines:true});
        allData=parsed.data.map(parseRow);
      }
      if(allData.length>0){updateCards(allData[allData.length-1]);updateCharts();updateLog(allData);}
    } catch(e){ console.error('Fetch error:',e); }
  }

  fetchData();
  setInterval(fetchData, isLocal ? 10000 : 300000);
</script>
</body>
</html>
"""

class BatteryHTTPHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode("utf-8"))
        elif self.path == "/api/battery":
            records = []
            if CSV_FILE.exists():
                with open(CSV_FILE, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        row["percent"] = int(row["percent"])
                        row["plugged_in"] = row["plugged_in"] == "True"
                        row["seconds_left"] = int(row["seconds_left"])
                        row["power_watts"] = float(row.get("power_watts") or 0)
                        row["kb_count"] = int(row.get("kb_count") or 0)
                        row["mouse_count"] = int(row.get("mouse_count") or 0)
                        row["net_sent_mb"] = float(row.get("net_sent_mb") or 0)
                        row["net_recv_mb"] = float(row.get("net_recv_mb") or 0)
                        records.append(row)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(json.dumps(records, ensure_ascii=False).encode("utf-8"))
        elif self.path == "/api/current":
            info = get_battery_info()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(json.dumps(info, ensure_ascii=False).encode("utf-8"))
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        pass

# ============================================================
# 主程式
# ============================================================
def monitor_loop(interval: int):
    print(f"📝 開始記錄電池狀態（每 {interval} 秒）")
    print(f"📄 CSV 檔案：{CSV_FILE}")
    while True:
        info = get_battery_info()
        append_csv(info)
        pct = info['percent']; status = info['status']; ts = info['timestamp']
        kb = info['kb_count']; ms = info['mouse_count']
        ns = info['net_sent_mb']; nr = info['net_recv_mb']
        plugged = "🔌" if info['plugged_in'] else "🔋"
        print(f"  {ts}  {plugged} {pct}%  ({status})  ⌨️{kb} 🖱️{ms}  ⬇️{nr}MB ⬆️{ns}MB")
        time.sleep(interval)

def main():
    parser = argparse.ArgumentParser(description="電池監測工具")
    parser.add_argument("--interval", type=int, default=60, help="記錄間隔（秒），預設 60")
    parser.add_argument("--port", type=int, default=5678, help="Web Server port，預設 5678")
    parser.add_argument("--push-interval", type=int, default=5, help="Git push 間隔（分鐘），預設 5")
    parser.add_argument("--no-push", action="store_true", help="不推送到 GitHub")
    args = parser.parse_args()

    init_csv()
    start_input_listeners()

    # 背景記錄
    threading.Thread(target=monitor_loop, args=(args.interval,), daemon=True).start()

    # Git push
    if not args.no_push:
        threading.Thread(target=push_loop, args=(args.push_interval,), daemon=True).start()
    else:
        print("⏸️  GitHub 推送已停用")

    # Web Server
    server = HTTPServer(("0.0.0.0", args.port), BatteryHTTPHandler)
    print(f"\n🌐 本機儀表板：http://localhost:{args.port}")
    print(f"🌍 遠端儀表板：https://TJC-KM.github.io/battery-monitor/")
    print(f"   按 Ctrl+C 停止\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 已停止監測")
        server.server_close()

if __name__ == "__main__":
    main()

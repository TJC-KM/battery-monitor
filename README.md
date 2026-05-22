# 🔋 電池監測工具 Battery Monitor

即時監測筆電電池狀態，記錄到 CSV，並提供網頁即時圖表儀表板。

## 安裝

需要 Python 3.7+ 和 psutil：

```bash
pip install psutil
```

## 使用方式

```bash
# 基本使用（每 60 秒記錄一次，Web 在 port 5678）
python battery_monitor.py

# 自訂記錄間隔（每 30 秒）
python battery_monitor.py --interval 30

# 自訂 port
python battery_monitor.py --port 8888
```

啟動後開瀏覽器打開 http://localhost:5678 就能看到即時儀表板。

## 功能

- ✅ 即時顯示電量百分比、充電狀態、剩餘時間
- ✅ 電量變化趨勢圖（支援 1H / 6H / 24H / 全部）
- ✅ 充電中（綠點）/ 放電中（黃點）一目瞭然
- ✅ 歷史記錄表格
- ✅ 所有資料存成 CSV（battery_log.csv），可用 Excel 打開分析
- ✅ 深色主題儀表板，不刺眼

## 開機自動啟動

1. 按 `Win + R`，輸入 `shell:startup`
2. 在開啟的資料夾中建立捷徑，目標設為：
   ```
   pythonw battery_monitor.py
   ```
   （用 `pythonw` 不會跳出黑色視窗）

## CSV 欄位說明

| 欄位 | 說明 |
|------|------|
| timestamp | 記錄時間 |
| percent | 電量百分比 |
| status | charging / discharging / full |
| plugged_in | True / False |
| seconds_left | 預估剩餘秒數（-1=充電中, -2=未知） |
| power_watts | 預留欄位（未來擴充用） |

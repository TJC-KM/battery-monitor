@echo off
REM ============================================
REM  初始化 GitHub Repo（只需執行一次）
REM ============================================

cd /d "%~dp0"

echo 正在初始化 Git repo...

git init
git remote add origin https://github.com/TJC-KM/battery-monitor.git 2>nul

REM 建立 .gitignore
echo tunnel_log.txt > .gitignore
echo __pycache__/ >> .gitignore
echo *.pyc >> .gitignore

git add index.html battery_monitor.py start_monitor.vbs stop_monitor.bat show_tunnel_url.bat start_with_tunnel.bat setup_github.bat README.md .gitignore
git commit -m "🚀 Initial commit - Battery Monitor"
git branch -M main
git push -u origin main

echo.
echo ============================================
echo  ✅ GitHub Repo 初始化完成！
echo.
echo  接下來到 GitHub 開啟 Pages：
echo  1. 打開 https://github.com/TJC-KM/battery-monitor/settings/pages
echo  2. Source 選 Deploy from a branch
echo  3. Branch 選 main，資料夾選 / (root)
echo  4. 點 Save
echo.
echo  等幾分鐘後就能從這個網址看到儀表板：
echo  https://TJC-KM.github.io/battery-monitor/
echo ============================================
echo.
pause

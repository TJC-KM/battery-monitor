@echo off
taskkill /f /im pythonw.exe 2>nul
if %errorlevel%==0 (
    echo 已停止電池監測
) else (
    echo 電池監測未在運行
)
pause

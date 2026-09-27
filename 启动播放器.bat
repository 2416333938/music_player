@echo off
rem 启动多平台音乐播放器（图形界面）
cd /d "%~dp0"
where py >nul 2>nul && (py -3.11 main_gui.py) || (python main_gui.py)
if errorlevel 1 pause

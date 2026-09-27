@echo off
rem 启动多平台音乐播放器（命令行版）
cd /d "%~dp0"
where py >nul 2>nul && (py -3.11 main.py) || (python main.py)
if errorlevel 1 pause

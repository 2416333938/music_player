@echo off
rem ==========================================
rem  多平台音乐播放器 —— 一键安装依赖
rem  适用系统：Windows
rem  使用方式：双击本文件，等待安装完成
rem ==========================================
chcp 65001 >nul
title 安装音乐播放器依赖
echo.
echo ==========================================
echo    多平台音乐播放器 — 一键安装依赖
echo ==========================================
echo.

rem ---------- 1. 自动选择合适的 Python ----------
set "PYEXE="
where py >nul 2>nul
if errorlevel 1 goto :use_python

py -3.11 -c "import sys" >nul 2>nul
if errorlevel 1 goto :try_py3
set "PYEXE=py -3.11"
echo [1/3] 已找到 Python 3.11
goto :pip_ready

:try_py3
py -3 -c "import sys" >nul 2>nul
if errorlevel 1 goto :use_python
set "PYEXE=py -3"
echo [1/3] 已找到 Python 3（自动选用最新版本）
goto :pip_ready

:use_python
python -c "import sys" >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python 环境。
    echo        请先安装 Python 3.9 及以上版本：
    echo        https://www.python.org/downloads/
    echo        安装时务必勾选 Add Python to PATH
    pause
    exit /b 1
)
set "PYEXE=python"
echo [1/3] 已找到 Python（%PYEXE%）

:pip_ready
echo        Python 命令: %PYEXE%

rem ---------- 2. 升级 pip 并安装依赖 ----------
echo.
echo [2/3] 正在升级 pip ...
%PYEXE% -m pip install --upgrade pip
if errorlevel 1 (
    echo [警告] pip 升级失败，继续尝试安装依赖 ...
)

echo.
echo [3/3] 正在安装依赖库（约 1-3 分钟，请耐心等待）...
%PYEXE% -m pip install pygame requests pyncm "qqmusic-api-python>=0.7.3,<0.8" "bilibili-api-python>=17,<18" qrcode Pillow
if errorlevel 1 (
    echo.
    echo [错误] 依赖安装失败。请检查网络后重新运行本脚本。
    pause
    exit /b 1
)

rem ---------- 3. 验证安装结果 ----------
echo.
echo 正在验证依赖是否可用 ...
%PYEXE% -c "import pygame, requests, pyncm, qqmusic_api, bilibili_api, qrcode, PIL; print('全部依赖导入成功 ✔')" >nul 2>nul
if errorlevel 1 (
    echo [警告] 依赖导入验证未通过，请重试或手动排查。
) else (
    echo 全部依赖导入成功 ✔
)

echo.
echo ==========================================
echo    安装完成！
echo ==========================================
echo  下一步：双击「启动播放器.bat」打开图形界面，
echo  或双击「命令行版.bat」使用命令行模式。
echo.
pause

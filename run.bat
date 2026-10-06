@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem 本脚本启动管理入口；服务解释器由 local_runtime.py 按 .python-version 精确校验。
set "PYEXE=python"
if exist "%~dp0.venv\Scripts\python.exe" set "PYEXE=%~dp0.venv\Scripts\python.exe"
if exist "%~dp0python\python.exe" set "PYEXE=%~dp0python\python.exe"
"%PYEXE%" "%~dp0local_runtime.py" %*
set "RUN_EXIT=%ERRORLEVEL%"
if not defined CANVAS_NO_PAUSE pause
exit /b %RUN_EXIT%

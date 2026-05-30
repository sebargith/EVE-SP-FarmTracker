@echo off
setlocal

set "SCRIPT=%~dp0scripts\launch_streamlit.ps1"

if not exist "%SCRIPT%" (
    echo Launcher script was not found:
    echo %SCRIPT%
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*

if errorlevel 1 (
    echo.
    echo Launcher failed.
    pause
)

endlocal

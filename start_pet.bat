@echo off
chcp 65001 >nul
setlocal

if exist "%~dp0BunnymanDesktopPet.exe" (
    "%~dp0BunnymanDesktopPet.exe" %*
    set "EXIT_CODE=%ERRORLEVEL%"
    goto finish
)

if not exist "%~dp0launcher.py" (
    echo No desktop executable or source script was found beside this launcher.
    set "EXIT_CODE=1"
    goto finish
)

where py >nul 2>nul
if not errorlevel 1 (
    py -3 "%~dp0launcher.py" %*
    set "EXIT_CODE=%ERRORLEVEL%"
    goto finish
)

where python >nul 2>nul
if not errorlevel 1 (
    python "%~dp0launcher.py" %*
    set "EXIT_CODE=%ERRORLEVEL%"
    goto finish
)

echo Python 3 was not found. Install Python 3 and the dependencies in requirements.txt.
set "EXIT_CODE=1"

:finish
if not "%EXIT_CODE%"=="0" (
    echo.
    echo Desktop pet failed with exit code %EXIT_CODE%.
    pause
)
exit /b %EXIT_CODE%

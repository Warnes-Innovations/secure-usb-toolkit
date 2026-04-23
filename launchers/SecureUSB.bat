@echo off
:: Secure USB Toolkit — Windows launcher
:: This launcher expects SecureUSB\SecureUSB.exe to be present in the same folder.
:: Build it from the source repo with: make dist   (requires PyInstaller on macOS/Linux)
:: Or on Windows:  pip install pyinstaller  then  pyinstaller --onedir --name SecureUSB tui.py

cd /d "%~dp0"

if exist "SecureUSB\SecureUSB.exe" (
    start "" "SecureUSB\SecureUSB.exe"
) else (
    echo.
    echo  SecureUSB.exe was not found.
    echo.
    echo  The Windows launcher requires a pre-built executable.
    echo  Please contact the person who gave you this USB drive,
    echo  or visit the project page for build instructions.
    echo.
    pause
)

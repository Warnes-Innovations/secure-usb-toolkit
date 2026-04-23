@echo off
:: Secure USB Toolkit — Windows guide
:: Installs VeraCrypt (if needed) then opens README.html.
setlocal

cd /d "%~dp0"

:: ── Step 1: Check if VeraCrypt is already installed ──────────────────────────
set "VC_EXE=%ProgramFiles%\VeraCrypt\VeraCrypt.exe"
if exist "%VC_EXE%" goto already_installed
set "VC_EXE=%ProgramFiles(x86)%\VeraCrypt\VeraCrypt.exe"
if exist "%VC_EXE%" goto already_installed

:: ── Step 2: Not installed — look for bundled installer ───────────────────────
set "INSTALLER="
for /f "delims=" %%F in ('dir /b "%~dp0VeraCrypt\VeraCrypt Setup *.exe" 2^>nul') do set "INSTALLER=%~dp0VeraCrypt\%%F"

if not defined INSTALLER goto no_installer

echo.
echo  VeraCrypt is not installed on this computer.
echo.
echo  A VeraCrypt installer is included on this USB drive:
echo  %INSTALLER%
echo.
set /p "ANSWER=  Install VeraCrypt now? (Y/N): "
if /i "%ANSWER%" neq "Y" goto open_readme

echo.
echo  Launching installer — follow the on-screen steps, then come back here.
echo.
start /wait "" "%INSTALLER%"
echo.
echo  Installation complete (or cancelled). Continuing...
goto open_readme

:already_installed
echo  VeraCrypt is already installed.
goto open_readme

:no_installer
echo.
echo  VeraCrypt installer not found on this USB.
echo  Please download it from https://veracrypt.io/en/Downloads.html
echo.

:open_readme
echo  Opening README.html...
start "" "%~dp0README.html"
endlocal

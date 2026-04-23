@echo off
:: Secure USB Toolkit — Windows guide
:: Opens the getting-started instructions in your default browser.
::
:: Windows users: this USB contains a read-only guide and the VeraCrypt installer.
:: See README.html for instructions on installing VeraCrypt and accessing your files.

cd /d "%~dp0"
start "" "%~dp0README.html"

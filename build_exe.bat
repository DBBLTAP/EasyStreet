@echo off
title Build EasyStreet.exe
echo ================================================
echo   Building EasyStreet.exe - a one-double-click app
echo   First time can take 1-3 minutes. Sit tight.
echo ================================================
cd /d "%~dp0"
python -m pip install --user --upgrade pyinstaller
python -m PyInstaller --onefile --windowed --name EasyStreet easystreet.py
echo.
echo ------------------------------------------------
echo   Done. Your shareable app is here:  dist\EasyStreet.exe
echo   First run on a new PC, it will ask for the DayZServer folder
echo   if it cannot auto-find it. That's it.
echo ------------------------------------------------
pause

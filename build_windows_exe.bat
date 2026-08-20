@echo off
REM Builds a standalone Windows .exe for the NSDL CAS -> Excel converter.
REM Run this ONCE on a Windows machine that has Python installed
REM (get it from python.org if needed -- tick "Add to PATH" during install).
REM
REM After it finishes, the app is at: dist\NSDL_CAS_Converter.exe
REM That single file is what you double-click from then on -- copy it
REM anywhere (a USB stick, your CA's machine, etc.), Python is not needed
REM on the machine that runs the .exe, only on the machine that builds it.

echo Installing required packages...
pip install -r requirements.txt

echo.
echo Building NSDL_CAS_Converter.exe ...
pyinstaller --onefile --windowed --name NSDL_CAS_Converter nsdl_cas_converter.py

echo.
echo Done. Find your app at: dist\NSDL_CAS_Converter.exe
pause

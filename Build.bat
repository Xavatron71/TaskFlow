@echo off
echo Closing any running instances of SmartHomeworkTracker...
taskkill /F /IM SmartHomeworkTracker.exe 2>nul

echo Rebuilding Smart Homework Tracker...
python -m PyInstaller --noconsole --onefile --name="SmartHomeworkTracker" main.py

echo.
echo Build complete! Your updated executable is in the dist folder.
pause
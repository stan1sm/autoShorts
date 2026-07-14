@echo off
rem Double-click to start the shorts-generator GUI.
cd /d "%~dp0.."
echo Starting shorts-generator GUI ... your browser will open shortly.
echo Keep this window open while using the app. Close it to stop.
".venv\Scripts\shorts.exe" gui
pause

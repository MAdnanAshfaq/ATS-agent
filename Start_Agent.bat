@echo off
title AI Job Application Agent
echo ====================================================
echo      Starting AI Job Application Agent...
echo ====================================================
echo.

:: Navigate to the directory where this script is located
cd /d "%~dp0"

:: Open the browser to the dashboard
start http://127.0.0.1:5000

:: Start the Flask app
py app.py

pause

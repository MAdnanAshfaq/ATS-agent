@echo off
setlocal EnableDelayedExpansion
title AI Job Application Agent
color 0A

echo.
echo ====================================================
echo      AI Job Application Agent -- Startup
echo ====================================================
echo.

:: Make absolutely sure we stay in script directory
cd /d "%~dp0"

:: ===========================================================
:: STEP 1: Check Python
:: ===========================================================
echo [1/4] Checking Python environment...

set PYTHON_CMD=
if exist ".venv\Scripts\python.exe" (
    set PYTHON_CMD=.venv\Scripts\python.exe
    goto :python_found
)
if exist "venv\Scripts\python.exe" (
    set PYTHON_CMD=venv\Scripts\python.exe
    goto :python_found
)
where py >nul 2>&1
if not errorlevel 1 (
    set PYTHON_CMD=py
    goto :python_found
)
where python >nul 2>&1
if not errorlevel 1 (
    set PYTHON_CMD=python
    goto :python_found
)
where python3 >nul 2>&1
if not errorlevel 1 (
    set PYTHON_CMD=python3
    goto :python_found
)

echo.
echo  *** ERROR: Python not found on PATH ***
echo  Install Python 3.10+ from https://python.org
echo  Make sure to tick "Add Python to PATH" during install.
echo.
goto :end

:python_found
for /f "tokens=*" %%V in ('!PYTHON_CMD! --version 2^>^&1') do echo        !PYTHON_CMD! = %%V
echo.

:: Ensure .env exists
if not exist ".env" (
    if exist ".env.example" (
        copy /y ".env.example" ".env" >nul 2>&1
    ) else (
        (
            echo GEMINI_API_KEY=
            echo SIMPLIFY_EMAIL=
            echo SIMPLIFY_PASSWORD=
            echo OUTPUT_DIR=output
        ) > ".env"
    )
    echo        Created default .env configuration.
)

:: ===========================================================
:: STEP 2: Install required packages
:: ===========================================================
echo [2/4] Installing required packages (only missing ones)...

!PYTHON_CMD! -m pip install --quiet --upgrade pip 2>nul

if exist "requirements.txt" (
    !PYTHON_CMD! -m pip install -r requirements.txt --quiet 2>&1
) else (
    !PYTHON_CMD! -m pip install ^
        flask ^
        flask-cors ^
        google-genai ^
        playwright ^
        beautifulsoup4 ^
        python-docx ^
        python-dotenv ^
        lxml ^
        httpx ^
        pdfplumber ^
        pypdf ^
        pywin32 ^
        docx2pdf ^
        nest_asyncio ^
        requests ^
        --quiet 2>&1
)


if errorlevel 1 (
    echo  [WARN] Some packages may have had issues above -- trying to continue anyway.
) else (
    echo        Packages OK.
)
echo.

:: ===========================================================
:: STEP 3: Playwright Chromium browser
:: ===========================================================
echo [3/4] Verifying Playwright Chromium browser...
!PYTHON_CMD! -m playwright install chromium 2>&1
echo        Browser check done.
echo.

:: ===========================================================
:: STEP 4: Kill any old process on port 5000, then launch
:: ===========================================================
echo [4/4] Starting Flask server on port 5000...

:: Kill anything still running on 5000 so Flask can bind cleanly
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":5000 " ^| findstr "LISTENING"') do (
    echo        Killing old process %%P on port 5000...
    taskkill /PID %%P /F >nul 2>&1
)

timeout /t 2 /nobreak >nul

:: Open browser with a delay so Flask has time to start
start /b cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:5000"

echo.
echo ====================================================
echo  Server running at: http://127.0.0.1:5000
echo  Press Ctrl+C to stop.
echo ====================================================
echo.

!PYTHON_CMD! app.py

echo.
echo ====================================================
echo  Server has stopped.
echo ====================================================

:end
echo.
echo Press any key to close this window...
pause >nul

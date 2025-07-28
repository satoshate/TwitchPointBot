@echo off
title Twitch Channel Points Bot [Auto-Updater]

:: =================================================================
:: 1. GITHUB DIRECT-DOWNLOAD LINKS
:: =================================================================
SET SCRIPT_URL="https://raw.githubusercontent.com/satoshate/TwitchPointBot/main/twitch_key_bot.py"
SET REQS_URL="https://raw.githubusercontent.com/satoshate/TwitchPointBot/main/requirements.txt"

:: =================================================================
:: 2. Check for Administrator privileges
:: =================================================================
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Requesting Administrator privileges...
    powershell -Command "Start-Process -FilePath '%0' -Verb RunAs"
    exit
)
echo [OK] Script is running with Administrator privileges.

:: =================================================================
:: 3. Force-download the script (NO CHECKS!)
:: =================================================================
echo.
echo [UPDATE] Forcibly downloading the latest script version...
:: This command ALWAYS overwrites the local file. No more comparison issues.
powershell -Command "try { Invoke-WebRequest -Uri %SCRIPT_URL% -OutFile twitch_key_bot.py } catch { Write-Host '[ERROR] Failed to download twitch_key_bot.py'; exit 1 }"
if %errorlevel% neq 0 ( pause & exit )

:: We still check requirements.txt to avoid re-installing every time
powershell -Command "try { Invoke-WebRequest -Uri %REQS_URL% -OutFile requirements.txt.new } catch {}"
if exist "requirements.txt" (
    fc /b "requirements.txt" "requirements.txt.new" > nul
    if %errorlevel% neq 0 (
        echo [UPDATE] Changes detected in requirements.txt. Re-installing.
        del "requirements.txt" & ren "requirements.txt.new" "requirements.txt" & if exist ".installed_flag" del ".installed_flag"
    ) else ( del "requirements.txt.new" )
) else (
    if exist "requirements.txt.new" ( ren "requirements.txt.new" "requirements.txt" )
)
echo [UPDATE] Files updated/checked successfully.

:: =================================================================
:: 4. VENV (Virtual Environment) setup
:: =================================================================
echo.
if not exist ".venv\Scripts\activate.bat" (
    echo [VENV] Virtual environment not found. Creating...
    python -m venv .venv
    if %errorlevel% neq 0 ( echo [ERROR] Failed to create .venv. Make sure Python is installed. & pause & exit )
    echo [VENV] Virtual environment created successfully.
    if exist ".installed_flag" del ".installed_flag"
)
echo [VENV] Activating virtual environment...
call .venv\Scripts\activate.bat

:: =================================================================
:: 5. Install dependencies (if needed)
:: =================================================================
echo.
if not exist ".installed_flag" (
    echo [SETUP] Installing/updating libraries in .venv...
    pip install -r requirements.txt
    if %errorlevel% neq 0 ( echo [ERROR] Failed to install libraries. & pause & exit )
    echo [SETUP] Libraries installed successfully.
    echo 1 > .installed_flag
) else (
    echo [SETUP] Libraries are already installed in .venv.
)

:: =================================================================
:: 6. Run the bot
:: =================================================================
echo.
echo [START] Starting the bot...
echo.
python "%~dp0\twitch_key_bot.py"

echo.
echo [INFO] Bot has finished. Press any key to close this window.
pause >nul
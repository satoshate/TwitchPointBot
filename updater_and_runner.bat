@echo off
title Twitch Channel Points Bot [Auto-Updater]

:: =================================================================
:: 1. GITHUB DIRECT-DOWNLOAD LINKS
:: =================================================================
SET SCRIPT_URL="https://raw.githubusercontent.com/satoshate/TwitchPointBot/main/twitch_key_bot.py"
SET REQS_URL="https://raw.githubusercontent.com/satoshate/TwitchPointBot/main/requirements.txt"
:: ### НОВАЯ ССЫЛКА ###: Указываем ссылку на звуковой файл
SET SOUND_URL="https://raw.githubusercontent.com/satoshate/TwitchPointBot/main/sounds/alert.mp3"

:: =================================================================
:: 2. Check for Administrator privileges
:: ... (остальной код батника без изменений) ...
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
:: 3. Force-download latest versions
:: =================================================================
echo.
echo [UPDATE] Forcibly downloading the latest script version...
powershell -Command "try { Invoke-WebRequest -Uri %SCRIPT_URL% -OutFile twitch_key_bot.py } catch { Write-Host '[ERROR] Failed to download twitch_key_bot.py'; exit 1 }"
if %errorlevel% neq 0 ( pause & exit )

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

:: ### НОВЫЙ БЛОК ###: Скачивание звука
echo [UPDATE] Checking for sound file...
:: Создаем папку, если ее нет
if not exist "sounds" mkdir "sounds"
:: Скачиваем файл, только если его нет, чтобы не перезаписывать каждый раз
if not exist "sounds\alert.mp3" (
    echo [UPDATE] Sound file not found, downloading...
    powershell -Command "try { Invoke-WebRequest -Uri %SOUND_URL% -OutFile sounds\alert.mp3 } catch { Write-Host '[ERROR] Failed to download sound file.' }"
)

echo [UPDATE] Files updated/checked successfully.

:: =================================================================
:: 4. VENV, 5. SETUP, 6. RUN
:: ... (остальная часть батника без изменений) ...
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

echo.
echo [START] Starting the bot...
echo.
python "%~dp0\twitch_key_bot.py"

echo.
echo [INFO] Bot has finished. Press any key to close this window.
pause >nul
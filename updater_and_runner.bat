@echo off
chcp 65001 >nul
title Twitch Channel Points Bot [Auto-Updater]

:: =================================================================
:: 1. НАСТРОЙКА: ПРЯМЫЕ ССЫЛКИ НА GITHUB
:: =================================================================
SET SCRIPT_URL="https://raw.githubusercontent.com/satoshate/TwitchPointBot/main/twitch_key_bot.py"
SET REQS_URL="https://raw.githubusercontent.com/satoshate/TwitchPointBot/main/requirements.txt"

:: =================================================================
:: 2. Общие настройки и проверка прав
:: =================================================================
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Запрашиваю права Администратора...
    powershell -Command "Start-Process -FilePath '%0' -Verb RunAs"
    exit
)
echo [OK] Скрипт запущен с правами Администратора.

:: =================================================================
:: 3. СКАЧИВАНИЕ ОБНОВЛЕНИЙ
:: =================================================================
echo.
echo [UPDATE] Принудительно скачиваю последнюю версию скрипта...
powershell -Command "try { Invoke-WebRequest -Uri %SCRIPT_URL% -OutFile twitch_key_bot.py } catch { Write-Host '[ERROR] Не удалось скачать twitch_key_bot.py'; exit 1 }"
if %errorlevel% neq 0 ( pause & exit )
powershell -Command "try { Invoke-WebRequest -Uri %REQS_URL% -OutFile requirements.txt.new } catch {}"
if exist "requirements.txt" (
    fc /b "requirements.txt" "requirements.txt.new" > nul
    if %errorlevel% neq 0 (
        echo [UPDATE] Обнаружены изменения в requirements.txt.
        del "requirements.txt" & ren "requirements.txt.new" "requirements.txt" & if exist ".installed_flag" del ".installed_flag"
    ) else ( del "requirements.txt.new" )
) else (
    if exist "requirements.txt.new" ( ren "requirements.txt.new" "requirements.txt" )
)
echo [UPDATE] Файлы успешно обновлены/проверены.


:: =================================================================
:: 4. РАБОТА С ВИРТУАЛЬНЫМ ОКРУЖЕНИЕМ (VENV)
:: =================================================================
echo.
if not exist ".venv\Scripts\activate.bat" (
    echo [VENV] Виртуальное окружение не найдено. Создаю...
    python -m venv .venv
    if %errorlevel% neq 0 ( echo [ERROR] Не удалось создать .venv & pause & exit )
    echo [VENV] Виртуальное окружение успешно создано.
    if exist ".installed_flag" del ".installed_flag"
)
echo [VENV] Активирую виртуальное окружение...
call .venv\Scripts\activate.bat

:: =================================================================
:: 5. Установка зависимостей (если нужно)
:: =================================================================
echo.
if not exist ".installed_flag" (
    echo [SETUP] Устанавливаю/обновляю библиотеки в .venv...
    pip install -r requirements.txt
    if %errorlevel% neq 0 ( echo [ERROR] Не удалось установить библиотеки. & pause & exit )
    echo [SETUP] Библиотеки успешно установлены.
    echo 1 > .installed_flag
) else (
    echo [SETUP] Библиотеки уже установлены в .venv.
)

:: =================================================================
:: 6. Запуск бота
:: =================================================================
echo.
echo [START] Запускаю бота...
echo.
:: ### КЛЮЧЕВОЕ ИЗМЕНЕНИЕ ### Добавляем флаг -X utf8, чтобы Python принудительно использовал UTF-8
python -X utf8 "%~dp0\twitch_key_bot.py"

echo.
echo [INFO] Бот завершил работу. Нажмите любую клавишу для закрытия окна.
pause >nul

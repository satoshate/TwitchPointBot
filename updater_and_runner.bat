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
:: 3. СКАЧИВАНИЕ И ПРОВЕРКА ОБНОВЛЕНИЙ (Код без изменений)
:: =================================================================
echo.
echo [UPDATE] Проверяю наличие обновлений...
curl -s -L %SCRIPT_URL% -o twitch_key_bot.py.new && curl -s -L %REQS_URL% -o requirements.txt.new
if %errorlevel% neq 0 (
    powershell -Command "try { Invoke-WebRequest -Uri %SCRIPT_URL% -OutFile twitch_key_bot.py.new } catch {}"
    powershell -Command "try { Invoke-WebRequest -Uri %REQS_URL% -OutFile requirements.txt.new } catch {}"
)
if not exist "twitch_key_bot.py" ( ren twitch_key_bot.py.new twitch_key_bot.py ) else ( fc /b "twitch_key_bot.py" "twitch_key_bot.py.new" > nul || (del "twitch_key_bot.py" && ren "twitch_key_bot.py.new" "twitch_key_bot.py" && echo [UPDATE] Скрипт обновлен.) )
if not exist "requirements.txt" ( ren requirements.txt.new requirements.txt ) else ( fc /b "requirements.txt" "requirements.txt.new" > nul || (del "requirements.txt" && ren "requirements.txt.new" "requirements.txt" && echo [UPDATE] Файл зависимостей обновлен. && if exist ".installed_flag" del ".installed_flag") )
if exist "*.new" del "*.new"
echo [UPDATE] Проверка завершена.

:: =================================================================
:: 4. РАБОТА С ВИРТУАЛЬНЫМ ОКРУЖЕНИЕМ (VENV) - НОВЫЙ БЛОК
:: =================================================================
echo.
:: Проверяем, существует ли папка виртуального окружения
if not exist ".venv\Scripts\activate.bat" (
    echo [VENV] Виртуальное окружение не найдено. Создаю...
    
    :: Проверяем наличие Python
    python --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo [ERROR] Python не найден! Пожалуйста, установите Python с сайта python.org
        echo [INFO] При установке обязательно поставьте галочку "Add Python to PATH".
        pause
        exit
    )
    
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] Не удалось создать виртуальное окружение.
        pause
        exit
    )
    echo [VENV] Виртуальное окружение успешно создано.
    :: Принудительно сбрасываем флаг установки, чтобы библиотеки установились в новое окружение
    if exist ".installed_flag" del ".installed_flag"
)

:: Активируем виртуальное окружение. Все последующие команды (pip, python) будут выполняться в нем.
echo [VENV] Активирую виртуальное окружение...
call .venv\Scripts\activate.bat

:: =================================================================
:: 5. Установка зависимостей (теперь внутри VENV)
:: =================================================================
echo.
if not exist ".installed_flag" (
    echo [SETUP] Устанавливаю/обновляю библиотеки в .venv...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [ERROR] Не удалось установить библиотеки.
        pause
        exit
    )
    echo [SETUP] Библиотеки успешно установлены.
    echo 1 > .installed_flag
) else (
    echo [SETUP] Библиотеки уже установлены в .venv.
)

:: =================================================================
:: 6. Запуск бота (теперь внутри VENV)
:: =================================================================
echo.
echo [START] Запускаю бота...
echo.
python "%~dp0\twitch_key_bot.py"

echo.
echo [INFO] Бот завершил работу. Нажмите любую клавишу для закрытия окна.
pause >nul

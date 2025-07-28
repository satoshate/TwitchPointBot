@echo off
chcp 65001 >nul
title Twitch Channel Points Bot [Auto-Updater]

:: =================================================================
:: 1. НАСТРОЙКА: УКАЖИТЕ ПРЯМЫЕ ССЫЛКИ НА ВАШИ ФАЙЛЫ НА GITHUB
:: =================================================================
:: Как получить ссылку: зайдите на GitHub, откройте файл, нажмите кнопку "Raw". Скопируйте URL из адресной строки.
SET SCRIPT_URL="https://raw.githubusercontent.com/satoshate/TwitchPointBot/refs/heads/main/twitch_key_bot.py"
SET REQS_URL="https://raw.githubusercontent.com/satoshate/TwitchPointBot/refs/heads/main/requirements.txt"

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
:: 3. СКАЧИВАНИЕ И ПРОВЕРКА ОБНОВЛЕНИЙ
:: =================================================================
echo.
echo [UPDATE] Проверяю наличие обновлений...

:: Скачиваем последнюю версию скрипта и файла зависимостей
echo [UPDATE] Скачиваю twitch_key_bot.py...
curl -s -L %SCRIPT_URL% -o twitch_key_bot.py.new
if %errorlevel% neq 0 (
    echo [WARN] curl не сработал. Пробую через PowerShell...
    powershell -Command "try { Invoke-WebRequest -Uri %SCRIPT_URL% -OutFile twitch_key_bot.py.new } catch {}"
)

echo [UPDATE] Скачиваю requirements.txt...
curl -s -L %REQS_URL% -o requirements.txt.new
if %errorlevel% neq 0 (
    echo [WARN] curl не сработал. Пробую через PowerShell...
    powershell -Command "try { Invoke-WebRequest -Uri %REQS_URL% -OutFile requirements.txt.new } catch {}"
)

:: Проверяем, существует ли локальный файл. Если нет, то это первый запуск.
if not exist "twitch_key_bot.py" (
    echo [UPDATE] Локальный скрипт не найден. Устанавливаю скачанную версию.
    ren twitch_key_bot.py.new twitch_key_bot.py
) else (
    :: Сравниваем файлы. fc /b - бинарное сравнение.
    fc /b "twitch_key_bot.py" "twitch_key_bot.py.new" > nul
    if %errorlevel%==0 (
        echo [UPDATE] Скрипт twitch_key_bot.py уже последней версии.
        del "twitch_key_bot.py.new"
    ) else (
        echo [UPDATE] !!! Обнаружена новая версия twitch_key_bot.py! Обновляю...
        del "twitch_key_bot.py"
        ren "twitch_key_bot.py.new" "twitch_key_bot.py"
        echo [UPDATE] Скрипт успешно обновлен.
    )
)

:: Делаем то же самое для requirements.txt
if not exist "requirements.txt" (
    ren requirements.txt.new requirements.txt
) else (
    fc /b "requirements.txt" "requirements.txt.new" > nul
    if %errorlevel%==0 (
        del "requirements.txt.new"
    ) else (
        echo [UPDATE] !!! Обнаружены изменения в requirements.txt! Обновляю...
        del "requirements.txt"
        ren "requirements.txt.new" "requirements.txt"
        echo [UPDATE] Файл зависимостей обновлен. Сбрасываю флаг установки.
        if exist ".installed_flag" del ".installed_flag"
    )
)

:: =================================================================
:: 4. Установка зависимостей (если нужно)
:: =================================================================
echo.
if not exist ".installed_flag" (
    echo [SETUP] Устанавливаю/обновляю библиотеки...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [ERROR] Не удалось установить библиотеки.
        pause
        exit
    )
    echo [SETUP] Библиотеки успешно установлены.
    echo 1 > .installed_flag
) else (
    echo [SETUP] Библиотеки уже установлены.
)

:: =================================================================
:: 5. Запуск бота
:: =================================================================
echo.
echo [START] Запускаю бота...
echo.
python "%~dp0\twitch_key_bot.py"

echo.
echo [INFO] Бот завершил работу. Нажмите любую клавишу для закрытия окна.
pause >nul

import asyncio
import logging
import json
import os
import sys
import webbrowser
from twitchio.ext.pubsub import PubSubPool
from twitchio.client import Client
import pyautogui
import keyboard

# --- КОНФИГУРАЦИЯ ---
SETTINGS_FILE = "bot_settings.json"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# --- ГЛОБАЛЬНЫЙ КОНТЕЙНЕР ---
app_settings = {}
twitch_client = None
RESTART_FLAG = False

# --- ФУНКЦИИ УПРАВЛЕНИЯ НАСТРОЙКАМИ ---
def load_settings():
    global app_settings
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                app_settings = json.load(f)
            logger.info(f"Настройки успешно загружены из {SETTINGS_FILE}")
        except (json.JSONDecodeError, KeyError):
            logger.error(f"Файл {SETTINGS_FILE} поврежден. Будут запрошены новые настройки.")
            app_settings = {}
    else:
        logger.info(f"Файл {SETTINGS_FILE} не найден. Будет произведена первоначальная настройка.")
        app_settings = {}

def save_settings():
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(app_settings, f, ensure_ascii=False, indent=4)
    logger.info(f"Настройки сохранены в {SETTINGS_FILE}")

def initial_setup():
    global app_settings
    if not app_settings.get("twitch_channel_name"):
        app_settings["twitch_channel_name"] = input("Введите имя вашего канала Twitch: ").strip().lower()
    if not app_settings.get("twitch_oauth_token"):
        print("\n--- ПОЛУЧЕНИЕ OAuth ТОКЕНА ---")
        print("1. На сайте нажмите 'Custom Scope Token'.")
        print("2. Поставьте ОДНУ галочку напротив 'channel:read:redemptions'.")
        print("3. Нажмите 'Generate Token!' и авторизуйтесь.")
        print("4. Скопируйте 'Access Token' и вставьте его сюда.")
        if input("Нажмите Enter, чтобы открыть браузер..."): pass
        webbrowser.open("https://twitchtokengenerator.com/")
        app_settings["twitch_oauth_token"] = input("Вставьте ваш OAuth токен сюда: ").strip()
    app_settings.setdefault("rewards", {"Пример награды": "space"})
    app_settings.setdefault("key_behavior", {
        "hold_duration_seconds": 1.0,
        "hold_keys": ["w", "a", "s", "d"],
        "single_press_keys": ["e", "r", "f", "g", "q", "space", "lmb", "rmb"]
    })
    save_settings()
    logger.info("Первоначальная настройка завершена. Запускаю бота...")
    return True

# --- ОСНОВНАЯ ЛОГИКА БОТА ---
async def handle_key_action(key_name: str):
    key = key_name.lower()
    key_behavior = app_settings.get("key_behavior", {})
    try:
        if key in key_behavior.get('hold_keys', []):
            hold_time = float(key_behavior.get('hold_duration_seconds', 1.0))
            keyboard.press(key)
            logger.info(f"HOLD: Зажата клавиша '{key.upper()}' на {hold_time} сек...")
            await asyncio.sleep(hold_time)
            keyboard.release(key)
            logger.info(f"RELEASED: Клавиша '{key.upper()}' отпущена.")
        elif key in key_behavior.get('single_press_keys', []):
            if key == 'lmb': pyautogui.click(button='left'); logger.info("CLICK: ЛКМ.")
            elif key == 'rmb': pyautogui.click(button='right'); logger.info("CLICK: ПКМ.")
            else: keyboard.press_and_release(key); logger.info(f"PRESS: '{key.upper()}'.")
        else: logger.warning(f"Действие для '{key.upper()}' не определено.")
    except Exception as e: logger.error(f"Ошибка при нажатии '{key.upper()}': {e}")

async def on_channel_points(data: dict):
    try:
        reward_data = data.get('data', {}).get('redemption', {})
        if not reward_data: return
        reward_title = reward_data.get('reward', {}).get('title')
        user_name = reward_data.get('user', {}).get('display_name')
        key_to_press = app_settings.get("rewards", {}).get(reward_title)
        if key_to_press:
            logger.info(f"Награда '{reward_title}' от {user_name} -> Нажимаю '{key_to_press.upper()}'")
            asyncio.create_task(handle_key_action(key_to_press))
        else:
            logger.warning(f"Получена не настроенная награда: '{reward_title}'")
    except Exception as e:
        logger.error(f"Ошибка при обработке награды: {e}")

# --- ИНТЕРАКТИВНАЯ КОНСОЛЬ ---
async def console_input_worker():
    global RESTART_FLAG
    loop = asyncio.get_event_loop()
    logger.info("Консоль управления активна. Введите 'help' для списка команд.")
    while True:
        try:
            cmd_line = await loop.run_in_executor(None, sys.stdin.readline)
            parts = cmd_line.strip().split(maxsplit=2)
            if not parts: continue
            command = parts[0].lower()
            if command == "help":
                print("\n--- СПИСОК КОМАНД КОНСОЛИ ---")
                print("  status                   - Показать текущие настройки")
                print("  reward add \"<название>\" <клавиша> - Добавить/изменить привязку награды")
                print("  reward remove \"<название>\"      - Удалить привязку награды")
                print("  holdkey add/remove <клавиша> - Управление списком ЗАЖИМАЕМЫХ клавиш")
                print("  presskey add/remove <клавиша>- Управление списком ОДИНОЧНЫХ клавиш")
                print("  holdtime <число>         - Установить время зажатия в секундах")
                print("  restart                  - Перезапустить подключение к Twitch")
                print("  exit                     - Выйти из программы")
                print("-----------------------------------\n")
            elif command == "status":
                print("\n--- ТЕКУЩИЕ НАСТРОЙКИ ---")
                status_settings = app_settings.copy()
                if 'twitch_oauth_token' in status_settings and status_settings['twitch_oauth_token']:
                    status_settings['twitch_oauth_token'] = f"***{status_settings['twitch_oauth_token'][-4:]}"
                print(json.dumps(status_settings, ensure_ascii=False, indent=4))
                print("---------------------------\n")
            elif command == "reward" and len(parts) > 2:
                action = parts[1].lower()
                try:
                    reward_name = cmd_line.strip().split('"', 2)[1]
                    if action == "add":
                        key_to_bind = cmd_line.strip().split('"', 2)[2].strip()
                        if not key_to_bind: raise IndexError
                        app_settings["rewards"][reward_name] = key_to_bind
                        logger.info(f"Награда '{reward_name}' теперь привязана к '{key_to_bind}'.")
                    elif action == "remove":
                        if reward_name in app_settings["rewards"]:
                            del app_settings["rewards"][reward_name]
                            logger.info(f"Привязка для '{reward_name}' удалена.")
                        else: logger.warning(f"Награда '{reward_name}' не найдена.")
                    save_settings()
                except IndexError: logger.warning("Формат: reward add/remove \"Название\" <клавиша>")
            elif command in ["holdkey", "presskey"] and len(parts) > 2:
                key_list_name = f"{command}s"
                action, key = parts[1].lower(), parts[2].lower()
                if action == "add" and key not in app_settings["key_behavior"][key_list_name]:
                    app_settings["key_behavior"][key_list_name].append(key)
                    logger.info(f"'{key}' добавлена в '{key_list_name}'.")
                elif action == "remove" and key in app_settings["key_behavior"][key_list_name]:
                    app_settings["key_behavior"][key_list_name].remove(key)
                    logger.info(f"'{key}' удалена из '{key_list_name}'.")
                else: logger.warning(f"Действие не выполнено.")
                save_settings()
            elif command == "holdtime" and len(parts) > 1:
                try:
                    app_settings["key_behavior"]["hold_duration_seconds"] = float(parts[1])
                    logger.info(f"Время зажатия установлено на {parts[1]} сек.")
                    save_settings()
                except ValueError: logger.warning("Некорректное число.")
            elif command == "restart":
                logger.warning("Перезапускаю подключение к Twitch...")
                RESTART_FLAG = True
                if twitch_client: await twitch_client.close()
                break
            elif command == "exit":
                logger.info("Завершение работы по команде...")
                RESTART_FLAG = False
                if twitch_client: await twitch_client.close()
                break
            else: logger.warning(f"Неизвестная команда. Введите 'help'.")
        except Exception as e: logger.error(f"Ошибка в консоли: {e}")

# --- ОСНОВНОЙ ЦИКЛ ЗАПУСКА ---
async def main_loop():
    global twitch_client, RESTART_FLAG
    load_settings()
    if not app_settings.get("twitch_channel_name") or not app_settings.get("twitch_oauth_token"):
        initial_setup()
    while True:
        RESTART_FLAG = False
        channel_name = app_settings.get("twitch_channel_name")
        token = app_settings.get("twitch_oauth_token")
        twitch_client = Client() 
        pubsub_pool = PubSubPool(twitch_client)
        topic_str = "channel-points-channel-v1"
        console_task = asyncio.create_task(console_input_worker())
        try:
            users = await twitch_client.fetch_users(names=[channel_name])
            if not users:
                logger.error(f"Канал '{channel_name}' не найден.")
                break
            channel_id = users[0].id
            await pubsub_pool.subscribe_topic(f"{topic_str}.{channel_id}", token, on_channel_points)
            logger.info(f"Успешно подписан на события баллов канала '{channel_name}'.")
            logger.warning("=" * 60)
            logger.warning("Бот запущен. Для остановки нажмите Ctrl+C или введите 'exit'.")
            logger.warning("=" * 60)
            await console_task
        except Exception as e:
            if "401" in str(e):
                logger.error("ОШИБКА АВТОРИЗАЦИИ (401). Ваш токен недействителен.")
                app_settings["twitch_oauth_token"] = ""
                save_settings()
                logger.info("Неверный токен сброшен. Перезапустите бота для ввода нового.")
            else: logger.error(f"Критическая ошибка: {e}")
            if not console_task.done(): console_task.cancel()
            break
        finally:
            if twitch_client and not twitch_client.is_closed():
                await pubsub_pool.unsubscribe_topic(f"{topic_str}.{channel_id}")
                await twitch_client.close()
        if not RESTART_FLAG: break
    logger.info("Программа завершена.")

if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logger.info("\nСкрипт остановлен пользователем (Ctrl+C).")

import asyncio
import logging
import json
import os
import sys
import uuid
import pyautogui
import keyboard
from twitchio.ext import pubsub # Теперь импортируем только pubsub
from twitchio.client import Client

# --- КОНФИГУРАЦИЯ ---
SETTINGS_FILE = "bot_settings.json"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# --- ГЛОБАЛЬНЫЙ КОНТЕЙНЕР ---
app_settings = {}
twitch_client = None

# --- ФУНКЦИИ УПРАВЛЕНИЯ НАСТРОЙКАМИ (Без изменений) ---
def load_or_create_settings():
    """Загружает настройки из файла или создает его, если он не существует."""
    global app_settings
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                app_settings = json.load(f)
            logger.info(f"Настройки успешно загружены из {SETTINGS_FILE}")
            return True
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Файл {SETTINGS_FILE} поврежден или имеет неверный формат: {e}")
            return False
    else:
        logger.warning(f"Файл {SETTINGS_FILE} не найден. Создаю файл с настройками по умолчанию.")
        default_settings = {
            "twitch_channel_name": "your_channel_name_here",
            "twitch_oauth_token": "paste_your_oauth_token_from_twitchtokengenerator_here",
            "rewards": {
                "Бежать вперед (1 сек)": "w",
                "Использовать/Открыть (E)": "e",
                "Выстрел": "lmb"
            },
            "key_behavior": {
                "hold_duration_seconds": 1.0,
                "hold_keys": ["w", "a", "s", "d"],
                "single_press_keys": ["e", "r", "f", "g", "q", "space", "lmb", "rmb"]
            }
        }
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(default_settings, f, ensure_ascii=False, indent=4)
        logger.info(f"Создан файл {SETTINGS_FILE}. Пожалуйста, отредактируйте его и перезапустите бота.")
        return False

# --- ОСНОВНАЯ ЛОГИКА БОТА (Без изменений) ---
async def handle_key_action(key_name: str):
    """Обрабатывает нажатие клавиши в соответствии с настройками."""
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
            if key == 'lmb':
                pyautogui.click(button='left')
                logger.info("CLICK: Нажата левая кнопка мыши.")
            elif key == 'rmb':
                pyautogui.click(button='right')
                logger.info("CLICK: Нажата правая кнопка мыши.")
            else:
                keyboard.press_and_release(key)
                logger.info(f"PRESS: Нажата и отпущена клавиша '{key.upper()}'.")
        else:
            logger.warning(f"Действие для клавиши '{key.upper()}' не определено в 'key_behavior' в настройках.")

    except Exception as e:
        logger.error(f"Ошибка при попытке нажать '{key.upper()}': {e}")


### ИЗМЕНЕНИЕ ###: Убрали декоратор @pubsub.pubsub_callback
# Теперь это обычная функция, которую мы зарегистрируем вручную.
async def on_channel_points(data: pubsub.PubSubChannelPointsMessage):
    """Эта функция вызывается, когда кто-то активирует награду за баллы канала."""
    try:
        reward_title = data.reward.title
        user_name = data.user.name
        logger.info(f"ПОЛУЧЕНА НАГРАДА! Пользователь: {user_name}, Награда: '{reward_title}'")

        key_to_press = app_settings.get("rewards", {}).get(reward_title)

        if key_to_press:
            logger.info(f"Награда '{reward_title}' найдена в настройках. Действие: нажать '{key_to_press.upper()}'")
            asyncio.create_task(handle_key_action(key_to_press))
        else:
            logger.warning(f"Для награды '{reward_title}' не настроено действие в {SETTINGS_FILE}")
    except Exception as e:
        logger.error(f"Ошибка при обработке награды: {e}")


async def run_bot():
    """Основная функция запуска и подключения бота."""
    global twitch_client
    
    channel_name = app_settings.get("twitch_channel_name")
    token = app_settings.get("twitch_oauth_token")

    if not channel_name or "your_channel_name" in channel_name or not token or "paste_your_oauth_token" in token:
        logger.error("Имя канала или OAuth токен не указаны в bot_settings.json!")
        logger.error("Пожалуйста, заполните файл настроек и перезапустите бота.")
        input("Нажмите Enter для выхода...") # ### ИЗМЕНЕНИЕ ###: Добавил input для ожидания
        return

    twitch_client = Client(token=token)
    pubsub_service = pubsub.PubSub(twitch_client)
    
    ### ИЗМЕНЕНИЕ ###: Вот новый способ регистрации функции-обработчика
    pubsub_service.register_callback(pubsub.Topic.channel_points_v1, on_channel_points)

    try:
        users = await twitch_client.fetch_users(names=[channel_name])
        if not users:
            logger.error(f"Не удалось найти пользователя с ником '{channel_name}'. Проверьте имя канала в настройках.")
            input("Нажмите Enter для выхода...") # ### ИЗМЕНЕНИЕ ###: Добавил input для ожидания
            return
        
        channel_id = users[0].id
        
        ### ИЗМЕНЕНИЕ ###: Новый способ подписки на топик
        topics = [pubsub.Topic(channel_id, "channel-points-channel-v1", token)]
        await pubsub_service.subscribe_topics(topics)
        
        logger.info(f"Успешно подписан на события баллов канала '{channel_name}' (ID: {channel_id}).")
        
        logger.warning("=" * 60)
        logger.warning("Бот запущен и слушает события баллов канала.")
        logger.warning("Не закрывайте это окно! Для остановки нажмите Ctrl+C.")
        logger.warning("=" * 60)
        
        # Бесконечный цикл, чтобы скрипт не завершался
        await asyncio.Event().wait()

    except Exception as e:
        if "401" in str(e):
             logger.error("ОШИБКА АВТОРИЗАЦИИ (401). Ваш OAuth токен недействителен или не имеет прав 'channel:read:redemptions'.")
        else:
             logger.error(f"Произошла критическая ошибка при подключении к Twitch: {e}")
        input("Нажмите Enter для выхода...") # ### ИЗМЕНЕНИЕ ###: Добавил input для ожидания
    finally:
        if twitch_client:
            await pubsub_service.unsubscribe_topics(topics)
            await twitch_client.close()
            logger.info("Соединение с Twitch закрыто.")

async def main():
    if not load_or_create_settings():
        input("Нажмите Enter для выхода...")
        return
    
    await run_bot()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nСкрипт остановлен пользователем (Ctrl+C).")

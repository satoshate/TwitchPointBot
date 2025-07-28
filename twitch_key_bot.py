import asyncio
import logging
import json
import os
import sys
import webbrowser
from twitchio.ext import eventsub
from twitchio.client import Client
import pyautogui
import keyboard

# --- CONFIGURATION ---
SETTINGS_FILE = "bot_settings.json"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# --- GLOBAL CONTAINER ---
app_settings = {}
# Глобальный флаг для перезапуска, чтобы основной цикл мог его видеть
RESTART_FLAG = False

# --- THE BOT CLASS ---
class TwitchBot:

    def __init__(self, settings):
        self.settings = settings
        self.client = Client(token=settings.get("twitch_oauth_token")) # Для получения user_id
        self.eventsub_client = eventsub.EventSubClient(
            self.client,
            webhook_secret="s3cRe7_s3cRe7_s3cRe7", # Секрет не используется для WebSocket, но обязателен
            callback_route="/",
        )
        self.is_restarting = False
        self.console_task = None

    async def run(self):
        # Получаем ID канала
        users = await self.client.fetch_users(names=[self.settings.get("twitch_channel_name")])
        if not users:
            logger.error(f"Channel '{self.settings.get('twitch_channel_name')}' not found.")
            return

        broadcaster_id = users[0].id
        
        # Запускаем фоновую задачу для консоли
        loop = asyncio.get_event_loop()
        self.console_task = loop.create_task(self.console_input_worker())

        # Запускаем прослушивание EventSub
        logger.info("Connecting to Twitch EventSub...")
        await self.eventsub_client.listen(port=8080) # Порт не важен для WebSocket, но вызов необходим

    # Обработчик событий EventSub
    @eventsub.event(eventsub.ChannelPointsCustomRewardRedemptionAddEvent)
    async def on_channel_points_redemption(self, event: eventsub.ChannelPointsCustomRewardRedemptionAddEvent):
        try:
            reward_title = event.data.reward.title
            user_name = event.data.user.name
            key_to_press = self.settings.get("rewards", {}).get(reward_title)

            if key_to_press:
                logger.info(f"Reward '{reward_title}' from {user_name} -> Pressing '{key_to_press.upper()}'")
                asyncio.create_task(self.handle_key_action(key_to_press))
            else:
                logger.warning(f"Received an unconfigured reward: '{reward_title}'")
        except Exception as e:
            logger.error(f"Error processing reward: {e}")
            
    async def stop(self):
        if self.console_task and not self.console_task.done():
            self.console_task.cancel()
        await self.eventsub_client.close()
        await self.client.close()

    async def handle_key_action(self, key_name: str):
        # ... (этот метод без изменений)
        key = key_name.lower()
        key_behavior = self.settings.get("key_behavior", {})
        try:
            if key in key_behavior.get('hold_keys', []):
                hold_time = float(key_behavior.get('hold_duration_seconds', 1.0))
                keyboard.press(key); await asyncio.sleep(hold_time); keyboard.release(key)
                logger.info(f"HOLD/RELEASED: '{key.upper()}' for {hold_time}s")
            elif key in key_behavior.get('single_press_keys', []):
                if key == 'lmb': pyautogui.click(button='left'); logger.info("CLICK: Left Mouse Button.")
                elif key == 'rmb': pyautogui.click(button='right'); logger.info("CLICK: Right Mouse Button.")
                else: keyboard.press_and_release(key); logger.info(f"PRESS: Key '{key.upper()}'.")
            else: logger.warning(f"Action for key '{key.upper()}' is not defined.")
        except Exception as e: logger.error(f"Error while pressing key '{key.upper()}': {e}")
    
    async def console_input_worker(self):
        # ... (этот метод без изменений)
        global RESTART_FLAG
        loop = asyncio.get_event_loop()
        logger.info("Control console is active. Type 'help' for a list of commands.")
        while True:
            try:
                cmd_line = await loop.run_in_executor(None, sys.stdin.readline)
                parts = cmd_line.strip().split(maxsplit=2)
                if not parts: continue
                command = parts[0].lower()
                if command == "restart":
                    logger.warning("Restarting bot...")
                    RESTART_FLAG = True
                    await self.stop()
                    break
                elif command == "exit":
                    logger.info("Exiting on command...")
                    RESTART_FLAG = False
                    await self.stop()
                    break
            except asyncio.CancelledError: break
            except Exception as e: logger.error(f"Error in console: {e}")


# --- FUNCTIONS FOR SETTINGS AND INITIAL SETUP ---
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: return {}
    else: return {}

def save_settings(settings):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)
    logger.info(f"Settings saved to {SETTINGS_FILE}")

def initial_setup(settings):
    if not settings.get("twitch_channel_name"):
        settings["twitch_channel_name"] = input("Enter your Twitch channel name: ").strip().lower()
    
    if not settings.get("twitch_client_id"):
        print("\n--- GETTING Client ID ---")
        print("Go to your Twitch Developer Console (dev.twitch.tv/console/apps).")
        print("Register a new application (or use an existing one).")
        settings["twitch_client_id"] = input("Paste your Client ID here: ").strip()

    if not settings.get("twitch_oauth_token"):
        print("\n--- GETTING OAuth TOKEN ---")
        print("A browser will now open to generate a token.")
        print("This token needs permissions for EventSub.")
        print("Required scopes: channel:read:redemptions AND user:read:broadcast")
        input("Press Enter to open the browser...")
        webbrowser.open("https://twitchtokengenerator.com/")
        settings["twitch_oauth_token"] = input("Paste your OAuth token here: ").strip()
        
    settings.setdefault("rewards", {"Example Reward": "space"})
    save_settings(settings)
    logger.info("Initial setup complete. Starting the bot...")
    return True

# --- MAIN EXECUTION BLOCK ---
async def main():
    global RESTART_FLAG
    while True:
        RESTART_FLAG = False
        settings = load_settings()
        if not all(k in settings for k in ["twitch_channel_name", "twitch_oauth_token", "twitch_client_id"]):
            if not initial_setup(settings): break
        
        # Устанавливаем Client ID и токен для API запросов
        Client.inactive_client_id = settings.get("twitch_client_id")
        Client.inactive_token = settings.get("twitch_oauth_token")

        bot = TwitchBot(settings)
        
        logger.warning("=" * 60); logger.warning("Bot is starting..."); logger.warning("=" * 60)
        
        try:
            await bot.run()
        except Exception as e:
            if "401" in str(e) or "invalid token" in str(e).lower():
                logger.error("AUTHORIZATION FAILED. The token is likely invalid or expired.")
                settings["twitch_oauth_token"] = "" # Сбрасываем токен
                save_settings(settings)
                logger.info("Invalid token has been cleared. Restart the bot.")
            else:
                logger.error(f"An unhandled error occurred: {e}")
            
            await bot.stop()
            break

        if not RESTART_FLAG:
            break
        logger.info("Restarting bot in 3 seconds..."); await asyncio.sleep(3)

    logger.info("Program has terminated.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nScript stopped by user (Ctrl+C).")

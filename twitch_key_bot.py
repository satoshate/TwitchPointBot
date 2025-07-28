import asyncio
import logging
import json
import os
import sys
import webbrowser
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

# --- THE BOT CLASS ---
class TwitchBot(Client):

    def __init__(self, settings):
        self.app_settings = settings
        token = settings.get("twitch_oauth_token", "")
        # Automatically add the "oauth:" prefix if it's missing
        if token and not token.startswith("oauth:"):
            token = f"oauth:{token}"
        
        # This is the corrected constructor call, without client_id
        super().__init__(
            token=token,
            initial_channels=[settings.get("twitch_channel_name")]
        )
        self.console_task = None
        self.is_restarting = False

    async def event_ready(self):
        logger.info(f"Connected to Twitch chat as | {self.nick}")
        channel_name = self.app_settings.get("twitch_channel_name")
        
        try:
            users = await self.fetch_users(names=[channel_name])
            if not users:
                logger.error(f"Channel '{channel_name}' not found.")
                await self.close()
                return
            
            channel_id = users[0].id
            # The token for pubsub does not need the "oauth:" prefix
            pubsub_token = self.app_settings.get("twitch_oauth_token", "")
            topics = [f"channel-points-channel-v1.{channel_id}"]
            await self.pubsub_subscribe(pubsub_token, *topics)
            logger.info(f"Successfully subscribed to channel points events for '{channel_name}'.")
            
            if not self.console_task or self.console_task.done():
                self.console_task = self.loop.create_task(self.console_input_worker())
            
        except Exception as e:
            logger.error(f"A critical error occurred during setup: {e}")
            await self.close()

    async def event_pubsub_channel_points(self, event):
        try:
            reward_title = event.reward.title
            user_name = event.user.name
            key_to_press = self.app_settings.get("rewards", {}).get(reward_title)
            if key_to_press:
                logger.info(f"Reward '{reward_title}' from {user_name} -> Pressing '{key_to_press.upper()}'")
                asyncio.create_task(self.handle_key_action(key_to_press))
            else:
                logger.warning(f"Received an unconfigured reward: '{reward_title}'")
        except Exception as e:
            logger.error(f"Error processing reward: {e}")

    async def handle_key_action(self, key_name: str):
        key = key_name.lower()
        key_behavior = self.app_settings.get("key_behavior", {})
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
        logger.info("Control console is active. Type 'help' for a list of commands.")
        while True:
            try:
                cmd_line = await self.loop.run_in_executor(None, sys.stdin.readline)
                if not self.is_connected: break
                parts = cmd_line.strip().split(maxsplit=2)
                if not parts: continue
                command = parts[0].lower()
                if command == "restart":
                    logger.warning("Restarting connection to Twitch...")
                    self.is_restarting = True
                    await self.close()
                    break
                elif command == "exit":
                    logger.info("Exiting on command...")
                    self.is_restarting = False
                    await self.close()
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
    # This function no longer asks for Client ID
    if not settings.get("twitch_channel_name"):
        settings["twitch_channel_name"] = input("Enter your Twitch channel name: ").strip().lower()

    if not settings.get("twitch_oauth_token"):
        print("\n--- GETTING OAuth TOKEN ---")
        print("A browser will now open to generate a token.")
        print("1. On the website, click 'Custom Scope Token'.")
        print("2. Check ONLY the box next to 'channel:read:redemptions'.")
        print("3. Click 'Generate Token!' and authorize.")
        print("4. Copy the Access Token (the long string of characters).")
        input("Press Enter to open the browser...")
        webbrowser.open("https://twitchtokengenerator.com/")
        settings["twitch_oauth_token"] = input("Paste your OAuth token here: ").strip()
        
    settings.setdefault("rewards", {"Example Reward": "space"})
    settings.setdefault("key_behavior", {})
    save_settings(settings)
    logger.info("Initial setup complete. Starting the bot...")
    return True

# --- MAIN EXECUTION BLOCK ---
def main():
    while True:
        settings = load_settings()
        # The check no longer includes client_id
        if not all(k in settings for k in ["twitch_channel_name", "twitch_oauth_token"]):
            if not initial_setup(settings): break
        
        bot = TwitchBot(settings)
        
        logger.warning("=" * 60); logger.warning("Bot is starting..."); logger.warning("=" * 60)
        
        try:
            bot.run()
        except Exception as e:
            if "Login unsuccessful" in str(e):
                logger.error("AUTHORIZATION FAILED. The token is likely invalid or expired.")
                settings["twitch_oauth_token"] = "" # Clear the bad token
                save_settings(settings)
                logger.info("Invalid token has been cleared. Please restart the bot to enter a new one.")
            else:
                logger.error(f"An unhandled error occurred: {e}")
            break

        if not bot.is_restarting:
            break
        logger.info("Restarting bot in 3 seconds..."); asyncio.run(asyncio.sleep(3))

    logger.info("Program has terminated.")

if __name__ == "__main__":
    main()

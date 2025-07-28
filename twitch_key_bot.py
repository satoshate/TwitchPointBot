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
twitch_client = None
RESTART_FLAG = False

# --- SETTINGS MANAGEMENT ---
def load_settings():
    global app_settings
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                app_settings = json.load(f)
            logger.info(f"Settings successfully loaded from {SETTINGS_FILE}")
        except (json.JSONDecodeError, KeyError):
            logger.error(f"File {SETTINGS_FILE} is corrupted. New settings will be requested.")
            app_settings = {}
    else:
        logger.info(f"File {SETTINGS_FILE} not found. Starting initial setup.")
        app_settings = {}

def save_settings():
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(app_settings, f, ensure_ascii=False, indent=4)
    logger.info(f"Settings saved to {SETTINGS_FILE}")

def initial_setup():
    global app_settings
    if not app_settings.get("twitch_channel_name"):
        app_settings["twitch_channel_name"] = input("Enter your Twitch channel name: ").strip().lower()
    if not app_settings.get("twitch_oauth_token"):
        print("\n--- GETTING OAuth TOKEN ---")
        print("A browser will now open to generate a token.")
        print("1. On the website, click 'Custom Scope Token'.")
        print("2. Check the ONE box next to 'channel:read:redemptions'.")
        print("3. Click 'Generate Token!' and authorize.")
        print("4. Copy the 'Access Token' and paste it here.")
        if input("Press Enter to open the browser..."): pass
        webbrowser.open("https://twitchtokengenerator.com/")
        app_settings["twitch_oauth_token"] = input("Paste your OAuth token here: ").strip()
    app_settings.setdefault("rewards", {"Example Reward": "space"})
    app_settings.setdefault("key_behavior", {
        "hold_duration_seconds": 1.0,
        "hold_keys": ["w", "a", "s", "d"],
        "single_press_keys": ["e", "r", "f", "g", "q", "space", "lmb", "rmb"]
    })
    save_settings()
    logger.info("Initial setup complete. Starting the bot...")
    return True

# --- CORE BOT LOGIC ---
async def handle_key_action(key_name: str):
    key = key_name.lower()
    key_behavior = app_settings.get("key_behavior", {})
    try:
        if key in key_behavior.get('hold_keys', []):
            hold_time = float(key_behavior.get('hold_duration_seconds', 1.0))
            keyboard.press(key)
            logger.info(f"HOLD: Holding key '{key.upper()}' for {hold_time} sec...")
            await asyncio.sleep(hold_time)
            keyboard.release(key)
            logger.info(f"RELEASED: Key '{key.upper()}' has been released.")
        elif key in key_behavior.get('single_press_keys', []):
            if key == 'lmb': pyautogui.click(button='left'); logger.info("CLICK: Left Mouse Button.")
            elif key == 'rmb': pyautogui.click(button='right'); logger.info("CLICK: Right Mouse Button.")
            else: keyboard.press_and_release(key); logger.info(f"PRESS: Key '{key.upper()}'.")
        else: logger.warning(f"Action for key '{key.upper()}' is not defined.")
    except Exception as e: logger.error(f"Error while pressing key '{key.upper()}': {e}")

async def on_channel_points(data: dict):
    try:
        reward_data = data.get('data', {}).get('redemption', {})
        if not reward_data: return
        reward_title = reward_data.get('reward', {}).get('title')
        user_name = reward_data.get('user', {}).get('display_name')
        key_to_press = app_settings.get("rewards", {}).get(reward_title)
        if key_to_press:
            logger.info(f"Reward '{reward_title}' from {user_name} -> Pressing '{key_to_press.upper()}'")
            asyncio.create_task(handle_key_action(key_to_press))
        else:
            logger.warning(f"Received an unconfigured reward: '{reward_title}'")
    except Exception as e:
        logger.error(f"Error processing reward: {e}")

# --- INTERACTIVE CONSOLE ---
async def console_input_worker():
    global RESTART_FLAG
    loop = asyncio.get_event_loop()
    logger.info("Control console is active. Type 'help' for a list of commands.")
    while True:
        try:
            cmd_line = await loop.run_in_executor(None, sys.stdin.readline)
            parts = cmd_line.strip().split(maxsplit=2)
            if not parts: continue
            command = parts[0].lower()
            if command == "help":
                print("\n--- CONSOLE COMMANDS ---")
                print("  status                   - Show current settings")
                print("  reward add \"<name>\" <key> - Add/edit a reward binding")
                print("  reward remove \"<name>\"      - Remove a reward binding")
                print("  holdkey add/remove <key> - Manage the HOLD keys list")
                print("  presskey add/remove <key>- Manage the PRESS keys list")
                print("  holdtime <number>        - Set the hold duration in seconds")
                print("  restart                  - Restart the connection to Twitch")
                print("  exit                     - Exit the program")
                print("--------------------------\n")
            elif command == "status":
                print("\n--- CURRENT SETTINGS ---")
                status_settings = app_settings.copy()
                if 'twitch_oauth_token' in status_settings and status_settings['twitch_oauth_token']:
                    status_settings['twitch_oauth_token'] = f"***{status_settings['twitch_oauth_token'][-4:]}"
                print(json.dumps(status_settings, ensure_ascii=False, indent=4))
                print("------------------------\n")
            elif command == "reward" and len(parts) > 2:
                action = parts[1].lower()
                try:
                    reward_name = cmd_line.strip().split('"', 2)[1]
                    if action == "add":
                        key_to_bind = cmd_line.strip().split('"', 2)[2].strip()
                        if not key_to_bind: raise IndexError
                        app_settings["rewards"][reward_name] = key_to_bind
                        logger.info(f"Reward '{reward_name}' is now bound to key '{key_to_bind}'.")
                    elif action == "remove":
                        if reward_name in app_settings["rewards"]:
                            del app_settings["rewards"][reward_name]
                            logger.info(f"Binding for reward '{reward_name}' has been removed.")
                        else: logger.warning(f"Reward '{reward_name}' not found.")
                    save_settings()
                except IndexError: logger.warning("Format: reward add/remove \"Reward Name\" <key>")
            elif command in ["holdkey", "presskey"] and len(parts) > 2:
                key_list_name = f"{command}s"
                action, key = parts[1].lower(), parts[2].lower()
                if action == "add" and key not in app_settings["key_behavior"][key_list_name]:
                    app_settings["key_behavior"][key_list_name].append(key)
                    logger.info(f"Key '{key}' added to '{key_list_name}'.")
                elif action == "remove" and key in app_settings["key_behavior"][key_list_name]:
                    app_settings["key_behavior"][key_list_name].remove(key)
                    logger.info(f"Key '{key}' removed from '{key_list_name}'.")
                else: logger.warning(f"Action failed (key already in/not in list).")
                save_settings()
            elif command == "holdtime" and len(parts) > 1:
                try:
                    app_settings["key_behavior"]["hold_duration_seconds"] = float(parts[1])
                    logger.info(f"Hold time set to {parts[1]} seconds.")
                    save_settings()
                except ValueError: logger.warning("Invalid number for time.")
            elif command == "restart":
                logger.warning("Restarting connection to Twitch...")
                RESTART_FLAG = True
                if twitch_client: await twitch_client.close()
                break
            elif command == "exit":
                logger.info("Exiting on command...")
                RESTART_FLAG = False
                if twitch_client: await twitch_client.close()
                break
            else: logger.warning(f"Unknown command. Type 'help'.")
        except Exception as e: logger.error(f"Error in console: {e}")

# --- MAIN LOOP ---
async def main_loop():
    global twitch_client, RESTART_FLAG
    load_settings()
    if not app_settings.get("twitch_channel_name") or not app_settings.get("twitch_oauth_token"):
        initial_setup()
    while True:
        RESTART_FLAG = False
        channel_name = app_settings.get("twitch_channel_name")
        token = app_settings.get("twitch_oauth_token")
        
        # This is the corrected line
        twitch_client = Client(token=token) 
        
        pubsub_pool = PubSubPool(twitch_client)
        topic_str = "channel-points-channel-v1"
        console_task = asyncio.create_task(console_input_worker())
        try:
            users = await twitch_client.fetch_users(names=[channel_name])
            if not users:
                logger.error(f"Channel '{channel_name}' not found.")
                break
            channel_id = users[0].id
            # The token is not needed here for this library version
            await pubsub_pool.subscribe_topic(f"{topic_str}.{channel_id}", on_channel_points)
            logger.info(f"Successfully subscribed to channel points events for '{channel_name}'.")
            logger.warning("=" * 60)
            logger.warning("Bot is running. To stop, press Ctrl+C or type 'exit'.")
            logger.warning("=" * 60)
            await console_task
        except Exception as e:
            if "401" in str(e):
                logger.error("AUTHORIZATION ERROR (401). Your OAuth token is invalid.")
                app_settings["twitch_oauth_token"] = ""
                save_settings()
                logger.info("Invalid token has been cleared. Please restart the bot to enter a new one.")
            else: logger.error(f"A critical error occurred: {e}")
            if not console_task.done(): console_task.cancel()
            break
        finally:
            if twitch_client and not twitch_client.is_closed():
                await pubsub_pool.unsubscribe_topic(f"{topic_str}.{channel_id}")
                await twitch_client.close()
        if not RESTART_FLAG: break
    logger.info("Program has terminated.")

if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logger.info("\nScript stopped by user (Ctrl+C).")

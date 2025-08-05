import asyncio
import json
import logging
import os
import re
import sys
import webbrowser
import aiohttp
import websockets
import pyautogui
import keyboard
import pygame

# --- CONFIGURATION & LOGGING ---
SETTINGS_FILE = "bot_settings.json"
logging.basicConfig(
    # ### ИЗМЕНЕНИЕ ###: Включаем DEBUG-логи для отладки
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
STOP_EVENT = asyncio.Event()
RESTART_FLAG = False

# --- SOUND MANAGEMENT ---
try:
    # ### ИЗМЕНЕНИЕ ###: Предварительная инициализация для лучшей совместимости
    pygame.mixer.pre_init(44100, -16, 2, 512)
    pygame.mixer.init()
    logger.info("Pygame mixer initialized successfully for sound playback.")
except Exception as e:
    logger.error(f"Failed to initialize pygame mixer: {e}. Sound will not be available.")
    pygame = None

def trigger_sound(sound_file):
    """Stops any currently playing sound and starts a new one using pygame.mixer.Sound."""
    if not pygame or not pygame.mixer.get_init():
        logger.warning("Pygame mixer is not available. Skipping sound.")
        return
        
    # ### ИЗМЕНЕНИЕ ###: Улучшенная диагностика пути к файлу
    full_path = os.path.abspath(sound_file)
    logger.debug(f"Attempting to play sound from full path: {full_path}")
    
    if not os.path.exists(full_path):
        logger.warning(f"Sound file not found at: {full_path}")
        return

    try:
        # ### ИЗМЕНЕНИЕ ###: Используем pygame.mixer.Sound
        # Останавливаем все предыдущие звуки на всех каналах
        pygame.mixer.stop()
        
        # Загружаем и проигрываем новый звук
        sound = pygame.mixer.Sound(full_path)
        sound.play()
        logger.info(f"Playing sound: {sound_file}")
    except Exception as e:
        logger.error(f"Could not play sound with pygame.mixer.Sound: {e}")

# --- SETTINGS MANAGEMENT ---
def load_settings():
    """Loads settings from the JSON file."""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.error(f"Error decoding {SETTINGS_FILE}. Starting fresh.")
            return {}
    return {}

def save_settings(settings):
    """Saves the current settings to the JSON file."""
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)
    logger.info(f"Settings saved to {SETTINGS_FILE}")

def ensure_defaults(settings):
    """Ensures that default values exist in the settings."""
    settings.setdefault("rewards", {"Example Reward": "space"})
    settings.setdefault("sound_on_redemption", {
        "enabled": True,
        # ### ИЗМЕНЕНИЕ ###: По умолчанию теперь используется OGG
        "sound_file": "sounds/alert.ogg"
    })
    settings.setdefault("key_behavior", {
        "hold_duration_seconds": 1.0,
        "hold_keys": ["w", "a", "s", "d"],
        "single_press_keys": ["e", "r", "f", "g", "q", "space", "lmb", "rmb"]
    })

def initial_setup(settings):
    """Guides the user through the first-time setup process."""
    if not settings.get("twitch_channel_name"):
        settings["twitch_channel_name"] = input("Enter your Twitch channel name: ").strip().lower()
    
    if not settings.get("twitch_client_id"):
        print("\n--- GETTING Client ID ---")
        print("Go to your Twitch Developer Console (dev.twitch.tv/console/apps).")
        while True:
            client_id = input("Paste your Client ID here: ").strip()
            if re.match(r"^[a-zA-Z0-9]{20,}$", client_id):
                settings["twitch_client_id"] = client_id
                break
            else:
                logger.warning("Invalid Client ID format. It should be at least 20 letters and numbers. Please try again.")

    if not settings.get("twitch_oauth_token"):
        client_id = settings.get("twitch_client_id")
        auth_url = (f"https://id.twitch.tv/oauth2/authorize?client_id={client_id}"
                    f"&redirect_uri=http://localhost&response_type=token"
                    f"&scope=channel:read:redemptions+user:read:broadcast")
        
        print("\n--- GETTING OAuth TOKEN ---")
        print("A special URL has been created for you...")
        print(f"\nYOUR URL IS:\n{auth_url}\n")
        
        while True:
            token = input("Paste your freshly generated OAuth token here: ").strip()
            if re.match(r"^[a-z0-9]{20,}$", token):
                settings["twitch_oauth_token"] = token
                break
            else:
                logger.warning("Invalid token format. Please try again.")
    
    ensure_defaults(settings)
    save_settings(settings)
    logger.info("Initial setup complete. Starting the bot...")
    return True

# --- CORE LOGIC ---
async def handle_key_action(key_name: str, settings: dict):
    """Handles the actual key press/hold action."""
    key = key_name.lower()
    key_behavior = settings.get("key_behavior", {})
    try:
        if key in key_behavior.get('hold_keys', []):
            hold_time = float(key_behavior.get('hold_duration_seconds', 1.0))
            keyboard.press(key); await asyncio.sleep(hold_time); keyboard.release(key)
            logger.info(f"ACTION: HOLD/RELEASED '{key.upper()}' for {hold_time}s")
        elif key in key_behavior.get('single_press_keys', []):
            if key == 'lmb': pyautogui.click(button='left'); logger.info("ACTION: CLICK Left Mouse Button.")
            elif key == 'rmb': pyautogui.click(button='right'); logger.info("ACTION: CLICK Right Mouse Button.")
            else: keyboard.press_and_release(key); logger.info(f"ACTION: PRESS Key '{key.upper()}'.")
        else: logger.warning(f"Action for key '{key.upper()}' is not defined in key_behavior settings.")
    except Exception as e: logger.error(f"Error while pressing key '{key.upper()}': {e}")

async def handle_redemption_event(event: dict, settings: dict):
    """Processes a redemption event and triggers actions if a match is found."""
    try:
        reward_title = event.get("reward", {}).get("title")
        user_name = event.get("user_name")
        logger.info(f"EVENT RECEIVED: Reward '{reward_title}' from {user_name}.")
        
        sound_config = settings.get("sound_on_redemption", {})
        if sound_config.get("enabled"):
            trigger_sound(sound_config.get("sound_file"))
        
        key_to_press = settings.get("rewards", {}).get(reward_title)
        if key_to_press:
            logger.info(f"MATCH FOUND: Binding '{reward_title}' -> '{key_to_press}'. Triggering key press.")
            asyncio.create_task(handle_key_action(key_to_press, settings))
        else:
            logger.info(f"NO KEY MATCH: Reward '{reward_title}' is not configured for a key press (sound only).")
    except Exception as e:
        logger.error(f"Error processing reward event: {e}")

# --- TWITCH EVENTSUB LISTENER ---
async def subscribe_to_events(http_session: aiohttp.ClientSession, session_id: str, settings: dict):
    """Creates an EventSub subscription for channel points."""
    token = settings['twitch_oauth_token']
    headers = { "Client-ID": settings["twitch_client_id"], "Authorization": f"Bearer {token}", "Content-Type": "application/json" }
    broadcaster_id = None
    async with http_session.get(f"https://api.twitch.tv/helix/users?login={settings['twitch_channel_name']}", headers=headers) as resp:
        if resp.status != 200: logger.error(f"Failed to get user ID: {resp.status}, {await resp.text()}"); return None
        data = await resp.json();
        if not data.get("data"): logger.error(f"Channel '{settings['twitch_channel_name']}' not found."); return None
        broadcaster_id = data["data"][0]["id"]
        logger.info(f"Got Broadcaster ID: {broadcaster_id}")
    body = { "type": "channel.channel_points_custom_reward_redemption.add", "version": "1", "condition": {"broadcaster_user_id": broadcaster_id}, "transport": {"method": "websocket", "session_id": session_id} }
    async with http_session.post("https://api.twitch.tv/helix/eventsub/subscriptions", headers=headers, json=body) as resp:
        if resp.status != 202: logger.error(f"Failed to create EventSub subscription: {resp.status}, {await resp.text()}"); return False
        logger.info("Successfully created EventSub subscription.")
        return True

async def listen_to_eventsub(http_session: aiohttp.ClientSession, settings: dict):
    """Connects to the EventSub WebSocket and listens for events."""
    global RESTART_FLAG
    ws_url = "wss://eventsub.wss.twitch.tv/ws"
    try:
        async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
            logger.info("Connected to EventSub WebSocket.")
            async for message in ws:
                data = json.loads(message)
                msg_type = data.get("metadata", {}).get("message_type")
                if msg_type == "session_welcome":
                    session_id = data["payload"]["session"]["id"]
                    logger.info(f"Session established: {session_id}")
                    if not await subscribe_to_events(http_session, session_id, settings): logger.error("Subscription failed."); break 
                elif msg_type == "notification": await handle_redemption_event(data["payload"]["event"], settings)
                elif msg_type == "session_reconnect": RESTART_FLAG = True; logger.warning("Reconnect message received. Restarting..."); break
    except asyncio.CancelledError: logger.info("EventSub listener task cancelled.")
    except websockets.exceptions.ConnectionClosed as e:
        logger.error(f"Connection closed: {e.code} {e.reason}")
        if "4001" in str(e.reason) or "4003" in str(e.reason): raise ConnectionRefusedError("Authorization failed")
    except Exception as e: logger.error(f"Critical error in EventSub listener: {e}")
    finally: STOP_EVENT.set()

# --- CONSOLE WORKER ---
async def console_input_worker(settings: dict):
    """Handles user input from the console for live configuration."""
    global RESTART_FLAG
    loop = asyncio.get_event_loop()
    logger.info("Control console is active. Type 'help' for a list of commands.")
    try:
        while not STOP_EVENT.is_set():
            cmd_line = await loop.run_in_executor(None, lambda: input("> "))
            if STOP_EVENT.is_set(): break
            parts = cmd_line.strip().split(maxsplit=2)
            if not parts: continue
            command = parts[0].lower()

            if command == "help":
                print("\n--- CONSOLE COMMANDS ---", flush=True)
                print("  status                   - Show current settings", flush=True)
                print("  reward add \"<name>\" <key> - Add/edit a reward binding for a key press", flush=True)
                print("  reward remove \"<name>\"      - Remove a reward binding", flush=True)
                print("  sound <on|off|path>      - Manage redemption sound (e.g., sound on, sound sounds/new.ogg)", flush=True)
                print("  restart                  - Restart the bot", flush=True)
                print("  exit                     - Exit the program", flush=True)
                print("--------------------------\n", flush=True)

            elif command == "status":
                print("\n--- CURRENT SETTINGS ---", flush=True)
                status_settings = settings.copy()
                if 'twitch_oauth_token' in status_settings: status_settings['twitch_oauth_token'] = f"***{status_settings['twitch_oauth_token'][-4:]}"
                if 'twitch_client_id' in status_settings: status_settings['twitch_client_id'] = f"***{status_settings['twitch_client_id'][-4:]}"
                print(json.dumps(status_settings, ensure_ascii=False, indent=4), flush=True)
                print("------------------------\n", flush=True)
            
            elif command == "reward" and len(parts) >= 3 and parts[1].lower() in ["add", "remove"]:
                action = parts[1].lower()
                try:
                    reward_name = parts[2].split('"', 2)[1]
                    if action == "add":
                        key_to_bind = parts[2].split('"', 2)[2].strip()
                        if not key_to_bind: raise IndexError
                        settings["rewards"][reward_name] = key_to_bind
                        logger.info(f"Reward '{reward_name}' is now bound to key '{key_to_bind}'.")
                    elif action == "remove":
                        if reward_name in settings["rewards"]: del settings["rewards"][reward_name]; logger.info(f"Binding for reward '{reward_name}' removed.")
                        else: logger.warning(f"Reward '{reward_name}' not found.")
                    save_settings(settings)
                except IndexError: logger.warning("Format: reward add/remove \"Reward Name\" <key>")
            
            elif command == "sound" and len(parts) > 1:
                param = parts[1].lower()
                if param == "on": settings["sound_on_redemption"]["enabled"] = True; logger.info("Sound on redemption has been ENABLED.")
                elif param == "off": settings["sound_on_redemption"]["enabled"] = False; logger.info("Sound on redemption has been DISABLED.")
                else: settings["sound_on_redemption"]["sound_file"] = param; logger.info(f"Sound file path set to: {param}")
                save_settings(settings)

            elif command == "restart": logger.warning("Restarting bot..."); RESTART_FLAG = True; STOP_EVENT.set()
            elif command == "exit": logger.info("Exiting on command..."); RESTART_FLAG = False; STOP_EVENT.set()
            else: logger.warning("Unknown command. Type 'help' for a list of commands.")
    except asyncio.CancelledError: pass
    finally: logger.info("Console worker stopped.")

# --- MAIN EXECUTION BLOCK ---
async def main():
    """Main function that orchestrates the bot's lifecycle."""
    global RESTART_FLAG
    logger.warning("=" * 60); logger.warning("Bot is starting..."); logger.warning("=" * 60)
    while True:
        RESTART_FLAG = False
        STOP_EVENT.clear()
        settings = load_settings()
        if not all(k in settings for k in ["twitch_channel_name", "twitch_oauth_token", "twitch_client_id"]):
            if not initial_setup(settings): logger.info("Setup cancelled. Exiting."); return
        
        async with aiohttp.ClientSession() as http_session:
            listen_task = asyncio.create_task(listen_to_eventsub(http_session, settings))
            console_task = asyncio.create_task(console_input_worker(settings))
            done, pending = await asyncio.wait([listen_task, console_task], return_when=asyncio.FIRST_COMPLETED)
            for task in pending: task.cancel()
            try:
                for task in done:
                    if task.exception(): raise task.exception()
            except ConnectionRefusedError:
                logger.error("AUTHORIZATION FAILED. The token is likely invalid or expired.")
                settings["twitch_oauth_token"] = ""; save_settings(settings)
                logger.info("Invalid token has been cleared. Restart the bot."); RESTART_FLAG = False
        
        if not RESTART_FLAG: break
        logger.info("Restarting bot in 3 seconds..."); await asyncio.sleep(3)
    
    logger.info("Program has terminated.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nScript stopped by user (Ctrl+C).")
    finally:
        if pygame and pygame.mixer.get_init():
            pygame.quit()
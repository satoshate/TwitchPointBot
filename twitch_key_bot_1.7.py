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
PAUSE_LOGGING = False

class PauseFilter(logging.Filter):
    """Фильтр, который блокирует логи уровня INFO и DEBUG, если включена пауза."""
    def filter(self, record):
        return not PAUSE_LOGGING or record.levelno > logging.INFO

logger = logging.getLogger(__name__)
logger.addFilter(PauseFilter())
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)
STOP_EVENT = asyncio.Event()
RESTART_FLAG = False

# --- SOUND MANAGEMENT ---
try:
    pygame.mixer.pre_init(44100, -16, 2, 512)
    pygame.mixer.init()
    logger.info("Pygame mixer initialized successfully for sound playback.")
except Exception as e:
    logger.error(f"Failed to initialize pygame mixer: {e}. Sound will not be available.")
    pygame = None

def trigger_sound(sound_file):
    if not pygame or not pygame.mixer.get_init(): return
    full_path = os.path.abspath(sound_file)
    if not os.path.exists(full_path):
        logger.warning(f"Sound file not found at: {full_path}"); return
    try:
        pygame.mixer.stop()
        sound = pygame.mixer.Sound(full_path)
        sound.play()
        logger.info(f"Playing sound: {sound_file}")
    except Exception as e:
        logger.error(f"Could not play sound with pygame.mixer.Sound: {e}")

# --- SETTINGS MANAGEMENT ---
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: return {}
    else: return {}

def save_settings(settings):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f: json.dump(settings, f, ensure_ascii=False, indent=4)
    logger.info(f"Settings saved to {SETTINGS_FILE}")

def ensure_defaults(settings):
    settings.setdefault("rewards", {"Example Reward": "space"})
    if "sound_on_redemption" not in settings:
        settings["sound_on_redemption"] = {"enabled": True, "sound_file": "sounds/alert.ogg"}
    settings.setdefault("key_behavior", {
        "hold_duration_seconds": 1.0,
        "hold_keys": ["w", "a", "s", "d"],
        "single_press_keys": ["e", "r", "f", "g", "q", "space", "lmb", "rmb"]
    })

def initial_setup(settings):
    if not settings.get("twitch_channel_name"):
        settings["twitch_channel_name"] = input("Enter your Twitch channel name: ").strip().lower()
    if not settings.get("twitch_client_id"):
        print("\n--- GETTING Client ID ---")
        print("Go to your Twitch Developer Console (dev.twitch.tv/console/apps).")
        while True:
            client_id = input("Paste your Client ID here: ").strip()
            if re.match(r"^[a-zA-Z0-9]{20,}$", client_id): settings["twitch_client_id"] = client_id; break
            else: logger.warning("Invalid Client ID format. Try again.")
    if not settings.get("twitch_oauth_token"):
        client_id = settings.get("twitch_client_id")
        auth_url = (f"https://id.twitch.tv/oauth2/authorize?client_id={client_id}"
                    f"&redirect_uri=http://localhost&response_type=token"
                    f"&scope=channel:read:redemptions+user:read:broadcast")
        print("\n--- GETTING OAuth TOKEN ---")
        print(f"\nYOUR URL IS:\n{auth_url}\n")
        while True:
            token = input("Paste your freshly generated OAuth token here: ").strip()
            if re.match(r"^[a-z0-9]{20,}$", token): settings["twitch_oauth_token"] = token; break
            else: logger.warning("Invalid token format. Try again.")
    ensure_defaults(settings)
    save_settings(settings)
    logger.info("Initial setup complete. Starting the bot...")
    return True

# --- CORE LOGIC ---
async def handle_key_action(key_name: str, settings: dict):
    """Handles key actions using pyautogui for better compatibility."""
    key = key_name.lower()
    key_behavior = settings.get("key_behavior", {})
    try:
        if key in key_behavior.get('hold_keys', []):
            hold_time = float(key_behavior.get('hold_duration_seconds', 1.0))
            pyautogui.keyDown(key); await asyncio.sleep(hold_time); pyautogui.keyUp(key)
            logger.info(f"ACTION: HOLD/RELEASED '{key.upper()}' for {hold_time}s")
        elif key in key_behavior.get('single_press_keys', []):
            if key == 'lmb': pyautogui.click(button='left'); logger.info("ACTION: CLICK Left Mouse Button.")
            elif key == 'rmb': pyautogui.click(button='right'); logger.info("ACTION: CLICK Right Mouse Button.")
            else: pyautogui.press(key); logger.info(f"ACTION: PRESS Key '{key.upper()}'.")
        else: logger.warning(f"Action for key '{key.upper()}' is not defined.")
    except Exception as e: logger.error(f"Error while pressing key '{key.upper()}': {e}")

async def handle_redemption_event(event: dict, settings: dict):
    try:
        reward_title = event.get("reward", {}).get("title")
        user_name = event.get("user_name")
        logger.info(f"EVENT RECEIVED: Reward '{reward_title}' from {user_name}.")
        sound_config = settings.get("sound_on_redemption", {})
        if sound_config.get("enabled"): trigger_sound(sound_config.get("sound_file"))
        key_to_press = settings.get("rewards", {}).get(reward_title)
        if key_to_press:
            logger.info(f"MATCH FOUND: Binding '{reward_title}' -> '{key_to_press}'. Triggering key press.")
            asyncio.create_task(handle_key_action(key_to_press, settings))
        else:
            logger.info(f"NO KEY MATCH: Reward '{reward_title}' (sound only).")
    except Exception as e: logger.error(f"Error processing reward event: {e}")

# --- TWITCH EVENTSUB LISTENER ---
async def subscribe_to_events(http_session: aiohttp.ClientSession, session_id: str, settings: dict):
    token = settings['twitch_oauth_token']
    headers = { "Client-ID": settings["twitch_client_id"], "Authorization": f"Bearer {token}", "Content-Type": "application/json" }
    broadcaster_id = None
    try:
        async with http_session.get(f"https://api.twitch.tv/helix/users?login={settings['twitch_channel_name']}", headers=headers, timeout=10) as resp:
            if resp.status != 200: logger.error(f"Failed to get user ID: {resp.status} {await resp.text()}"); return None
            data = await resp.json()
            if not data.get("data"): logger.error(f"Channel '{settings['twitch_channel_name']}' not found."); return None
            broadcaster_id = data["data"][0]["id"]
            logger.info(f"Got Broadcaster ID: {broadcaster_id}")
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.error(f"HTTP error getting user ID: {e}"); return None

    body = { "type": "channel.channel_points_custom_reward_redemption.add", "version": "1", "condition": {"broadcaster_user_id": broadcaster_id}, "transport": {"method": "websocket", "session_id": session_id} }
    try:
        async with http_session.post("https://api.twitch.tv/helix/eventsub/subscriptions", headers=headers, json=body, timeout=10) as resp:
            if resp.status != 202: logger.error(f"Failed to create EventSub subscription: {resp.status} {await resp.text()}"); return False
            logger.info("Successfully created EventSub subscription.")
            return True
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.error(f"HTTP error creating subscription: {e}"); return False

async def listen_to_eventsub(http_session: aiohttp.ClientSession, settings: dict):
    ws_url = "wss://eventsub.wss.twitch.tv/ws"
    reconnect_delay = 1
    while not STOP_EVENT.is_set():
        try:
            async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20, close_timeout=1) as ws:
                logger.info("Connected to EventSub WebSocket.")
                reconnect_delay = 1 # Сбрасываем задержку при успешном подключении
                async for message in ws:
                    data = json.loads(message)
                    msg_type = data.get("metadata", {}).get("message_type")
                    if msg_type == "session_welcome":
                        session_id = data["payload"]["session"]["id"]
                        logger.info(f"Session established: {session_id}")
                        if not await subscribe_to_events(http_session, session_id, settings):
                            logger.error("Subscription failed. Retrying connection..."); break 
                    elif msg_type == "notification": await handle_redemption_event(data["payload"]["event"], settings)
                    elif msg_type == "session_reconnect": logger.warning("Reconnect message received. Restarting connection..."); break
        except asyncio.CancelledError: logger.info("EventSub listener task cancelled."); break
        except websockets.exceptions.ConnectionClosed as e:
            if "4001" in str(e.reason) or "4003" in str(e.reason): raise ConnectionRefusedError("Authorization failed")
            logger.warning(f"Connection closed unexpectedly: {e.code}. Retrying in {reconnect_delay}s...")
        except Exception as e: logger.error(f"Critical error in EventSub listener: {e}. Retrying in {reconnect_delay}s...")
        
        await asyncio.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 2, 60) # Экспоненциальная задержка до 60 секунд
    STOP_EVENT.set()

# --- CONSOLE WORKER ---
async def console_input_worker(settings: dict):
    global RESTART_FLAG, PAUSE_LOGGING
    loop = asyncio.get_event_loop()
    logger.info("Control console is active. Type 'help' for a list of commands.")
    try:
        while not STOP_EVENT.is_set():
            cmd_line = await loop.run_in_executor(None, lambda: input("> " if not PAUSE_LOGGING else "(PAUSED) > "))
            if STOP_EVENT.is_set(): break
            parts = cmd_line.strip().split(maxsplit=2)
            if not parts: continue
            command = parts[0].lower()
            if command == "help":
                print("\n--- CONSOLE COMMANDS ---", flush=True)
                print("  status                   - Show current settings", flush=True)
                print("  reward add \"<name>\" <key> - Add/edit a reward binding", flush=True)
                print("  reward remove \"<name>\"      - Remove a reward binding", flush=True)
                print("  sound <on|off|path>      - Manage redemption sound", flush=True)
                print("  pause                    - Pause INFO/DEBUG logs to enter commands", flush=True)
                print("  unpause                  - Resume logging", flush=True)
                print("  restart                  - Restart the bot", flush=True)
                print("  exit                     - Exit the program", flush=True)
                print("--------------------------\n", flush=True)
            elif command == "pause": PAUSE_LOGGING = True; print("Logging is paused. Type 'unpause' to resume.", flush=True)
            elif command == "unpause": PAUSE_LOGGING = False; logger.info("Logging has been resumed.")
            elif command == "restart": logger.warning("Restarting bot..."); RESTART_FLAG = True; STOP_EVENT.set()
            elif command == "exit": logger.info("Exiting on command..."); RESTART_FLAG = False; STOP_EVENT.set()
            else:
                logger.warning(f"Unknown command: '{command}'. Type 'help' for assistance.")
    except asyncio.CancelledError: pass
    finally: logger.info("Console worker stopped.")

# --- MAIN EXECUTION BLOCK ---
async def main():
    global RESTART_FLAG
    logger.warning("=" * 60); logger.warning("Bot is starting..."); logger.warning("=" * 60)
    while True:
        RESTART_FLAG = False
        STOP_EVENT.clear()
        settings = load_settings()
        ensure_defaults(settings)
        if not all(k in settings for k in ["twitch_channel_name", "twitch_oauth_token", "twitch_client_id"]) or \
           not settings.get("twitch_channel_name") or not settings.get("twitch_oauth_token"):
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
    try: asyncio.run(main())
    except KeyboardInterrupt: logger.info("\nScript stopped by user (Ctrl+C).")
    finally:
        if pygame and pygame.mixer.get_init(): pygame.quit()

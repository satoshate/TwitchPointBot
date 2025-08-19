import asyncio
import json
import logging
import os
import re
import shlex
import sys
import webbrowser
from time import time
import aiohttp
import websockets
import pyautogui
import pygame

# --- CONFIGURATION & LOGGING ---
SETTINGS_FILE = "bot_settings.json"
PAUSE_LOGGING = False

class PauseFilter(logging.Filter):
    def filter(self, record):
        return not PAUSE_LOGGING or record.levelno > logging.INFO

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
logger.addFilter(PauseFilter())

STOP_EVENT = asyncio.Event()
RESTART_FLAG = False

# --- PREFERRED LIBRARIES SETUP ---
try:
    import pydirectinput
    pydirectinput.FAILSAFE = False; pydirectinput.PAUSE = 0
    INPUT_LIB = pydirectinput
    logger.info("Using pydirectinput for input emulation (recommended for games).")
except ImportError:
    pyautogui.FAILSAFE = False; pyautogui.PAUSE = 0
    INPUT_LIB = pyautogui
    logger.warning("pydirectinput not found, falling back to pyautogui (may not work in some games).")

try:
    import pygetwindow as gw
    logger.info("pygetwindow is available for window focusing.")
except ImportError:
    gw = None; logger.warning("pygetwindow not found, window focusing disabled.")

try:
    import psutil
except ImportError:
    psutil = None; logger.warning("psutil not found, automatic game window detection disabled.")

# --- KEY ALIASES ---
KEY_ALIASES = {
    "spacebar": "space", "space": "space", "enter": "enter", "return": "enter",
    "ctrl": "ctrl", "control": "ctrl", "lmb": "lmb", "rmb": "rmb"
}

# --- RATE LIMITING ---
_LAST_TRIGGER = {}
RATE_LIMIT_SECONDS = 1.0

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
    focus_behavior = settings.setdefault("focus_behavior", {})
    focus_behavior.setdefault("auto_focus_enabled", True)
    focus_behavior.setdefault("manual_focus_title", "")
    known_games = focus_behavior.setdefault("known_game_processes", ["RobloxPlayerBeta.exe", "cs2.exe", "dota2.exe"])
    focus_behavior["known_game_processes"] = sorted(list(set(known_games)))

def initial_setup(settings):
    if not settings.get("twitch_channel_name"):
        while True:
            name = input("Enter your Twitch channel name: ").strip().lower()
            if name: settings["twitch_channel_name"] = name; break
            logger.warning("Channel name cannot be empty.")
    
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

# --- WINDOW FOCUS & KEY ACTION ---
_active_game_window = None

async def auto_detect_game_window(known_processes):
    global _active_game_window
    if not gw or not psutil: return
    while not STOP_EVENT.is_set():
        try:
            active_windows = gw.getAllTitles()
            running_processes = {p.name() for p in psutil.process_iter(['name'])}
            found_window = None
            for proc_name in known_processes:
                if proc_name in running_processes:
                    proc_base_name = proc_name.split('.')[0].lower()
                    for title in active_windows:
                        if title and proc_base_name in title.lower():
                            wins = gw.getWindowsWithTitle(title)
                            if wins: found_window = wins[0]; break
                    if found_window: break
            if found_window and (_active_game_window is None or _active_game_window.title != found_window.title):
                 _active_game_window = found_window; logger.info(f"Auto-detected game window: '{found_window.title}'")
            elif not found_window and _active_game_window is not None:
                logger.info("Previously detected game window closed."); _active_game_window = None
        except Exception as e:
            logger.debug(f"Error during game window auto-detection: {e}")
        await asyncio.sleep(5)

def focus_window(settings):
    global _active_game_window # ### ОБЯЗАТЕЛЬНОЕ ИСПРАВЛЕНИЕ ###
    if not gw: return False
    manual_title = settings.get("focus_behavior", {}).get("manual_focus_title")
    target_win = None
    if manual_title:
        wins = gw.getWindowsWithTitle(manual_title)
        if wins: target_win = wins[0]
        else: logger.warning(f"Manual focus window '{manual_title}' not found."); return False
    elif settings.get("focus_behavior", {}).get("auto_focus_enabled") and _active_game_window:
        try:
            if _active_game_window.title in gw.getAllTitles(): target_win = _active_game_window
            else: _active_game_window = None; return False
        except: _active_game_window = None; return False
    if not target_win: return False
    try:
        if target_win.isMinimized: target_win.restore()
        target_win.activate()
        logger.debug(f"Activated window: {target_win.title}")
        return True
    except Exception as e:
        logger.error(f"Failed to activate window '{target_win.title}': {e}")
        return False

async def safe_press(key):
    """Safely presses a key, trying different methods as a fallback."""
    if hasattr(INPUT_LIB, "press"):
        INPUT_LIB.press(key)
    elif hasattr(INPUT_LIB, "keyDown") and hasattr(INPUT_LIB, "keyUp"):
        INPUT_LIB.keyDown(key)
        await asyncio.sleep(0.01)
        INPUT_LIB.keyUp(key)
    else: # Ultimate fallback
        pyautogui.press(key)

async def handle_key_action(key_name: str, settings: dict):
    key = (key_name or "").lower()
    key = KEY_ALIASES.get(key, key)
    if not key: logger.warning("Empty key requested."); return
    if focus_window(settings):
        await asyncio.sleep(0.05)
    else:
        logger.debug("Could not focus any game window. Key press will be sent to the active window.")
    
    logger.debug(f"Using input lib: {getattr(INPUT_LIB, '__name__', 'pyautogui_fallback')} to send key '{key}'")
    try:
        key_behavior = settings.get("key_behavior", {})
        if key in key_behavior.get('hold_keys', []):
            hold_time = float(key_behavior.get('hold_duration_seconds', 1.0))
            INPUT_LIB.keyDown(key); await asyncio.sleep(hold_time); INPUT_LIB.keyUp(key)
            logger.info(f"ACTION: HOLD/RELEASED '{key.upper()}' for {hold_time}s")
        elif key in key_behavior.get('single_press_keys', []):
            if hasattr(INPUT_LIB, "click") and key in ['lmb', 'rmb']:
                button = 'left' if key == 'lmb' else 'right'
                INPUT_LIB.click(button=button); logger.info(f"ACTION: CLICK {button.title()} Mouse Button.")
            else:
                await safe_press(key); logger.info(f"ACTION: PRESS Key '{key.upper()}'.")
        else:
            logger.warning(f"Action for key '{key.upper()}' is not defined.")
    except Exception as e:
        logger.error(f"Error while pressing key '{key.upper()}': {e}")

# --- EVENT HANDLING & MAIN LOGIC ---
async def handle_redemption_event(event: dict, settings: dict):
    try:
        reward_title = event.get("reward", {}).get("title")
        user_name = event.get("user_name")
        logger.info(f"EVENT RECEIVED: Reward '{reward_title}' from {user_name}.")
        norm_title = (reward_title or "").strip().lower()
        now = time()
        last = _LAST_TRIGGER.get(norm_title, 0)
        if now - last < RATE_LIMIT_SECONDS:
            logger.info(f"Throttled reward '{reward_title}' (last trigger {now - last:.2f}s ago).")
            return
        _LAST_TRIGGER[norm_title] = now
        sound_config = settings.get("sound_on_redemption", {})
        if sound_config.get("enabled"): trigger_sound(sound_config.get("sound_file"))
        
        rewards = {k.strip().lower(): v for k, v in settings.get("rewards", {}).items()}
        key_to_press = rewards.get(norm_title)
        
        if key_to_press:
            logger.info(f"MATCH FOUND: Binding '{reward_title}' -> '{key_to_press}'. Triggering key press.")
            asyncio.create_task(handle_key_action(key_to_press, settings))
        else:
            logger.info(f"NO KEY MATCH: Reward '{reward_title}' (sound only).")
    except Exception as e: logger.error(f"Error processing reward event: {e}")

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
            async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20, close_timeout=5) as ws:
                logger.info("Connected to EventSub WebSocket.")
                reconnect_delay = 1
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
            logger.warning(f"Connection closed unexpectedly: {getattr(e, 'code', '?')}. Retrying in {reconnect_delay}s...")
        except Exception as e: logger.error(f"Critical error in EventSub listener: {e}. Retrying in {reconnect_delay}s...")
        await asyncio.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 2, 60)
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
            parts = cmd_line.strip().split(maxsplit=1)
            if not parts: continue
            command, arg = parts[0].lower(), (parts[1] if len(parts) > 1 else "")
            
            if command == "help":
                print("\n--- CONSOLE COMMANDS ---", flush=True)
                print("  status                   - Show current settings", flush=True)
                print('  reward add "name" <key>  - Add/edit a reward binding', flush=True)
                print('  reward remove "name"       - Remove a reward binding', flush=True)
                print("  sound <on|off|path>      - Manage redemption sound", flush=True)
                print("  focus <title>            - Manually set window title (empty to clear)", flush=True)
                print("  focus auto <on|off>      - Enable/disable automatic game window detection", flush=True)
                print("  focus add <process.exe>  - Add a game process to auto-detection list", flush=True)
                print("  pause                    - Pause INFO/DEBUG logs to enter commands", flush=True)
                print("  unpause                  - Resume logging", flush=True)
                print("  restart                  - Restart the bot", flush=True)
                print("  exit                     - Exit the program", flush=True)
                print("--------------------------\n", flush=True)

            elif command == "pause": PAUSE_LOGGING = True; print("Logging is paused. Type 'unpause' to resume.", flush=True)
            elif command == "unpause": PAUSE_LOGGING = False; logger.info("Logging has been resumed.")
            elif command == "status":
                display = settings.copy()
                if 'twitch_oauth_token' in display: display['twitch_oauth_token'] = f"***{display['twitch_oauth_token'][-4:]}"
                if 'twitch_client_id' in display: display['twitch_client_id'] = f"***{display['twitch_client_id'][-4:]}"
                print(json.dumps(display, ensure_ascii=False, indent=4), flush=True)
            
            elif command == "reward":
                try:
                    tokens = shlex.split(arg)
                    if not tokens: raise ValueError
                    action = tokens[0].lower()
                    if action == "add" and len(tokens) >= 3:
                        reward_name, key_to_bind = tokens[1], tokens[2]
                        settings["rewards"][reward_name] = key_to_bind
                        save_settings(settings); logger.info(f"Reward '{reward_name}' bound to '{key_to_bind}'.")
                    elif action == "remove" and len(tokens) >= 2:
                        reward_name_to_remove = tokens[1]
                        found_key = None
                        norm_remove_name = reward_name_to_remove.strip().lower()
                        for k in list(settings.get("rewards", {}).keys()):
                            if k.strip().lower() == norm_remove_name:
                                found_key = k; break
                        if found_key:
                            del settings["rewards"][found_key]; save_settings(settings)
                            logger.info(f"Removed reward binding for '{found_key}'.")
                        else:
                            logger.warning(f"Reward '{reward_name_to_remove}' not found.")
                    else:
                        raise ValueError
                except Exception:
                    logger.warning('Format: reward add/remove "Reward Name" <key>')
            
            elif command == "sound" and arg:
                param = arg.strip()
                if "sound_on_redemption" not in settings: settings["sound_on_redemption"] = {}
                if param.lower() == "on": settings["sound_on_redemption"]["enabled"] = True; logger.info("Sound on redemption ENABLED.")
                elif param.lower() == "off": settings["sound_on_redemption"]["enabled"] = False; logger.info("Sound on redemption DISABLED.")
                else: settings["sound_on_redemption"]["sound_file"] = param; logger.info(f"Sound file set to: {param}")
                save_settings(settings)
            
            elif command == "focus":
                val = arg.strip()
                if not val:
                    settings["focus_behavior"]["manual_focus_title"] = ""
                    save_settings(settings); logger.info("Manual focus title cleared.")
                else:
                    parts = val.split(maxsplit=1)
                    sub = parts[0].lower()
                    rest = parts[1] if len(parts) > 1 else ""
                    if sub == "auto":
                        if rest.lower() == "on": settings["focus_behavior"]["auto_focus_enabled"] = True; logger.info("Auto-focus ENABLED.")
                        elif rest.lower() == "off": settings["focus_behavior"]["auto_focus_enabled"] = False; logger.info("Auto-focus DISABLED.")
                        else: logger.warning("Usage: focus auto <on|off>")
                    elif sub == "add":
                        if rest and rest.endswith(".exe"):
                            lst = settings["focus_behavior"].setdefault("known_game_processes", [])
                            if rest not in lst:
                                lst.append(rest); logger.info(f"Process '{rest}' added to auto-detection.")
                            else:
                                logger.info(f"Process '{rest}' already in list.")
                        else: logger.warning("Usage: focus add <process.exe>")
                    else:
                        settings["focus_behavior"]["manual_focus_title"] = val
                        logger.info(f"Manual window focus title set to: '{val}'")
                    save_settings(settings)

            elif command == "restart": logger.warning("Restarting bot..."); RESTART_FLAG = True; STOP_EVENT.set()
            elif command == "exit": logger.info("Exiting on command..."); RESTART_FLAG = False; STOP_EVENT.set()
            else: logger.warning(f"Unknown command: '{command}'. Type 'help' for assistance.")
    except asyncio.CancelledError: pass
    finally: logger.info("Console worker stopped.")

# --- MAIN EXECUTION BLOCK ---
async def main():
    global RESTART_FLAG
    logger.warning("=" * 60); logger.warning("Bot is starting..."); logger.warning("=" * 60)
    while True:
        RESTART_FLAG = False; STOP_EVENT.clear()
        settings = load_settings()
        ensure_defaults(settings)
        if not all(k in settings for k in ["twitch_channel_name", "twitch_oauth_token", "twitch_client_id"]) or \
           not settings.get("twitch_channel_name") or not settings.get("twitch_oauth_token"):
            if not initial_setup(settings): logger.info("Setup cancelled. Exiting."); return
        
        detector_task = asyncio.create_task(auto_detect_game_window(settings["focus_behavior"]["known_game_processes"]))
        async with aiohttp.ClientSession() as http_session:
            listen_task = asyncio.create_task(listen_to_eventsub(http_session, settings))
            console_task = asyncio.create_task(console_input_worker(settings))
            
            done, pending = await asyncio.wait([listen_task, console_task], return_when=asyncio.FIRST_COMPLETED)
            
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

            detector_task.cancel()
            await asyncio.gather(detector_task, return_exceptions=True)
            
            try:
                for task in done:
                    if task.exception(): raise task.exception()
            except ConnectionRefusedError:
                logger.error("AUTHORIZATION FAILED..."); settings["twitch_oauth_token"] = ""; save_settings(settings); RESTART_FLAG = False
        if not RESTART_FLAG: break
        logger.info("Restarting bot in 3 seconds..."); await asyncio.sleep(3)
    logger.info("Program has terminated.")

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: logger.info("\nScript stopped by user (Ctrl-C).")
    finally:
        if pygame and pygame.mixer.get_init(): pygame.quit()

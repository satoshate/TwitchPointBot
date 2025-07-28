import asyncio
import json
import logging
import os
import sys
import uuid
import webbrowser
import aiohttp
import websockets
import pyautogui
import keyboard

# --- CONFIGURATION & LOGGING ---
SETTINGS_FILE = "bot_settings.json"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
RESTART_FLAG = False

# --- SETTINGS MANAGEMENT ---
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
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
        settings["twitch_client_id"] = input("Paste your Client ID here: ").strip()
    if not settings.get("twitch_oauth_token"):
        print("\n--- GETTING OAuth TOKEN ---")
        print("A browser will now open. On the website:")
        print("1. Click 'Custom Scope Token'.")
        print("2. Check TWO boxes: 'channel:read:redemptions' AND 'user:read:broadcast'.")
        print("3. Click 'Generate Token!' and authorize.")
        input("Press Enter to open the browser...")
        webbrowser.open("https://twitchtokengenerator.com/")
        settings["twitch_oauth_token"] = input("Paste your OAuth token here: ").strip()
    settings.setdefault("rewards", {"Example Reward": "space"})
    settings.setdefault("key_behavior", {
        "hold_duration_seconds": 1.0,
        "hold_keys": ["w", "a", "s", "d"],
        "single_press_keys": ["e", "r", "f", "g", "q", "space", "lmb", "rmb"]
    })
    save_settings(settings)
    logger.info("Initial setup complete. Starting the bot...")
    return True

# --- CORE LOGIC ---
async def handle_key_action(key_name: str, settings: dict):
    key = key_name.lower()
    key_behavior = settings.get("key_behavior", {})
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

async def handle_redemption_event(event: dict, settings: dict):
    try:
        reward_title = event.get("reward", {}).get("title")
        user_name = event.get("user_name")
        key_to_press = settings.get("rewards", {}).get(reward_title)
        if key_to_press:
            logger.info(f"Reward '{reward_title}' from {user_name} -> Pressing '{key_to_press.upper()}'")
            asyncio.create_task(handle_key_action(key_to_press, settings))
        else:
            logger.warning(f"Received an unconfigured reward: '{reward_title}'")
    except Exception as e:
        logger.error(f"Error processing reward: {e}")

async def subscribe_to_events(session_id: str, settings: dict):
    headers = {
        "Client-ID": settings["twitch_client_id"],
        "Authorization": f"Bearer {settings['twitch_oauth_token']}",
        "Content-Type": "application/json"
    }
    # 1. Get broadcaster ID
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://api.twitch.tv/helix/users?login={settings['twitch_channel_name']}", headers=headers) as resp:
            if resp.status != 200:
                logger.error(f"Failed to get user ID. Status: {resp.status}, Response: {await resp.text()}")
                return None
            data = await resp.json()
            if not data.get("data"):
                logger.error(f"Channel '{settings['twitch_channel_name']}' not found.")
                return None
            broadcaster_id = data["data"][0]["id"]
            logger.info(f"Got Broadcaster ID: {broadcaster_id}")

    # 2. Create EventSub subscription
    body = {
        "type": "channel.channel_points_custom_reward_redemption.add",
        "version": "1",
        "condition": {"broadcaster_user_id": broadcaster_id},
        "transport": {"method": "websocket", "session_id": session_id}
    }
    async with aiohttp.ClientSession() as session:
        async with session.post("https://api.twitch.tv/helix/eventsub/subscriptions", headers=headers, json=body) as resp:
            if resp.status != 202:
                logger.error(f"Failed to create EventSub subscription. Status: {resp.status}, Response: {await resp.text()}")
                return False
            logger.info("Successfully created EventSub subscription.")
            return True

async def listen_to_eventsub(settings: dict):
    ws_url = "wss://eventsub.wss.twitch.tv/ws"
    async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
        logger.info("Connected to EventSub WebSocket.")
        async for message in ws:
            data = json.loads(message)
            msg_type = data.get("metadata", {}).get("message_type")

            if msg_type == "session_welcome":
                session_id = data["payload"]["session"]["id"]
                logger.info(f"Session established: {session_id}")
                if not await subscribe_to_events(session_id, settings):
                    break # Exit if subscription failed
            elif msg_type == "notification":
                event = data["payload"]["event"]
                await handle_redemption_event(event, settings)
            elif msg_type == "session_reconnect":
                logger.warning("Reconnect message received. A new connection will be attempted.")
                # The library handles this automatically by reconnecting
            elif msg_type == "session_keepalive":
                pass # Keepalive received, connection is healthy
            else:
                logger.info(f"Received unknown message type: {msg_type}")

# --- MAIN EXECUTION BLOCK ---
async def main():
    logger.warning("=" * 60); logger.warning("Bot is starting..."); logger.warning("=" * 60)
    settings = load_settings()
    if not all(k in settings for k in ["twitch_channel_name", "twitch_oauth_token", "twitch_client_id"]):
        if not initial_setup(settings):
            logger.info("Setup cancelled. Exiting.")
            return

    try:
        await listen_to_eventsub(settings)
    except Exception as e:
        if "401" in str(e) or "invalid token" in str(e).lower():
            logger.error("AUTHORIZATION FAILED. The token is likely invalid or expired.")
            settings["twitch_oauth_token"] = ""
            save_settings(settings)
            logger.info("Invalid token has been cleared. Restart the bot.")
        else:
            logger.error(f"A critical error occurred: {e}")

    logger.info("Program has terminated.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nScript stopped by user (Ctrl+C).")

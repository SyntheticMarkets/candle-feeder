# ==============================
# 🔇 Disable noisy logs (OPTIONAL)
# ==============================
# import logging
# logging.getLogger().setLevel(logging.CRITICAL)

import asyncio
import time
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pyquotex.stable_api import Quotex
from dotenv import load_dotenv

# ==============================
# 🌍 Load Environment Variables
# ==============================
load_dotenv("session.env")  # not used on Render, but useful for local

# ==============================
# 📦 Storage
# ==============================
candles = {}
assets_to_track = []
client = None

# ==============================
# 🕯 Candle Storage
# ==============================
def append_candle(symbol, candle):
    if symbol not in candles:
        candles[symbol] = []
    candles[symbol].append(candle)
    candles[symbol] = candles[symbol][-100:]

def get_candles(symbol):
    return candles.get(symbol, [])

# ==============================
# 🚀 FastAPI Setup
# ==============================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/candles/{symbol}")
def get_candle_data(symbol: str):
    return JSONResponse(content=get_candles(symbol))

@app.get("/tracked-assets")
def tracked_assets():
    return JSONResponse(content=assets_to_track)

# ==============================
# ✅ Asset Filtering
# ==============================
async def filter_available_assets(client, min_payout=70):
    print("🔍 Filtering available assets...")
    valid_assets = []

    for _ in range(5):
        asset_names = client.get_all_asset_name()
        payouts = client.get_payment()
        if asset_names and payouts:
            break
        print("⏳ Waiting for asset names and payouts...")
        await asyncio.sleep(1)

    if not asset_names or not payouts:
        print("❌ Failed to load asset names or payouts")
        return []

    for asset_pair in asset_names:
        try:
            name = asset_pair[0] if isinstance(asset_pair, list) else asset_pair
            display = asset_pair[1] if isinstance(asset_pair, list) and len(asset_pair) > 1 else name
            payout_info = payouts.get(display, {}).get("profit", {}).get("1M", 0)

            asset_status = await client.get_available_asset(name, force_open=True)
            is_open = asset_status[1][2] if isinstance(asset_status[1], tuple) else False

            if is_open and int(payout_info) >= min_payout:
                valid_assets.append(name)
        except Exception as e:
            print(f"⚠️ Skipping asset {asset_pair} due to error: {e}")
            continue

    print(f"✅ Valid assets: {valid_assets}")
    return valid_assets

# ==============================
# 🔁 Stream Candle Handler
# ==============================
def handle_stream_candle(data):
    try:
        asset = data.get("active")
        if not asset:
            return
        append_candle(asset, {
            "open": float(data["open"]),
            "high": float(data["max"]),
            "low": float(data["min"]),
            "close": float(data["close"]),
            "time": time.time()
        })
    except Exception as e:
        print(f"❌ Error processing streamed candle: {e}")

# ==============================
# 🎯 Main Candle Streamer
# ==============================
async def stream_candles():
    global client, assets_to_track

    email = os.getenv("QX_EMAIL")
    password = os.getenv("QX_PASSWORD")

    print("📩 Email:", email)
    print("🔐 Password present:", bool(password))

    if not email or not password:
        print("❌ Missing email or password in env variables")
        return

    client = Quotex(email=email, password=password)

    connected, msg = await client.connect()
    print(f"🔌 Connected: {connected} | Message: {msg}")
    await client.change_account("demo")

    print("✅ Connected to Quotex WebSocket")

    while True:
        new_assets = await filter_available_assets(client, min_payout=70)

        if new_assets:
            for asset in assets_to_track:
                try:
                    client.unsubscribe_realtime_candle(asset)
                    client.unfollow_candle(asset)
                except:
                    pass

            assets_to_track.clear()
            assets_to_track.extend(new_assets)

            for asset in assets_to_track:
                try:
                    client.start_candles_stream(asset, 60)
                    client.follow_candle(asset, handle_stream_candle)
                    print(f"📡 Subscribed to {asset}")
                except Exception as e:
                    print(f"❌ Failed to subscribe to {asset}: {e}")
                    continue
        else:
            print("⚠️ No valid assets found")

        await asyncio.sleep(60)

# ==============================
# 🚀 Startup Event
# ==============================
@app.on_event("startup")
async def on_startup():
    print("🚀 Launching candle streaming task...")
    asyncio.create_task(stream_candles())

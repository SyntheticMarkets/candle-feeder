import logging
logging.getLogger().setLevel(logging.CRITICAL)

import asyncio
import time
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pyquotex.stable_api import Quotex
import builtins
builtins.print = lambda *args, **kwargs: __import__("builtins").__dict__["__print"](*args, **kwargs)
__import__("builtins").__dict__["__print"] = print

candles = {}
assets_to_track = []

def append_candle(symbol, candle):
    if symbol not in candles:
        candles[symbol] = []
    candles[symbol].append(candle)
    candles[symbol] = candles[symbol][-100:]

def get_candles(symbol):
    return candles.get(symbol, [])

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/candles/{symbol}")
def get_candle_data(symbol: str):
    result = get_candles(symbol)
    return JSONResponse(content=result)

@app.get("/tracked-assets")
def tracked_assets():
    return JSONResponse(content=assets_to_track)

async def filter_available_assets(client, min_payout=70):
    valid_assets = []
    try:
        asset_names = client.get_all_asset_name()
        payouts = client.get_payment()

        for asset_pair in asset_names:
            try:
                name = asset_pair[0] if isinstance(asset_pair, list) else asset_pair
                display = asset_pair[1] if isinstance(asset_pair, list) and len(asset_pair) > 1 else name
                payout_info = payouts.get(display, {}).get("profit", {}).get("1M", 0)

                asset_status = await client.get_available_asset(name, force_open=True)
                is_open = asset_status[1][2] if isinstance(asset_status, tuple) and isinstance(asset_status[1], tuple) else False

                if is_open and int(payout_info) >= min_payout:
                    valid_assets.append(name)
            except Exception as e:
                print(f"[FILTER ERROR] {e}")
                continue
    except Exception as e:
        print(f"[FILTER FAILED] {e}")
    return valid_assets

async def fetch_and_feed():
    global assets_to_track

    print("🔄 Creating Quotex client...")
    client = Quotex(
        email=os.getenv("QX_EMAIL"),
        password=os.getenv("QX_PASSWORD")
    )

    try:
        await client.connect()
        await client.change_account("demo")
        print("✅ Connected to Quotex (demo)")
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        return

    async def refresh_assets():
        global assets_to_track
        while True:
            assets_to_track = await filter_available_assets(client, min_payout=70)
            print(f"🔁 Valid assets: {assets_to_track}")
            await asyncio.sleep(60)

    asyncio.create_task(refresh_assets())

    while not assets_to_track:
        print("⏳ Waiting for assets...")
        await asyncio.sleep(1)

    while True:
        for asset in assets_to_track:
            try:
                candles_raw = await client.get_candles(asset, 1, 15, 60)
                if candles_raw:
                    for candle in candles_raw:
                        append_candle(asset, {
                            "open": float(candle["open"]),
                            "high": float(candle["high"]),
                            "low": float(candle["low"]),
                            "close": float(candle["close"]),
                            "time": time.time()
                        })
                    print(f"📈 Updated candles: {asset} - {len(candles_raw)}")
            except Exception as e:
                print(f"[CANDLE ERROR] {asset}: {e}")
        await asyncio.sleep(1)

@app.on_event("startup")
async def on_startup():
    asyncio.create_task(fetch_and_feed())

import logging
logging.getLogger().setLevel(logging.CRITICAL)  # 🔇 Still silences external logs

import asyncio
import time
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pyquotex.stable_api import Quotex
# Comment out forced print override
# import builtins
# builtins.print = lambda *args, **kwargs: None

candles = {}
assets_to_track = []

def append_candle(symbol, candle):
    if symbol not in candles:
        candles[symbol] = []
    candles[symbol].append(candle)
    candles[symbol] = candles[symbol][-100:]  # Keep last 100 candles only

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
    print(f"📤 Served {symbol} candles: {len(result)}")
    return JSONResponse(content=result)

@app.get("/tracked-assets")
def tracked_assets():
    print(f"📡 Reporting {len(assets_to_track)} tracked assets...")
    return JSONResponse(content=assets_to_track)

# ✅ Filter only open instruments with 70%+ payout
async def filter_available_assets(client, min_payout=70):
    valid_assets = []
    try:
        asset_names = await client.get_all_assets()  # dict of { 'EURUSD_otc': {...}, ... }
        payouts = client.get_payment()

        for name in asset_names.keys():
            try:
                payout_info = payouts.get(name, {}).get("profit", {}).get("1M", 0)

                asset_status = await client.get_available_asset(name, force_open=False)
                is_open = asset_status[1][2] if isinstance(asset_status, tuple) and isinstance(asset_status[1], tuple) else False

                print(f"🔎 Checking {name} | Open: {is_open} | 1M Payout: {payout_info}")
                if is_open and int(payout_info) >= min_payout:
                    valid_assets.append(name)

            except Exception as e:
                print(f"[ERROR] Asset filter issue for {name}: {e}")
                continue

    except Exception as e:
        print(f"[ERROR] Filtering assets: {e}")

    print(f"✅ Valid assets after filter: {valid_assets}")
    return valid_assets

# ✅ Background fetch logic
async def fetch_and_feed():
    global assets_to_track

    client = Quotex(
        email=os.getenv("QX_EMAIL"),
        password=os.getenv("QX_PASSWORD")
    )
    success, message = await client.connect()
    print(f"🔌 Quotex connection: {success} | Message: {message}")
    if not success:
        raise RuntimeError("❌ Failed to connect to Quotex: " + message)

    await client.change_account("demo")
    print("✅ Switched to demo account.")

    # 🔁 Refresh valid assets every 60 seconds
    async def refresh_assets():
        global assets_to_track
        while True:
            assets_to_track = await filter_available_assets(client, min_payout=70)
            print(f"🔁 Refreshed valid assets: {assets_to_track}")
            await asyncio.sleep(60)

    asyncio.create_task(refresh_assets())

    # ⏳ Wait until valid assets are available
    while not assets_to_track:
        print("⏳ Waiting for valid assets to track...")
        await asyncio.sleep(1)

    # 🔄 Candle fetching
    while True:
        for asset in assets_to_track:
            try:
                print(f"⏳ Fetching candles for {asset}...")
                now = time.time()
                candles_raw = await client.get_candles(asset, now, 900, 60)  # 900 = 15m back

                if candles_raw:
                    for candle in candles_raw:
                        append_candle(asset, {
                            "open": float(candle["open"]),
                            "high": float(candle["high"]),
                            "low": float(candle["low"]),
                            "close": float(candle["close"]),
                            "time": candle.get("from", time.time())
                        })
                    print(f"✅ Saved {len(candles_raw)} candles for {asset}")
                else:
                    print(f"⚠️ No candles returned for {asset}")

            except Exception as e:
                print(f"[ERROR] Failed fetching candles for {asset}: {e}")
        await asyncio.sleep(1)

@app.on_event("startup")
async def on_startup():
    asyncio.create_task(fetch_and_feed())

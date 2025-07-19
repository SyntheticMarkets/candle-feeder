import logging
logging.getLogger().setLevel(logging.CRITICAL)  # Silence external logs

import asyncio
import time
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pyquotex.stable_api import Quotex

# 🟢 Enable print logs for debugging
# builtins.print = lambda *args, **kwargs: None  # ← Leave this commented to see logs

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

# ✅ Filter only open instruments with 70%+ payout (with debug prints)
async def filter_available_assets(client, min_payout=70):
    valid_assets = []

    # 🔁 Retry to let Quotex load asset and payout data
    for _ in range(5):
        asset_names = client.get_all_asset_name()
        payouts = client.get_payment()

        print("💥 get_all_asset_name:", asset_names[:5])  # show first 5
        print("💥 get_payment keys:", list(payouts.keys())[:5])  # show some payout keys

        if asset_names and payouts:
            break
        await asyncio.sleep(1)

    if not asset_names:
        print("❌ No asset names received.")
        return []

    if not payouts:
        print("❌ No payout info received.")
        return []

    for asset_pair in asset_names:
        try:
            name = asset_pair[0] if isinstance(asset_pair, list) else asset_pair
            display = asset_pair[1] if isinstance(asset_pair, list) and len(asset_pair) > 1 else name
            payout_info = payouts.get(display, {}).get("profit", {}).get("1M", 0)

            print(f"🔎 {name} | {display} | Payout: {payout_info}")

            asset_status = await client.get_available_asset(name, force_open=True)
            is_open = asset_status[1][2] if isinstance(asset_status, tuple) and isinstance(asset_status[1], tuple) else False

            if is_open and int(payout_info) >= min_payout:
                print(f"✅ Tracking: {name}")
                valid_assets.append(name)

        except Exception as e:
            print(f"❌ Error with {asset_pair}: {e}")

    print("📦 Final valid assets:", valid_assets)
    return valid_assets

# ✅ Background fetch logic
async def fetch_and_feed():
    global assets_to_track

    client = Quotex(
        email=os.getenv("QX_EMAIL"),
        password=os.getenv("QX_PASSWORD")
    )
    await client.connect()
    await client.change_account("demo")
    print("✅ Connected to Quotex")

    # 🔁 Refresh valid assets every 60 seconds
    async def refresh_assets():
        global assets_to_track
        while True:
            assets_to_track = await filter_available_assets(client, min_payout=70)
            print("🔁 Updated tracked assets:", assets_to_track)
            await asyncio.sleep(60)

    asyncio.create_task(refresh_assets())

    # ⏳ Wait until valid assets are available
    while not assets_to_track:
        print("⏳ Waiting for valid assets...")
        await asyncio.sleep(1)

    # 🔄 Candle fetching
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
            except Exception as e:
                print(f"❌ Error fetching candles for {asset}: {e}")
        await asyncio.sleep(1)

@app.on_event("startup")
async def on_startup():
    asyncio.create_task(fetch_and_feed())

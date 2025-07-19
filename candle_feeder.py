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
builtins.print = lambda *args, **kwargs: None

candles = {}
assets_to_track = []
client = None

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

# ✅ Filter only open instruments with 70%+ payout
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
            except:
                continue
    except:
        pass
    return valid_assets

# ✅ Candle handler for WebSocket stream
async def on_candle_update(data):
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

# ✅ Main background fetch logic
async def fetch_and_feed():
    global client, assets_to_track

    client = Quotex(
        email=os.getenv("QX_EMAIL"),
        password=os.getenv("QX_PASSWORD")
    )
    await client.connect()
    await client.change_account("demo")
    print("✅ Connected to Quotex")

    # 🔁 Refresh valid assets and resubscribe every 60s
    async def refresh_assets():
        global assets_to_track
        while True:
            new_assets = await filter_available_assets(client, min_payout=70)

            # Only resubscribe if asset list changed
            if set(new_assets) != set(assets_to_track):
                for asset in assets_to_track:
                    try:
                        await client.candles_unsubscribe(asset)
                    except:
                        pass

                assets_to_track = new_assets

                for asset in assets_to_track:
                    try:
                        await client.candles_subscribe(asset, 60)
                        client.candle_observe(asset, on_candle_update)

                        # Preload last 15 candles on fresh subscription
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
                    except:
                        continue

            await asyncio.sleep(60)

    asyncio.create_task(refresh_assets())

@app.on_event("startup")
async def on_startup():
    asyncio.create_task(fetch_and_feed())

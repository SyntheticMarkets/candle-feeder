import time
import asyncio
import logging
import builtins
import inspect
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import os
from pyquotex.stable_api import Quotex
from pyquotex.utils.processor import process_candles

# === LOGGING / PRINT SETUP ===
original_print = builtins.print
def smart_print(*args, **kwargs):
    frame = inspect.currentframe().f_back
    filename = frame.f_globals.get("__file__", "")
    if "candle_feeder_currencies.py" in filename:
        original_print(*args, **kwargs)
builtins.print = smart_print
logging.basicConfig(level=logging.CRITICAL + 1)
def log(*args, **kwargs):
    original_print(*args, **kwargs)

# === GLOBAL STORES ===
candles_memory = {}
assets_store = {"track": []}

# === ASSETS ===
TARGET_OTC_ASSETS = [
    "USDINR_otc", "AUDUSD_otc", "EURCAD_otc", "EURUSD_otc", "USDDZD_otc",
    "USDARS_otc", "AUDJPY_otc", "EURJPY_otc", "GBPAUD_otc", "USDCHF_otc",
    "EURGBP_otc", "USDPHP_otc", "USDEGP_otc", "GBPUSD_otc", "NZDCHF_otc",
    "NZDJPY_otc", "USDJPY_otc", "AUDCAD_otc", "GBPNZD_otc", "EURNZD_otc",
    "GBPJPY_otc", "CHFJPY_otc", "USDTRY_otc", "USDBDT_otc", "USDCOP_otc",
    "AUDCHF_otc", "NZDCAD_otc", "USDCAD_otc", "USDIDR_otc", "USDNGN_otc",
    "CADCHF_otc", "USDMXN_otc", "BRLUSD_otc", "EURAUD_otc", "USDPKR_otc",
    "CADJPY_otc", "NZDUSD_otc", "USDZAR_otc", "AUDNZD_otc", "GBPCAD_otc",
    "GBPCHF_otc", "EURSGD_otc"
]

# === CANDLE UTILS ===
async def update_latest_candle(client, asset, lock):
    async with lock:
        now = time.time()
        candles = await client.get_candles(asset, now, 60, 60)
        if candles and not candles[0].get("open"):
            candles = process_candles(candles, 60)
        if candles:
            candles_memory.setdefault(asset, []).append(candles[-1])
            candles_memory[asset] = candles_memory[asset][-15:]

async def load_initial_candles(client, asset, lock):
    async with lock:
        now = time.time()
        candles = await client.get_candles(asset, now, 900, 60)
        if candles and not candles[0].get("open"):
            candles = process_candles(candles, 60)
        if candles:
            candles_memory[asset] = candles[-15:]
            log(f"📊 {asset} — Initialized with 15 candles")

async def filter_assets_by_payout(client):
    all_assets = client.get_all_asset_name()
    payouts = client.get_payment()
    result = []
    for asset in TARGET_OTC_ASSETS:
        try:
            display = next((a[1] for a in all_assets if a[0] == asset), None)
            if not display:
                continue
            payout = payouts.get(display, {}).get("profit", {}).get("1M", 0)
            if int(payout) == 93:
                result.append(asset)
        except Exception as e:
            log(f"[ERROR] filtering {asset}: {e}")
    log(f"✅ Filtered OTC 93% assets: {len(result)}")
    return result

# === MAIN BOT LOOP ===
async def bot_loop(client):
    lock = asyncio.Lock()
    valid_assets = await filter_assets_by_payout(client)
    await asyncio.gather(*(load_initial_candles(client, a, lock) for a in valid_assets))
    assets_store["track"] = valid_assets
    log(f"✅ Tracked assets now ready: {assets_store['track']}")

    while True:
        now = time.localtime()
        if now.tm_sec == 0:
            log("🕛 00:00 — updating candles")
            start = time.time()
            await asyncio.gather(*(update_latest_candle(client, a, lock) for a in valid_assets))
            log(f"✅ Updated all with latest candle in {round(time.time()-start, 2)}s")
            await asyncio.sleep(1)
        elif now.tm_sec == 10:
            log("🔄 00:10 — refreshing assets")
            valid_assets = await filter_assets_by_payout(client)
            await asyncio.gather(*(load_initial_candles(client, a, lock) for a in valid_assets))
            assets_store["track"] = valid_assets
            log(f"✅ Refreshed tracked assets: {assets_store['track']}")
            await asyncio.sleep(1)
        await asyncio.sleep(0.5)

# === SAFE LOGIN + START ===
async def start_bot():
    await asyncio.sleep(3)  # ✅ Give network stack time to settle (especially on Render)
    email = os.getenv("QX_EMAIL")
    password = os.getenv("QX_PASSWORD")
    client = Quotex(email=email, password=password, lang="en")
    log("🔐 Connecting to Quotex...")
    check, msg = await client.connect()
    log(f"🔌 Login success: {check} | {msg}")
    if not check:
        log("❌ Login failed. Bot will not start.")
        return
    await client.change_account("demo")
    asyncio.create_task(bot_loop(client))

# === FASTAPI APP ===
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(start_bot())

@app.get("/candles/{symbol}")
def get_candle(symbol: str):
    return JSONResponse(content=candles_memory.get(symbol, []))

@app.get("/tracked-assets/currencies")
def get_assets():
    tracked = assets_store["track"]
    log(f"📡 Reporting {len(tracked)} tracked assets: {tracked}")
    return JSONResponse(content=tracked)

# === ENTRY POINT ===
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

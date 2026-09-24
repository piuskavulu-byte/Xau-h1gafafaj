# main.py - FIX 520 - tries 2 Deriv servers
import os, time, requests, json, asyncio, websockets
from flask import Flask
import threading, pandas as pd

DERIV_TOKEN = os.getenv("DERIV_TOKEN", "")
DERIV_MT5_LOGIN = os.getenv("DERIV_MT5_LOGIN", "")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")
BOT_NAME = os.getenv("BOT_NAME", "BOT-2-FINAL")
SYMBOLS = ["BOOM_1000", "CRASH_1000"]
LOT = 0.01

ENDPOINTS = [
    "wss://ws.binaryws.com/websockets/v3?app_id=1089",
    "wss://ws.derivws.com/websockets/v3?app_id=1089"
]

app = Flask(__name__)

def tg(msg):
    print(msg)
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", json={"chat_id": TG_CHAT, "text": msg, "parse_mode":"Markdown"}, timeout=10)
    except: pass

async def ws_call(payload):
    for uri in ENDPOINTS:
        try:
            async with websockets.connect(uri, ping_interval=20) as ws:
                await ws.send(json.dumps({"authorize": DERIV_TOKEN}))
                a = json.loads(await ws.recv())
                if "error" in a:
                    tg(f"❌ AUTH ERROR: {a['error']['message']}\nYour DERIV_TOKEN is wrong - recreate token with Trading scope")
                    return None
                await ws.send(json.dumps(payload))
                r = json.loads(await ws.recv())
                return r
        except Exception as e:
            if "520" in str(e):
                tg(f"⚠️ 520 on {uri.split('/')[2]} trying next server...")
                await asyncio.sleep(5)
                continue
            else:
                print(f"ws err {e}")
                await asyncio.sleep(5)
    return None

def loop():
    tg(f"🟢 {BOT_NAME} STARTING - Testing 2 Deriv servers")
    time.sleep(3)
    # TEST 1: Check candles
    r = asyncio.run(ws_call({"ticks_history": "BOOM_1000", "style": "candles", "granularity": 300, "count": 10, "end": "latest"}))
    if r and "candles" in r:
        tg(f"✅ Candles OK - Deriv connected")
    else:
        tg(f"❌ Candles FAILED: {str(r)[:300]}\nThis is Deriv outage, wait 10 min")
        return

    # TEST 2: Test trade
    r2 = asyncio.run(ws_call({"mt5_new_trade": 1, "login": DERIV_MT5_LOGIN, "symbol": "BOOM_1000", "volume": 0.01, "type": "buy"}))
    tg(f"🧪 TEST TRADE:\n```{json.dumps(r2, indent=2)[:900] if r2 else 'No response'}```")

    tg(f"🟢 {BOT_NAME} LIVE - BOS only - Will trade every 5 min")
    while True:
        try:
            for s in SYMBOLS:
                df_resp = asyncio.run(ws_call({"ticks_history": s, "style": "candles", "granularity": 300, "count": 50, "end": "latest"}))
                if not df_resp or "candles" not in df_resp:
                    time.sleep(30); continue
                import pandas as pd
                df = pd.DataFrame(df_resp["candles"])
                hi = df.tail(30)['high'].max(); lo = df.tail(30)['low'].min()
                close = df.iloc[-1]['close']
                if close > hi:
                    asyncio.run(ws_call({"mt5_new_trade": 1, "login": DERIV_MT5_LOGIN, "symbol": s, "volume": LOT, "type": "buy", "sl": close-5, "tp": close+10}))
                    tg(f"✅ {s} BULLISH BOS")
                elif close < lo:
                    asyncio.run(ws_call({"mt5_new_trade": 1, "login": DERIV_MT5_LOGIN, "symbol": s, "volume": LOT, "type": "sell", "sl": close+5, "tp": close-10}))
                    tg(f"✅ {s} BEARISH BOS")
                time.sleep(5)
            time.sleep(60)
        except Exception as e:
            print(e); time.sleep(30)

@app.route('/')
def home(): return "FIXED"
threading.Thread(target=loop, daemon=True).start()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

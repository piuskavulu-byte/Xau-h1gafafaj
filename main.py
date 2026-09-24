# main.py - CLEAN + TEST TRADE ON START
import os, time, requests, json, asyncio, websockets
from flask import Flask
import threading
import pandas as pd

DERIV_TOKEN = os.getenv("DERIV_TOKEN", "")
DERIV_MT5_LOGIN = os.getenv("DERIV_MT5_LOGIN", "")
DERIV_APP_ID = "1089"
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")
BOT_NAME = os.getenv("BOT_NAME", "BOT-2-FINAL")

SYMBOLS = ["BOOM_1000", "CRASH_1000", "BOOM_500", "CRASH_500", "BOOM_300", "CRASH_300"]
LOT = 0.01
BE_PROFIT = 1.0
BE_OFFSET = 0.3

app = Flask(__name__)

def tg(msg):
    print(msg)
    if not TG_TOKEN or not TG_CHAT: return
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": msg, "parse_mode":"Markdown"}, timeout=10)
    except: pass

async def get_candles(symbol, granularity, count=100):
    uri = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
    try:
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({"authorize": DERIV_TOKEN}))
            await ws.recv()
            await ws.send(json.dumps({"ticks_history": symbol, "style": "candles", "granularity": granularity, "count": count, "end": "latest"}))
            r = json.loads(await ws.recv())
            if "candles" not in r: return None
            return pd.DataFrame(r["candles"])
    except: return None

async def place(bias, symbol, sl, tp, is_test=False):
    uri = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
    try:
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({"authorize": DERIV_TOKEN}))
            auth_resp = json.loads(await ws.recv())
            if "error" in auth_resp:
                tg(f"❌ *AUTH FAILED* {auth_resp['error']['message']}")
                return None
            await ws.send(json.dumps({"mt5_new_trade": 1, "login": DERIV_MT5_LOGIN, "symbol": symbol, "volume": LOT, "type": "buy" if bias=="BULLISH" else "sell", "sl": float(sl), "tp": float(tp)}))
            resp = json.loads(await ws.recv())
            if is_test:
                tg(f"🧪 *TEST TRADE RESULT {symbol}*\n```{json.dumps(resp, indent=2)[:800]}```")
            else:
                tg(f"✅ *{symbol} {bias} PLACED* SL {sl:.2f} TP {tp:.2f}\n`{str(resp)[:300]}`")
            return resp
    except Exception as e:
        tg(f"❌ Place err {e}")
        return None

async def manage():
    uri = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
    try:
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({"authorize": DERIV_TOKEN}))
            await ws.recv()
            await ws.send(json.dumps({"mt5_get_positions": 1, "login": DERIV_MT5_LOGIN}))
            r = json.loads(await ws.recv())
            for pos in r.get("mt5_get_positions", []):
                if pos["symbol"] not in SYMBOLS: continue
                entry = float(pos["open_price"]); curr = float(pos["current_price"])
                sl = float(pos["sl"]) if pos["sl"] else 0
                is_buy = pos["type"]=="buy"
                profit = (curr - entry) if is_buy else (entry - curr)
                money = profit * 100 * LOT
                if money >= BE_PROFIT:
                    if (is_buy and sl < entry) or (not is_buy and sl > entry) or sl==0:
                        be_sl = entry + BE_OFFSET if is_buy else entry - BE_OFFSET
                        await ws.send(json.dumps({"mt5_modify_position": 1, "login": DERIV_MT5_LOGIN, "ticket": pos["ticket"], "sl": float(be_sl), "tp": float(pos["tp"])}))
                        await ws.recv()
                        tg(f"🛡️ BE {pos['symbol']} +${money:.2f}")
    except: pass

async def scan_one(symbol):
    df = await get_candles(symbol, 300, 50)
    if df is None or len(df)<30: return
    last30_high = df.tail(30)['high'].max()
    last30_low = df.tail(30)['low'].min()
    close = df.iloc[-1]['close']
    bias = None
    if close > last30_high: bias = "BULLISH"
    elif close < last30_low: bias = "BEARISH"
    else: return
    sl = close - 4 if bias=="BULLISH" else close + 4
    tp = close + 8 if bias=="BULLISH" else close - 8
    await place(bias, symbol, sl, tp)

async def scan_all():
    for s in SYMBOLS:
        await scan_one(s)
        await asyncio.sleep(0.3)

def loop():
    # --- TEST TRADE ON START ---
    tg(f"🟢 *{BOT_NAME} STARTING...* Sending TEST TRADE in 5 sec")
    time.sleep(5)
    # Test on BOOM_1000 - will buy with SL/TP 0 to test connection
    asyncio.run(place("BULLISH", "BOOM_1000", 0, 0, is_test=True))
    
    tg(f"🟢 *{BOT_NAME} CLEAN LIVE*\nBOS only | SL/TP | BE +${BE_PROFIT}\nScanning {', '.join(SYMBOLS)}")
    while True:
        try:
            asyncio.run(scan_all())
            asyncio.run(manage())
            time.sleep(10)
        except Exception as e:
            print(e); time.sleep(5)

@app.route('/')
def home(): return "CLEAN + TEST"
threading.Thread(target=loop, daemon=True).start()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

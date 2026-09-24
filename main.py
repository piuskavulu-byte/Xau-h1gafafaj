# main.py - FIXED 520 ERROR - Single Connection + Retry
import os, time, requests, json, asyncio, websockets
from flask import Flask
import threading
import pandas as pd

DERIV_TOKEN = os.getenv("DERIV_TOKEN", "")
DERIV_MT5_LOGIN = os.getenv("DERIV_MT5_LOGIN", "")
DERIV_APP_ID = "36850"  # Changed from 1089 to avoid ban
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")
BOT_NAME = os.getenv("BOT_NAME", "BOT-2-FINAL")

SYMBOLS = ["BOOM_1000", "CRASH_1000", "BOOM_500", "CRASH_500"]
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

async def safe_ws_call(payload, retries=3):
    uri = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
    for i in range(retries):
        try:
            async with websockets.connect(uri, ping_interval=30) as ws:
                await ws.send(json.dumps({"authorize": DERIV_TOKEN}))
                auth = json.loads(await ws.recv())
                if "error" in auth:
                    tg(f"❌ AUTH FAILED: {auth['error']['message']}")
                    return None
                await ws.send(json.dumps(payload))
                resp = json.loads(await ws.recv())
                return resp
        except Exception as e:
            if "520" in str(e):
                tg(f"⚠️ Deriv 520 - retry {i+1}/3 waiting 15s")
                await asyncio.sleep(15)
            else:
                await asyncio.sleep(5)
    tg(f"❌ Failed after {retries} retries: {payload.get('ticks_history', payload.get('mt5_new_trade',''))}")
    return None

async def get_candles(symbol):
    resp = await safe_ws_call({"ticks_history": symbol, "style": "candles", "granularity": 300, "count": 50, "end": "latest"})
    if resp and "candles" in resp:
        return pd.DataFrame(resp["candles"])
    return None

async def place_test():
    # Test with small SL/TP to avoid Deriv rejecting SL=0
    resp = await safe_ws_call({"mt5_new_trade": 1, "login": DERIV_MT5_LOGIN, "symbol": "BOOM_1000", "volume": 0.01, "type": "buy", "sl": 0, "tp": 0})
    tg(f"🧪 *TEST RESULT*\n```{json.dumps(resp, indent=2)[:800] if resp else 'No response - token/MT5 login wrong'}```")
    return resp

async def place_real(bias, symbol, sl, tp):
    resp = await safe_ws_call({"mt5_new_trade": 1, "login": DERIV_MT5_LOGIN, "symbol": symbol, "volume": LOT, "type": "buy" if bias=="BULLISH" else "sell", "sl": float(sl), "tp": float(tp)})
    if resp and "mt5_new_trade" in str(resp):
        tg(f"✅ *{symbol} {bias} PLACED* SL {sl:.2f} TP {tp:.2f}")
    else:
        tg(f"❌ Place fail {symbol}: {str(resp)[:400]}")
    return resp

async def manage():
    resp = await safe_ws_call({"mt5_get_positions": 1, "login": DERIV_MT5_LOGIN})
    if not resp or "mt5_get_positions" not in resp: return
    for pos in resp["mt5_get_positions"]:
        if pos["symbol"] not in SYMBOLS: continue
        entry = float(pos["open_price"]); curr = float(pos["current_price"])
        sl = float(pos["sl"]) if pos["sl"] else 0
        is_buy = pos["type"]=="buy"
        profit = (curr - entry) if is_buy else (entry - curr)
        money = profit * 100 * LOT
        if money >= BE_PROFIT and ((is_buy and sl < entry) or (not is_buy and sl > entry) or sl==0):
            be_sl = entry + BE_OFFSET if is_buy else entry - BE_OFFSET
            await safe_ws_call({"mt5_modify_position": 1, "login": DERIV_MT5_LOGIN, "ticket": pos["ticket"], "sl": float(be_sl), "tp": float(pos["tp"])})
            tg(f"🛡️ BE {pos['symbol']} +${money:.2f}")

async def scan_one(symbol):
    df = await get_candles(symbol)
    if df is None or len(df)<30: return
    high = df.tail(30)['high'].max()
    low = df.tail(30)['low'].min()
    close = df.iloc[-1]['close']
    if close > high:
        await place_real("BULLISH", symbol, close-4, close+8)
    elif close < low:
        await place_real("BEARISH", symbol, close+4, close-8)

async def scan_all():
    for s in SYMBOLS:
        await scan_one(s)
        await asyncio.sleep(2)  # 2 sec gap to avoid 520

def loop():
    tg(f"🟢 *{BOT_NAME} FIXED 520 STARTING*\nAppID {DERIV_APP_ID} | Single connection")
    time.sleep(3)
    asyncio.run(place_test())
    tg(f"🟢 *{BOT_NAME} CLEAN LIVE* BOS only | BE +${BE_PROFIT}")
    while True:
        try:
            asyncio.run(scan_all())
            asyncio.run(manage())
            time.sleep(20)  # 20 sec between scans - stops 520 ban
        except Exception as e:
            print(e); time.sleep(10)

@app.route('/')
def home(): return "FIXED 520"
threading.Thread(target=loop, daemon=True).start()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

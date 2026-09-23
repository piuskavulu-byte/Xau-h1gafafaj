# main.py - BOT 2 FINAL V3 - AGGRESSIVE + BE + UNMITIGATED OB + VOLATILITY
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
RR = 3.0
BREAK_EVEN_PROFIT = 1.0
BREAK_EVEN_OFFSET = 0.3
TRAILING_START = 3.5
TRAILING_DIST = 1.0
MAX_DAILY_LOSS = 2
MAX_DAILY_TRADES = 6
MIN_ATR = 1.8

app = Flask(__name__)
last_test = 0
daily_losses = 0
daily_trades = 0
last_day = 0

def tg(msg):
    print(msg)
    if not TG_TOKEN or not TG_CHAT: return
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": msg, "parse_mode":"Markdown"}, timeout=10)
    except: pass

async def get_candles(symbol, granularity, count=200):
    uri = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
    try:
        async with websockets.connect(uri) as ws:
            if DERIV_TOKEN:
                await ws.send(json.dumps({"authorize": DERIV_TOKEN}))
                await ws.recv()
            await ws.send(json.dumps({"ticks_history": symbol, "style": "candles", "granularity": granularity, "count": count, "end": "latest"}))
            resp = json.loads(await ws.recv())
            if "candles" not in resp: return None
            df = pd.DataFrame(resp["candles"])
            df = df.rename(columns={"open":"open","high":"high","low":"low","close":"close"})
            return df
    except Exception as e:
        print(f"{symbol} err {e}")
        return None

async def place_mt5(bias, symbol, sl, tp):
    uri = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
    try:
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({"authorize": DERIV_TOKEN}))
            await ws.recv()
            order = {"mt5_new_trade": 1, "login": DERIV_MT5_LOGIN, "symbol": symbol, "volume": LOT, "type": "buy" if bias=="BULLISH" else "sell", "sl": float(sl), "tp": float(tp)}
            await ws.send(json.dumps(order))
            resp = json.loads(await ws.recv())
            print(f"Place {symbol} {resp}")
            return resp
    except Exception as e:
        print(f"Place err {e}")
        return None

async def manage_trades():
    uri = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
    try:
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({"authorize": DERIV_TOKEN}))
            await ws.recv()
            await ws.send(json.dumps({"mt5_get_positions": 1, "login": DERIV_MT5_LOGIN}))
            resp = json.loads(await ws.recv())
            if "mt5_get_positions" not in resp: return
            for pos in resp["mt5_get_positions"]:
                if pos["symbol"] not in SYMBOLS: continue
                ticket = pos["ticket"]
                entry_price = float(pos["open_price"])
                curr = float(pos["current_price"])
                sl = float(pos["sl"]) if pos["sl"] else 0
                is_buy = pos["type"]=="buy"
                profit = (curr - entry_price) if is_buy else (entry_price - curr)
                profit_money = profit * 100 * LOT
                if profit_money >= BREAK_EVEN_PROFIT:
                    already_be = (is_buy and sl >= entry_price) or (not is_buy and sl <= entry_price and sl!=0)
                    if not already_be:
                        be_sl = entry_price + BREAK_EVEN_OFFSET if is_buy else entry_price - BREAK_EVEN_OFFSET
                        await ws.send(json.dumps({"mt5_modify_position": 1, "login": DERIV_MT5_LOGIN, "ticket": ticket, "sl": float(be_sl), "tp": float(pos["tp"])}))
                        await ws.recv()
                        tg(f"🛡️ *[{BOT_NAME}] BREAK EVEN {pos['symbol']}* Ticket {ticket} +${profit_money:.2f} → SL `{be_sl:.2f}` Can't lose!")
                if profit_money >= TRAILING_START:
                    new_sl = (curr - TRAILING_DIST) if is_buy else (curr + TRAILING_DIST)
                    if (is_buy and new_sl > sl) or (not is_buy and new_sl < sl):
                        await ws.send(json.dumps({"mt5_modify_position": 1, "login": DERIV_MT5_LOGIN, "ticket": ticket, "sl": float(new_sl), "tp": float(pos["tp"])}))
                        await ws.recv()
                        tg(f"🔒 *[{BOT_NAME}] TRAILING {pos['symbol']}* SL `{new_sl:.2f}` +${profit_money:.2f}")
    except Exception as e:
        print(f"Manage err {e}")

def get_strong_levels(df):
    if df is None or len(df) < 50: return None, None, None
    recent = df.tail(50)
    sh = recent.loc[recent['high'].idxmax()]
    sl = recent.loc[recent['low'].idxmin()]
    df['ema50'] = df['close'].ewm(span=50).mean()
    df['ema200'] = df['close'].ewm(span=200).mean()
    bias = "BULLISH" if df.iloc[-1]['ema50'] > df.iloc[-1]['ema200'] else "BEARISH"
    return sh, sl, bias

def has_volatility(df):
    if df is None or len(df) < 15: return False
    atr = (df['high'] - df['low']).tail(14).mean()
    return atr >= MIN_ATR

def find_liquidity_aggressive(df):
    if df is None or len(df) < 20: return None
    last_20 = df.tail(20)
    return [{"type":"BUY_LIQUIDITY","price":last_20['high'].max()}, {"type":"SELL_LIQUIDITY","price":last_20['low'].min()}]

def check_sweep(df, price, typ):
    if df is None: return False
    c = df.iloc[-1]
    if typ=="BUY_LIQUIDITY": return c['high'] > price and c['close'] < price
    else: return c['low'] < price and c['close'] > price

def check_bos(df, sh, sl):
    if df is None: return None
    close = df.iloc[-1]['close']
    if close > sh['high']: return {"bias":"BULLISH","level":sh['high']}
    if close < sl['low']: return {"bias":"BEARISH","level":sl['low']}
    return None

def get_ob(df, bos):
    if df is None or bos is None: return None
    for i in range(len(df)-3, len(df)-30, -1):
        c = df.iloc[i]
        nxt = df.iloc[i+1:i+4]
        if len(nxt)<2: continue
        if bos["bias"]=="BULLISH" and c['close']<c['open'] and nxt['close'].iloc[-1] > c['high']:
            return {"type":"BEARISH_OB","high":c['high'],"low":c['low'],"ob_high":c['high'],"ob_low":c['open'], "index": i}
        if bos["bias"]=="BEARISH" and c['close']>c['open'] and nxt['close'].iloc[-1] < c['low']:
            return {"type":"BULLISH_OB","high":c['high'],"low":c['low'],"ob_high":c['open'],"ob_low":c['low'], "index": i}
    return None

def is_ob_unmitigated(df, ob):
    if df is None or ob is None: return False
    idx = ob.get('index', 0)
    after = df.iloc[idx+1:]
    for _, c in after.iterrows():
        if c['low'] <= ob['ob_high'] and c['high'] >= ob['ob_low']:
            return False
    return True

async def scan_symbol(symbol):
    global daily_trades
    df_15m = await get_candles(symbol, 900, 200)
    df_5m = await get_candles(symbol, 300, 100)
    df_1m = await get_candles(symbol, 60, 100)
    if df_15m is None or df_5m is None: return
    if not has_volatility(df_5m): return
    sh, sl, htf_bias = get_strong_levels(df_15m)
    if sh is None: return
    liqs = find_liquidity_aggressive(df_5m)
    bos = check_bos(df_5m, sh, sl)
    if not bos: return
    swept = None
    for liq in liqs:
        if check_sweep(df_5m, liq["price"], liq["type"]):
            swept = liq
            break
    if not swept: return
    ob = get_ob(df_5m, bos)
    if not ob: return
    if not is_ob_unmitigated(df_5m, ob): return
    entry = df_1m.iloc[-1]['close'] if df_1m is not None else df_5m.iloc[-1]['close']
    stop = ob['high'] + 1 if bos["bias"]=="BEARISH" else ob['low'] - 1
    tp = entry + abs(entry-stop)*RR if bos["bias"]=="BULLISH" else entry - abs(entry-stop)*RR
    tg(f"🔥 *[{BOT_NAME}] {symbol} {bos['bias']} PROTECTED*\n💧 Liq {swept['type']} Swept {swept['price']:.2f}\n💥 BOS {bos['level']:.2f}\n📦 OB UNMITIGATED {ob['ob_low']:.2f}-{ob['ob_high']:.2f} ✅\n📈 Volatility ATR≥{MIN_ATR} ✅\n🎯 E {entry:.2f} SL {stop:.2f} TP {tp:.2f}\n🛡️ BE at +${BREAK_EVEN_PROFIT}")
    await place_mt5(bos["bias"], symbol, stop, tp)
    daily_trades += 1

async def scan_all():
    for s in SYMBOLS:
        try:
            await scan_symbol(s)
            await asyncio.sleep(0.8)
        except: pass

def bot_loop():
    global last_test, last_day, daily_losses, daily_trades
    tg(f"🟢 *[{BOT_NAME}] V3 FINAL LIVE*\nScan {', '.join(SYMBOLS)}\nBE +${BREAK_EVEN_PROFIT} | OB Unmitigated | Vol ATR≥{MIN_ATR}")
    while True:
        try:
            if time.localtime().tm_mday!= last_day:
                daily_losses = 0
                daily_trades = 0
                last_day = time.localtime().tm_mday
            if daily_losses >= MAX_DAILY_LOSS:
                tg(f"⛔ [{BOT_NAME}] Daily loss {MAX_DAILY_LOSS} hit - pause 1h")
                time.sleep(3600)
                continue
            if time.time() - last_test > 300:
                tg(f"✅ *[{BOT_NAME}] ALIVE - Protected*\nOB: Unmitigated | Vol: ATR≥{MIN_ATR}\nBE +${BREAK_EVEN_PROFIT} | Trades {daily_trades}/{MAX_DAILY_TRADES}")
                last_test = time.time()
            asyncio.run(scan_all())
            asyncio.run(manage_trades())
            time.sleep(10)
        except Exception as e:
            print(f"Loop err {e}")
            time.sleep(5)

@app.route('/')
def home(): return f"{BOT_NAME} FINAL"
threading.Thread(target=bot_loop, daemon=True).start()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

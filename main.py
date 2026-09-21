# main.py - FLY.IO - XAU MT5 PHONE - H1/H4 + 15m Liquidity + 5m Entry 1:3
import os, time, requests
import pandas as pd
from datetime import datetime, timezone

SYMBOL = "XAUUSD"
RR = 3.0
EMA_FAST = 50
EMA_SLOW = 200
LOT = 0.01 # Change to 0.01 for now, auto 0.7% in next version

METAAPI_TOKEN = os.getenv("METAAPI_TOKEN", "")
ACCOUNT_ID = os.getenv("METAAPI_ACCOUNT_ID", "")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")

print(f"🟢 XAU FLY BOT LIVE | H1/H4 Bias | 15m Liquidity | 5m Entry 1:{RR}")

def tg(msg):
    print(msg, flush=True)
    if not TG_TOKEN or not TG_CHAT: return
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                      json={"chat_id": TG_CHAT, "text": msg, "parse_mode":"Markdown"}, timeout=5)
    except: pass

def get_candles(tf, count=250):
    """tf: 1h, 4h, 15m, 5m"""
    url = f"https://mt-client-api-v1.agiliumtrade.agiliumtrade.ai/users/current/accounts/{ACCOUNT_ID}/historical-market-data/symbols/{SYMBOL}/timeframes/{tf}/candles"
    headers = {"auth-token": METAAPI_TOKEN}
    try:
        r = requests.get(url, headers=headers, params={"count": count}, timeout=15)
        data = r.json()
        if isinstance(data, list) and len(data) > 0:
            return pd.DataFrame(data)
        else:
            print(f"Candle empty {tf}: {str(data)[:100]}")
            return None
    except Exception as e:
        print(f"Candle error {tf}: {e}")
        return None

def get_trend(df):
    if df is None or len(df) < EMA_SLOW: return "NEUTRAL"
    df['ema_fast'] = df['close'].ewm(span=EMA_FAST).mean()
    df['ema_slow'] = df['close'].ewm(span=EMA_SLOW).mean()
    last = df.iloc[-1]
    return "BULLISH" if last['ema_fast'] > last['ema_slow'] else "BEARISH"

def check_liquidity_15m(df_15m, bias):
    """15m Sweep: wick takes recent high/low then closes back"""
    if df_15m is None or len(df_15m) < 30: return False, 0
    recent_high = df_15m['high'].iloc[-21:-1].max()
    recent_low = df_15m['low'].iloc[-21:-1].min()
    last = df_15m.iloc[-1]

    if bias == "BULLISH":
        swept = last['low'] < recent_low and last['close'] > recent_low
        return swept, recent_low
    else:
        swept = last['high'] > recent_high and last['close'] < recent_high
        return swept, recent_high

def check_entry_5m(df_5m, bias):
    """5m BOS after sweep"""
    if df_5m is None or len(df_5m) < 25: return None
    recent_high = df_5m['high'].iloc[-21:-1].max()
    recent_low = df_5m['low'].iloc[-21:-1].min()
    last_close = df_5m['close'].iloc[-1]

    if bias == "BULLISH" and last_close > recent_high:
        return {"entry": last_close, "sl": recent_low, "bos": recent_high}
    if bias == "BEARISH" and last_close < recent_low:
        return {"entry": last_close, "sl": recent_high, "bos": recent_low}
    return None

def place_mt5(bias, sl, tp, lot):
    """Trade that APPEARS IN YOUR MT5 PHONE"""
    url = f"https://mt-client-api-v1.agiliumtrade.agiliumtrade.ai/users/current/accounts/{ACCOUNT_ID}/trade"
    headers = {"auth-token": METAAPI_TOKEN, "Content-Type": "application/json"}
    payload = {
        "actionType": "ORDER_TYPE_BUY" if bias == "BULLISH" else "ORDER_TYPE_SELL",
        "symbol": SYMBOL,
        "volume": float(lot),
        "stopLoss": float(sl),
        "takeProfit": float(tp)
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        print(f"MT5 Trade Response: {r.text}", flush=True)
        if r.status_code == 200 and "tradeId" in r.text:
            tg(f"✅ *MT5 TRADE PLACED - {bias} 1:{RR}*\nEntry: {SYMBOL}\nSL: {sl:.2f}\nTP: {tp:.2f}\nCheck MT5 Phone NOW")
            return True
        else:
            tg(f"⚠️ MT5 Failed: {r.text[:300]}")
            return False
    except Exception as e:
        print(f"Place error: {e}")
        return False

def run():
    if not METAAPI_TOKEN or not ACCOUNT_ID:
        print("❌ ADD SECRETS: METAAPI_TOKEN and METAAPI_ACCOUNT_ID")
        time.sleep(99999)
        return

    tg(f"🟢 *XAU FLY BOT STARTED*\nH1/H4 Bias\n15m Liquidity Sweep\n5m Entry\nRR 1:{RR} LONG TERM\nRunning 24/7 on Fly.io")

    while True:
        try:
            now = datetime.now(timezone.utc).strftime('%H:%M:%S')
            print(f"[{now}] Scanning {SYMBOL}...", flush=True)

            df_h1 = get_candles("1h", 250)
            df_h4 = get_candles("4h", 250)
            df_15m = get_candles("15m", 100)
            df_5m = get_candles("5m", 100)

            if None in [df_h1, df_h4, df_15m, df_5m]:
                print("Waiting candles...")
                time.sleep(60)
                continue

            trend_h1 = get_trend(df_h1)
            trend_h4 = get_trend(df_h4)
            print(f"Bias -> H1:{trend_h1} H4:{trend_h4}", flush=True)

            if trend_h1!= trend_h4 or trend_h1 == "NEUTRAL":
                time.sleep(60)
                continue

            bias = trend_h1
            swept, liq_level = check_liquidity_15m(df_15m, bias)
            print(f"15m Liquidity Swept: {swept} | Level: {liq_level}", flush=True)

            if not swept:
                time.sleep(30)
                continue

            signal = check_entry_5m(df_5m, bias)
            if signal:
                entry = signal['entry']
                sl = signal['sl']
                tp_dist = abs(entry - sl) * RR
                tp = entry + tp_dist if bias == "BULLISH" else entry - tp_dist

                msg = f"""
🟢 *XAU {bias} LIQUIDITY*

*Bias:* H1 {trend_h1} + H4 {trend_h4} ✅
*15m:* Sweep ✅ `{liq_level:.2f}`
*5m:* BOS ✅ `{signal['bos']:.2f}`

Entry: `{entry:.2f}`
SL: `{sl:.2f}`
TP: `{tp:.2f}` (1:{RR})
*Will hold long term*
"""
                tg(msg)
                place_mt5(bias, sl, tp, LOT)
                print("Trade placed, cooling 30min...", flush=True)
                time.sleep(1800)
            else:
                time.sleep(20)

        except Exception as e:
            print(f"Loop Error: {e}", flush=True)
            time.sleep(60)

if __name__ == "__main__":
    run()

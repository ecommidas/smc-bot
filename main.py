import requests
import pandas as pd
import time
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

BASE_URL = "https://fapi.binance.com"

# ================= TELEGRAM =================
def send(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

# ================= DATA =================
def get_symbols():
    url = BASE_URL + "/fapi/v1/exchangeInfo"
    
    try:
        res = requests.get(url, timeout=10)
        data = res.json()

        # check lỗi API
        if isinstance(data, dict) and "symbols" not in data:
            print("API ERROR:", data)
            return []

        symbols = [
            s['symbol'] for s in data['symbols']
            if s['quoteAsset'] == "USDT" and s['contractType'] == "PERPETUAL"
        ]

        return symbols[:60]

    except Exception as e:
        print("ERROR get_symbols:", e)
        return []

def get_klines(symbol, interval):
    url = f"{BASE_URL}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit=100"
    data = requests.get(url).json()
    df = pd.DataFrame(data, columns=[
        "time","open","high","low","close","volume",
        "close_time","qav","trades","tbbav","tbqav","ignore"
    ])
    return df.astype(float)

# ================= INDICATORS =================
def ema(series, n):
    return series.ewm(span=n).mean()

def atr(df, n=14):
    df['tr'] = df['high'] - df['low']
    return df['tr'].rolling(n).mean()

# ================= SMC =================
def detect_sweep(df):
    high = df['high'].iloc[-5:-1].max()
    low = df['low'].iloc[-5:-1].min()
    last = df.iloc[-1]

    sweep_high = last['high'] > high and last['close'] < high
    sweep_low = last['low'] < low and last['close'] > low

    return sweep_high, sweep_low

def detect_bos(df, direction):
    if direction == "LONG":
        return df['close'].iloc[-1] > df['high'].iloc[-5:-1].max()
    if direction == "SHORT":
        return df['close'].iloc[-1] < df['low'].iloc[-5:-1].min()
    return False

# ================= SCORE =================
def score(trend_ok, sweep, bos, vol, atr_ok):
    s = 0
    if trend_ok: s += 4
    if sweep: s += 2
    if bos: s += 2
    if vol: s += 1
    if atr_ok: s += 1
    return s

# ================= TRADE PLAN =================
def trade_plan_smc(m15, h4, trend):
    entry = m15['close'].iloc[-1]

    # ===== LONG =====
    if trend == "LONG":
        # SL = đáy sweep gần nhất
        sl = m15['low'].iloc[-5:-1].min()

        # TP = H4 high gần nhất
        tp = h4['high'].iloc[-20:].max()

    # ===== SHORT =====
    else:
        # SL = đỉnh sweep gần nhất
        sl = m15['high'].iloc[-5:-1].max()

        # TP = H4 low gần nhất
        tp = h4['low'].iloc[-20:].min()

    return entry, sl, tp

def link(symbol):
    return f"https://www.binance.com/en/futures/{symbol}"

# ================= SCAN =================
def scan():
    results = []

    for sym in get_symbols():
        try:
            h4 = get_klines(sym, "4h")
            m15 = get_klines(sym, "15m")

            # EMA
            h4['ema34'] = ema(h4['close'], 34)
            h4['ema89'] = ema(h4['close'], 89)

            m15['ema34'] = ema(m15['close'], 34)
            m15['ema89'] = ema(m15['close'], 89)
            m15['atr'] = atr(m15)

            # Trend
            if h4['ema34'].iloc[-1] > h4['ema89'].iloc[-1]:
                trend = "LONG"
            elif h4['ema34'].iloc[-1] < h4['ema89'].iloc[-1]:
                trend = "SHORT"
            else:
                continue

            trend_ok = (
                (trend == "LONG" and m15['ema34'].iloc[-1] > m15['ema89'].iloc[-1]) or
                (trend == "SHORT" and m15['ema34'].iloc[-1] < m15['ema89'].iloc[-1])
            )

            if not trend_ok:
                continue

            # SMC
            sh, sl = detect_sweep(m15)

            if trend == "LONG":
                if not sl: continue
                bos = detect_bos(m15, "LONG")
                sweep = sl
            else:
                if not sh: continue
                bos = detect_bos(m15, "SHORT")
                sweep = sh

            if not bos:
                continue

            # Volume + ATR
            vol_now = m15['volume'].iloc[-1]
            vol_avg = m15['volume'].rolling(20).mean().iloc[-1]
            vol_ok = vol_now > 1.5 * vol_avg

            atr_ok = m15['atr'].iloc[-1] > m15['atr'].rolling(20).mean().iloc[-1]

            sc = score(trend_ok, sweep, bos, vol_ok, atr_ok)

            price, sl_p, tp1, tp2 = plan(m15, trend)

            results.append({
                "sym": sym,
                "trend": trend,
                "score": sc,
                "price": round(price, 4),
                "sl": round(sl_p, 4),
                "tp1": round(tp1, 4),
                "tp2": round(tp2, 4)
            })

        except:
            continue

    return sorted(results, key=lambda x: x['score'], reverse=True)[:5]

# ================= RUN =================
def run():
    while True:
        setups = scan()

        if setups:
            msg = "🔥 TOP SMC SETUPS\n\n"
            for i, s in enumerate(setups, 1):
                msg += f"""{i}. {s['sym']} - {s['trend']} (Score {s['score']})
Entry: {s['price']}
SL: {s['sl']}
TP1: {s['tp1']}
TP2: {s['tp2']}
{s['sym']} → {link(s['sym'])}

"""
            send(msg)
        else:
            send("No setup")

        time.sleep(300)

run()

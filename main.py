import requests
import pandas as pd
import time
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

BASE_URL = "https://fapi.binance.com"

# ================= TELEGRAM =================
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except:
        pass

# ================= DATA =================
def get_symbols():
    url = BASE_URL + "/fapi/v1/exchangeInfo"
    try:
        res = requests.get(url, timeout=10)
        data = res.json()

        if isinstance(data, dict) and "symbols" not in data:
            return []

        symbols = [
            s['symbol'] for s in data['symbols']
            if s['quoteAsset'] == "USDT" and s['contractType'] == "PERPETUAL"
        ]

        return symbols[:30]

    except:
        return []

def get_klines(symbol, interval):
    url = f"{BASE_URL}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit=100"

    for _ in range(3):
        try:
            res = requests.get(url, timeout=10)
            data = res.json()

            if isinstance(data, list):
                df = pd.DataFrame(data, columns=[
                    "time","open","high","low","close","volume",
                    "close_time","qav","trades","tbbav","tbqav","ignore"
                ])
                return df.astype(float)

        except:
            time.sleep(1)

    return None

# ================= INDICATORS =================
def ema(series, n):
    return series.ewm(span=n).mean()

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

# ================= TRADE PLAN =================
def trade_plan_smc(m15, h4, trend):
    # Entry tại EMA34 (pullback đẹp hơn)
    entry = m15['ema34'].iloc[-1]

    if trend == "LONG":
        sl = m15['low'].iloc[-5:-1].min()
        tp = h4['high'].iloc[-20:].max()
    else:
        sl = m15['high'].iloc[-5:-1].max()
        tp = h4['low'].iloc[-20:].min()

    return entry, sl, tp

def calc_rr(entry, sl, tp):
    risk = abs(entry - sl)
    reward = abs(tp - entry)

    if risk == 0:
        return 0

    return reward / risk

# ================= SCORE =================
def calc_score(trend_ok, sweep, bos, vol_ok):
    score = 0

    if trend_ok: score += 4
    if sweep: score += 2
    if bos: score += 2
    if vol_ok: score += 2

    return score

# ================= LINK =================
def link(symbol):
    return f"https://www.binance.com/en/futures/{symbol}"

# ================= SCAN =================
def scan():
    results = []

    for sym in get_symbols():
        try:
            h4 = get_klines(sym, "4h")
            m15 = get_klines(sym, "15m")

            if h4 is None or m15 is None:
                continue

            # EMA
            h4['ema34'] = ema(h4['close'], 34)
            h4['ema89'] = ema(h4['close'], 89)

            m15['ema34'] = ema(m15['close'], 34)
            m15['ema89'] = ema(m15['close'], 89)

            # Trend H4
            if h4['ema34'].iloc[-1] > h4['ema89'].iloc[-1]:
                trend = "LONG"
            elif h4['ema34'].iloc[-1] < h4['ema89'].iloc[-1]:
                trend = "SHORT"
            else:
                continue

            # Trend M15 confirm
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

            # Volume filter
            vol_now = m15['volume'].iloc[-1]
            vol_avg = m15['volume'].rolling(20).mean().iloc[-1]
            vol_ok = vol_now > 1.5 * vol_avg

            # Trade plan
            entry, sl_p, tp = trade_plan_smc(m15, h4, trend)
            rr = calc_rr(entry, sl_p, tp)

            # Filter RR
            if rr < 4:
                continue

            score = calc_score(trend_ok, sweep, bos, vol_ok)

            results.append({
                "sym": sym,
                "trend": trend,
                "score": score,
                "entry": round(entry, 5),
                "sl": round(sl_p, 5),
                "tp": round(tp, 5),
                "rr": round(rr, 2)
            })

        except:
            continue

    return sorted(results, key=lambda x: x['score'], reverse=True)[:5]

# ================= RUN =================
def run():
    while True:
        setups = scan()

        if setups:
            msg = "🔥 TOP SMC SETUPS (RR > 4)\n\n"

            for i, s in enumerate(setups, 1):
                msg += f"""{i}. {s['sym']} - {s['trend']} (Score {s['score']})
Entry: {s['entry']}
SL: {s['sl']} (M15)
TP: {s['tp']} (H4)
RR: {s['rr']}

Trade: {link(s['sym'])}

"""

            send(msg)
        else:
            send("No SMC setup (RR > 4)")

        time.sleep(300)  # 5 phút

run()

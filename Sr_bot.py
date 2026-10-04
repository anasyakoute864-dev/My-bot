"""
Support/Resistance + Fair Value Gap alert bot (multi-timeframe).
ALERTS ONLY: no orders are ever placed, nothing is predicted.

Usage:
  python sr_bot.py status   -> analyze now, print and send to Telegram
  python sr_bot.py run      -> keep watching and alert on new signals

Env vars: TG_TOKEN, TG_CHAT
"""
import os
import sys
import time
import urllib.parse
import urllib.request

import ccxt
import pandas as pd

SYMBOL = "BTC/USDT"
TIMEFRAMES = ["1h", "4h"]
LOOKBACK = 100          # candles used to find the recent top / bottom
ZONE_PCT = 0.005        # 0.5% distance counts as "at the zone"
FVG_LOOKBACK = 30       # how far back to look for open gaps
CHECK_SECONDS = 60
EXCHANGES = ["kraken", "bitstamp", "coinbase"]
ERROR_ALERT_AFTER = 5   # consecutive failures before a Telegram warning

TG_TOKEN = os.environ.get("TG_TOKEN", "").strip()
TG_CHAT = os.environ.get("TG_CHAT", "").strip()

_exchanges = {}


def notify(msg):
    print(msg, flush=True)
    print("-" * 30, flush=True)
    if not TG_TOKEN or not TG_CHAT:
        return
    try:
        url = "https://api.telegram.org/bot" + TG_TOKEN + "/sendMessage"
        data = urllib.parse.urlencode({"chat_id": TG_CHAT, "text": msg}).encode()
        with urllib.request.urlopen(url, data=data, timeout=10):
            pass
    except Exception as e:
        # never print the URL: it contains the token
        print("Telegram error:", type(e).__name__, flush=True)


def get_exchange(name):
    if name not in _exchanges:
        _exchanges[name] = getattr(ccxt, name)(
            {"enableRateLimit": True, "timeout": 15000}
        )
    return _exchanges[name]


def fetch(tf, limit=300):
    last_err = None
    for name in EXCHANGES:
        try:
            raw = get_exchange(name).fetch_ohlcv(SYMBOL, tf, limit=limit)
            if raw and len(raw) > LOOKBACK + 2:
                df = pd.DataFrame(
                    raw,
                    columns=["time", "open", "high", "low", "close", "volume"],
                )
                df["time"] = pd.to_datetime(df["time"], unit="ms")
                return df
        except Exception as e:
            last_err = e
    raise RuntimeError("Could not fetch data: " + str(last_err))


def find_fvgs(df):
    """Open (not fully filled) bullish and bearish gaps in recent candles."""
    hi = df["high"].values
    lo = df["low"].values
    n = len(df)
    bull, bear = [], []
    for i in range(max(2, n - FVG_LOOKBACK), n):
        if lo[i] > hi[i - 2]:
            bottom, top = hi[i - 2], lo[i]
            if i + 1 >= n or lo[i + 1:].min() > bottom:
                bull.append((float(bottom), float(top)))
        if hi[i] < lo[i - 2]:
            bottom, top = hi[i], lo[i - 2]
            if i + 1 >= n or hi[i + 1:].max() < top:
                bear.append((float(bottom), float(top)))
    return bull, bear


def analyze(df):
    df = df.iloc[:-1].reset_index(drop=True)   # closed candles only
    last = df.iloc[-1]
    window = df.iloc[-(LOOKBACK + 1):-1]
    res = float(window["high"].max())
    sup = float(window["low"].min())
    price = float(last["close"])
    bull, bear = find_fvgs(df)
    return {
        "time": str(last["time"]),
        "price": price,
        "res": res,
        "sup": sup,
        "near_res": float(last["high"]) >= res * (1 - ZONE_PCT),
        "near_sup": float(last["low"]) <= sup * (1 + ZONE_PCT),
        "broke_res": price > res,
        "broke_sup": price < sup,
        "bull": bull,
        "bear": bear,
        "in_bull": any(b <= price <= t for b, t in bull),
        "in_bear": any(b <= price <= t for b, t in bear),
    }


def summary(tf, r):
    lines = [
        SYMBOL + " " + tf + " | candle " + r["time"],
        "Price: {:.2f}".format(r["price"]),
        "Resistance ({}c high): {:.2f}".format(LOOKBACK, r["res"]),
        "Support ({}c low): {:.2f}".format(LOOKBACK, r["sup"]),
        "Open bullish FVG: {} | bearish FVG: {}".format(len(r["bull"]), len(r["bear"])),
    ]
    if r["in_bull"]:
        lines.append("Price is INSIDE a bullish FVG")
    if r["in_bear"]:
        lines.append("Price is INSIDE a bearish FVG")
    return "\n".join(lines)


def build_alerts(results, seen):
    alerts = []
    for side, key_near, key_break, fvg_key, level_key in (
        ("SELL ZONE", "near_res", "broke_res", "bear", "res"),
        ("BUY ZONE", "near_sup", "broke_sup", "bull", "sup"),
    ):
        flagged = [tf for tf, r in results.items() if r[key_near]]
        for tf in flagged:
            r = results[tf]
            key = (tf, side, r["time"])
            if key in seen:
                continue
            seen.add(key)
            lines = ["[" + side + "] " + SYMBOL + " " + tf, "Price: {:.2f}".format(r["price"])]
            lines.append("Level: {:.2f}".format(r[level_key]))
            if r[key_break]:
                lines.append("Level was BROKEN (possible breakout, not a reversal)")
            lines.append("Same-direction open FVG: " + ("yes" if r[fvg_key] else "no"))
            if len(flagged) == len(results):
                lines.append("ALL timeframes are at this zone")
            lines.append("Alert only. Not a prediction or advice.")
            alerts.append("\n".join(lines))
    return alerts


def get_results():
    return {tf: analyze(fetch(tf)) for tf in TIMEFRAMES}


def status():
    results = get_results()
    text = "\n\n".join(summary(tf, r) for tf, r in results.items())
    notify("STATUS\n" + text)


def run():
    notify("S/R + FVG alert bot started | " + SYMBOL + " " + ",".join(TIMEFRAMES))
    seen = set()
    fails = 0
    try:
        while True:
            try:
                results = get_results()
                for msg in build_alerts(results, seen):
                    notify(msg)
                # keep memory bounded: forget alerts from old candles
                current = {r["time"] for r in results.values()}
                seen.intersection_update({k for k in seen if k[2] in current})
                if fails >= ERROR_ALERT_AFTER:
                    notify("Bot recovered: data is coming in again.")
                fails = 0
            except Exception as e:
                fails += 1
                print("Error ({}): {}".format(fails, e), flush=True)
                if fails == ERROR_ALERT_AFTER:
                    notify("WARNING: bot cannot fetch data ({} failures). Still retrying.".format(fails))
            time.sleep(CHECK_SECONDS * min(max(fails, 1), 5))
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    if "run" in sys.argv:
        run()
    else:
        status()

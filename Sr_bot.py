"""
Support/Resistance + Fair Value Gap alert bot (multi-timeframe).
Crypto via ccxt, Forex and Gold via Yahoo Finance.
ALERTS ONLY: no orders are ever placed, nothing is predicted.

Usage:
  python Sr_bot.py status   -> analyze now, print and send to Telegram
  python Sr_bot.py run      -> keep watching and alert on new signals

Env vars: TG_TOKEN, TG_CHAT
Optional: FOREX_SYMBOLS (comma separated Yahoo symbols, empty = no forex)
"""
import os
import sys
import time
import urllib.parse
import urllib.request

import ccxt
import pandas as pd

CRYPTO_SYMBOLS = ["BTC/USDT"]
_fx = os.environ.get("FOREX_SYMBOLS")
if _fx is None:
    _fx = "EURUSD=X,GBPUSD=X,USDJPY=X,GC=F"
FOREX_SYMBOLS = [s.strip() for s in _fx.split(",") if s.strip()]

TIMEFRAMES = ["1h", "4h"]
LOOKBACK = 100 # candles used to find the recent top / bottom
FVG_LOOKBACK = 30 # how far back to look for open gaps
CHECK_SECONDS = 60
EXCHANGES = ["kraken", "bitstamp", "coinbase"]
ERROR_ALERT_AFTER = 5 # consecutive failures before a Telegram warning
FOREX_CACHE_SECONDS = 300
FOREX_RETRY_SECONDS = 300

# distance from the level that counts as "at the zone"
ZONE_PCT_CRYPTO = 0.005
ZONE_PCT_FOREX = 0.0015
ZONE_OVERRIDE = {"GC=F": 0.003, "SI=F": 0.004}
NAMES = {"GC=F": "GOLD", "SI=F": "SILVER"}

TG_TOKEN = os.environ.get("TG_TOKEN", "").strip()
TG_CHAT = os.environ.get("TG_CHAT", "").strip()

_exchanges = {}
_fx_cache = {}
_fx_fail = {}


def display(sym):
    if sym in NAMES:
        return NAMES[sym]
    if sym.endswith("=X") and len(sym) == 8:
        return sym[:3] + "/" + sym[3:6]
    return sym


def zone_for(sym):
    if sym in ZONE_OVERRIDE:
        return ZONE_OVERRIDE[sym]
    if sym in FOREX_SYMBOLS:
        return ZONE_PCT_FOREX
    return ZONE_PCT_CRYPTO


def fmt(p):
    if p >= 1000:
        return "{:.2f}".format(p)
    if p >= 20:
        return "{:.3f}".format(p)
    return "{:.5f}".format(p)


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


def fetch_crypto(symbol, tf, limit=300):
    last_err = None
    for name in EXCHANGES:
        try:
            raw = get_exchange(name).fetch_ohlcv(symbol, tf, limit=limit)
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


def fetch_forex_1h(symbol):
    now = time.time()
    hit = _fx_cache.get(symbol)
    if hit and now - hit[0] < FOREX_CACHE_SECONDS:
        return hit[1]
    bad = _fx_fail.get(symbol)
    if bad and now - bad[0] < FOREX_RETRY_SECONDS:
        raise RuntimeError(bad[1])
    try:
        import yfinance as yf

        raw = yf.Ticker(symbol).history(period="60d", interval="1h")
        if raw is None or raw.empty:
            raise RuntimeError("No Yahoo data for " + symbol)
        raw = raw.reset_index()
        tcol = raw.columns[0]
        base = pd.DataFrame(
            {
                "time": pd.to_datetime(raw[tcol], utc=True).dt.tz_localize(None),
                "open": raw["Open"].astype(float),
                "high": raw["High"].astype(float),
                "low": raw["Low"].astype(float),
                "close": raw["Close"].astype(float),
                "volume": raw["Volume"].astype(float),
            }
        )
        base = base.dropna().reset_index(drop=True)
    except Exception as e:
        msg = "Yahoo error for {}: {}".format(symbol, str(e)[:150])
        _fx_fail[symbol] = (now, msg)
        raise RuntimeError(msg)
    _fx_fail.pop(symbol, None)
    _fx_cache[symbol] = (now, base)
    return base


def fetch_forex(symbol, tf):
    base = fetch_forex_1h(symbol)
    if tf == "1h":
        return base.copy()
    if tf == "4h":
        out = (
            base.set_index("time")
            .resample("4h")
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna(subset=["open"])
            .reset_index()
        )
        return out
    raise RuntimeError("Unsupported timeframe for forex: " + tf)


def fetch(symbol, tf):
    if symbol in FOREX_SYMBOLS:
        return fetch_forex(symbol, tf)
    return fetch_crypto(symbol, tf)


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


def analyze(df, zone):
    df = df.iloc[:-1].reset_index(drop=True) # closed candles only
    if len(df) < LOOKBACK + 2:
        raise RuntimeError("Not enough candles ({})".format(len(df)))
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
        "near_res": float(last["high"]) >= res * (1 - zone),
        "near_sup": float(last["low"]) <= sup * (1 + zone),
        "broke_res": price > res,
        "broke_sup": price < sup,
        "bull": bull,
        "bear": bear,
        "in_bull": any(b <= price <= t for b, t in bull),
        "in_bear": any(b <= price <= t for b, t in bear),
    }


def summary(sym, tf, r):
    lines = [
        display(sym) + " " + tf + " | candle " + r["time"],
        "Price: " + fmt(r["price"]),
        "Resistance ({}c high): {}".format(LOOKBACK, fmt(r["res"])),
        "Support ({}c low): {}".format(LOOKBACK, fmt(r["sup"])),
        "Open bullish FVG: {} | bearish FVG: {}".format(len(r["bull"]), len(r["bear"])),
    ]
    if r["in_bull"]:
        lines.append("Price is INSIDE a bullish FVG")
    if r["in_bear"]:
        lines.append("Price is INSIDE a bearish FVG")
    return "\n".join(lines)


def build_alerts(results, seen):
    alerts = []
    for sym, per_tf in results.items():
        for side, key_near, key_break, fvg_key, level_key in (
            ("SELL ZONE", "near_res", "broke_res", "bear", "res"),
            ("BUY ZONE", "near_sup", "broke_sup", "bull", "sup"),
        ):
            flagged = [tf for tf, r in per_tf.items() if r[key_near]]
            for tf in flagged:
                r = per_tf[tf]
                key = (sym, tf, side, r["time"])
                if key in seen:
                    continue
                seen.add(key)
                lines = [
                    "[" + side + "] " + display(sym) + " " + tf,
                    "Price: " + fmt(r["price"]),
                    "Level: " + fmt(r[level_key]),
                ]
                if r[key_break]:
                    lines.append("Level was BROKEN (possible breakout, not a reversal)")
                lines.append("Same-direction open FVG: " + ("yes" if r[fvg_key] else "no"))
                if len(flagged) == len(per_tf):
                    lines.append("ALL timeframes are at this zone")
                lines.append("Alert only. Not a prediction or advice.")
                alerts.append("\n".join(lines))
    return alerts


def get_results():
    results, errors = {}, []
    for sym in CRYPTO_SYMBOLS + FOREX_SYMBOLS:
        try:
            zone = zone_for(sym)
            results[sym] = {tf: analyze(fetch(sym, tf), zone) for tf in TIMEFRAMES}
        except Exception as e:
            errors.append((sym, str(e)[:200]))
    return results, errors


def status():
    results, errors = get_results()
    parts = []
    for sym, per_tf in results.items():
        for tf, r in per_tf.items():
            parts.append(summary(sym, tf, r))
    for sym, msg in errors:
        parts.append("Could not load " + display(sym) + ": " + msg)
    notify("STATUS\n" + "\n\n".join(parts))


def run():
    names = [display(s) for s in CRYPTO_SYMBOLS + FOREX_SYMBOLS]
    notify("S/R + FVG alert bot started | " + ", ".join(names) + " | " + ",".join(TIMEFRAMES))
    seen = set()
    fails = {}
    try:
        while True:
            try:
                results, errors = get_results()
                for sym, msg in errors:
                    fails[sym] = fails.get(sym, 0) + 1
                    print("Error {} ({}): {}".format(display(sym), fails[sym], msg), flush=True)
                    if fails[sym] == ERROR_ALERT_AFTER:
                        notify("WARNING: cannot fetch " + display(sym) + ". Still retrying.")
                for sym in results:
                    if fails.get(sym, 0) >= ERROR_ALERT_AFTER:
                        notify("Recovered: " + display(sym) + " data is coming in again.")
                    fails[sym] = 0
                for msg in build_alerts(results, seen):
                    notify(msg)
                # keep memory bounded: forget alerts from old candles
                current = {r["time"] for per_tf in results.values() for r in per_tf.values()}
                seen.intersection_update({k for k in seen if k[3] in current})
            except Exception as e:
                print("Loop error:", type(e).__name__, str(e)[:200], flush=True)
            time.sleep(CHECK_SECONDS)
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    if "run" in sys.argv:
        run()
    else:
        status()

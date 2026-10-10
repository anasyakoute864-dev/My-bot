"""
gold_signals.py - Gold signals to Telegram (signals only, no trading).
Runs every ~10 minutes on GitHub Actions.

Logic (same ideas as the MT5 EA, minus tick order flow):
  - Fibonacci auto swing (H1)           - Fixed-range Volume Profile (H1): POC / VAH / VAL
  - EMA trend + MACD + RSI (M10)        - D1 candle bias (engulfing / pin bar / doji)
  - Breakout and liquidity-sweep reversal on the last closed M10 bar
  - High-impact USD news warning
Data: Yahoo Finance gold futures (GC=F). Price is close to XAUUSD but not identical.
"""
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

TG_TOKEN = os.environ.get("TG_TOKEN", "")
TG_CHAT = os.environ.get("TG_CHAT_ID", "")
SYMBOL = os.environ.get("YF_SYMBOL", "GC=F")
MIN_SCORE = int(os.environ.get("MIN_SCORE", "6"))   # max 8
SL_ATR = 1.5
RR = 2.0
STRUCT = 20          # structure lookback (M10 bars)
FIB_BARS = 120       # H1 bars
VP_BARS = 200        # H1 bars
VP_BINS = 48
NEWS_BLOCK_MIN = 30
LOOKBACK = int(os.environ.get("LOOKBACK_BARS", "1"))        # closed M10 bars to scan per run
INTERVAL_MIN = int(os.environ.get("INTERVAL_MIN", "10"))    # how often the cron runs (minutes)


# ----------------------------------------------------------------- utils
def tg(msg):
    if not TG_TOKEN or not TG_CHAT:
        print("[no telegram config]\n" + msg)
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data={"chat_id": TG_CHAT, "text": msg},
            timeout=20,
        )
        if r.status_code != 200:
            print("Telegram error", r.status_code, r.text[:200])
    except Exception as e:  # noqa
        print("Telegram exception", e)


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def atr(df, n=14):
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def fetch(interval, period):
    import yfinance as yf
    df = yf.Ticker(SYMBOL).history(interval=interval, period=period, auto_adjust=False)
    df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])
    return df


def to_10m(m5):
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    return m5.resample("10min").agg(agg).dropna(subset=["close"])


def drop_incomplete(df, minutes):
    if len(df) and df.index[-1] + pd.Timedelta(minutes=minutes) > pd.Timestamp.now(tz="UTC"):
        return df.iloc[:-1]
    return df


# ------------------------------------------------------------ components
def volume_profile(df, bins=VP_BINS, va=0.70):
    hi, lo = df["high"].max(), df["low"].min()
    bs = (hi - lo) / bins
    vol = np.zeros(bins)
    for hh, ll, vv in zip(df["high"], df["low"], df["volume"]):
        vv = vv if vv > 0 else 1.0
        b1 = min(bins - 1, max(0, int((ll - lo) // bs)))
        b2 = min(bins - 1, max(0, int((hh - lo) // bs)))
        vol[b1:b2 + 1] += vv / (b2 - b1 + 1)
    poc_i = int(vol.argmax())
    lo_i = hi_i = poc_i
    acc, target = vol[poc_i], vol.sum() * va
    while acc < target and (lo_i > 0 or hi_i < bins - 1):
        up = vol[hi_i + 1] if hi_i < bins - 1 else -1
        dn = vol[lo_i - 1] if lo_i > 0 else -1
        if up >= dn:
            hi_i += 1
            acc += vol[hi_i]
        else:
            lo_i -= 1
            acc += vol[lo_i]
    return lo + (poc_i + 0.5) * bs, lo + (hi_i + 1) * bs, lo + lo_i * bs


def d1_bias(d1):
    if len(d1) < 3:
        return "none", 0
    a, b = d1.iloc[-1], d1.iloc[-2]
    o1, c1, h1, l1 = a["open"], a["close"], a["high"], a["low"]
    o2, c2 = b["open"], b["close"]
    body, rng = abs(c1 - o1), h1 - l1
    up_w, lo_w = h1 - max(o1, c1), min(o1, c1) - l1
    if rng <= 0:
        return "none", 0
    if body < rng * 0.1:
        return "Doji", 0
    if c2 < o2 and c1 > o1 and c1 >= o2 and o1 <= c2:
        return "Bullish Engulfing", 1
    if c2 > o2 and c1 < o1 and c1 <= o2 and o1 >= c2:
        return "Bearish Engulfing", -1
    if lo_w > body * 2 and up_w < body:
        return "Bullish Pin Bar", 1
    if up_w > body * 2 and lo_w < body:
        return "Bearish Pin Bar", -1
    if c1 > o1 and body > rng * 0.6:
        return "Strong Bull Candle", 1
    if c1 < o1 and body > rng * 0.6:
        return "Strong Bear Candle", -1
    return "none", 0


def usd_news():
    try:
        data = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=15).json()
    except Exception as e:  # noqa
        print("news fetch failed", e)
        return []
    ev = []
    for e in data:
        if e.get("country") != "USD" or e.get("impact") != "High":
            continue
        try:
            t = datetime.fromisoformat(e["date"]).astimezone(timezone.utc)
        except Exception:  # noqa
            continue
        ev.append((t, e.get("title", "")))
    ev.sort()
    return ev


# --------------------------------------------------------------- analysis
def analyze(m10, h1, d1, news):
    c, h, l, v = (m10[k].values for k in ("close", "high", "low", "volume"))
    ef = ema(m10["close"], 21).values
    es = ema(m10["close"], 50).values
    rs = rsi(m10["close"]).values
    at = atr(m10).values
    macd_line = ema(m10["close"], 12) - ema(m10["close"], 26)
    ml, ms = macd_line.values, ema(macd_line, 9).values
    if np.isnan(at[-1]) or np.isnan(rs[-1]):
        return [], "not enough data"

    hb = h1.tail(FIB_BARS)
    highs, lows = hb["high"].values, hb["low"].values
    hi_pos, lo_pos = int(np.argmax(highs)), int(np.argmin(lows))
    fhi, flo = highs[hi_pos], lows[lo_pos]
    frng, fup = fhi - flo, lo_pos < hi_pos

    def fib(r):
        return fhi - frng * r if fup else flo + frng * r

    poc, vah, val = volume_profile(h1.tail(VP_BARS))
    d1name, d1b = d1_bias(d1)

    def score(i):
        px, tol = c[i], at[i] * 0.3
        b = s = 0
        rb, rr = [], []
        if ef[i] > es[i]:
            b += 1; rb.append("EMA trend up")
        if ef[i] < es[i]:
            s += 1; rr.append("EMA trend down")
        if d1b > 0:
            b += 1; rb.append(f"D1 {d1name}")
        if d1b < 0:
            s += 1; rr.append(f"D1 {d1name}")
        if ml[i] > ms[i]:
            b += 1; rb.append("MACD bull")
        if ml[i] < ms[i]:
            s += 1; rr.append("MACD bear")
        if 35 < rs[i] < 65 and rs[i] > rs[i - 1]:
            b += 1; rb.append("RSI rising")
        if 35 < rs[i] < 65 and rs[i] < rs[i - 1]:
            s += 1; rr.append("RSI falling")
        f50, f618, f786 = fib(0.5), fib(0.618), fib(0.786)
        if fup and f618 - tol <= px <= f50 + tol and px > f786:
            b += 2; rb.append("Fibo golden zone")
        if (not fup) and f50 - tol <= px <= f618 + tol and px < f786:
            s += 2; rr.append("Fibo golden zone")
        if abs(px - val) <= tol or (abs(px - poc) <= tol and px <= poc + tol):
            b += 2; rb.append("Volume Profile support (VAL/POC)")
        if abs(px - vah) <= tol or (abs(px - poc) <= tol and px >= poc - tol):
            s += 2; rr.append("Volume Profile resistance (VAH/POC)")
        return b, s, rb, rr

    def dir_of(i):
        b, s, _, _ = score(i)
        if b >= MIN_SCORE and b > s:
            return 1
        if s >= MIN_SCORE and s > b:
            return -1
        return 0

    now = datetime.now(timezone.utc)
    near = [(t, n) for t, n in news if abs((t - now).total_seconds()) <= NEWS_BLOCK_MIN * 60]
    news_line = ("WARNING high-impact news: " + near[0][1] + " - avoid entries") if near else "News: clear"
    nxt = [(t, n) for t, n in news if t > now][:2]
    next_line = "Next USD news: " + ("; ".join(f"{n} {t.strftime('%a %H:%M')} UTC" for t, n in nxt) if nxt else "none this week")

    px, a = c[-1], at[-1]

    def levels(d):
        sl = px - a * SL_ATR if d > 0 else px + a * SL_ATR
        tp = px + a * SL_ATR * RR if d > 0 else px - a * SL_ATR * RR
        return f"Entry ~{px:.2f} | SL {sl:.2f} | TP {tp:.2f}"

    footer = f"\nPOC {poc:.2f} | VAH {vah:.2f} | VAL {val:.2f}\n{news_line}\n(levels from GC futures, adjust to your XAUUSD price)"
    msgs = []

    # scan the last LOOKBACK closed M10 bars (needed when the cron runs less often than every 10 min)
    for k in range(LOOKBACK):
        i = -1 - k
        try:
            bar = m10.index[i].tz_convert("UTC").strftime("%H:%M UTC")
        except Exception:  # noqa
            bar = str(m10.index[i])
        tag = f" [bar {bar}]" if LOOKBACK > 1 else ""

        # confluence signal (only when direction changes)
        d_now, d_prev = dir_of(i), dir_of(i - 1)
        if d_now != 0 and d_now != d_prev:
            b_, s_, rb_, rr_ = score(i)
            why = rb_ if d_now > 0 else rr_
            sc = b_ if d_now > 0 else s_
            msgs.append(f"{'BUY' if d_now > 0 else 'SELL'} GOLD | score {sc}/8{tag}\n{levels(d_now)}\nWhy: {', '.join(why)}{footer}")

        # breakout / sweep
        prior_h = h[i - STRUCT:i].max()
        prior_l = l[i - STRUCT:i].min()
        vmean = v[i - 20:i].mean()
        vol_ok = v[i] > 1.2 * vmean if vmean > 0 else True
        if c[i] > prior_h + at[i] * 0.1 and ef[i] > es[i] and vol_ok:
            msgs.append(f"BREAKOUT BUY GOLD above {prior_h:.2f}{tag}\n{levels(1)}{footer}")
        if c[i] < prior_l - at[i] * 0.1 and ef[i] < es[i] and vol_ok:
            msgs.append(f"BREAKOUT SELL GOLD below {prior_l:.2f}{tag}\n{levels(-1)}{footer}")
        if l[i] < prior_l and c[i] > prior_l:
            msgs.append(f"SWEEP REVERSAL BUY GOLD (liquidity grab below {prior_l:.2f}){tag}\n{levels(1)}{footer}")
        if h[i] > prior_h and c[i] < prior_h:
            msgs.append(f"SWEEP REVERSAL SELL GOLD (liquidity grab above {prior_h:.2f}){tag}\n{levels(-1)}{footer}")

    b, s, _, _ = score(-1)

    status = (f"Status: price {px:.2f} | buy {b}/8 sell {s}/8 | Fibo {'UP' if fup else 'DOWN'} {flo:.2f}->{fhi:.2f}\n"
              f"D1: {d1name}\n{news_line}\n{next_line}\n{footer.split(chr(10))[1]}")
    # warning shortly before news (fires once per 10-min cron window)
    upcoming = [(t, n) for t, n in news if 5 <= (t - now).total_seconds() / 60 < 5 + INTERVAL_MIN]
    for t, n in upcoming:
        msgs.append(f"NEWS in ~{int((t - now).total_seconds() / 60)} min: {n} (USD high impact). Expect volatility.")
    return msgs, status


# ------------------------------------------------------------------ main
def main():
    manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    m10 = drop_incomplete(to_10m(fetch("5m", "5d")), 10)
    h1 = drop_incomplete(fetch("60m", "60d"), 60)
    d1 = fetch("1d", "90d")
    if len(d1) and d1.index[-1].date() == pd.Timestamp.now(tz=d1.index.tz).date():
        d1 = d1.iloc[:-1]

    age = pd.Timestamp.now(tz="UTC") - m10.index[-1]
    if age > pd.Timedelta(minutes=45):
        print("Market closed / stale data, last bar:", m10.index[-1])
        if manual:
            tg("Gold signal bot is connected. Market is closed now; signals start when it opens.")
        return

    msgs, status = analyze(m10, h1, d1, usd_news())
    if manual:
        tg("Gold signal bot connected.\n" + status)
    for m in msgs:
        tg(m)
    print(f"{len(msgs)} message(s) sent")


if __name__ == "__main__":
    main()

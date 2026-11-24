"""Claude Swing (فريم 1 ساعة): Donchian 20/10 شراء + بيع بفلتر اتجاه، ستوب 2×ATR20 (نفس regime_backtest.py).
شراء: إغلاق فوق أعلى 20 شمعة فاتجاه صاعد (close>EMA200 و EMA50>EMA200). بيع: إغلاق تحت أدنى 20 شمعة فاتجاه نازل.
خروج: الستوب ولا إغلاق عكس أعلى/أدنى 10 شموع. كنخدمو غير على الشموع المسدودة."""
import pandas as pd

N, X, ATRN, MULT = 20, 10, 20, 2.0
STEP = pd.Timedelta(hours=1)


def prep(df):
    d = df.copy()
    d["tc"] = pd.to_datetime(d["time"], utc=True) + STEP          # وقت سد الشمعة
    pc = d["close"].shift(1)
    tr = pd.concat([d["high"] - d["low"], (d["high"] - pc).abs(), (d["low"] - pc).abs()], axis=1).max(axis=1)
    d["atr20"] = tr.rolling(ATRN).mean()
    d["hiN"] = d["high"].rolling(N).max().shift(1)
    d["loX"] = d["low"].rolling(X).min().shift(1)
    d["loN"] = d["low"].rolling(N).min().shift(1)
    d["hiX"] = d["high"].rolling(X).max().shift(1)
    e50, e200 = d["close"].ewm(span=50, adjust=False).mean(), d["close"].ewm(span=200, adjust=False).mean()
    d["up"] = (d["close"] > e200) & (e50 > e200)
    d["dn"] = (d["close"] < e200) & (e50 < e200)
    return d.reset_index(drop=True)


def evaluate(df, pos, now, stale_min=90):
    """يرجع (events, pos_جديد). event: {"kind": "entry"|"exit", "side": 1|-1, ...}"""
    d = prep(df)
    events, exited_bar = [], None
    if pos:
        side = int(pos.get("side", 1))
        t0 = pd.Timestamp(pos["t"])
        for _, b in d[d["tc"] > t0].iterrows():
            stop_hit = (side == 1 and b["low"] <= pos["sl"]) or (side == -1 and b["high"] >= pos["sl"])
            if stop_hit:
                px = min(float(b["open"]), pos["sl"]) if side == 1 else max(float(b["open"]), pos["sl"])
                events.append({"kind": "exit", "side": side, "reason": "stop", "price": px, "entry": pos["entry"], "t": b["tc"]})
                pos, exited_bar = None, b["tc"]
                break
            chan = (side == 1 and pd.notna(b["loX"]) and b["close"] < b["loX"]) or (side == -1 and pd.notna(b["hiX"]) and b["close"] > b["hiX"])
            if chan:
                events.append({"kind": "exit", "side": side, "reason": "channel", "price": float(b["close"]), "entry": pos["entry"], "t": b["tc"]})
                pos, exited_bar = None, b["tc"]
                break
    if not pos and len(d):
        last = d.iloc[-1]
        fresh = (pd.Timestamp(now) - last["tc"]) <= pd.Timedelta(minutes=stale_min)
        if fresh and exited_bar != last["tc"] and pd.notna(last["atr20"]) and pd.notna(last["hiN"]) and pd.notna(last["loN"]):
            side = 1 if (last["up"] and last["close"] > last["hiN"]) else -1 if (last["dn"] and last["close"] < last["loN"]) else 0
            if side:
                e = float(last["close"])
                risk = MULT * float(last["atr20"])
                sl = e - side * risk
                pos = {"t": last["tc"].isoformat(), "entry": e, "sl": sl, "side": side}
                events.append({"kind": "entry", "side": side, "price": e, "sl": sl, "risk": risk, "t": last["tc"]})
    return events, pos

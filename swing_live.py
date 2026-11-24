"""Claude Swing (فريم 1 ساعة): Donchian 20/10 شراء فقط، ستوب 2×ATR20. نفس القاعدة اللي جربناها فالـ backtest.
دخول: إغلاق شمعة ساعة فوق أعلى 20 شمعة سابقة. خروج: الستوب ولا إغلاق تحت أدنى 10 شموع سابقة. كنخدمو غير على الشموع المسدودة."""
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
    return d.reset_index(drop=True)


def evaluate(df, pos, now, stale_min=90):
    """يرجع (events, pos_جديد). event: {"kind": "entry"|"exit", ...}"""
    d = prep(df)
    events, exited_bar = [], None
    if pos:
        t0 = pd.Timestamp(pos["t"])
        for _, b in d[d["tc"] > t0].iterrows():
            if pd.notna(b["low"]) and b["low"] <= pos["sl"]:
                px = min(float(b["open"]), pos["sl"])
                events.append({"kind": "exit", "reason": "stop", "price": px, "entry": pos["entry"], "t": b["tc"]})
                pos, exited_bar = None, b["tc"]
                break
            if pd.notna(b["loX"]) and b["close"] < b["loX"]:
                events.append({"kind": "exit", "reason": "channel", "price": float(b["close"]), "entry": pos["entry"], "t": b["tc"]})
                pos, exited_bar = None, b["tc"]
                break
    if not pos and len(d):
        last = d.iloc[-1]
        fresh = (pd.Timestamp(now) - last["tc"]) <= pd.Timedelta(minutes=stale_min)
        if fresh and exited_bar != last["tc"] and pd.notna(last["hiN"]) and pd.notna(last["atr20"]) and last["close"] > last["hiN"]:
            e = float(last["close"])
            sl = e - MULT * float(last["atr20"])
            pos = {"t": last["tc"].isoformat(), "entry": e, "sl": sl}
            events.append({"kind": "entry", "price": e, "sl": sl, "risk": MULT * float(last["atr20"]), "t": last["tc"]})
    return events, pos

"""Claude Daily (تجريبي، 15 دقيقة): نفس قواعد claude_daily_backtest.py، كنقراو غير آخر شمعة مسدودة.
A لندن: كسر مدى آسيا فاتجاه اليوم (خروج 11:00 ET). B نيويورك: رجوع لـ VWAP فاتجاه اليوم (خروج 16:00 ET). RR = 1.5."""
import numpy as np
import pandas as pd
from valentini_backtest import prep

RR = 1.5
STEP = pd.Timedelta(minutes=15)


def _reg(c):
    e1, e2 = c.ewm(span=200, adjust=False).mean(), c.ewm(span=800, adjust=False).mean()
    return np.where((e1 > e2) & (c > e1), 1, np.where((e1 < e2) & (c < e1), -1, 0))


def detect(df_raw, now, stale_min=45):
    df = prep(df_raw)
    if len(df) < 900:
        return []
    h, l, c, o, a, vw = (df[x].values for x in ("high", "low", "close", "open", "atr", "vwap"))
    et = df["et"]
    hr, mn = et.dt.hour.values, et.dt.minute.values
    dates = df["date"].values
    key = (et + pd.Timedelta(hours=4)).dt.date.values
    reg = _reg(df["close"])
    i = len(df) - 1
    tc = et.iloc[i] + STEP
    if (pd.Timestamp(now).tz_convert("America/New_York") - tc) > pd.Timedelta(minutes=stale_min):
        return []
    d = dates[i]
    day_idx = np.where(dates == d)[0]
    out = []
    # A
    if 3 <= hr[i] < 8:
        asia = np.where((key == d) & ((hr >= 20) | (hr < 3)))[0]
        if len(asia) >= 20:
            top, bot = h[asia].max(), l[asia].min()
            first = None
            for k in [x for x in day_idx if 3 <= hr[x] < 8]:
                s = 1 if c[k] > top else -1 if c[k] < bot else 0
                if s:
                    first = (k, s); break
            if first and first[0] == i and first[1] == reg[i]:
                side, entry, sl = first[1], c[i], (top + bot) / 2
                risk = side * (entry - sl)
                if risk >= 1.0:
                    out.append({"key": f"cd|{d}|A", "sig": "A", "side": side, "entry": entry, "sl": sl,
                                "tp": entry + side * RR * risk, "exit": 11, "t": tc})
    # B
    def okB(k):
        s = reg[k]
        if not s or k < 1 or not ((hr[k] == 9 and mn[k] >= 30) or hr[k] in (10, 11)):
            return 0
        near = (l[k - 1] <= vw[k - 1] + 0.3 * a[k]) if s == 1 else (h[k - 1] >= vw[k - 1] - 0.3 * a[k])
        good = (s == 1 and c[k] > vw[k] and c[k] > o[k] and near) or (s == -1 and c[k] < vw[k] and c[k] < o[k] and near)
        return s if good else 0
    if okB(i):
        earlier = [k for k in day_idx if k < i and okB(k)]
        if not earlier:
            side = okB(i); entry = c[i]; risk = 1.5 * a[i]
            out.append({"key": f"cd|{d}|B", "sig": "B", "side": side, "entry": entry, "sl": entry - side * risk,
                        "tp": entry + side * RR * risk, "exit": 16, "t": tc})
    return out

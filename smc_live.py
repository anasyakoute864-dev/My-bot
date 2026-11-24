"""SMC (تجريبي) 15 دقيقة: تغير الاتجاه (MSS) + FVG -> أمر معلق عند أعلى/أسفل FVG. نفس قواعد S1 فالـ backtest.
كنقراو غير الشموع المسدودة. صالح 20 شمعة، ويتلغى إيلا سدات شمعة وراء الـ FVG قبل الدخول."""
import numpy as np
import pandas as pd

PN = 3
STEP = pd.Timedelta(minutes=15)


def pivots(h, l):
    ph, pl = [], []
    for i in range(PN, len(h) - PN):
        if h[i] == h[i - PN:i + PN + 1].max(): ph.append((i, h[i]))
        if l[i] == l[i - PN:i + PN + 1].min(): pl.append((i, l[i]))
    return ph, pl


def detect(df, now, stale_min=45, hours=(3, 17)):
    """كيرجع قائمة setups ديال آخر شمعة مسدودة: {"key","side","entry","sl","tp","zone","t"}"""
    h, l, c, a = (df[x].values for x in ("high", "low", "close", "atr"))
    n = len(df)
    if n < 60:
        return []
    i = n - 1
    tc = pd.to_datetime(df["time"].iloc[i], utc=True) + STEP
    if (pd.Timestamp(now) - tc) > pd.Timedelta(minutes=stale_min):
        return []
    hr = tc.tz_convert("America/New_York").hour
    if not (hours[0] <= hr < hours[1]):
        return []
    ph, pl = pivots(h, l)
    SH = [p for p in ph if p[0] + PN <= i]
    SL = [p for p in pl if p[0] + PN <= i]
    if len(SH) < 2 or len(SL) < 2:
        return []
    out = []
    # شراء: بنية نازلة ثم إغلاق كاسر آخر قمة
    if SH[-1][1] < SH[-2][1] and c[i] > SH[-1][1] and c[i - 1] <= SH[-1][1]:
        leg_lo = l[SL[-1][0]:i + 1].min()
        zone = next(((h[k - 2], l[k]) for k in range(i, max(i - 5, 2), -1) if l[k] > h[k - 2]), None)
        if zone:
            entry, sl, tp = zone[1], leg_lo - 0.1 * a[i], SH[-2][1]
            risk = entry - sl
            if risk >= 0.5 and tp - entry >= risk:
                out.append({"key": f"smc|{tc.isoformat()}|BUY", "side": 1, "entry": entry, "sl": sl, "tp": tp, "zone": zone, "t": tc})
    if SL[-1][1] > SL[-2][1] and c[i] < SL[-1][1] and c[i - 1] >= SL[-1][1]:
        leg_hi = h[SH[-1][0]:i + 1].max()
        zone = next(((h[k], l[k - 2]) for k in range(i, max(i - 5, 2), -1) if h[k] < l[k - 2]), None)
        if zone:
            entry, sl, tp = zone[0], leg_hi + 0.1 * a[i], SL[-2][1]
            risk = sl - entry
            if risk >= 0.5 and entry - tp >= risk:
                out.append({"key": f"smc|{tc.isoformat()}|SELL", "side": -1, "entry": entry, "sl": sl, "tp": tp, "zone": zone, "t": tc})
    return out

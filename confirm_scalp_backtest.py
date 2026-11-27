"""سكالب بتأكيدات (5د، GC=F، 60 يوم). score 1-3 حسب التأكيدات، واللوت كيتضرب فـscore (سقف). تكلفة 0.5 نقطة/لوت."""
import yfinance as yf, pandas as pd, numpy as np, itertools
COST = 0.5
raw = yf.download("GC=F", interval="5m", period="59d", auto_adjust=False, progress=False)
if hasattr(raw.columns, "levels"): raw.columns = [c[0] for c in raw.columns]
d = raw.reset_index(); d.columns = [str(c).lower() for c in d.columns]
d = d.rename(columns={d.columns[0]: "time"}).dropna(subset=["close"]).reset_index(drop=True)
pc = d["close"].shift()
d["atr"] = pd.concat([d.high - d.low, (d.high - pc).abs(), (d.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean()
d["e20"] = d.close.ewm(span=20, adjust=False).mean(); d["e50"] = d.close.ewm(span=50, adjust=False).mean()
d["e200"] = d.close.ewm(span=200, adjust=False).mean()
d["hi"] = d.high.rolling(12).max().shift(1); d["lo"] = d.low.rolling(12).min().shift(1)
d["body"] = (d.close - d.open).abs() / (d.high - d.low).replace(0, np.nan)
d["vol"] = d.volume.rolling(20).mean() if "volume" in d else 0
tt = pd.to_datetime(d["time"], utc=True).dt.tz_convert("America/New_York"); d["h"] = tt.dt.hour

def run(stop_atr, rr, minscore, maxlot, hours):
    out, i, n = [], 200, len(d)
    while i < n - 40:
        b = d.iloc[i]
        if not (hours[0] <= b.h < hours[1]) or pd.isna(b.atr) or b.atr <= 0: i += 1; continue
        up = b.close > b.hi; dn = b.close < b.lo
        if not (up or dn): i += 1; continue
        s = 1 if up else -1
        sc = 0
        sc += (s == 1 and b.e20 > b.e50 > b.e200) or (s == -1 and b.e20 < b.e50 < b.e200)   # اتجاه
        sc += b.body >= 0.6                                                                    # شمعة قوية
        sc += (b.high - b.low) >= 1.2 * b.atr                                                  # توسع التذبذب
        if sc < minscore: i += 1; continue
        e = b.close; r = stop_atr * b.atr; sl = e - s * r; tp = e + s * r * rr
        res = None
        for j in range(i + 1, min(i + 40, n)):
            x = d.iloc[j]
            if (s == 1 and x.low <= sl) or (s == -1 and x.high >= sl): res = -r; break
            if (s == 1 and x.high >= tp) or (s == -1 and x.low <= tp): res = r * rr; break
        if res is None: res = (d.iloc[min(i + 39, n - 1)].close - e) * s
        lot = min(sc, maxlot)
        out.append(((res - COST) * lot, res - COST, lot)); i = j + 1 if res is not None else i + 1
    return out

for stop, rr, ms, ml, hrs in itertools.product((1.0, 1.5), (1.0, 1.5), (1, 2, 3), (1, 3), ((3, 17), (0, 24))):
    if ms == 3 and ml == 1: continue
    t = run(stop, rr, ms, ml, hrs)
    if len(t) < 20: continue
    w = [x[0] for x in t]; p1 = [x[1] for x in t]; h = len(w) // 2
    win = 100 * sum(1 for x in p1 if x > 0) / len(p1)
    eq = np.cumsum(w); dd = (np.maximum.accumulate(eq) - eq).max()
    print(f"stop={stop}ATR rr={rr} minscore={ms} maxlot={ml} hrs={hrs} n={len(t)} win%={win:.0f} lot-weighted={sum(w):+.0f} (1lot={sum(p1):+.0f}) h1={sum(w[:h]):+.0f} h2={sum(w[h:]):+.0f} maxDD={dd:.0f}")

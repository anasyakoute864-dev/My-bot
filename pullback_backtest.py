"""Claude Pullback: فاتجاه (EMA50/200) كنشري الانخفاض (RSI2 منخفض) وكنبيع الارتفاع. 1h GC=F 730 يوم، تكلفة 0.5."""
import yfinance as yf, pandas as pd, numpy as np, itertools
COST = 0.5
raw = yf.download("GC=F", interval="1h", period="730d", auto_adjust=False, progress=False)
if hasattr(raw.columns, "levels"): raw.columns = [c[0] for c in raw.columns]
d = raw.reset_index(); d.columns = [str(c).lower() for c in d.columns]
d = d.rename(columns={d.columns[0]: "time"}).dropna(subset=["close"]).reset_index(drop=True)
pc = d.close.shift()
d["atr"] = pd.concat([d.high - d.low, (d.high - pc).abs(), (d.low - pc).abs()], axis=1).max(axis=1).rolling(20).mean()
e50, e200 = d.close.ewm(span=50, adjust=False).mean(), d.close.ewm(span=200, adjust=False).mean()
d["up"] = (d.close > e200) & (e50 > e200); d["dn"] = (d.close < e200) & (e50 < e200)
def rsi(s, n):
    dl = s.diff(); g = dl.clip(lower=0).ewm(alpha=1/n, adjust=False).mean(); l = (-dl.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, np.nan))
d["r"] = rsi(d.close, 2)
d["ma"] = d.close.rolling(10).mean()

def run(lo, stop_atr, tp_r, maxbars, sides):
    out, i, n = [], 210, len(d)
    while i < n - 2:
        b = d.iloc[i]
        s = 0
        if b.up and b.r < lo and 1 in sides: s = 1
        elif b.dn and b.r > 100 - lo and -1 in sides: s = -1
        if not s or pd.isna(b.atr): i += 1; continue
        e = b.close; r = stop_atr * b.atr; sl = e - s * r; tp = e + s * r * tp_r if tp_r else None
        res, j = None, i
        for j in range(i + 1, min(i + 1 + maxbars, n)):
            x = d.iloc[j]
            if (s == 1 and x.low <= sl) or (s == -1 and x.high >= sl): res = -r; break
            if tp and ((s == 1 and x.high >= tp) or (s == -1 and x.low <= tp)): res = r * tp_r; break
            if (s == 1 and x.close > x.ma) or (s == -1 and x.close < x.ma): res = (x.close - e) * s; break
        if res is None: res = (d.iloc[j].close - e) * s
        out.append((res - COST, d.iloc[j].time)); i = j + 1
    return out

print("rows", len(d))
for lo, st, tp, mb, sd in itertools.product((5, 10, 20), (1.5, 2.5), (0, 1.0), (12, 24), ((1,), (-1,), (1, -1))):
    t = run(lo, st, tp, mb, sd); v = [x[0] for x in t]
    if len(v) < 30: continue
    h = len(v) // 2; w = 100 * sum(x > 0 for x in v) / len(v); eq = np.cumsum(v); dd = (np.maximum.accumulate(eq) - eq).max()
    q = len(v) // 4
    print(f"rsi<{lo} stop={st} tp={tp} bars={mb} sides={sd} n={len(v)} win%={w:.0f} tot={sum(v):+.0f} avg={sum(v)/len(v):+.1f} q={[round(sum(v[k*q:(k+1)*q if k<3 else None])) for k in range(4)]} dd={dd:.0f}")

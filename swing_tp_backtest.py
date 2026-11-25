"""Claude Swing مع هدف ثابت (TP = R×المخاطرة) مقابل بلا هدف. 1h GC=F، 730 يوم. تكلفة 0.5 نقطة."""
import yfinance as yf, pandas as pd, swing_live as sl
COST = 0.5
raw = yf.download("GC=F", interval="1h", period="730d", auto_adjust=False, progress=False)
if hasattr(raw.columns, "levels"):
    raw.columns = [c[0] for c in raw.columns]
raw = raw.reset_index(); raw.columns = [str(c).lower() for c in raw.columns]
raw = raw.rename(columns={raw.columns[0]: "time"})
d = sl.prep(raw)

def run(tp_r):
    tr, pos = [], None
    for i, b in d.iterrows():
        if pos:
            s = pos["side"]; ex = None
            if (s == 1 and b["low"] <= pos["sl"]) or (s == -1 and b["high"] >= pos["sl"]):
                ex = pos["sl"]
            elif tp_r and ((s == 1 and b["high"] >= pos["tp"]) or (s == -1 and b["low"] <= pos["tp"])):
                ex = pos["tp"]
            elif (s == 1 and pd.notna(b["loX"]) and b["close"] < b["loX"]) or (s == -1 and pd.notna(b["hiX"]) and b["close"] > b["hiX"]):
                ex = float(b["close"])
            if ex is not None:
                tr.append(((ex - pos["e"]) * s - COST, b["tc"])); pos = None
            continue
        if pd.isna(b["atr20"]) or pd.isna(b["hiN"]) or pd.isna(b["loN"]): continue
        s = 1 if (b["up"] and b["close"] > b["hiN"]) else -1 if (b["dn"] and b["close"] < b["loN"]) else 0
        if s:
            e = float(b["close"]); r = 2 * float(b["atr20"])
            pos = {"e": e, "side": s, "sl": e - s * r, "tp": e + s * r * (tp_r or 0)}
    return tr

for tp in (0, 0.5, 0.75, 1.0, 1.5, 2.0):
    t = run(tp); v = [x[0] for x in t]
    if not v: print(tp, "no trades"); continue
    h = len(v) // 2
    w = sum(1 for x in v if x > 0)
    print(f"TP={tp}R n={len(v)} win%={100*w/len(v):.0f} total={sum(v):+.0f} avg={sum(v)/len(v):+.1f} | half1={sum(v[:h]):+.0f} half2={sum(v[h:]):+.0f}")

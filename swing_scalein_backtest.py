"""Claude Swing + تعدد الدخول: كل مرة السعر يمشي ADD_ATR×ATR فالاتجاه نزيد وحدة (سقف MAXU). كل وحدة ستوب 2×ATR ديالها، والخروج بقناة 10 شموع. وحدة = 0.01 لوت."""
import yfinance as yf, pandas as pd, numpy as np, itertools, swing_live as sl
COST = 0.5
raw = yf.download("GC=F", interval="1h", period="730d", auto_adjust=False, progress=False)
if hasattr(raw.columns, "levels"): raw.columns = [c[0] for c in raw.columns]
raw = raw.reset_index(); raw.columns = [str(c).lower() for c in raw.columns]
raw = raw.rename(columns={raw.columns[0]: "time"}); d = sl.prep(raw)

def run(maxu, add_atr, tp_r, be):
    """tp_r: هدف للوحدة الأولى فقط (0 = بلا). be: بعد الإضافة نحرك ستوب الوحدات القديمة للدخول"""
    trades, units, side, atr0 = [], [], 0, 0
    for i, b in d.iterrows():
        if units:
            closed = []
            for u in units:
                if (side == 1 and b["low"] <= u["sl"]) or (side == -1 and b["high"] >= u["sl"]):
                    closed.append((u, u["sl"]))
                elif u["tp"] and ((side == 1 and b["high"] >= u["tp"]) or (side == -1 and b["low"] <= u["tp"])):
                    closed.append((u, u["tp"]))
            for u, px in closed:
                trades.append(((px - u["e"]) * side - COST, b["tc"])); units.remove(u)
            if units:
                chan = (side == 1 and pd.notna(b["loX"]) and b["close"] < b["loX"]) or (side == -1 and pd.notna(b["hiX"]) and b["close"] > b["hiX"])
                if chan:
                    for u in units: trades.append(((b["close"] - u["e"]) * side - COST, b["tc"]))
                    units = []
                elif len(units) < maxu and (b["close"] - units[-1]["e"]) * side >= add_atr * atr0:
                    if be:
                        for u in units: u["sl"] = max(u["sl"], u["e"]) if side == 1 else min(u["sl"], u["e"])
                    e = float(b["close"]); units.append({"e": e, "sl": e - side * 2 * atr0, "tp": None})
            if units or closed: continue
        if units: continue
        if pd.isna(b["atr20"]) or pd.isna(b["hiN"]) or pd.isna(b["loN"]): continue
        s = 1 if (b["up"] and b["close"] > b["hiN"]) else -1 if (b["dn"] and b["close"] < b["loN"]) else 0
        if s:
            side, atr0 = s, float(b["atr20"]); e = float(b["close"]); r = 2 * atr0
            units = [{"e": e, "sl": e - s * r, "tp": e + s * r * tp_r if tp_r else None}]
    return trades

print("rows", len(d))
for maxu, add, tp, be in itertools.product((1, 2, 3, 5), (0.5, 1.0), (0, 1.0), (0, 1)):
    if maxu == 1 and (add != 0.5 or be): continue
    t = sorted(run(maxu, add, tp, be), key=lambda x: x[1]); v = [x[0] for x in t]
    if len(v) < 20: continue
    q = len(v) // 4; eq = np.cumsum(v); dd = (np.maximum.accumulate(eq) - eq).max()
    print(f"maxunits={maxu} add={add}ATR tp1={tp} breakeven={be} trades={len(v)} win%={100*sum(x>0 for x in v)/len(v):.0f} total={sum(v):+.0f} q={[round(sum(v[k*q:(k+1)*q if k<3 else None])) for k in range(4)]} maxDD={dd:.0f}")

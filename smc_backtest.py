"""Backtest استراتيجيتين SMC على الذهب (5m و15m، 59 يوم، GC=F):
S1: تغير الاتجاه (MSS: إغلاق كاسر آخر قمة/قاع فعكس بنية سابقة) + FVG فالحركة -> دخول ملي يرجع السعر لـ FVG، ستوب عند بداية الحركة، هدف = آخر قمة/قاع قبل الحركة (>=1R).
S2: سحب سيولة: ذيل كيخرج من آخر قمة/قاع مؤكد ويسد داخل. V0 عادي | V1 + فوليوم >1.5× المتوسط | V2 + السحب برا Value Area ديال Volume Profile (50 شمعة). ستوب وراء الذيل، هدف = POC (>=1R).
دخول S2 فافتتاح الشمعة اللي من بعد. ستوب أولا. سبريد COST. 3-17 ET. شمعة وحدة مفتوحة فكل مرة."""
import os
import numpy as np
import pandas as pd
from valentini_backtest import prep, summarize

COST = float(os.getenv("VAL_COST", "0.5"))
PN = 3


def vprofile(df, i, n=50, rows=24):
    lo, hi = df["low"].iloc[i - n + 1:i + 1].min(), df["high"].iloc[i - n + 1:i + 1].max()
    if hi <= lo:
        return None
    edges = np.linspace(lo, hi, rows + 1); vol = np.zeros(rows)
    for k in range(i - n + 1, i + 1):
        a, b, vv = df["low"].iloc[k], df["high"].iloc[k], df["v"].iloc[k]
        for r in range(rows):
            ov = min(b, edges[r + 1]) - max(a, edges[r])
            if ov > 0:
                vol[r] += vv * ov / max(b - a, 1e-9)
    poc = int(vol.argmax()); tot, lo_i, hi_i, acc = vol.sum(), poc, poc, vol[poc]
    while acc < 0.7 * tot and (lo_i > 0 or hi_i < rows - 1):
        up = vol[hi_i + 1] if hi_i < rows - 1 else -1; dn = vol[lo_i - 1] if lo_i > 0 else -1
        if up >= dn: hi_i += 1; acc += vol[hi_i]
        else: lo_i -= 1; acc += vol[lo_i]
    return edges[lo_i], edges[hi_i + 1], (edges[poc] + edges[poc + 1]) / 2


def sim(df, j0, d, entry, sl, tp, maxbars=96):
    """j0 = أول شمعة فيها الصفقة مفتوحة. ستوب أولا. يرجع R صافي."""
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    risk = abs(entry - sl)
    for k in range(j0, min(j0 + maxbars, len(df))):
        hs = (d == 1 and l[k] <= sl) or (d == -1 and h[k] >= sl)
        ht = (k > j0 or True) and ((d == 1 and h[k] >= tp) or (d == -1 and l[k] <= tp))
        if hs: return -1.0 - COST / risk, k
        if ht: return abs(tp - entry) / risk - COST / risk, k
    k = min(j0 + maxbars - 1, len(df) - 1)
    return d * (c[k] - entry) / risk - COST / risk, k


def pivots(df):
    h, l = df["high"].values, df["low"].values
    ph, pl = {}, {}
    for i in range(PN, len(df) - PN):
        if h[i] == h[i - PN:i + PN + 1].max(): ph[i + PN] = (i, h[i])      # مؤكدة فالشمعة i+PN
        if l[i] == l[i - PN:i + PN + 1].min(): pl[i + PN] = (i, l[i])
    return ph, pl


def s1(df, hours=(3, 17)):
    h, l, c, o, a = (df[x].values for x in ("high", "low", "close", "open", "atr"))
    eth = df["et"].dt.hour.values
    ph, pl = pivots(df)
    SH, SL, tr, busy = [], [], [], -1
    for i in range(30, len(df) - 2):
        if i in ph: SH.append(ph[i])
        if i in pl: SL.append(pl[i])
        if i <= busy or not (hours[0] <= eth[i] < hours[1]) or len(SH) < 2 or len(SL) < 2:
            continue
        for d in (1, -1):
            if d == 1:
                struct = SH[-1][1] < SH[-2][1]                 # بنية نازلة قبل
                if not (struct and c[i] > SH[-1][1] and c[i - 1] <= SH[-1][1]): continue
                leg_lo = l[SL[-1][0]:i + 1].min()
                zone = None
                for k in range(i, max(i - 5, 2), -1):
                    if l[k] > h[k - 2]: zone = (h[k - 2], l[k]); break      # FVG صاعد (أسفل، أعلى)
                if not zone: continue
                entry, sl, tp = zone[1], leg_lo - 0.1 * a[i], SH[-2][1]
            else:
                struct = SL[-1][1] > SL[-2][1]
                if not (struct and c[i] < SL[-1][1] and c[i - 1] >= SL[-1][1]): continue
                leg_hi = h[SH[-1][0]:i + 1].max()
                zone = None
                for k in range(i, max(i - 5, 2), -1):
                    if h[k] < l[k - 2]: zone = (h[k], l[k - 2]); break
                if not zone: continue
                entry, sl, tp = zone[0], leg_hi + 0.1 * a[i], SL[-2][1]
            risk = abs(entry - sl)
            if risk < 0.5 or d * (tp - entry) < risk:
                continue
            j = None
            for m in range(i + 1, min(i + 21, len(df))):
                if (d == 1 and c[m] < zone[0]) or (d == -1 and c[m] > zone[1]): break     # الـ FVG تكسرات
                if (d == 1 and l[m] <= entry) or (d == -1 and h[m] >= entry):
                    j = m; break
            if j is None: continue
            r, k = sim(df, j, d, entry, sl, tp)
            tr.append({"time": df["et"].iloc[j], "R": r}); busy = k
            break
    return tr


def s2(df, variant, hours=(3, 17)):
    h, l, c, o, a, v, va = (df[x].values for x in ("high", "low", "close", "open", "atr", "v", "vavg"))
    eth = df["et"].dt.hour.values
    ph, pl = pivots(df)
    SH, SL, tr, busy = [], [], [], -1
    for i in range(60, len(df) - 2):
        if i in ph: SH.append(ph[i])
        if i in pl: SL.append(pl[i])
        if i <= busy or not (hours[0] <= eth[i] < hours[1]) or not SH or not SL:
            continue
        d = 0
        if h[i] > SH[-1][1] and c[i] < SH[-1][1] and i - SH[-1][0] > 5: d = -1; lvl = SH[-1][1]
        elif l[i] < SL[-1][1] and c[i] > SL[-1][1] and i - SL[-1][0] > 5: d = 1; lvl = SL[-1][1]
        if not d: continue
        if variant >= 1 and not (v[i] > 1.5 * va[i]): continue
        p = vprofile(df, i) if variant >= 1 else None
        if variant >= 2:
            if not p: continue
            val, vah, poc = p
            if (d == -1 and lvl < vah) or (d == 1 and lvl > val): continue       # السحب خاصو يكون برا Value Area
        if p is None: p = vprofile(df, i)
        if not p: continue
        poc = p[2]
        entry = o[i + 1]
        sl = (h[i] + 0.2 * a[i]) if d == -1 else (l[i] - 0.2 * a[i])
        risk = abs(entry - sl)
        if risk < 0.5 or d * (poc - entry) < risk: continue
        r, k = sim(df, i + 1, d, entry, sl, poc)
        tr.append({"time": df["et"].iloc[i + 1], "R": r}); busy = k
    return tr


if __name__ == "__main__":
    import gold_analyzer as ga
    L = [f"SMC على {ga.SYMBOL} | سبريد {COST} | 3-17 ET | 59 يوم", ""]
    for tf in ("5m", "15m"):
        df = prep(ga.get_data(tf, "59d")); mid = df["et"].iloc[len(df) // 2]
        L.append(f"== {tf}: {len(df)} شمعة، {df['date'].nunique()} يوم")
        for name, tr in (("S1 MSS+FVG", s1(df)), ("S2-V0 سحب عادي", s2(df, 0)), ("S2-V1 +فوليوم", s2(df, 1)), ("S2-V2 +برا Value Area", s2(df, 2))):
            L.append(f"{name}: {summarize(tr)}")
            if tr:
                L.append(f"      نصف1: {summarize([t for t in tr if t['time'] < mid])}")
                L.append(f"      نصف2: {summarize([t for t in tr if t['time'] >= mid])}")
        L.append("")
    os.makedirs("results", exist_ok=True)
    open("results/smc_backtest.txt", "w").write("\n".join(L)); print("\n".join(L))

"""S3: كسر خط الاتجاه (trendline) -> FVG -> رجوع للـ FVG (تأكيد) -> هدف آخر قاع/قمة.
خط صاعد = يمر بآخر قاعين مؤكدين (الثاني أعلى). الكسر = إغلاق تحت الخط (والشمعة اللي قبلها فوقو). FVG هابط فآخر 5 شموع.
mode=limit: دخول ملي السعر يلمس أسفل FVG. mode=confirm: لازم شمعة تلمس FVG وتسد تحتو (رفض)، والدخول افتتاح اللي من بعد.
ستوب فوق أعلى الحركة، هدف = آخر قاع مؤكد (>=1R). العكس للشراء بخط نازل. ستوب أولا، سبريد COST، 3-17 ET."""
import os
import numpy as np
from smc_backtest import prep, summarize, pivots, sim, COST


def s3(df, mode, hours=(3, 17)):
    h, l, c, o, a = (df[x].values for x in ("high", "low", "close", "open", "atr"))
    eth = df["et"].dt.hour.values
    ph, pl = pivots(df)
    SH, SL, tr, busy = [], [], [], -1
    for i in range(40, len(df) - 3):
        if i in ph: SH.append(ph[i])
        if i in pl: SL.append(pl[i])
        if i <= busy or not (hours[0] <= eth[i] < hours[1]) or len(SH) < 2 or len(SL) < 2:
            continue
        for d in (-1, 1):
            if d == -1:      # خط صاعد (قيعان صاعدة) كيتكسر لتحت
                (i1, p1), (i2, p2) = SL[-2], SL[-1]
                if not (p2 > p1 and i2 > i1 and i - i2 < 60): continue
                sl_ = (p2 - p1) / (i2 - i1)
                ln, lp = p2 + sl_ * (i - i2), p2 + sl_ * (i - 1 - i2)
                if not (c[i] < ln and c[i - 1] >= lp): continue
                zone = None
                for k in range(i, max(i - 5, 2), -1):
                    if h[k] < l[k - 2]: zone = (h[k], l[k - 2]); break          # (أسفل، أعلى)
                if not zone: continue
                leg = h[max(SH[-1][0], i - 40):i + 1].max()
                sl, tp = leg + 0.1 * a[i], SL[-1][1]
                touch = lambda m: h[m] >= zone[0]
                confirm = lambda m: touch(m) and c[m] < zone[0]
                broke = lambda m: c[m] > zone[1]
                entry_lim = zone[0]
            else:            # خط نازل (قمم نازلة) كيتكسر لفوق
                (i1, p1), (i2, p2) = SH[-2], SH[-1]
                if not (p2 < p1 and i2 > i1 and i - i2 < 60): continue
                sl_ = (p2 - p1) / (i2 - i1)
                ln, lp = p2 + sl_ * (i - i2), p2 + sl_ * (i - 1 - i2)
                if not (c[i] > ln and c[i - 1] <= lp): continue
                zone = None
                for k in range(i, max(i - 5, 2), -1):
                    if l[k] > h[k - 2]: zone = (h[k - 2], l[k]); break
                if not zone: continue
                leg = l[max(SL[-1][0], i - 40):i + 1].min()
                sl, tp = leg - 0.1 * a[i], SH[-1][1]
                touch = lambda m: l[m] <= zone[1]
                confirm = lambda m: touch(m) and c[m] > zone[1]
                broke = lambda m: c[m] < zone[0]
                entry_lim = zone[1]
            j = entry = None
            for m in range(i + 1, min(i + 21, len(df) - 1)):
                if broke(m): break
                if mode == "limit" and touch(m):
                    j, entry = m, entry_lim; break
                if mode == "confirm" and confirm(m):
                    j, entry = m + 1, o[m + 1]; break
            if j is None: continue
            risk = abs(entry - sl)
            if risk < 0.5 or d * (tp - entry) < risk: continue
            r, k = sim(df, j, d, entry, sl, tp)
            tr.append({"time": df["et"].iloc[j], "R": r, "dir": d}); busy = k
            break
    return tr


if __name__ == "__main__":
    import gold_analyzer as ga
    L = [f"S3 كسر الترندلاين + FVG + رجوع | {ga.SYMBOL} | سبريد {COST} | 59 يوم", ""]
    for tf in ("5m", "15m"):
        df = prep(ga.get_data(tf, "59d")); mid = df["et"].iloc[len(df) // 2]
        L.append(f"== {tf}: {df['date'].nunique()} يوم")
        for mode in ("limit", "confirm"):
            tr = s3(df, mode)
            L.append(f"دخول={mode}: {summarize(tr)}")
            L.append(f"   بيع فقط: {summarize([t for t in tr if t['dir'] == -1])}")
            L.append(f"   شراء فقط: {summarize([t for t in tr if t['dir'] == 1])}")
            if tr:
                L.append(f"   نصف1: {summarize([t for t in tr if t['time'] < mid])}")
                L.append(f"   نصف2: {summarize([t for t in tr if t['time'] >= mid])}")
        L.append("")
    os.makedirs("results", exist_ok=True)
    open("results/smc2_backtest.txt", "w").write("\n".join(L)); print("\n".join(L))

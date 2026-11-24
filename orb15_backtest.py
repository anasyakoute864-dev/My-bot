"""Backtest قاعدة day-trader-skill (Jakeschincariol) على الذهب: مدى أول 15د، أول شمعة 5د تسد خارج المدى = دخول،
ستوب = نص المدى، هدف 1R، خروج 15:55 ET. نجربو 3 افتتاحات (لندن 3:00، كومكس 8:20، أمريكا 9:30). الدخول: افتتاح الشمعة اللي من بعد (واقعي)
ولا إغلاق شمعة الإشارة (حرفي كيف فالريبو). ستوب أولا إيلا جوج فنفس الشمعة. سبريد COST."""
import os
import numpy as np
import pandas as pd
from valentini_backtest import prep, summarize

COST = float(os.getenv("VAL_COST", "0.5"))


def run(df, start_min, direction="both", entry_mode="next_open", rr=1.0, end_min=955):
    h, l, c, o = (df[x].values for x in ("high", "low", "close", "open"))
    hm, dates = df["hm"].values, df["date"].values
    tr = []
    for d in pd.unique(dates):
        idx = np.where(dates == d)[0]
        orb = [i for i in idx if start_min <= hm[i] < start_min + 15]
        if len(orb) < 3:
            continue
        hi, lo = h[orb].max(), l[orb].min()
        mid = (hi + lo) / 2
        if hi - lo < 1.0:
            continue
        for i in [k for k in idx if start_min + 15 <= hm[k] < end_min]:
            side = 1 if c[i] > hi else -1 if c[i] < lo else 0
            if side == 0 or (direction == "long" and side == -1):
                continue
            j = i if entry_mode == "close" else i + 1
            if j >= len(df) or dates[j] != d:
                break
            entry = c[i] if entry_mode == "close" else o[j]
            risk = side * (entry - mid)
            if risk <= 0.5:
                break
            sl, tp = mid, entry + side * rr * risk
            r = None
            for k in [m for m in idx if m >= (i + 1 if entry_mode == "close" else j)]:
                if hm[k] >= end_min:
                    r = side * (c[k] - entry) / risk; break
                hs = (side == 1 and l[k] <= sl) or (side == -1 and h[k] >= sl)
                ht = (side == 1 and h[k] >= tp) or (side == -1 and l[k] <= tp)
                if hs: r = -1.0; break
                if ht: r = rr; break
            if r is None:
                k = idx[-1]; r = side * (c[k] - entry) / risk
            tr.append({"time": df["et"].iloc[j], "R": r - COST / risk})
            break
    return tr


if __name__ == "__main__":
    import gold_analyzer as ga
    df = prep(ga.get_data("5m", "59d"))
    mid = df["et"].iloc[len(df) // 2]
    L = [f"قاعدة day-trader-skill (ORB 15د، ستوب نص المدى، هدف 1R) على {ga.SYMBOL} 5m: {df['date'].nunique()} يوم | سبريد {COST}", ""]
    for name, st in (("لندن 3:00", 180), ("كومكس 8:20", 500), ("أمريكا 9:30", 570)):
        for em in ("next_open", "close"):
            for dr in ("both", "long"):
                tr = run(df, st, dr, em)
                L.append(f"{name:11} دخول={em:9} اتجاه={dr:4}: {summarize(tr)}")
                if em == "next_open" and dr == "both":
                    L.append(f"      نصف1: {summarize([t for t in tr if t['time'] < mid])}")
                    L.append(f"      نصف2: {summarize([t for t in tr if t['time'] >= mid])}")
        L.append("")
    os.makedirs("results", exist_ok=True)
    open("results/orb15_backtest.txt", "w").write("\n".join(L)); print("\n".join(L))

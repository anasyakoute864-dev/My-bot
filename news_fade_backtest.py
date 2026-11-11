"""Backtest: عكس الأخبار على الذهب 5د. شمعة الخبر = الشمعة لي كتبدا 8:30 ET (CPI/NFP/...) ولا 14:00 ET (FOMC) بمدى > K×ATR.
fade = دخول عكس الشمعة فافتتاح الشمعة اللي من بعد، ستوب عند طرف الشمعة، هدف RR. follow = نفس الشي مع الاتجاه (للمقارنة).
ماكاينش تقويم أخبار حقيقي: هادي تقريب (الشموع الكبيرة فهاد الأوقات)."""
import os
import numpy as np
import pandas as pd
from valentini_backtest import prep, summarize

COST = float(os.getenv("VAL_COST", "0.5"))


def run(df, mode, k=2.0, rr=1.5, hold=24):
    h, l, c, o, a = (df[x].values for x in ("high", "low", "close", "open", "atr"))
    hm = df["hm"].values
    tr = []
    for i in range(20, len(df) - hold - 1):
        if hm[i] not in (510, 840):
            continue
        rng = h[i] - l[i]
        if rng < k * a[i - 1]:
            continue
        up = c[i] > o[i]
        d = (-1 if up else 1) if mode == "fade" else (1 if up else -1)
        j = i + 1
        entry = o[j]
        sl = (h[i] + 0.2 if d == -1 else l[i] - 0.2) if mode == "fade" else (l[i] - 0.2 if d == 1 else h[i] + 0.2)
        risk = abs(entry - sl)
        if risk < 0.5:
            continue
        tp = entry + d * rr * risk
        r = None
        for m in range(j, j + hold):
            hs = (d == 1 and l[m] <= sl) or (d == -1 and h[m] >= sl)
            ht = (m > j) and ((d == 1 and h[m] >= tp) or (d == -1 and l[m] <= tp))
            if hs: r = -1.0; break
            if ht: r = rr; break
        if r is None:
            r = d * (c[j + hold - 1] - entry) / risk
        tr.append({"time": df["et"].iloc[j], "R": r - COST / risk})
    return tr


if __name__ == "__main__":
    import gold_analyzer as ga
    df = prep(ga.get_data("5m", "59d"))
    lines = [f"عكس/مع الأخبار على {ga.SYMBOL} 5m ({df['date'].nunique()} يوم) | سبريد {COST} | خروج من بعد ساعتين كحد أقصى", ""]
    mid = df["et"].iloc[len(df) // 2]
    for mode in ("fade", "follow"):
        for k in (1.5, 2.0, 3.0):
            for rr in (1.0, 1.5, 2.0):
                tr = run(df, mode, k, rr)
                lines.append(f"{mode:6} مدى>{k}ATR RR{rr}: {summarize(tr)}")
                if k == 2.0 and rr == 1.5:
                    lines.append(f"      نصف1: {summarize([t for t in tr if t['time'] < mid])}")
                    lines.append(f"      نصف2: {summarize([t for t in tr if t['time'] >= mid])}")
    os.makedirs("results", exist_ok=True)
    open("results/news_fade_backtest.txt", "w").write("\n".join(lines))
    print("\n".join(lines))

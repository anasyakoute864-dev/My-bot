"""Backtest ديال "No-Wick candle retest" (فيديو @algo.jan) على الذهب.
القاعدة (من الترجمة): شمعة صاعدة بلا ذيل سفلي فترند صاعد (ولا هابطة بلا ذيل علوي فترند هابط) -> كنعلمو مستوى الافتتاح،
ملي السعر يرجع يلمسو (retest) ندخلو مع الترند. الستوب/الهدف ما بانوش فالفيديو: كنجربو ATR ستوب و RR. ترند = EMA50 طالعة/نازلة.
الدخول = limit فمستوى الافتتاح فأول لمسة (فالشمعة اللي من بعد، حتى MAXWAIT شمعة). ستوب أولا إيلا جوج فنفس الشمعة. سبريد COST."""
import os
import numpy as np
import pandas as pd
from valentini_backtest import prep, summarize

COST = float(os.getenv("VAL_COST", "0.5"))
TOL = float(os.getenv("WICK_TOL", "0.1"))
MAXWAIT = 30


def run(df, sl_atr, rr, tol=TOL, wait=MAXWAIT, hours=(3, 17)):
    h, l, c, o, a = (df[x].values for x in ("high", "low", "close", "open", "atr"))
    ema = pd.Series(c).ewm(span=50, adjust=False).mean().values
    et_h = df["et"].dt.hour.values
    tr = []
    busy = -1
    for i in range(60, len(df) - wait - 2):
        if not (hours[0] <= et_h[i] < hours[1]):
            continue
        up = ema[i] > ema[i - 10] and c[i] > ema[i]
        dn = ema[i] < ema[i - 10] and c[i] < ema[i]
        if up and c[i] > o[i] and (o[i] - l[i]) <= tol:
            d = 1
        elif dn and c[i] < o[i] and (h[i] - o[i]) <= tol:
            d = -1
        else:
            continue
        lvl = o[i]
        risk = sl_atr * a[i]
        if risk <= 0:
            continue
        j = None
        for m in range(i + 2, i + 2 + wait):      # لمسة المستوى (من الشمعة الثانية)
            if (d == 1 and l[m] <= lvl) or (d == -1 and h[m] >= lvl):
                j = m
                break
        if j is None or j <= busy:
            continue
        sl, tp = lvl - d * risk, lvl + d * rr * risk
        r = None
        for k in range(j, min(j + 96, len(df))):
            hs = (d == 1 and l[k] <= sl) or (d == -1 and h[k] >= sl)
            ht = k > j and ((d == 1 and h[k] >= tp) or (d == -1 and l[k] <= tp))
            if hs: r = -1.0; break
            if ht: r = rr; break
        if r is None:
            k = min(j + 95, len(df) - 1)
            r = d * (c[k] - lvl) / risk
        busy = k
        tr.append({"time": df["et"].iloc[j], "R": r - COST / risk})
    return tr


if __name__ == "__main__":
    import gold_analyzer as ga
    lines = [f"No-Wick retest على {ga.SYMBOL} | سبريد {COST} | tol {TOL} | ترند EMA50 | 3-17 ET", ""]
    for tf, per in (("5m", "59d"), ("15m", "59d")):
        df = prep(ga.get_data(tf, per))
        mid = df["et"].iloc[len(df) // 2]
        lines.append(f"== {tf}: {len(df)} شمعة، {df['date'].nunique()} يوم")
        for sl in (1.0, 1.5, 2.0):
            for rr in (0.5, 1.0, 2.0):
                tr = run(df, sl, rr)
                lines.append(f"ستوب {sl}ATR RR{rr}: {summarize(tr)}")
                if (sl, rr) in ((1.0, 1.0), (1.5, 1.0)):
                    lines.append(f"     نصف1: {summarize([t for t in tr if t['time'] < mid])}")
                    lines.append(f"     نصف2: {summarize([t for t in tr if t['time'] >= mid])}")
        lines.append("")
    os.makedirs("results", exist_ok=True)
    open("results/nowick_backtest.txt", "w").write("\n".join(lines)); print("\n".join(lines))

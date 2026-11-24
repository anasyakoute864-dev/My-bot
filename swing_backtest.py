"""Backtest سوينغ على الذهب (GC=F يومي، تاريخ طويل). 3 قواعد كلاسيكية (ماشي مفتشة بالـ optimization):
A) Donchian 20/10: دخول كسر أعلى/أدنى 20 يوم، خروج كسر 10 أيام عكس، ستوب 2×ATR20
B) Donchian 55/20 (Turtle طويل)
C) EMA50/EMA200 + ستوب 2×ATR20 (دخول عند التقاطع، خروج عند التقاطع العكسي ولا الستوب)
دخول/خروج فافتتاح اليوم الجاي. تكلفة 0.5 نقطة لكل جهة (+ سبريد). نقاط (1 أونصة). نقارنو مع Buy&Hold.
تقسيم الفترة لنصفين (in/out of sample) + كل سنة."""
import os
import numpy as np
import pandas as pd
import yfinance as yf

COST = float(os.getenv("SW_COST", "0.5"))


def load():
    df = yf.download("GC=F", period="max", interval="1d", auto_adjust=False, progress=False)
    df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
    df = df.dropna(subset=["open", "high", "low", "close"]).copy()
    pc = df["close"].shift(1)
    tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(20).mean()
    return df


def backtest(df, rule, shorts=True):
    o, h, l, c, a = (df[x].values for x in ("open", "high", "low", "close", "atr"))
    idx = df.index
    n = len(df)
    ema50 = df.close.ewm(span=50, adjust=False).mean().values
    ema200 = df.close.ewm(span=200, adjust=False).mean().values
    if rule in ("A", "B"):
        N, X = (20, 10) if rule == "A" else (55, 20)
        hiN = df.high.rolling(N).max().shift(1).values
        loN = df.low.rolling(N).min().shift(1).values
        hiX = df.high.rolling(X).max().shift(1).values
        loX = df.low.rolling(X).min().shift(1).values
    pos, entry, stop, tr = 0, 0.0, 0.0, []
    start = 205
    for i in range(start, n - 1):
        if pos:
            # ستوب داخل اليوم ثم إشارة خروج على الإغلاق
            hit = (pos == 1 and l[i] <= stop) or (pos == -1 and h[i] >= stop)
            px = None
            if hit:
                px = min(o[i], stop) if pos == 1 else max(o[i], stop)   # جاب (gap) كيتحسب
            else:
                if rule in ("A", "B"):
                    ex = (pos == 1 and c[i] < loX[i]) or (pos == -1 and c[i] > hiX[i])
                else:
                    ex = (pos == 1 and ema50[i] < ema200[i]) or (pos == -1 and ema50[i] > ema200[i])
                if ex:
                    px = o[i + 1]
            if px is not None:
                tr.append({"t": idx[i], "pnl": pos * (px - entry) - 2 * COST, "risk": 2 * a[ei], "dir": pos})
                pos = 0
        if not pos:
            sig = 0
            if rule in ("A", "B"):
                if c[i] > hiN[i]: sig = 1
                elif c[i] < loN[i] and shorts: sig = -1
            else:
                up = ema50[i] > ema200[i] and ema50[i - 1] <= ema200[i - 1]
                dn = ema50[i] < ema200[i] and ema50[i - 1] >= ema200[i - 1] and shorts
                sig = 1 if up else -1 if dn else 0
            if sig:
                pos, entry, ei = sig, o[i + 1], i
                stop = entry - sig * 2 * a[i]
    return pd.DataFrame(tr)


def stats(t, label, years):
    if t is None or len(t) == 0:
        return f"{label}: 0 صفقات"
    p = t["pnl"].values
    eq = np.cumsum(p)
    dd = (np.maximum.accumulate(eq) - eq).max()
    gp, gl = p[p > 0].sum(), -p[p < 0].sum()
    r = p / t["risk"].values
    return (f"{label}: {len(p)} صفقة | نجاح {np.mean(p > 0)*100:.0f}% | مجموع {p.sum():+.0f} نقطة | متوسط {p.mean():+.1f} | "
            f"أكبر نزول {dd:.0f} | PF {gp/gl if gl else float('inf'):.2f} | متوسط R {r.mean():+.2f}")


if __name__ == "__main__":
    df = load()
    yrs = (df.index[-1] - df.index[205]).days / 365.25
    bh = df.close.iloc[-1] - df.close.iloc[205]
    L = [f"سوينغ GC=F يومي: {df.index[205].date()} -> {df.index[-1].date()} ({yrs:.1f} سنة) | تكلفة {COST}/جهة", "",
         f"Buy&Hold نفس الفترة: {bh:+.0f} نقطة (من {df.close.iloc[205]:.0f} لـ {df.close.iloc[-1]:.0f}) | أكبر نزول فالفترة: "
         f"{(df.close.cummax()-df.close).iloc[205:].max():.0f}", ""]
    mid = df.index[205 + (len(df) - 205) // 2]
    L.append(f"نقطة التقسيم: {mid.date()}")
    for rule, name in (("A", "Donchian 20/10"), ("B", "Donchian 55/20"), ("C", "EMA50/200")):
        for shorts in (True, False):
            t = backtest(df, rule, shorts)
            tag = f"{name} {'long+short' if shorts else 'long فقط'}"
            L.append("")
            L.append(stats(t, tag + " | الكل", yrs))
            if len(t):
                L.append("   " + stats(t[t.t < mid], "النصف 1", yrs))
                L.append("   " + stats(t[t.t >= mid], "النصف 2", yrs))
                last5 = t[t.t >= df.index[-1] - pd.Timedelta(days=365 * 3)]
                L.append("   " + stats(last5, "آخر 3 سنين", yrs))
    os.makedirs("results", exist_ok=True)
    open("results/swing_backtest.txt", "w").write("\n".join(L)); print("\n".join(L))

"""Claude Daily: إشارتين فالنهار (قواعد كتبتها قبل الاختبار، بلا تحسين).
اتجاه اليوم (regime): EMA200 > EMA800 على 15د (= EMA50/200 فالساعة) و close فوقهم = صاعد، والعكس = نازل. بلا اتجاه واضح = ما كاينش إشارة.
A (لندن): مدى آسيا (20:00-03:00 ET). أول إغلاق 15د خارج المدى بين 03:00 و08:00 ET فاتجاه اليوم. ستوب نص المدى، هدف RR×المخاطرة، خروج 11:00 ET.
B (نيويورك): 09:30-12:00 ET. فاتجاه اليوم، السعر يرجع لـ VWAP (داخل 0.3 ATR) وشمعة تسد فاتجاه الاتجاه فوق/تحت VWAP. ستوب 1.5 ATR، هدف RR×المخاطرة، خروج 16:00 ET.
دخول فافتتاح الشمعة اللي من بعد. ستوب أولا. سبريد COST."""
import os
import numpy as np
import pandas as pd
from valentini_backtest import prep, summarize
from smc_backtest import sim, COST


def regime(df):
    c = df["close"]
    e1, e2 = c.ewm(span=200, adjust=False).mean(), c.ewm(span=800, adjust=False).mean()
    r = np.where((e1 > e2) & (c > e1), 1, np.where((e1 < e2) & (c < e1), -1, 0))
    return r


def run(df, rr, which):
    h, l, c, o, a = (df[x].values for x in ("high", "low", "close", "open", "atr"))
    vw = df["vwap"].values
    reg = regime(df)
    et = df["et"]
    hr, mn = et.dt.hour.values, et.dt.minute.values
    key = (et + pd.Timedelta(hours=4)).dt.date.values          # 20:00+ كيتحسب لنهار الجاي
    dates = df["date"].values
    trades = []
    for d in pd.unique(dates):
        idx = np.where(dates == d)[0]
        if which in ("A", "AB"):
            asia = np.where((key == d) & ((hr >= 20) | (hr < 3)))[0]
            asia = asia[(et.dt.date.values[asia] != d) | (hr[asia] < 3)] if len(asia) else asia
            if len(asia) >= 20:
                top, bot = h[asia].max(), l[asia].min()
                for i in [k for k in idx if 3 <= hr[k] < 8]:
                    side = 1 if c[i] > top else -1 if c[i] < bot else 0
                    if not side:
                        continue
                    if side != reg[i] or i + 1 >= len(df):
                        break
                    entry = o[i + 1]; sl = (top + bot) / 2; risk = side * (entry - sl)
                    if risk < 1.0:
                        break
                    tp = entry + side * rr * risk
                    # خروج 11:00 ET
                    last = max(k for k in idx if hr[k] < 11) if any(hr[idx] < 11) else idx[-1]
                    sub = df.iloc[:last + 1]
                    r, k = sim(sub, i + 1, side, entry, sl, tp, maxbars=last - i)
                    trades.append({"time": et.iloc[i + 1], "R": r, "sig": "A", "dir": side}); break
        if which in ("B", "AB"):
            for i in [k for k in idx if (hr[k] == 9 and mn[k] >= 30) or hr[k] in (10, 11)]:
                s = reg[i]
                if not s or i + 1 >= len(df): continue
                near = (l[i - 1] <= vw[i - 1] + 0.3 * a[i]) if s == 1 else (h[i - 1] >= vw[i - 1] - 0.3 * a[i])
                ok = (s == 1 and c[i] > vw[i] and c[i] > o[i] and near) or (s == -1 and c[i] < vw[i] and c[i] < o[i] and near)
                if not ok: continue
                entry = o[i + 1]; risk = 1.5 * a[i]; sl = entry - s * risk; tp = entry + s * rr * risk
                last = max(k for k in idx if hr[k] < 16)
                sub = df.iloc[:last + 1]
                r, k = sim(sub, i + 1, s, entry, sl, tp, maxbars=last - i)
                trades.append({"time": et.iloc[i + 1], "R": r, "sig": "B", "dir": s}); break
    return trades


if __name__ == "__main__":
    import gold_analyzer as ga
    df = prep(ga.get_data("15m", "59d")); mid = df["et"].iloc[len(df) // 2]
    days = df["date"].nunique()
    L = [f"Claude Daily على {ga.SYMBOL} 15m: {days} يوم | سبريد {COST}", ""]
    for rr in (1.0, 1.5, 2.0):
        tr = run(df, rr, "AB")
        L.append(f"RR={rr} | الجوج: {summarize(tr)} | {len(tr)/days:.2f} إشارة فالنهار")
        for s in ("A", "B"):
            t = [x for x in tr if x["sig"] == s]
            L.append(f"    {s}: {summarize(t)}")
        L.append(f"    نصف1: {summarize([t for t in tr if t['time'] < mid])}")
        L.append(f"    نصف2: {summarize([t for t in tr if t['time'] >= mid])}")
        L.append("")
    os.makedirs("results", exist_ok=True)
    open("results/claude_daily_backtest.txt", "w").write("\n".join(L)); print("\n".join(L))

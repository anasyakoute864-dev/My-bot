"""Backtest استراتيجية Fibonacci ديال الفيديو (Simplicity using fibs) على فريم 5 دقايق.
قراءتي للفيديو (ماشي مضمونة): موجة (قمة 1 -> قاع 0) ثم ارتداد. الدخول عند مستوى فيبو (0.618)، الستوب عند القمة (1)، الهدف RR=2.
للشراء كلشي معكوس. كل صفقة صالحة حتى الستوب/الهدف (الستوب أولا إيلا جوج فنفس الشمعة)."""
import os
import numpy as np
import pandas as pd

TF = os.getenv("FIB_TF", "5m")


def find_pivots(h, l, n):
    out = []
    for i in range(n, len(h) - n):
        if h[i] == h[i - n:i + n + 1].max():
            out.append((i, h[i], "H"))
        if l[i] == l[i - n:i + n + 1].min():
            out.append((i, l[i], "L"))
    return sorted(out)


COST = float(os.getenv("FIB_COST", "0.5"))   # سبريد + slippage بالنقاط (كيتخصم من كل صفقة)


def run(df, piv=6, level=0.618, rr=2.0, min_atr=0.0, max_bars=288, cost=None, tp_same_bar=False):
    cost = COST if cost is None else cost
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    a = df["atr"].values
    n = len(df)
    pv = find_pivots(h, l, piv)
    trades, used = [], set()
    for q in range(1, len(pv)):
        (i1, p1, t1), (i2, p2, t2) = pv[q - 1], pv[q]
        if t1 == t2 or (i1, i2) in used:
            continue
        leg = abs(p1 - p2)
        if leg <= 0 or leg < min_atr * a[i2]:
            continue
        d = -1 if t1 == "H" else 1            # موجة نازلة (H->L) = بيع | صاعدة (L->H) = شراء
        entry = p2 - d * level * leg           # مستوى الارتداد
        sl = p1
        risk = abs(sl - entry)
        tp = entry + d * rr * risk
        start = i2 + piv                       # الـ pivot كيتأكد من بعد piv شموع (بلا look-ahead)
        for j in range(start, min(n, start + max_bars)):
            if (d == -1 and l[j] < p2) or (d == 1 and h[j] > p2):
                break                           # الموجة الثانية بدات بلا ارتداد
            if (d == -1 and h[j] >= entry) or (d == 1 and l[j] <= entry):
                r, k = None, j
                for k in range(j, min(n, j + max_bars)):
                    hit_sl = (d == -1 and h[k] >= sl) or (d == 1 and l[k] <= sl)
                    # شمعة الدخول: ما نعرفوش واش القاع/القمة جات قبل ولا من بعد الدخول، فالهدف كيتحسب من الشمعة اللي من بعد (تحفظ)
                    hit_tp = (k > j or tp_same_bar) and ((d == -1 and l[k] <= tp) or (d == 1 and h[k] >= tp))
                    if hit_sl:
                        r = -1.0
                        break
                    if hit_tp:
                        r = rr
                        break
                if r is None:
                    r = d * (c[min(n, j + max_bars) - 1] - entry) / risk
                r = r - cost / risk            # R صافي من السبريد
                used.add((i1, i2))
                trades.append({"time": df["time"].iloc[j], "dir": d, "entry": entry, "sl": sl, "tp": tp, "R": r})
                break
    return trades


def summarize(tr):
    if not tr:
        return "0 صفقات"
    r = np.array([t["R"] for t in tr])
    gp, gl = r[r > 0].sum(), -r[r < 0].sum()
    return f"{len(r)} صفقة | نجاح {np.mean(r > 0) * 100:.0f}% | مجموع {r.sum():+.1f}R | متوسط {r.mean():+.2f}R | PF {gp / gl if gl else float('inf'):.2f}"


if __name__ == "__main__":
    import gold_analyzer as ga
    df = ga.get_data(TF, "59d")
    days = (df["time"].iloc[-1] - df["time"].iloc[0]).days or 1
    lines = [f"Fib {TF} على {ga.SYMBOL}: {len(df)} شمعة ({days} يوم) | القاعدة: دخول عند المستوى، ستوب عند القمة/القاع (1)، هدف RR 2 | سبريد {COST} نقطة", ""]
    half = len(df) // 2
    lines.append("فرضيتين لترتيب الحركة داخل شمعة الدخول (OHLC ما كيعطيش الترتيب): متفائلة = الهدف يتحسب فنفس الشمعة | متحفظة = من الشمعة اللي من بعد")
    lines.append("")
    for piv in (3, 6, 10):
        for level in (0.618, 0.786, 0.886):
            lines.append(f"pivot={piv:>2} level={level}:")
            for name, same in (("متحفظة", False), ("متفائلة", True)):
                tr = run(df, piv, level, 2.0, 0.0, tp_same_bar=same)
                a1 = summarize([t for t in tr if t["time"] < df["time"].iloc[half]])
                a2 = summarize([t for t in tr if t["time"] >= df["time"].iloc[half]])
                lines.append(f"   {name}: {summarize(tr)}")
                lines.append(f"        نصف1: {a1}\n        نصف2: {a2}")
    med = np.median([t["entry"] - t["sl"] for t in run(df, 6, 0.618, 2.0, 0.0)])
    lines.append(f"\nالستوب العادي (pivot=6, 0.618): {abs(med):.1f} نقطة | متوسط مدى الشمعة 5د: {(df['high'] - df['low']).mean():.1f} نقطة | السبريد المفترض {COST}")
    base = run(df, 6, 0.618, 2.0, 0.0)
    lines += ["", "آخر 12 صفقة (pivot=6, 0.618, بلا حد للموجة):"]
    for t in base[-12:]:
        et = pd.Timestamp(t["time"]).tz_convert("America/New_York") if pd.Timestamp(t["time"]).tzinfo else pd.Timestamp(t["time"])
        lines.append(f"{et:%m-%d %H:%M} {'BUY' if t['dir'] == 1 else 'SELL'} entry={t['entry']:.1f} sl={t['sl']:.1f} R={t['R']:+.2f}")
    os.makedirs("results", exist_ok=True)
    open("results/fib5_backtest.txt", "w").write("\n".join(lines))
    print("\n".join(lines))

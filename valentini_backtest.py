"""Backtest نسخة مبسطة من استراتيجية Fabio Valentini على الذهب 5 دقايق (بلا order flow حقيقي، فقط OHLC + فوليوم Yahoo).
3 سيناريوهات: ORB30 (كسر أول 30د من 9:30 ET + فوليوم + VWAP) | VA (ارتداد من VAH/VAL ديال 50 شمعة) | AAA (امتصاص ثم تجميع ثم كسر).
ستوب ATR، هدف 2R، وقف من بعد 3 خسايرات فاليوم، خروج 16:00 ET. الدخول فافتتاح الشمعة اللي من بعد الإشارة. ستوب أولا إيلا جوج فنفس الشمعة."""
import os
import numpy as np
import pandas as pd

COST = float(os.getenv("VAL_COST", "0.5"))
RR = 2.0
MAXL = 3


def prep(df):
    df = df.copy()
    t = pd.to_datetime(df["time"], utc=True).dt.tz_convert("America/New_York")
    df["et"] = t
    df["date"] = t.dt.date
    df["hm"] = t.dt.hour * 60 + t.dt.minute
    tp = (df["high"] + df["low"] + df["close"]) / 3
    v = df["volume"].replace(0, np.nan).fillna(1.0)
    df["vwap"] = (tp * v).groupby(df["date"]).cumsum() / v.groupby(df["date"]).cumsum()
    df["vavg"] = v.rolling(20).mean().shift(1)
    df["v"] = v
    return df.reset_index(drop=True)


def profile(df, i, n=50, rows=24):
    lo, hi = df["low"].iloc[i - n + 1:i + 1].min(), df["high"].iloc[i - n + 1:i + 1].max()
    if hi <= lo:
        return None
    edges = np.linspace(lo, hi, rows + 1)
    vol = np.zeros(rows)
    for k in range(i - n + 1, i + 1):
        a, b, vv = df["low"].iloc[k], df["high"].iloc[k], df["v"].iloc[k]
        for r in range(rows):
            ov = min(b, edges[r + 1]) - max(a, edges[r])
            if ov > 0:
                vol[r] += vv * ov / max(b - a, 1e-9)
    poc = int(vol.argmax())
    tot, lo_i, hi_i, acc = vol.sum(), poc, poc, vol[poc]
    while acc < 0.7 * tot and (lo_i > 0 or hi_i < rows - 1):
        up = vol[hi_i + 1] if hi_i < rows - 1 else -1
        dn = vol[lo_i - 1] if lo_i > 0 else -1
        if up >= dn:
            hi_i += 1; acc += vol[hi_i]
        else:
            lo_i -= 1; acc += vol[lo_i]
    return edges[lo_i], edges[hi_i + 1]          # VAL, VAH


def signals(df, model):
    """يرجع (index الشمعة اللي سدات الإشارة، اتجاه). مرة وحدة فاليوم للـ ORB."""
    out = []
    h, l, c, o = df["high"].values, df["low"].values, df["close"].values, df["open"].values
    a, vw, v, va = df["atr"].values, df["vwap"].values, df["v"].values, df["vavg"].values
    hm = df["hm"].values
    dates = df["date"].values
    seen = set()
    for i in range(60, len(df) - 1):
        if not (570 <= hm[i] < 900):               # 9:30 -> 15:00 ET
            continue
        d = dates[i]
        if model == "ORB30":
            if hm[i] < 600 or d in seen:
                continue
            day = np.where((dates == d) & (hm >= 570) & (hm < 600))[0]
            if len(day) < 5:
                continue
            rh, rl = h[day].max(), l[day].min()
            if c[i] > rh and c[i] > vw[i] and v[i] > va[i]:
                out.append((i, 1)); seen.add(d)
            elif c[i] < rl and c[i] < vw[i] and v[i] > va[i]:
                out.append((i, -1)); seen.add(d)
        elif model == "VA":
            p = profile(df, i)
            if not p:
                continue
            val, vah = p
            if l[i] <= val and c[i] > val and c[i] > o[i]:
                out.append((i, 1))
            elif h[i] >= vah and c[i] < vah and c[i] < o[i]:
                out.append((i, -1))
        elif model == "AAA":
            k = i - 4                               # شمعة الامتصاص: فوليوم كبير + مدى صغير
            if not (v[k] > 1.5 * va[k] and (h[k] - l[k]) < 0.6 * a[k]):
                continue
            box = slice(k, i)                       # 4 شموع تجميع ضيقة
            rh, rl = h[box].max(), l[box].min()
            if rh - rl > 1.2 * a[i]:
                continue
            if c[i] > rh and v[i] > va[i] and c[i] > vw[i]:
                out.append((i, 1))
            elif c[i] < rl and v[i] > va[i] and c[i] < vw[i]:
                out.append((i, -1))
    return out


def simulate(df, sigs, stop_atr, cost=COST, tp_same=False):
    h, l, c, o = df["high"].values, df["low"].values, df["close"].values, df["open"].values
    a = df["atr"].values
    hm, dates = df["hm"].values, df["date"].values
    trades, busy_until, losses = [], -1, {}
    for i, d in sigs:
        j = i + 1
        if j <= busy_until or dates[j] != dates[i] or hm[j] >= 960:
            continue
        if losses.get(dates[i], 0) >= MAXL:
            continue
        entry = o[j]
        risk = stop_atr * a[i]
        sl, tp = entry - d * risk, entry + d * RR * risk
        r, k = None, j
        for k in range(j, len(df)):
            if dates[k] != dates[i] or hm[k] >= 960:
                k -= 1
                r = d * (c[k] - entry) / risk
                break
            hs = (d == 1 and l[k] <= sl) or (d == -1 and h[k] >= sl)
            ht = (k > j or tp_same) and ((d == 1 and h[k] >= tp) or (d == -1 and l[k] <= tp))
            if hs:
                r = -1.0; break
            if ht:
                r = RR; break
        if r is None:
            r = d * (c[-1] - entry) / risk
        r -= cost / risk
        busy_until = k
        if r < 0:
            losses[dates[i]] = losses.get(dates[i], 0) + 1
        trades.append({"time": df["et"].iloc[j], "dir": d, "R": r})
    return trades


def summarize(tr):
    if not tr:
        return "0 صفقات"
    r = np.array([t["R"] for t in tr])
    gp, gl = r[r > 0].sum(), -r[r < 0].sum()
    return f"{len(r)} صفقة | نجاح {np.mean(r > 0) * 100:.0f}% | مجموع {r.sum():+.1f}R | متوسط {r.mean():+.2f}R | PF {gp / gl if gl else float('inf'):.2f}"


if __name__ == "__main__":
    import gold_analyzer as ga
    raw = ga.get_data("5m", "59d")
    df = prep(raw)
    days = df["date"].nunique()
    lines = [f"Valentini (نسخة مبسطة بلا order flow) على {ga.SYMBOL} 5m: {len(df)} شمعة، {days} يوم تداول | هدف RR {RR} | سبريد {COST} نقطة | وقف من بعد {MAXL} خسايرات | 9:30-15:00 ET", ""]
    mid = df["et"].iloc[len(df) // 2]
    for model in ("ORB30", "VA", "AAA"):
        sg = signals(df, model)
        for st in (1.0, 1.5, 2.0):
            for name, same in (("متحفظة", False), ("متفائلة", True)):
                tr = simulate(df, sg, st, tp_same=same)
                lines.append(f"{model} ستوب {st}ATR {name}: {summarize(tr)}")
                if name == "متحفظة":
                    lines.append(f"      نصف1: {summarize([t for t in tr if t['time'] < mid])}")
                    lines.append(f"      نصف2: {summarize([t for t in tr if t['time'] >= mid])}")
        lines.append("")
    os.makedirs("results", exist_ok=True)
    open("results/valentini_backtest.txt", "w").write("\n".join(lines))
    print("\n".join(lines))

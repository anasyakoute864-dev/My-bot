"""الشراء والبيع كاستراتيجيتين منفصلتين، بفلتر اتجاه (EMA200 + EMA50/200). Donchian N/X، ستوب 2×ATR20.
شراء: كسر أعلى N فاتجاه صاعد (close>EMA200 و EMA50>EMA200). بيع: كسر أدنى N فاتجاه نازل (close<EMA200 و EMA50<EMA200).
نجربو يومي (25 سنة) و4h و1h (2.4 سنة). تقسيم النصفين. قواعد كلاسيكية، بلا تحسين. تكلفة 0.5/جهة."""
import os
import numpy as np
import pandas as pd
import yfinance as yf
import swing_backtest as sb
import swing_tf_backtest as st

COST = 0.5


def bt(df, N, X, longs, shorts, regime=True):
    o, h, l, c, a = (df[x].values for x in ("open", "high", "low", "close", "atr"))
    e50 = df.close.ewm(span=50, adjust=False).mean().values
    e200 = df.close.ewm(span=200, adjust=False).mean().values
    hiN = df.high.rolling(N).max().shift(1).values; loN = df.low.rolling(N).min().shift(1).values
    hiX = df.high.rolling(X).max().shift(1).values; loX = df.low.rolling(X).min().shift(1).values
    idx, n = df.index, len(df)
    pos, tr, entry, stop, ei = 0, [], 0.0, 0.0, 0
    for i in range(205, n - 1):
        if pos:
            hit = (pos == 1 and l[i] <= stop) or (pos == -1 and h[i] >= stop)
            px = None
            if hit:
                px = min(o[i], stop) if pos == 1 else max(o[i], stop)
            elif (pos == 1 and c[i] < loX[i]) or (pos == -1 and c[i] > hiX[i]):
                px = o[i + 1]
            if px is not None:
                tr.append({"t": idx[i], "pnl": pos * (px - entry) - 2 * COST, "risk": 2 * a[ei], "dir": pos}); pos = 0
        if not pos:
            up = (c[i] > e200[i] and e50[i] > e200[i]) if regime else True
            dn = (c[i] < e200[i] and e50[i] < e200[i]) if regime else True
            sig = 0
            if longs and up and c[i] > hiN[i]: sig = 1
            elif shorts and dn and c[i] < loN[i]: sig = -1
            if sig:
                pos, entry, ei = sig, o[i + 1], i
                stop = entry - sig * 2 * a[i]
    return pd.DataFrame(tr)


def block(df, label, yrs, mid):
    L = []
    for N, X in ((20, 10), (55, 20)):
        for name, lg, sh, rg in (("شراء فقط (فلتر صاعد)", True, False, True), ("بيع فقط (فلتر نازل)", False, True, True),
                                 ("بيع فقط (بلا فلتر)", False, True, False), ("شراء+بيع (فلتر)", True, True, True)):
            t = bt(df, N, X, lg, sh, rg)
            L.append("")
            L.append(f"[{label}] Donchian {N}/{X} {name}: " + sb.stats(t, "", yrs) + (f" | {len(t)/yrs:.1f} صفقة/سنة" if len(t) else ""))
            if len(t):
                L.append("      نصف1: " + sb.stats(t[t.t < mid], "", yrs)); L.append("      نصف2: " + sb.stats(t[t.t >= mid], "", yrs))
    return L


if __name__ == "__main__":
    out = []
    d = sb.load(); yrs = (d.index[-1] - d.index[205]).days / 365.25; mid = d.index[205 + (len(d) - 205) // 2]
    out.append(f"== يومي {d.index[205].date()} -> {d.index[-1].date()} ({yrs:.1f} سنة)"); out += block(d, "1d", yrs, mid)
    for tf in ("4h", "1h"):
        d = st.load_tf(tf); yrs = (d.index[-1] - d.index[205]).days / 365.25; mid = d.index[205 + (len(d) - 205) // 2]
        out.append(""); out.append(f"== {tf} {d.index[205].date()} -> {d.index[-1].date()} ({yrs:.1f} سنة)"); out += block(d, tf, yrs, mid)
    os.makedirs("results", exist_ok=True)
    open("results/regime_backtest.txt", "w").write("\n".join(out)); print("\n".join(out))

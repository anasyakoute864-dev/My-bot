"""Swing على فريمات أصغر (4h و1h) بنفس قواعد Donchian: GC=F، آخر ~730 يوم (حد Yahoo للساعة). تكلفة 0.5/جهة. بدون تحسين."""
import os
import numpy as np
import pandas as pd
import yfinance as yf
import swing_backtest as sb


def load_tf(tf):
    df = yf.download("GC=F", period="730d", interval="1h", auto_adjust=False, progress=False)
    df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
    df = df.dropna(subset=["open", "high", "low", "close"])
    if tf == "4h":
        df = df.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    pc = df["close"].shift(1)
    tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(20).mean()
    return df


if __name__ == "__main__":
    L = []
    for tf in ("4h", "1h"):
        df = load_tf(tf)
        yrs = (df.index[-1] - df.index[205]).days / 365.25
        bh = df.close.iloc[-1] - df.close.iloc[205]
        mid = df.index[205 + (len(df) - 205) // 2]
        L += [f"=== {tf}: {df.index[205].date()} -> {df.index[-1].date()} ({yrs:.1f} سنة) | Buy&Hold {bh:+.0f} نقطة | تقسيم {mid.date()}"]
        for rule, name in (("A", "Donchian 20/10"), ("B", "Donchian 55/20")):
            for shorts in (True, False):
                t = sb.backtest(df, rule, shorts)
                tag = f"{name} {'long+short' if shorts else 'long فقط'}"
                L.append("")
                L.append(sb.stats(t, tag, yrs) + (f" | {len(t)/yrs:.0f} صفقة/سنة" if len(t) else ""))
                if len(t):
                    L.append("   " + sb.stats(t[t.t < mid], "النصف 1", yrs))
                    L.append("   " + sb.stats(t[t.t >= mid], "النصف 2", yrs))
        L.append("")
    os.makedirs("results", exist_ok=True)
    open("results/swing_tf_backtest.txt", "w").write("\n".join(L)); print("\n".join(L))

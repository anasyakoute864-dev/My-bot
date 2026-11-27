import yfinance as yf, pandas as pd
print("now", pd.Timestamp.now(tz="UTC"))
for sym in ("XAUUSD=X", "MGC=F", "GC=F", "GCZ26.CMX", "GCG27.CMX", "XAU=X", "GLD"):
    for iv, per in (("15m", "2d"),):
        try:
            d = yf.download(sym, interval=iv, period=per, auto_adjust=False, progress=False)
            if hasattr(d.columns, "levels"): d.columns = [c[0] for c in d.columns]
            print("SYM", sym, iv, "rows", len(d), "last", d.index[-1] if len(d) else None, "close", float(d["Close"].iloc[-1]) if len(d) else None)
        except Exception as e:
            print("SYM", sym, "err", type(e).__name__, str(e)[:80])

import yfinance as yf, pandas as pd, requests
for iv, per in (("15m","2d"),("1m","1d"),("1h","5d")):
    d = yf.download("GC=F", interval=iv, period=per, auto_adjust=False, progress=False)
    if hasattr(d.columns, "levels"): d.columns = [c[0] for c in d.columns]
    print(iv, "now", pd.Timestamp.now(tz="UTC"))
    print(d[["Open","High","Low","Close"]].tail(4))
try:
    print("spot", requests.get("https://forex-data-feed.swissquote.com/public-quotes/bboquotes/instrument/XAU/USD", timeout=10).json()[0]["spreadProfilePrices"][0])
except Exception as e: print("spot err", e)

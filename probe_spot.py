import datetime as dt, requests, yfinance as yf
out = [f"UTC now: {dt.datetime.utcnow():%Y-%m-%d %H:%M}"]
def yf_last(sym):
    d = yf.download(sym, interval="1m", period="1d", progress=False, auto_adjust=False)
    if hasattr(d.columns, "levels"): d.columns = d.columns.get_level_values(0)
    return float(d["Close"].iloc[-1]), str(d.index[-1])
for sym in ["GC=F", "MGC=F", "GLD"]:
    try: out.append(f"yahoo {sym}: {yf_last(sym)}")
    except Exception as e: out.append(f"yahoo {sym}: ERR {e}")
for name, url, path in [
    ("gold-api.com", "https://api.gold-api.com/price/XAU", None),
    ("metals.live", "https://api.metals.live/v1/spot/gold", None),
    ("swissquote", "https://forex-data-feed.swissquote.com/public-quotes/bboquotes/instrument/XAU/USD", None),
]:
    try:
        r = requests.get(url, timeout=15); out.append(f"{name}: {r.status_code} {r.text[:300]}")
    except Exception as e: out.append(f"{name}: ERR {type(e).__name__}")
open("results/probe_spot.txt", "w").write("\n".join(out) + "\n"); print("\n".join(out))

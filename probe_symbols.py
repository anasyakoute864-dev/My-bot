import yfinance as yf, requests, io, pandas as pd
out = []
for sym in ["XAUUSD=X", "XAU=X", "XAUUSD", "GC=F", "MGC=F", "GLD", "IAU"]:
    try:
        d = yf.download(sym, interval="1h", period="730d", progress=False, auto_adjust=False)
        out.append(f"yahoo {sym}: rows={len(d)}" + (f" last={float(d['Close'].iloc[-1]):.2f}" if len(d) else ""))
    except Exception as e:
        out.append(f"yahoo {sym}: ERR {type(e).__name__}")
for url in ["https://stooq.com/q/d/l/?s=xauusd&i=60", "https://stooq.com/q/d/l/?s=xauusd&i=d"]:
    try:
        r = requests.get(url, timeout=20)
        out.append(f"stooq {url[-18:]}: status={r.status_code} head={r.text[:80]!r} lines={len(r.text.splitlines())}")
    except Exception as e:
        out.append(f"stooq ERR {type(e).__name__}")
open("results/probe.txt", "w").write("\n".join(out) + "\n"); print("\n".join(out))

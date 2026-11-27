import gold_analyzer as ga, pandas as pd
for iv in ("15m", "1h", "1d"):
    d = ga.get_data(iv, "59d")
    print("T", iv, "rows", len(d), "fallback", ga.USING_FALLBACK, "last", d["time"].iloc[-1], "close", round(float(d["close"].iloc[-1]), 2), "atr", round(float(d["atr"].iloc[-1]), 2))
print("T ticker", ga.okx_last_price())
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    res = ga.analyze_recent()
print("T analyze", res[-1].get("decision"), res[-1].get("price"), "n", len(res))

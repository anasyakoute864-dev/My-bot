"""يقيّم كل إشارة مرسلة (signals_eval.csv) على بيانات 1د: ستوب أولا إيلا جوج فنفس الشمعة. الخروج 17:00 ET (22:00 UTC) ولا exit_utc."""
import pandas as pd, numpy as np, yfinance as yf
sg = pd.read_csv("signals_eval.csv", parse_dates=["time_utc"])
df = yf.download("GC=F", interval="1m", period="8d", auto_adjust=False, progress=False)
df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
df.index = pd.to_datetime(df.index, utc=True)
out = []
for _, s in sg.iterrows():
    t0 = s.time_utc.tz_localize("UTC")
    end = t0.normalize() + pd.Timedelta(hours=22)
    if s.exit_utc != "0":
        hh, mm = map(int, s.exit_utc.split(":")); end = t0.normalize() + pd.Timedelta(hours=hh, minutes=mm)
    w = df[(df.index > t0) & (df.index <= end)]
    d = 1 if s.side == "BUY" else -1
    res, tpx = "open/نهاية الجلسة", None
    for t, b in w.iterrows():
        hs = (d == 1 and b.low <= s.stop) or (d == -1 and b.high >= s.stop)
        ht = (d == 1 and b.high >= s.tp1) or (d == -1 and b.low <= s.tp1)
        if hs: res, tpx = "خسارة (ستوب)", t; break
        if ht: res, tpx = "ربح (TP)", t; break
    last = w.close.iloc[-1] if len(w) else np.nan
    pts = (s.tp1 - s.entry) * d if res.startswith("ربح") else (s.stop - s.entry) * d if res.startswith("خسارة") else (last - s.entry) * d
    mfe = ((w.high.max() - s.entry) if d == 1 else (s.entry - w.low.min())) if len(w) else np.nan
    mae = ((s.entry - w.low.min()) if d == 1 else (w.high.max() - s.entry)) if len(w) else np.nan
    out.append(f"{s.time_utc:%m-%d %H:%M}Z {s.kind:13} {s.side:4} @{s.entry:.1f} sl={s.stop:.1f} tp={s.tp1:.1f} -> {res:18} {pts:+.1f}pt | أقصى ربح عائم {mfe:+.1f} | أقصى عكس {mae:+.1f}")
lines = ["تقييم الإشارات (بيانات GC=F 1د، ستوب أولا):", ""] + out
for k in ("ours/scalp", "crabel_london", "crabel_ny"):
    sub = [l for l in out if f" {k} " in l or l.split()[1] == k]
    w_ = sum("ربح" in l for l in sub); l_ = sum("خسارة" in l for l in sub)
    lines.append(f"{k}: {len(sub)} إشارة | ربح {w_} | خسارة {l_} | مفتوحة {len(sub)-w_-l_}")
import os; os.makedirs("results", exist_ok=True)
open("results/eval_signals.txt", "w").write("\n".join(lines)); print("\n".join(lines))

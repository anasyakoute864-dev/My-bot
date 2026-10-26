#!/usr/bin/env python3
"""
Walk-forward: كنقسمو المدة نصفين (الأول/الثاني) وكنجربو عدة إعدادات.
الإعداد المقبول = كيربح فالنصفين معا (PF > 1.15 ولو 15 صفقة فكل نص)، ماشي غير فواحد.

تشغيل:  python experiments.py [step]
كنجمعو قرارات التحليل مرة وحدة (بأدنى حد ديال النقاط)، وكنفلتروها من بعد لكل إعداد،
باش ما نعاودوش التحليل 12 مرة.
"""
import sys

import pandas as pd

import backtest as bt
import gold_analyzer as ga

MIN_SCORES = [4, 5, 6, 7]
SELL_EXTRA = [(0, "BUY+SELL"), (1, "SELL +1"), (99, "BUY فقط")]


def collect(df, dd, step):
    ga.MIN_SCORE = 3  # أدنى حد: كنجمعو كلشي ونفلتروه من بعد
    dd = dd.copy()
    dd["day"] = dd["time"].map(bt.naive_utc).dt.normalize()
    recs = []
    for i in range(bt.WINDOW, len(df) - 1, step):
        t = bt.naive_utc(df["time"].iloc[i])
        dsub = dd[dd["day"] < t.normalize()].reset_index(drop=True)
        if len(dsub) < bt.MIN_DAILY:
            continue
        sub = df.iloc[i - bt.WINDOW + 1: i + 1].reset_index(drop=True)
        res = ga.evaluate(sub, dsub, macro=0.0, verbose=False, now=t.tz_localize("UTC"))
        recs.append((i, t, res))
    return recs


def trades_for(df, recs, min_score, sell_extra):
    out, last, busy = [], None, -1
    for i, t, res in recs:
        sig = None
        if res["decision"] == "trade":
            need = min_score + (sell_extra if res["side"] == -1 else 0)
            if abs(res["score"]) >= need:
                sig = "BUY" if res["side"] == 1 else "SELL"
        is_new = sig is not None and sig != last
        last = sig
        if not is_new or i <= busy:
            continue
        fut = df.iloc[i + 1: i + 1 + bt.MAX_HOLD]
        r, held = bt.simulate(res["side"], res["entry"], res["sl"], res["tp1"], res["tp2"],
                              fut["high"].values, fut["low"].values, fut["close"].values)
        r -= bt.SPREAD / res["risk"]
        out.append((t, round(r, 3)))
        busy = i + held
    return out


def stats(rs):
    if not rs:
        return {"n": 0, "win": 0.0, "pf": 0.0, "tot": 0.0, "dd": 0.0}
    r = pd.Series(rs)
    w, l = r[r > 0].sum(), abs(r[r < 0].sum())
    eq = r.cumsum()
    return {"n": len(r), "win": (r > 0).mean() * 100, "pf": (w / l if l else 99.0),
            "tot": r.sum(), "dd": (eq - eq.cummax()).min()}


def fmt(s):
    return f"n{s['n']} {s['win']:.0f}% PF{s['pf']:.2f} {s['tot']:+.1f}R"


def run_all(df, recs):
    t0, t1 = bt.naive_utc(df["time"].iloc[bt.WINDOW]), bt.naive_utc(df["time"].iloc[-1])
    mid = t0 + (t1 - t0) / 2
    rows = []
    for ms in MIN_SCORES:
        for extra, label in SELL_EXTRA:
            tr = trades_for(df, recs, ms, extra)
            a = stats([r for t, r in tr])
            h1 = stats([r for t, r in tr if t < mid])
            h2 = stats([r for t, r in tr if t >= mid])
            ok = all(h["n"] >= 15 and h["pf"] > 1.15 for h in (h1, h2))
            rows.append({"ms": ms, "label": label, "all": a, "h1": h1, "h2": h2, "ok": ok})
    return rows, mid


def report(rows, mid, start, end):
    lines = ["🔬 Walk-forward (الذهب 1h)", f"من {start} إلى {end} | الفاصل: {mid.date()}", ""]
    for r in rows:
        mark = "✅" if r["ok"] else "▫️"
        lines.append(f"{mark} MIN_SCORE={r['ms']} {r['label']}")
        lines.append(f"   كامل: {fmt(r['all'])} | تراجع {r['all']['dd']:.1f}R")
        lines.append(f"   نص1: {fmt(r['h1'])}")
        lines.append(f"   نص2: {fmt(r['h2'])}")
    good = [r for r in rows if r["ok"]]
    lines.append("")
    if good:
        best = max(good, key=lambda r: min(r["h1"]["pf"], r["h2"]["pf"]))
        lines.append(f"الأحسن (ثابت فالنصفين): MIN_SCORE={best['ms']} {best['label']}")
    else:
        lines.append("حتى إعداد ما ربح فالنصفين بشكل ثابت (PF>1.15 و15 صفقة+). ما كاينش تحسين مؤكد.")
    lines.append("(بلا ماكرو، تكلفة 0.3$ فالصفقة. ✅ = ثابت فالنصفين)")
    return "\n".join(lines)


def main():
    step = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    df = ga.get_data("1h", "730d")
    dd = ga.get_data("1d", "5y")
    print(f"1h: {len(df)} | 1d: {len(dd)} | step={step}")
    recs = collect(df, dd, step)
    rows, mid = run_all(df, recs)
    start = bt.naive_utc(df["time"].iloc[bt.WINDOW]).date()
    end = bt.naive_utc(df["time"].iloc[-1]).date()
    text = report(rows, mid, start, end)
    print(text)
    bt.send(text)


if __name__ == "__main__":
    main()

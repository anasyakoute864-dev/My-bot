#!/usr/bin/env python3
"""
Backtest ديال البوت: كيعاود تشغيل نفس منطق gold_analyzer.evaluate على شموع قديمة،
شمعة بشمعة، وكل مرة كيشوف غير اللي كان معروف وقتها (بلا نظر للمستقبل).

تشغيل:  python backtest.py [step]      (step=1 كل شمعة، 3 أسرع)
ملاحظات:
  - الماكرو (تضخم/بطالة/فيدرالي) ما كيدخلش فالـ backtest (ما عندناش تاريخ ديالو)، فالنقاط أقل شوية من الحقيقي.
  - إدارة الصفقة: عند TP1 كنسكرو النص وكنحركو الستوب لنقطة الدخول، والباقي لـ TP2.
  - إيلا لمسات الشمعة الستوب والهدف مع بعض، كنحسبو الستوب (تحفظ).
"""
import os
import sys

import pandas as pd
import requests

import gold_analyzer as ga

WINDOW = 800      # عدد شموع الساعة اللي كتعطى للتحليل فكل خطوة
MAX_HOLD = 72     # أقصى مدة للصفقة (بالشموع)، من بعد كنسكروها بسعر الإغلاق
SPREAD = 0.30     # تكلفة (سبريد + انزلاق) بالدولار فكل صفقة
BE_AFTER_TP1 = os.getenv("BE_AFTER_TP1", "0") == "1"   # الستوب للدخول من بعد الهدف الأول
MIN_DAILY = 30    # أقل عدد شموع يومية باش نحللو


def naive_utc(ts):
    ts = pd.Timestamp(ts)
    ts = ts.tz_convert("UTC").tz_localize(None) if ts.tzinfo else ts
    return ts


def simulate(side, entry, sl, tp1, tp2, h, l, c):
    """كيرجع (النتيجة بـ R، عدد الشموع اللي بقات فيها الصفقة)"""
    risk = abs(entry - sl)
    stop, stage, real, left = sl, 0, 0.0, 1.0
    for k in range(len(h)):
        if (side == 1 and l[k] <= stop) or (side == -1 and h[k] >= stop):
            return real + left * side * (stop - entry) / risk, k + 1
        if stage == 0 and ((side == 1 and h[k] >= tp1) or (side == -1 and l[k] <= tp1)):
            real += 0.5 * side * (tp1 - entry) / risk
            left, stop, stage = 0.5, entry, 1
            continue
        if stage == 1 and ((side == 1 and h[k] >= tp2) or (side == -1 and l[k] <= tp2)):
            return real + 0.5 * side * (tp2 - entry) / risk, k + 1
    return real + left * side * (c[-1] - entry) / risk, len(c)


def simulate_scalp(side, entry, sl, targets, h, l, c, be=None):
    """5 أهداف (كل واحد 20%) وستوب. be=True: من بعد الهدف الأول الستوب كيتحرك للدخول.
    كيرجع (R، شموع، واش ضرب الهدف الأول)"""
    be = BE_AFTER_TP1 if be is None else be
    risk = abs(entry - sl)
    n = len(targets)
    part = 1.0 / n
    done, real, hit1 = 0, 0.0, False
    stop = sl
    for k in range(len(h)):
        if (side == 1 and l[k] <= stop) or (side == -1 and h[k] >= stop):   # الستوب أولا (تحفظ)
            return real + (n - done) * part * side * (stop - entry) / risk, k + 1, hit1
        while done < n and ((side == 1 and h[k] >= targets[done]) or
                            (side == -1 and l[k] <= targets[done])):
            real += part * side * (targets[done] - entry) / risk
            done += 1
            hit1 = True
            if be:
                stop = entry
        if done == n:
            return real, k + 1, hit1
    return real + (n - done) * part * side * (c[-1] - entry) / risk, len(c), hit1


def _et(ts):
    ts = pd.Timestamp(ts)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return ts.tz_convert("America/New_York")


def simulate_crabel(side, entry, sl, h, l, c):
    """Crabel: الستوب = الطرف الآخر، والخروج فآخر الجلسة بسعر الإغلاق. كيرجع (R، شموع، None)"""
    risk = abs(entry - sl)
    for k in range(len(h)):
        if (side == 1 and l[k] <= sl) or (side == -1 and h[k] >= sl):
            return -1.0, k + 1, None
    if len(c) == 0:
        return 0.0, 1, None
    return side * (c[-1] - entry) / risk, len(c), None


def run(df, dd, step=1, window=WINDOW):
    dd = dd.copy()
    dd["day"] = dd["time"].map(naive_utc).dt.normalize()
    trades, last_signal, busy_until = [], None, -1
    n = len(df)
    for i in range(window, n - 1, step):
        t = naive_utc(df["time"].iloc[i])
        dsub = dd[dd["day"] < t.normalize()].reset_index(drop=True)
        if len(dsub) < MIN_DAILY:
            continue
        sub = df.iloc[i - window + 1: i + 1].reset_index(drop=True)
        res = ga.evaluate(sub, dsub, macro=0.0, verbose=False, now=t.tz_localize("UTC"))
        signal = None
        if res["decision"] == "trade":
            signal = "BUY" if res["side"] == 1 else "SELL"
        is_new = signal is not None and signal != last_signal
        last_signal = signal          # نفس منطق البوت الحي
        if not is_new or i <= busy_until:
            continue
        fut = df.iloc[i + 1: i + 1 + MAX_HOLD]
        if res.get("crabel"):
            e0 = _et(df["time"].iloc[i]).date()
            keep = 0
            for j in range(len(fut)):
                ej = _et(fut["time"].iloc[j])
                if ej.date() != e0 or ej.hour >= ga.CRABEL_EXIT_ET:
                    break
                keep += 1
            fut = fut.iloc[:keep]
            if keep == 0:
                continue
            r, held, hit1 = simulate_crabel(res["side"], res["entry"], res["sl"],
                                            fut["high"].values, fut["low"].values, fut["close"].values)
        elif res.get("targets"):
            r, held, hit1 = simulate_scalp(res["side"], res["entry"], res["sl"], res["targets"],
                                           fut["high"].values, fut["low"].values, fut["close"].values)
        else:
            r, held = simulate(res["side"], res["entry"], res["sl"], res["tp1"], res["tp2"],
                               fut["high"].values, fut["low"].values, fut["close"].values)
            hit1 = None
        r -= SPREAD / res["risk"]
        trades.append({"time": t, "side": signal, "entry": res["entry"], "sl": res["sl"],
                       "tp1": res["tp1"], "tp2": res["tp2"], "risk": res["risk"],
                       "bars_held": held, "R": round(r, 3), "hit1": hit1})
        busy_until = i + held
    return trades


def summarize(trades, start, end):
    days = max((pd.Timestamp(end) - pd.Timestamp(start)).days * 5 / 7, 1)  # أيام التداول تقريبا
    if not trades:
        return f"📈 Backtest الذهب (1h)\nمن {start} إلى {end}\n\nما كانت حتى صفقة فهاد المدة."
    r = pd.Series([t["R"] for t in trades])
    wins, losses = r[r > 0], r[r < 0]
    equity = r.cumsum()
    max_dd = (equity - equity.cummax()).min()
    streak = longest = 0
    for x in r:
        streak = streak + 1 if x < 0 else 0
        longest = max(longest, streak)
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    by_side = {s: pd.Series([t["R"] for t in trades if t["side"] == s]) for s in ("BUY", "SELL")}
    side_line = " | ".join(f"{s}: {len(v)} ({v.sum():+.1f}R)" for s, v in by_side.items() if len(v))
    return "\n".join([
        f"📈 Backtest الذهب ({ga.ENTRY_TF}) MIN_SCORE={ga.MIN_SCORE} {ga.STYLE} V={int(ga.VSHAPE)} AMD={int(ga.AMD)} BE={int(BE_AFTER_TP1)} CRABEL={int(ga.CRABEL)}{'only' if ga.CRABEL_ONLY else ''} nr7={int(ga.CRABEL_NR7)} X={ga.CRABEL_X} ICT={int(ga.ICT)}{'only' if ga.ICT_ONLY else ''} range={ga.ICT_RANGE_ET} entry={ga.ICT_ENTRY_ET} stop={ga.SCALP_STOP_ATR}ATR targets={ga.SCALP_TARGETS}",
        f"من {start} إلى {end}",
        "",
        f"عدد الصفقات: {len(r)}  (~{len(r) / days:.1f} فاليوم)",
        f"نسبة النجاح (صافي R>0): {(r > 0).mean() * 100:.0f}%",
        *([f"ضرب الهدف الأول: {sum(h)/len(h)*100:.0f}%"]
          if (h := [t["hit1"] for t in trades if t.get("hit1") is not None]) else []),
        f"متوسط الصفقة: {r.mean():+.2f}R",
        f"المجموع: {r.sum():+.1f}R",
        f"Profit factor: {pf:.2f}",
        f"أكبر تراجع: {max_dd:.1f}R",
        f"أطول سلسلة خسائر: {longest}",
        side_line,
        "",
        f"(بلا ماكرو، تكلفة {SPREAD}$ فالصفقة، R = المخاطرة ديال الصفقة)",
    ])


def send(text):
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "text": text}, timeout=20)
    print("telegram:", r.status_code)


def main():
    step = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    df = ga.get_data(ga.ENTRY_TF, ga.TF_PERIOD[ga.ENTRY_TF])
    dd = ga.get_data("1d", "5y")
    print(f"1h: {len(df)} شمعة | 1d: {len(dd)} شمعة | step={step}")
    trades = run(df, dd, step=step)
    start = naive_utc(df["time"].iloc[WINDOW]).date()
    end = naive_utc(df["time"].iloc[-1]).date()
    text = summarize(trades, start, end)
    print(text)
    pd.DataFrame(trades).to_csv("trades.csv", index=False)
    send(text)


if __name__ == "__main__":
    main()

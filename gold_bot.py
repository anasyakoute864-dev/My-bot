import contextlib, io, json, os, sys, traceback
import pandas as pd
import requests
import gold_analyzer as ga

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
STATE = os.getenv("STATE_FILE", "last_signal.json")
LABEL = os.getenv("SIGNAL_LABEL", "")   # مثلا "⚡ 15m" باش نفرقو بين البوتين
ALWAYS_SEND = os.getenv("ALWAYS_SEND", "0") == "1"
TEST_SIGNAL = os.getenv("TEST_SIGNAL", "0") == "1"


def send(text):
    for i in range(0, len(text), 3900):
        r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                          data={"chat_id": CHAT_ID, "text": text[i:i + 3900]}, timeout=20)
        print("telegram:", r.status_code)
        if not r.ok:
            # ما نستعملوش raise_for_status باش ما يطلعش التوكن فاللوغ
            raise RuntimeError(f"Telegram failed: {r.status_code} {r.text}")


def load_last():
    if not os.path.exists(STATE):
        return None
    try:
        with open(STATE) as f:
            last = json.load(f).get("signal")
    except Exception:
        return None
    if isinstance(last, dict):  # الصيغة القديمة
        last = last.get("side")
    return last


SPOT_URL = "https://forex-data-feed.swissquote.com/public-quotes/bboquotes/instrument/XAU/USD"
SPOT_ADJUST = os.getenv("SPOT_ADJUST", "1") == "1"


def spot_price():
    """سعر الذهب الفوري XAU/USD (وسط bid/ask) من Swissquote. None إلا فشل"""
    try:
        r = requests.get(SPOT_URL, timeout=10)
        p = r.json()[0]["spreadProfilePrices"][0]
        return (float(p["bid"]) + float(p["ask"])) / 2
    except Exception as e:
        print("spot fetch failed:", type(e).__name__)
        return None


def to_spot(res, ref=None):
    """كيحول الدخول والستوب والأهداف من سعر الفيوتشرز (GC=F) لسعر الفوري (XAUUSD) بنفس الفرق"""
    if not SPOT_ADJUST or res.get("decision") != "trade":
        return res
    spot = spot_price()
    if spot is None:
        return res
    off = spot - (ref if ref is not None else res.get("price", res["entry"]))   # الفرق بين الفوري وسعر الفيوتشرز الحالي
    if abs(off) > 60:  # فرق غير منطقي (بيانات غالطة): ما نبدلو والو
        print(f"spot offset {off:.1f} too large, ignored")
        return res
    print(f"futures {res['entry']:.2f} -> spot {spot:.2f} (offset {off:+.2f})")
    res = dict(res)
    for k in ("entry", "entry2", "sl", "tp1", "tp2"):
        if k in res:
            res[k] = res[k] + off
    if res.get("targets"):
        res["targets"] = [t + off for t in res["targets"]]
    if res.get("crabel") and res["crabel"].get("tp"):
        res["crabel"] = dict(res["crabel"], tp=res["crabel"]["tp"] + off)
    return res


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {}


ORD = ["الأول", "الثاني", "الثالث", "الرابع", "الخامس"]


def targets(r):
    """5 أهداف: 1R، 1.5R، TP1 (2R ولا منطقة)، نص الطريق، TP2 (3R)"""
    if r.get("targets"):  # نمط scalp: الأهداف جاهزة
        return r["targets"]
    e, side, risk = r["entry"], r["side"], r["risk"]
    return [e + side * risk, e + side * 1.5 * risk, r["tp1"], (r["tp1"] + r["tp2"]) / 2, r["tp2"]]


def build_message(r, new_signal=False):
    if r["decision"] != "trade":
        why = {"wait": "ما كاينش setup واضح", "blocked": "خبر قوي قريب", "weak_rr": "RR ضعيف",
               "off_hours": "خارج ساعات التداول"}.get(r["decision"], r["decision"])
        sc = r.get("score")
        extra = f" (النقاط {sc:+.1f} من أصل ±{r.get('min_score', '?')})" if sc is not None else ""
        return f"⏸ ما كاينش صفقة دابا: {why}{extra}"
    buy = r["side"] == 1
    head = f"{'شراء' if buy else 'بيع'} الذهب {'⬆️' if buy else '⬇️'} @ {r['entry']:.0f}"
    if not r.get("crabel"):
        head += f" - {r['entry2']:.0f}"
    lines = ([LABEL] if LABEL else []) + [head]
    if r.get("crabel"):
        if r["crabel"].get("tp"):
            lines.append(f"TP: 🎯 {r['crabel']['tp']:.0f}")
        lines.append(f"وقف الخسارة: 🔴 {r['sl']:.0f}")
        lines.append(f"الخروج: ⏰ آخر الجلسة ({r['crabel']['exit']}:00 نيويورك)")
    else:
        for name, t in zip(ORD, targets(r)):
            lines.append(f"الهدف {name}: {t:.0f}")
        lines.append(f"وقف الخسارة: 🔴 {r['sl']:.0f}")
        lines.append("🔁 من بعد الهدف الأول: حرك الستوب لنقطة الدخول")
    if r.get("ict"):
        lines.append("🧩 ICT: تجميع ← تلاعب ← CISD" + (" ← FVG" if r["ict"].get("fvg") else ""))
    if r.get("bar_close"):
        try:
            t = pd.Timestamp(r["bar_close"]).tz_convert("America/New_York")
            lines.append(f"🕒 وقت الإشارة: {t:%H:%M} (نيويورك)")
            a, b = (int(x) for x in os.getenv("STRONG_HOURS_ET", "3-12").split("-"))
            if not r.get("crabel") and not (a <= t.hour <= b):
                lines.append("⚠️ خارج ساعات لندن/نيويورك: أضعف فالـ backtest (PF أقل من 1)، خاطر بأقل")
        except Exception:
            pass
    if r.get("crabel"):
        lines.append("Crabel")
    return "\n".join(lines)


def main():
    if not TOKEN or not CHAT_ID:
        sys.exit("TOKEN / CHAT_ID ناقصين")
    if TEST_SIGNAL:  # صفقة وهمية للتجربة فقط، ما كتمس حتى حالة
        fake = {"decision": "trade", "side": 1, "entry": 4140.0, "entry2": 4130.0, "sl": 4036.0,
                "tp1": 4145.0, "tp2": 4160.0, "risk": 104.0,
                "targets": [4145.0, 4150.0, 4153.0, 4156.0, 4160.0],
                "bar_close": pd.Timestamp.now(tz="UTC").floor("15min").isoformat()}
        send("🧪 رسالة تجريبية (وهمية) - إشارة ديالنا (السكور)\n\n" + build_message(fake))
        fake_cr = {"decision": "trade", "side": 1, "entry": 4140.0, "entry2": 4140.0, "sl": 4128.0, "risk": 12.0,
                   "targets": None, "crabel": {"exit": 17, "tp": 4152.0},
                   "bar_close": pd.Timestamp.now(tz="UTC").floor("15min").isoformat()}
        send("🧪 رسالة تجريبية (وهمية) - إشارة Crabel\n\n" + build_message(fake_cr))
        return
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            results = ga.analyze_recent()
    except Exception:
        send("⚠️ خطأ فالتحليل:\n" + traceback.format_exc()[-800:])
        raise
    print(buf.getvalue())
    result = results[-1] if results else None
    ref = result["price"] if result else None

    if result:  # حالة آخر تشغيل (كنقراوها للتشخيص)
        import datetime as _dt
        with open("live_status.txt", "w", encoding="utf-8") as f:
            f.write(f"{_dt.datetime.utcnow():%Y-%m-%d %H:%M} UTC\n{buf.getvalue()}")

    # إشارات ديالنا (السكور) اللي وقعات فآخر الشموع: إشارة جديدة = اتجاه تبدل مقارنة بالشمعة اللي قبلها
    state = load_state()
    sk = list(state.get("sk") or [])
    new_sigs, prev = [], None
    for idx, r in enumerate(results):
        sg = None
        if r.get("decision") == "trade" and not r.get("crabel"):
            sg = "BUY" if r["side"] == 1 else "SELL"
        if idx > 0 and sg and sg != prev:
            key = f"{r.get('bar_close')}|{sg}"
            if key not in sk:
                new_sigs.append((key, r))
        prev = sg

    crs = result.get("crabel_all") if result else []
    cr_sent = None
    if result:
        if crs:
            sent = state.get("cr") or []
            sent = [sent] if isinstance(sent, str) else list(sent)
            for c_ in sorted(crs, key=lambda x: -x["bars_ago"]):   # الأقدم أولا
                key = f"{c_['session']}|{c_['date']}|{c_['dir']}"
                if key not in sent:
                    send(build_message(to_spot(ga.crabel_result(result, c_), ref), new_signal=True))
                    sent.append(key)
            cr_sent = sent[-10:]
        for key, r in new_sigs:
            send(build_message(to_spot(r, ref), new_signal=True))
            sk.append(key)
        if not new_sigs and not crs and ALWAYS_SEND:   # التشغيل اليدوي: سطر قصير للتأكيد
            send(build_message(to_spot(result, ref)))

    # نحفظو الحالة بعد الإرسال، باش إيلا فشل تيليغرام نعاودو نرسلو فالمرة الجاية
    with open(STATE, "w") as f:
        json.dump({"sk": sk[-20:], "cr": cr_sent if cr_sent is not None else state.get("cr")}, f)


if __name__ == "__main__":
    main()

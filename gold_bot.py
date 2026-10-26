import contextlib, io, json, os, sys, traceback
import requests
import gold_analyzer as ga

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
STATE = "last_signal.json"
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


def to_spot(res):
    """كيحول الدخول والستوب والأهداف من سعر الفيوتشرز (GC=F) لسعر الفوري (XAUUSD) بنفس الفرق"""
    if not SPOT_ADJUST or res.get("decision") != "trade":
        return res
    spot = spot_price()
    if spot is None:
        return res
    off = spot - res["entry"]
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
    return res


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
    lines = [f"{'شراء' if buy else 'بيع'} الذهب {'⬆️' if buy else '⬇️'} @ {r['entry']:.0f} - {r['entry2']:.0f}"]
    for name, t in zip(ORD, targets(r)):
        lines.append(f"الهدف {name}: {t:.0f}")
    lines.append(f"وقف الخسارة: 🔴 {r['sl']:.0f}")
    return "\n".join(lines)


def main():
    if not TOKEN or not CHAT_ID:
        sys.exit("TOKEN / CHAT_ID ناقصين")
    if TEST_SIGNAL:  # صفقة وهمية للتجربة فقط، ما كتمس حتى حالة
        fake = {"decision": "trade", "side": 1, "entry": 4140.0, "entry2": 4130.0, "sl": 4036.0,
                "tp1": 4145.0, "tp2": 4160.0, "risk": 104.0,
                "targets": [4145.0, 4150.0, 4153.0, 4156.0, 4160.0]}
        send("🧪 رسالة تجريبية (وهمية)\n\n" + build_message(fake))
        return
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            result = ga.analyze()
    except Exception:
        send("⚠️ خطأ فالتحليل:\n" + traceback.format_exc()[-800:])
        raise
    print(buf.getvalue())

    # الإشارة = الاتجاه فقط (BUY/SELL). السعر كيتبدل كل مرة، ما خاصوش يدخل فالمقارنة
    signal = None
    if result and result.get("decision") == "trade":
        signal = "BUY" if result["side"] == 1 else "SELL"

    if result:  # حالة آخر تشغيل (كنقراوها للتشخيص)
        import datetime as _dt
        with open("live_status.txt", "w", encoding="utf-8") as f:
            f.write(f"{_dt.datetime.utcnow():%Y-%m-%d %H:%M} UTC\n{buf.getvalue()}")
    last = load_last()
    if result:
        if signal and signal != last:
            send(build_message(to_spot(result), new_signal=True))
        elif ALWAYS_SEND:  # التشغيل اليدوي: صفقة إيلا كانت، وإلا سطر قصير للتأكيد
            send(build_message(to_spot(result)))

    # نحفظو الحالة بعد الإرسال، باش إيلا فشل تيليغرام نعاودو نرسلو فالمرة الجاية
    with open(STATE, "w") as f:
        json.dump({"signal": signal}, f)


if __name__ == "__main__":
    main()

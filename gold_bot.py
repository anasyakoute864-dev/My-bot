import contextlib, io, json, os, sys, traceback
import requests
import gold_analyzer as ga

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
STATE = "last_signal.json"
ALWAYS_SEND = os.getenv("ALWAYS_SEND", "0") == "1"
LINE = "━━━━━━━━━━"


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


def build_message(r, new_signal=False):
    price = f"{r['price']:.2f}"

    if r["decision"] == "trade":
        buy = r["side"] == 1
        title = "🟢 شراء BUY" if buy else "🔴 بيع SELL"
        lines = []
        if new_signal:
            lines.append("🔔 إشارة جديدة")
        lines += [
            f"🥇 الذهب | {title}",
            LINE,
            f"💰 السعر: {price}",
            f"🎯 الدخول: {r['entry']:.2f}",
            f"🛑 الستوب: {r['sl']:.2f}",
            f"✅ الهدف 1: {r['tp1']:.2f} (RR {r['rr']:.1f})",
            f"🏁 الهدف 2: {r['tp2']:.2f} (RR 3.0)",
            LINE,
        ]
        lines += ["", "⚠️ خاطر 0.5% - 1% فقط من الحساب فكل صفقة."]
        return "\n".join(lines)

    return "⏸ ما كاينش صفقة دابا."


def main():
    if not TOKEN or not CHAT_ID:
        sys.exit("TOKEN / CHAT_ID ناقصين")
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

    last = load_last()
    if result:
        if signal and signal != last:
            send(build_message(result, new_signal=True))
        elif ALWAYS_SEND:  # التشغيل اليدوي: صفقة إيلا كانت، وإلا سطر قصير للتأكيد
            send(build_message(result))

    # نحفظو الحالة بعد الإرسال، باش إيلا فشل تيليغرام نعاودو نرسلو فالمرة الجاية
    with open(STATE, "w") as f:
        json.dump({"signal": signal}, f)


if __name__ == "__main__":
    main()

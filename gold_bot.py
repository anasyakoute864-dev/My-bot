import contextlib, io, json, os, sys, traceback
import requests
import gold_analyzer as ga

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
STATE = "last_signal.json"
ALWAYS_SEND = os.getenv("ALWAYS_SEND", "0") == "1"


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


def main():
    if not TOKEN or not CHAT_ID:
        sys.exit("TOKEN / CHAT_ID ناقصين")
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            ga.analyze()
    except Exception:
        send("خطأ فالتحليل:\n" + traceback.format_exc()[-800:])
        raise
    text = buf.getvalue()
    print(text)

    # الإشارة = الاتجاه فقط (BUY/SELL). السعر كيتبدل كل مرة، ما خاصوش يدخل فالمقارنة
    signal = None
    for line in text.splitlines():
        if "القرار" in line and ("BUY" in line or "SELL" in line):
            signal = "BUY" if "BUY" in line else "SELL"

    last = load_last()
    if signal and signal != last:
        send("🔔 إشارة جديدة\n\n" + text)
    elif ALWAYS_SEND:
        send(text)

    # نحفظو الحالة بعد الإرسال، باش إيلا فشل تيليغرام نعاودو نرسلو فالمرة الجاية
    with open(STATE, "w") as f:
        json.dump({"signal": signal}, f)


if __name__ == "__main__":
    main()

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
    signal = None
    lines = text.splitlines()
    for line in lines:
        if "القرار" in line and ("BUY" in line or "SELL" in line):
            side = "BUY" if "BUY" in line else "SELL"
            entry = next((l.strip() for l in lines if l.strip().startswith("دخول")), "")
            signal = {"side": side, "entry": entry}
    last = None
    if os.path.exists(STATE):
        try:
            last = json.load(open(STATE)).get("signal")
        except Exception:
            pass
    if signal and (signal != last or ALWAYS_SEND):
        send("🔔 إشارة جديدة\n\n" + text)
    elif ALWAYS_SEND:
        send(text)
    json.dump({"signal": signal}, open(STATE, "w"))


if __name__ == "__main__":
    main()

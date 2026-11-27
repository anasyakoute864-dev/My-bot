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
SCALP_OLD = os.getenv("SCALP_OLD", "0") == "1"            # إشارة سكالب إضافية (النسخة القديمة): ستوب واسع + هدف واحد صغير
SCALP_OLD_STOP_ATR = float(os.getenv("SCALP_OLD_STOP_ATR", "5.0"))
SCALP_OLD_TP_ATR = float(os.getenv("SCALP_OLD_TP_ATR", "0.25"))
LATE_NOTE_MIN = int(os.getenv("LATE_NOTE_MIN", "0"))   # إيلا الإشارة وصلات متأخرة X دقيقة ولا أكثر كنزيدو سطر تنبيه (0 = مطفي)
MAX_LOSSES_DAY = int(os.getenv("MAX_LOSSES_DAY", "0"))   # 0 = مطفي. بعد N خسارات ف نفس النهار (توقيت نيويورك) ما كنصيفطوش إشارة جديدة (ديالنا فقط، ماشي Crabel)


def send(text):
    print("SENT>>", text.replace("\n", " | ")[:600])   # أرشيف فاللوغ باش نقدرو نراجعو كل إشارة
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


def futures_now(max_age_min=4):
    """آخر إغلاق 1د ديال GC=F إلا كان طري (أقل من max_age_min دقايق) وإلا None"""
    if getattr(ga, "USING_FALLBACK", False):
        return ga.okx_last_price()
    try:
        import yfinance as yf
        d = yf.download("GC=F", interval="1m", period="1d", auto_adjust=False, progress=False)
        if d is None or len(d) == 0:
            return None
        if hasattr(d.columns, "levels"):
            d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
        t = pd.Timestamp(d.index[-1])
        t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
        age = (pd.Timestamp.now(tz="UTC") - t).total_seconds() / 60 - 1
        if age > max_age_min:
            print(f"futures 1m stale ({age:.0f} min), using bar price")
            return None
        return float(d["Close"].iloc[-1])
    except Exception as e:
        print("futures_now failed:", type(e).__name__)
        return None


def to_spot(res, ref=None):
    """كيحول الدخول والستوب والأهداف من سعر الفيوتشرز (GC=F) لسعر الفوري (XAUUSD) بنفس الفرق"""
    if not SPOT_ADJUST or res.get("decision") != "trade":
        return res
    spot = spot_price()
    if spot is None:
        return res
    fut = futures_now()   # آخر سعر فيوتشرز طري (1د) باش الفرق ما يتلوثش بحركة السعر من إغلاق الشمعة
    if fut is None:
        fut = ref if ref is not None else res.get("price", res["entry"])
    off = spot - fut      # الفرق الحقيقي (basis) بين الفوري والفيوتشرز
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


def scalp_old(r):
    """نفس الإشارة (اتجاه/دخول/وقت) ولكن بالنسخة القديمة: ستوب X×ATR وهدف واحد Y×ATR"""
    a, side, e = r["atr"], r["side"], r["entry"]
    tp = e + side * SCALP_OLD_TP_ATR * a
    return dict(r, entry2=r["entry2"], sl=e - side * SCALP_OLD_STOP_ATR * a, tp1=tp, tp2=tp,
                risk=SCALP_OLD_STOP_ATR * a, targets=None, scalp=True)


def _et_date(ts):
    t = pd.Timestamp(ts)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    return t.tz_convert("America/New_York").date()


def trade_lost(tr, df, until=None):
    """True = الستوب تضرب قبل الهدف الأول (خسارة، نفس تعريف الـ backtest) | False = الهدف الأول ضرب | None = مازال مفتوح"""
    t0 = pd.Timestamp(tr["t"])
    delta = ga.TF_DELTA[ga.ENTRY_TF]
    side, sl, tp1 = tr["side"], tr["sl"], tr["tp1"]
    for tm, hi, lo in zip(pd.to_datetime(df["time"]), df["high"].values, df["low"].values):
        tm = tm.tz_localize("UTC") if tm.tzinfo is None else tm.tz_convert("UTC")
        if tm < t0:
            continue
        if until is not None and tm + delta > until:
            break
        if (side == 1 and lo <= sl) or (side == -1 and hi >= sl):   # الستوب أولا (تحفظ)
            return True
        if (side == 1 and hi >= tp1) or (side == -1 and lo <= tp1):
            return False
    return None


MAX_SIGNALS_DAY = int(os.getenv("MAX_SIGNALS_DAY", "0"))   # 0 = مطفي. أقصى عدد إشارات ديالنا فالنهار (توقيت نيويورك)
DAILY_SUMMARY = os.getenv("DAILY_SUMMARY", "0") == "1"      # ملخص يومي فتليغرام (من 17:00 نيويورك)
SWING = os.getenv("SWING", "0") == "1"                      # Claude Swing: سوينغ 1 ساعة (Donchian 20/10 شراء فقط)
SMC = os.getenv("SMC", "0") == "1"                          # SMC تجريبي: تغير الاتجاه + FVG (15 دقيقة)
CDAILY = os.getenv("CLAUDE_DAILY", "0") == "1"             # Claude Daily: إشارتين فالنهار (لندن + نيويورك) باتجاه اليوم
COOLDOWN_MIN = int(os.getenv("SIGNAL_COOLDOWN_MIN", "0"))   # 0 = مطفي. كيمنع إشارة فنفس الاتجاه من بعد أخرى داخل هاد المدة (ما كنزيدوش فنفس الحركة)


def recent_same_side(tracked, r, minutes):
    import pandas as pd
    try:
        t1 = pd.Timestamp(r["bar_close"])
        for x in tracked:
            if int(x.get("side", 0)) == int(r["side"]):
                d = (t1 - pd.Timestamp(x["t"])).total_seconds() / 60
                if 0 <= d < minutes:
                    return True
    except Exception:
        return False
    return False


def swing_messages(events, off, entry_off=None):
    """رسائل Claude Swing. off = الفرق بين الفوري وسعر الفيوتشرز (0 إلا ما كانش)"""
    out = []
    for ev in events:
        et = pd.Timestamp(ev["t"]).tz_convert("America/New_York").strftime("%H:%M")
        buy = ev.get("side", 1) == 1
        if ev["kind"] == "entry":
            out.append("🧭 Claude Swing (سوينغ 1 ساعة)\n"
                       f"{'شراء' if buy else 'بيع'} الذهب {'⬆️' if buy else '⬇️'} @ {ev['price'] + off:.0f}\n"
                       + (f"الهدف: 🎯 {ev['tp'] + off:.0f}\n" if ev.get("tp") is not None else "") +
                       f"وقف الخسارة: 🔴 {ev['sl'] + off:.0f} ({ev['risk']:.0f} نقطة)\n"
                       f"الخروج: غادي نصيفط ليك رسالة ملي تسد شمعة ساعة {'تحت أدنى' if buy else 'فوق أعلى'} 10 شموع، ولا ملي يضرب الستوب\n"
                       f"🕒 وقت الإشارة: {et} (نيويورك)")
        else:
            pts = (ev["price"] - ev["entry"]) * (1 if buy else -1)
            eo = off if entry_off is None else entry_off
            xprice = ev["entry"] + eo + pts * (1 if buy else -1)   # نفس فرق الدخول، باش الرقمين يتناسبو
            why = "ضرب الستوب" if ev["reason"] == "stop" else "ضرب الهدف 🎯" if ev["reason"] == "tp" else ("كسر أدنى 10 شموع" if buy else "كسر أعلى 10 شموع")
            out.append(f"🧭 Claude Swing: اخرج من {'الشراء' if buy else 'البيع'}\n"
                       f"السبب: {why}\n"
                       f"الخروج حوالي {xprice:.0f} | النتيجة حوالي {pts:+.0f} نقطة\n"
                       f"🕒 {et} (نيويورك)")
    return out


def smc_message(st, off):
    et = pd.Timestamp(st["t"]).tz_convert("America/New_York").strftime("%H:%M")
    buy = st["side"] == 1
    z_lo, z_hi = st["zone"]
    cancel = f"تحت {z_lo + off:.0f}" if buy else f"فوق {z_hi + off:.0f}"
    return ("🧩 SMC (تجريبي، 15 دقيقة) - أمر معلق\n"
            f"{'شراء' if buy else 'بيع'} الذهب {'⬆️' if buy else '⬇️'} {'Buy' if buy else 'Sell'} Limit @ {st['entry'] + off:.0f}\n"
            f"وقف الخسارة: 🔴 {st['sl'] + off:.0f}\n"
            f"الهدف: 🎯 {st['tp'] + off:.0f} (آخر {'قمة' if buy else 'قاع'})\n"
            f"صالح 5 ساعات. إلغيه إيلا سدات شمعة 15د {cancel} قبل ما يتنفذ.\n"
            f"🕒 وقت الإشارة: {et} (نيويورك)")


def cdaily_message(x, off):
    et = pd.Timestamp(x["t"]).strftime("%H:%M")
    buy = x["side"] == 1
    name = "لندن: كسر مدى آسيا" if x["sig"] == "A" else "نيويورك: رجوع لـ VWAP"
    return (f"🤖 Claude Daily ({name})\n"
            f"{'شراء' if buy else 'بيع'} الذهب {'⬆️' if buy else '⬇️'} @ {x['entry'] + off:.0f}\n"
            f"الهدف: 🎯 {x['tp'] + off:.0f}\n"
            f"وقف الخسارة: 🔴 {x['sl'] + off:.0f}\n"
            f"الخروج: ⏰ {x['exit']}:00 نيويورك إيلا ما ضربش الهدف ولا الستوب\n"
            f"🕒 وقت الإشارة: {et} (نيويورك)")


def day_trades(tracked, day):
    out = []
    for x in tracked:
        try:
            if str(_et_date(pd.Timestamp(x["t"]))) == day:
                out.append(x)
        except Exception:
            pass
    return out


def daily_summary_text(tracked, df, day):
    ts = day_trades(tracked, day)
    if not ts:
        return f"📊 ملخص {day}: ما كانتش إشارة ديالنا (السكور) اليوم."
    lines, w, l, o = [], 0, 0, 0
    for x in ts:
        res = trade_lost(x, df)
        et = pd.Timestamp(x["t"]).tz_convert("America/New_York").strftime("%H:%M")
        side = "شراء" if x["side"] == 1 else "بيع"
        if res is True:
            l += 1; tag = "❌ الستوب"
        elif res is False:
            w += 1; tag = "✅ الهدف الأول"
        else:
            o += 1; tag = "⏳ مفتوحة"
        lines.append(f"{et} {side}: {tag}")
    return (f"📊 ملخص {day} (إشارات السكور): {len(ts)} إشارة | ✅ {w} | ❌ {l} | ⏳ {o}\n"
            + "\n".join(lines) + "\n(الربح = الهدف الأول قبل الستوب. Crabel ما داخلش فهاد الملخص.)")


def losses_today(tracked, df, ts):
    day = _et_date(ts)
    until = pd.Timestamp(ts)
    until = until.tz_localize("UTC") if until.tzinfo is None else until.tz_convert("UTC")
    return sum(1 for tr in tracked if _et_date(tr["t"]) == day and trade_lost(tr, df, until) is True)


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
    elif r.get("scalp"):
        lines.append(f"TP: 🎯 {r['tp1']:.0f}")
        lines.append(f"وقف الخسارة: 🔴 {r['sl']:.0f}")
    else:
        for name, t in zip(ORD, targets(r)):
            lines.append(f"الهدف {name}: {t:.0f}")
        lines.append(f"وقف الخسارة: 🔴 {r['sl']:.0f}")
        lines.append("🔁 من بعد الهدف الأول: حرك الستوب لنقطة الدخول")
    if r.get("ict"):
        lines.append("🧩 ICT: تجميع ← تلاعب ← CISD" + (" ← FVG" if r["ict"].get("fvg") else ""))
    bc = (r.get("crabel") or {}).get("trigger_close") or r.get("bar_close")   # Crabel: وقت الاختراق الحقيقي ماشي وقت الفحص
    if bc:
        try:
            t = pd.Timestamp(bc).tz_convert("America/New_York")
            lines.append(f"🕒 وقت الإشارة: {t:%H:%M} (نيويورك)")
            if new_signal and LATE_NOTE_MIN:
                late = (pd.Timestamp.now(tz="UTC") - pd.Timestamp(bc).tz_convert("UTC")).total_seconds() / 60
                if late >= LATE_NOTE_MIN:
                    lines.append(f"⏱ وصلات متأخرة {int(late)} دقيقة: شوف السعر الحالي قبل ما تدخل")
            a, b = (int(x) for x in os.getenv("STRONG_HOURS_ET", "3-12").split("-"))
            if not r.get("crabel") and not (a <= t.hour <= b):
                lines.append("⚠️ خارج ساعات لندن/نيويورك: أضعف فالـ backtest (PF أقل من 1)، خاطر بأقل")
        except Exception:
            pass
    if r.get("crabel"):
        lines.append("Crabel")
    if r.get("scalp"):
        lines.append("Scalp")
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
        if SCALP_OLD:
            fake_sc = scalp_old(dict(fake, atr=8.0))
            send("🧪 رسالة تجريبية (وهمية) - إشارة Scalp\n\n" + build_message(fake_sc))
        t_ = pd.Timestamp.now(tz="UTC").tz_convert("America/New_York")
        send("🧪 رسالة تجريبية (وهمية) - Claude Swing\n\n" + swing_messages(
            [{"kind": "entry", "side": -1, "price": 4140.0, "sl": 4180.0, "risk": 40.0, "t": t_}], 0.0)[0])
        send("🧪 رسالة تجريبية (وهمية) - Claude Swing (خروج)\n\n" + swing_messages(
            [{"kind": "exit", "side": -1, "reason": "channel", "price": 4115.0, "entry": 4140.0, "t": t_}], 0.0)[0])
        send("🧪 رسالة تجريبية (وهمية) - SMC\n\n" + smc_message(
            {"side": 1, "entry": 4140.0, "sl": 4128.0, "tp": 4165.0, "zone": (4134.0, 4140.0), "t": t_}, 0.0))
        send("🧪 رسالة تجريبية (وهمية) - Claude Daily\n\n" + cdaily_message(
            {"sig": "A", "side": -1, "entry": 4140.0, "sl": 4151.0, "tp": 4123.5, "exit": 11, "t": t_}, 0.0))
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
        tr = [x for x in (state.get("tr") or []) if isinstance(x, dict)]
        df_ = None
        if MAX_LOSSES_DAY and new_sigs:
            try:
                df_ = ga.get_data(ga.ENTRY_TF, "59d" if ga.ENTRY_TF == "15m" else "60d")
            except Exception as e:   # إيلا فشل التحميل ما نبلوكيوش (الأحسن نصيفطو إشارة)
                print("loss-limit check skipped:", type(e).__name__)
        for key, r in new_sigs:
            if COOLDOWN_MIN and recent_same_side(tr, r, COOLDOWN_MIN):
                print(f"skipped {key}: same-side signal within {COOLDOWN_MIN} min")
                sk.append(key)
                continue
            if MAX_SIGNALS_DAY and len(day_trades(tr, str(_et_date(pd.Timestamp(r["bar_close"]))))) >= MAX_SIGNALS_DAY:
                print(f"skipped {key}: {MAX_SIGNALS_DAY} signals already today")
                sk.append(key)
                continue
            if df_ is not None:
                try:
                    n_loss = losses_today(tr, df_, r["bar_close"])
                except Exception as e:
                    print("loss-limit check failed:", type(e).__name__)
                    n_loss = 0
                if n_loss >= MAX_LOSSES_DAY:
                    print(f"skipped {key}: {n_loss} losses today (limit {MAX_LOSSES_DAY})")
                    if SCALP_OLD:
                        send(build_message(to_spot(scalp_old(r), ref), new_signal=True))
                    sk.append(key)
                    continue
            send(build_message(to_spot(r, ref), new_signal=True))
            if SCALP_OLD:
                send(build_message(to_spot(scalp_old(r), ref), new_signal=True))
            sk.append(key)
            if MAX_LOSSES_DAY or COOLDOWN_MIN or MAX_SIGNALS_DAY or DAILY_SUMMARY:
                tg = r.get("targets") or [r["tp1"]]
                tr.append({"t": r["bar_close"], "side": int(r["side"]), "sl": float(r["sl"]), "tp1": float(tg[0])})
        if not new_sigs and not crs and ALWAYS_SEND:   # التشغيل اليدوي: سطر قصير للتأكيد
            send(build_message(to_spot(result, ref)))

    fb = state.get("fb")
    if ga.USING_FALLBACK:
        today = pd.Timestamp.now(tz="America/New_York").strftime("%Y-%m-%d")
        if fb != today:
            send("⚠️ مصدر البيانات (Yahoo) واقف. البوت خدام دابا بمصدر بديل (OKX، ذهب XAUT). الأسعار كتتحول للسبوت تلقائياً، ولكن خاصها مراقبة.")
            fb = today
    sw_states = {}
    for key, tpr, tag in (("sw", None, ""), ("sw2", 0.5, " ⚡ هدف قريب 0.5R")):
        cur = state.get(key)
        sw_states[key] = cur
        if not (result and SWING):
            continue
        try:
            import swing_live
            df_w = ga.get_data("1h", "60d")
            evs, sw_new = swing_live.evaluate(df_w, cur, pd.Timestamp.now(tz="UTC"), tp_r=tpr)
            if evs:
                spot = spot_price() if SPOT_ADJUST else None
                fut = futures_now()
                if fut is None:
                    fut = ref if ref is not None else float(df_w["close"].iloc[-1])
                off = (spot - fut) if spot is not None and abs(spot - fut) <= 60 else 0.0
                old_off = (cur or {}).get("off", off)
                for m in swing_messages(evs, off, old_off):
                    send(m.replace("Claude Swing", "Claude Swing" + tag, 1) if tag else m)
                if sw_new:
                    sw_new = dict(sw_new, off=off) if any(e["kind"] == "entry" for e in evs) else dict(sw_new, off=old_off)
            sw_states[key] = sw_new
        except Exception as e:
            print("swing failed:", type(e).__name__, e)
    sw, sw2 = sw_states["sw"], sw_states["sw2"]

    smk = list(state.get("smk") or [])
    if result and SMC:
        try:
            import smc_live
            df_m = ga.get_data("15m", "59d")
            sts = [x for x in smc_live.detect(df_m, pd.Timestamp.now(tz="UTC")) if x["key"] not in smk]
            if sts:
                last_close = float(df_m["close"].iloc[-1])
                spot = spot_price() if SPOT_ADJUST else None
                off = (spot - last_close) if spot is not None and abs(spot - last_close) <= 60 else 0.0
                for x in sts:
                    send(smc_message(x, off))
                    smk.append(x["key"])
        except Exception as e:
            print("smc failed:", type(e).__name__, e)

    cdk = list(state.get("cdk") or [])
    if result and CDAILY:
        try:
            import claude_daily_live
            df_c = ga.get_data("15m", "59d")
            sts = [x for x in claude_daily_live.detect(df_c, pd.Timestamp.now(tz="UTC")) if x["key"] not in cdk]
            if sts:
                last_close = float(df_c["close"].iloc[-1])
                spot = spot_price() if SPOT_ADJUST else None
                off = (spot - last_close) if spot is not None and abs(spot - last_close) <= 60 else 0.0
                for x in sts:
                    send(cdaily_message(x, off))
                    cdk.append(x["key"])
        except Exception as e:
            print("claude daily failed:", type(e).__name__, e)

    ds = state.get("ds")
    if result and DAILY_SUMMARY:
        try:
            now_et = pd.Timestamp.now(tz="UTC").tz_convert("America/New_York")
            day = str(now_et.date())
            if now_et.hour >= 17 and ds != day and now_et.weekday() < 5:
                df_s = ga.get_data(ga.ENTRY_TF, "59d" if ga.ENTRY_TF == "15m" else "60d")
                send(daily_summary_text(tr, df_s, day))
                ds = day
        except Exception as e:
            print("daily summary failed:", type(e).__name__, e)

    # نحفظو الحالة بعد الإرسال، باش إيلا فشل تيليغرام نعاودو نرسلو فالمرة الجاية
    with open(STATE, "w") as f:
        json.dump({"tr": (tr if result else (state.get("tr") or []))[-30:], "sk": sk[-20:], "cr": cr_sent if cr_sent is not None else state.get("cr"), "ds": ds, "sw": sw, "sw2": sw2, "fb": fb, "smk": smk[-20:], "cdk": cdk[-20:]}, f)


if __name__ == "__main__":
    main()

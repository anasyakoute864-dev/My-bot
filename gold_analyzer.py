#!/usr/bin/env python3
"""
محلل الذهب (XAUUSD / GC=F) - Market Structure + Breakout + FVG + Liquidity Sweep + S/R + Fibo + Macro
تشغيل:  pip install yfinance pandas numpy requests
         export FRED_API_KEY=xxxx      (مفتاح مجاني من fred.stlouisfed.org)
         python gold_analyzer.py
تنبيه: هذا أداة تحليل، ماكاينش ضمان ربح. جرّبو على حساب ديمو وbacktest قبل الفلوس الحقيقية.
"""
import os
import sys
import numpy as np
import pandas as pd
import requests
import yfinance as yf

SYMBOL = os.getenv("SYMBOL", "GC=F")   # GC=F = فيوتشرز | XAUUSD=X = الذهب الفوري (سعر البروكر)
ENTRY_TF = os.getenv("ENTRY_TF", "1h")   # فريم الدخول: 1h ولا 15m
TF_DELTA = {"15m": pd.Timedelta(minutes=15), "1h": pd.Timedelta(hours=1), "1d": pd.Timedelta(days=1)}
TF_PERIOD = {"15m": "59d", "1h": "730d"}   # Yahoo كيعطي غير 60 يوم للـ 15m
HTF = "1d"                 # الفريم الكبير
PIVOT_N = 3                # عدد الشموع لتحديد القمم/القيعان
MIN_SCORE = int(os.getenv("MIN_SCORE", "5"))   # أقل نقطة باش نعطيك صفقة
SELL_EXTRA = 1             # البيع خاصو نقطة زايدة (walk-forward: SELL ضعيف إلا ما كانش قوي)
MIN_RR = 1.5               # أقل نسبة ربح/خسارة
FRED_KEY = os.getenv("FRED_API_KEY", "")
# نمط الإشارة: swing (أهداف 1R-3R، ستوب قريب) ولا scalp (أهداف قريبة بحال القنوات، ستوب بعيد)
STYLE = os.getenv("SIGNAL_STYLE", "swing")
# ساعات التداول بتوقيت نيويورك (لندن + أمريكا). "off" = بلا فلتر. مثال: "3-12"
TRADE_HOURS_ET = os.getenv("TRADE_HOURS_ET", "3-12")
VSHAPE = os.getenv("VSHAPE", "0") == "1"       # كشف حركة V (نزول/صعود سريع ثم انعكاس)
V_LOOK, V_DROP_ATR, V_REB_ATR, V_MAX_BARS = 12, 3.0, 2.0, 8
VTRADE = os.getenv("VTRADE", "0") == "1"                # حركة V كصفقة (دخول + ستوب + أهداف)
VTRADE_ONLY = os.getenv("VTRADE_ONLY", "0") == "1"
V_FRACS = [float(x) for x in os.getenv("V_FRACS", "0.2,0.4,0.6,0.8,1.0").split(",")]   # الأهداف = نسب من المسافة لبداية الحركة
V_MIN_RR = float(os.getenv("V_MIN_RR", "1.0"))          # أقل نسبة (المسافة للهدف الأخير / المخاطرة)
ICT = os.getenv("ICT", "0") == "1"                  # نموذج ICT: رينج -> سحب سيولة -> CISD -> FVG -> هدف الرينج
ICT_ONLY = os.getenv("ICT_ONLY", "0") == "1"        # 1 = غير نموذج ICT (بلا السكور العادي)
ICT_RANGE_ET = os.getenv("ICT_RANGE_ET", "20-2")    # ساعات الرينج (نيويورك). 20-2 = آسيا | 2-7 = لندن
ICT_ENTRY_ET = os.getenv("ICT_ENTRY_ET", "2-11")    # ساعات السحب والدخول (نيويورك)
CRABEL = os.getenv("CRABEL", "0") == "1"            # Toby Crabel: Opening Range Breakout (Stretch)
CRABEL_ONLY = os.getenv("CRABEL_ONLY", "0") == "1"
CRABEL_SESSIONS = os.getenv("CRABEL_SESSIONS", "3-11,8-17")   # جلسات: ساعة الفتحة-ساعة الخروج (نيويورك). لندن 3-11 | نيويورك 8-17
CRABEL_N = int(os.getenv("CRABEL_N", "10"))                    # عدد الجلسات السابقة لحساب الـ Stretch
CRABEL_X = float(os.getenv("CRABEL_X", "1.0"))                 # 1 = Stretch كيف هو
CRABEL_TP = float(os.getenv("CRABEL_TP", "0"))                  # TP بمضاعفات Stretch (0 = بلا TP، خروج آخر الجلسة)
ICT_HTF = os.getenv("ICT_HTF", "0") == "1"          # 1 = ما نداخلش ضد الاتجاه اليومي
ICT_FRACS = [0.35, 0.5, 0.65, 0.8, 1.0]             # الأهداف = نسب من المسافة للطرف الآخر ديال الرينج
SCALP_STOP_ATR = float(os.getenv("SCALP_STOP_ATR", "5.0"))   # الستوب = X ATR
SCALP_TARGETS = [float(x) for x in os.getenv("SCALP_TARGETS", "0.25,0.5,0.65,0.8,1.0").split(",")]   # 5 أهداف بـ ATR
# تواريخ/ساعات الأخبار القوية بتوقيت UTC (البوت ما كيدخلش ساعة قبل وساعة بعد)
# المصادر: federalreserve.gov (FOMC) و bls.gov/schedule (CPI, NFP). تأكد منها من وقت لآخر، وزيد 2027 فآخر السنة.
NEWS_BLACKOUT = [
    "2026-10-28 18:00",  # FOMC قرار الفايدة (2:00 PM ET)
    "2026-11-06 13:30",  # NFP تقرير الوظائف (8:30 AM ET)
    "2026-11-10 13:30",  # CPI التضخم
    "2026-12-04 13:30",  # NFP
    "2026-12-09 19:00",  # FOMC (2:00 PM ET)
    "2026-12-10 13:30",  # CPI
]


# ---------------------------------------------------------------- بيانات
def drop_unclosed(df, interval):
    """نحيدو آخر شمعة إيلا باقا ما سدّاتش، باش الإشارة ما تبانش وتمشي وسط الساعة"""
    delta = TF_DELTA[interval]
    last = df.index[-1]
    last = last.tz_localize("UTC") if last.tzinfo is None else last.tz_convert("UTC")
    if last + delta > pd.Timestamp.now(tz="UTC"):
        return df.iloc[:-1]
    return df


def prepare(df, interval):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower).dropna()
    df = drop_unclosed(df, interval)
    df["atr"] = atr(df)
    df["time"] = df.index          # وقت الشمعة (كيحتاجو الـ backtest)
    return df.dropna(subset=["atr"]).reset_index(drop=True)


def get_data(interval, period):
    df = yf.download(SYMBOL, interval=interval, period=period, auto_adjust=False, progress=False)
    return prepare(df, interval)


def atr(df, n=14):
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


# ---------------------------------------------------------------- Market Structure
def pivots(df, n=PIVOT_N):
    """يرجع قائمة (index, price, 'H'/'L') للقمم والقيعان المؤكدة"""
    out = []
    h, l = df["high"].values, df["low"].values
    for i in range(n, len(df) - n):
        if h[i] == max(h[i - n:i + n + 1]):
            out.append((i, h[i], "H"))
        if l[i] == min(l[i - n:i + n + 1]):
            out.append((i, l[i], "L"))
    return sorted(out)


def market_structure(df):
    pv = pivots(df)
    highs = [p for p in pv if p[2] == "H"][-3:]
    lows = [p for p in pv if p[2] == "L"][-3:]
    trend, bos = 0, None
    if len(highs) >= 2 and len(lows) >= 2:
        hh = highs[-1][1] > highs[-2][1]
        hl = lows[-1][1] > lows[-2][1]
        lh = highs[-1][1] < highs[-2][1]
        ll = lows[-1][1] < lows[-2][1]
        if hh and hl:
            trend = 1
        elif lh and ll:
            trend = -1
    close = df["close"].iloc[-1]
    # BOS: كسر آخر قمة/قاع بإغلاق
    if highs and close > highs[-1][1] and (len(df) - 1 - highs[-1][0]) < 40:
        bos = 1
    if lows and close < lows[-1][1] and (len(df) - 1 - lows[-1][0]) < 40:
        bos = -1
    return trend, bos, pv


# ---------------------------------------------------------------- Support / Resistance
def sr_zones(df, pv):
    a = df["atr"].iloc[-1]
    levels = sorted(p[1] for p in pv)
    zones, cur = [], []
    for lv in levels:
        if cur and lv - cur[-1] > 0.5 * a:
            zones.append(cur)
            cur = []
        cur.append(lv)
    if cur:
        zones.append(cur)
    res = [(min(z), max(z), len(z)) for z in zones if len(z) >= 2]
    return res  # (low, high, touches)


def nearest_zones(zones, price):
    below = [z for z in zones if z[1] <= price]
    above = [z for z in zones if z[0] >= price]
    sup = max(below, key=lambda z: z[1]) if below else None
    resi = min(above, key=lambda z: z[0]) if above else None
    return sup, resi


# ---------------------------------------------------------------- FVG
def find_fvg(df, lookback=60):
    fvgs = []
    start = max(2, len(df) - lookback)
    a = df["atr"].values
    for i in range(start, len(df)):
        lo, hi = df["low"].values, df["high"].values
        if lo[i] > hi[i - 2] and (lo[i] - hi[i - 2]) > 0.2 * a[i]:
            zone = (hi[i - 2], lo[i], 1)
            if not (df["close"].values[i + 1:] < zone[0]).any():
                fvgs.append(zone)
        if hi[i] < lo[i - 2] and (lo[i - 2] - hi[i]) > 0.2 * a[i]:
            zone = (hi[i], lo[i - 2], -1)
            if not (df["close"].values[i + 1:] > zone[1]).any():
                fvgs.append(zone)
    return fvgs  # (low, high, dir)


# ---------------------------------------------------------------- Liquidity Sweep
def find_sweep(df, pv, window=12):
    """
    نبحث على سحب سيولة فوق قمة / تحت قاع في آخر `window` شمعة.
    الحكم: حقيقي (Stop-hunt وكيرجع) / مزيف (كان اختراق فعلي) / غير مؤكد
    """
    n = len(df)
    o, h, l, c = (df[k].values for k in ("open", "high", "low", "close"))
    a = df["atr"].values
    vol = df["volume"].values if "volume" in df else None
    avg_vol = pd.Series(vol).rolling(20).mean().values if vol is not None else None
    for i in range(n - 1, n - 1 - window, -1):
        prior = [p for p in pv if p[0] < i - PIVOT_N and p[0] > i - 60]
        rng = max(h[i] - l[i], 1e-9)
        for idx, lv, kind in sorted(prior, key=lambda p: -p[0]):
            if kind == "H" and h[i] > lv + 0.05 * a[i] and c[i] < lv:
                wick = (h[i] - max(o[i], c[i])) / rng
                direction = -1
            elif kind == "L" and l[i] < lv - 0.05 * a[i] and c[i] > lv:
                wick = (min(o[i], c[i]) - l[i]) / rng
                direction = 1
            else:
                continue
            after = c[i + 1:]
            reclaimed_fail = (len(after) >= 1 and
                              ((direction == -1 and (after > lv).sum() >= 2) or
                               (direction == 1 and (after < lv).sum() >= 2)))
            vol_ok = bool(avg_vol is not None and avg_vol[i] and vol[i] > 1.2 * avg_vol[i])
            if reclaimed_fail:
                verdict = "مزيف (السعر رجع كمل الاختراق)"
            elif wick >= 0.5 and (len(after) == 0 or
                                  (direction == -1 and after[-1] < lv) or
                                  (direction == 1 and after[-1] > lv)):
                verdict = "حقيقي" + (" + فوليوم قوي" if vol_ok else "")
            else:
                verdict = "غير مؤكد"
            return {"level": lv, "extreme": h[i] if direction == -1 else l[i],
                    "dir": direction, "verdict": verdict, "wick": wick, "bars_ago": n - 1 - i}
    return None


# ---------------------------------------------------------------- حركة V
def v_shape(df):
    """
    V صاعد (+1): نزول >= 3 ATR من قمة قريبة لقاع، ومن بعد رجوع >= 2 ATR (وعلى الأقل نص النزول)
                 فـ <= 8 شموع. V نازل (-1): العكس.
    كيرجع None إلا ما كانتش حركة V.
    """
    n = len(df)
    if n < V_LOOK + 3:
        return None
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    a = float(df["atr"].iloc[-1])
    w0 = n - V_MAX_BARS - 1
    lows = l[w0:n]
    k = w0 + int(np.argmin(lows))
    bars = n - 1 - k
    if 1 <= bars <= V_MAX_BARS:
        drop = h[max(0, k - V_LOOK):k + 1].max() - l[k]
        reb = c[-1] - l[k]
        if drop >= V_DROP_ATR * a and reb >= V_REB_ATR * a and reb >= 0.5 * drop:
            return {"dir": 1, "extreme": float(l[k]), "drop": float(drop), "reb": float(reb), "bars_ago": bars}
    highs = h[w0:n]
    k = w0 + int(np.argmax(highs))
    bars = n - 1 - k
    if 1 <= bars <= V_MAX_BARS:
        rise = h[k] - l[max(0, k - V_LOOK):k + 1].min()
        fall = h[k] - c[-1]
        if rise >= V_DROP_ATR * a and fall >= V_REB_ATR * a and fall >= 0.5 * rise:
            return {"dir": -1, "extreme": float(h[k]), "drop": float(rise), "reb": float(fall), "bars_ago": bars}
    return None


# ---------------------------------------------------------------- ICT: رينج -> تلاعب -> CISD -> FVG -> توزيع
def _hours(rng):
    a, b = (int(x) for x in rng.split("-"))
    return a, b


def _in_window(hour, a, b):
    return (a <= hour < b) if a < b else (hour >= a or hour < b)


def ict_setup(df):
    """
    1) تجميع: رينج الجلسة السابقة (ICT_RANGE_ET بتوقيت نيويورك) -> قمة/قاع السيولة.
    2) تلاعب: السعر كيسحب قاع (ولا قمة) الرينج فنافذة ICT_ENTRY_ET.
    3) CISD: من بعد السحب، شمعة كتسد فوق (ولا تحت) فتحة سلسلة الشموع اللي دارت السحب.
    4) FVG: فجوة فالحركة الانعكاسية (كنستعملوها لمجال الدخول).
    5) توزيع: الهدف = الطرف الآخر ديال الرينج. الستوب = وراء طرف السحب.
    الدخول غير فأول شمعتين من CISD. dir=+1 شراء، -1 بيع.
    """
    n = len(df)
    if n < 60:
        return None
    t = pd.to_datetime(df["time"])
    t = t.dt.tz_localize("UTC") if t.dt.tz is None else t.dt.tz_convert("UTC")
    et = t.dt.tz_convert("America/New_York")
    hrs = et.dt.hour.values
    ra, rb = _hours(ICT_RANGE_ET)
    ea, eb = _hours(ICT_ENTRY_ET)
    close_hr = (et.iloc[-1] + TF_DELTA[ENTRY_TF]).hour
    if not _in_window(close_hr, ea, eb) and not _in_window(hrs[-1], ea, eb):
        return None
    in_rng = np.array([_in_window(int(x), ra, rb) for x in hrs])
    sid = (et - pd.Timedelta(hours=ra)).dt.strftime("%Y%m%d").values
    # آخر رينج مكتمل: آخر شمعة فالرينج قبل الشمعة الحالية، والحالية خارج الرينج
    idx = np.where(in_rng[:-1])[0]
    if len(idx) == 0 or in_rng[-1]:
        return None
    last_in = idx[-1]
    grp = [i for i in idx if sid[i] == sid[last_in]]
    need = max(3, int(((rb - ra) % 24) * (3600 / TF_DELTA[ENTRY_TF].total_seconds()) * 0.5))
    if len(grp) < need:
        return None
    o, h, l, c = (df[k].values for k in ("open", "high", "low", "close"))
    a = df["atr"].values
    rh, rl = h[grp].max(), l[grp].min()
    start = last_in + 1
    post = range(start, n)
    if len(post) < 3:
        return None
    for d in (1, -1):
        # أول سحب فالاتجاه d (شراء = سحب القاع)
        j = next((i for i in post if (d == 1 and l[i] < rl - 0.1 * a[i]) or (d == -1 and h[i] > rh + 0.1 * a[i])), None)
        if j is None:
            continue
        # ما نقبلوش إلا ما كان سحب الجهتين
        if any((d == 1 and h[i] > rh + 0.1 * a[i]) or (d == -1 and l[i] < rl - 0.1 * a[i]) for i in range(j, n)):
            continue
        seg = range(j, n)
        e = min(seg, key=lambda i: l[i]) if d == 1 else max(seg, key=lambda i: h[i])
        ext = l[e] if d == 1 else h[e]
        # سلسلة شموع التسليم (عكس d) اللي سالات عند الطرف
        q = e
        while q >= start and not ((c[q] < o[q]) if d == 1 else (c[q] > o[q])):
            q -= 1
        if q < start:
            continue
        s0 = q
        while s0 - 1 >= start and ((c[s0 - 1] < o[s0 - 1]) if d == 1 else (c[s0 - 1] > o[s0 - 1])):
            s0 -= 1
        level = o[s0]
        k = next((i for i in range(max(q, e) + 1, n) if (d == 1 and c[i] > level) or (d == -1 and c[i] < level)), None)
        if k is None or n - 1 - k > 1:
            continue
        price = c[-1]
        risk = (price - ext + 0.3 * a[-1]) if d == 1 else (ext + 0.3 * a[-1] - price)
        dist = (rh - price) if d == 1 else (price - rl)
        if not (0.5 * a[-1] <= risk <= 4 * a[-1]) or dist < 2 * risk:
            continue
        fvg = None
        for i in range(max(e - 1, 0), k):
            if i + 2 <= n - 1:
                if d == 1 and l[i + 2] > h[i]:
                    fvg = (float(h[i]), float(l[i + 2]))
                if d == -1 and h[i + 2] < l[i]:
                    fvg = (float(h[i + 2]), float(l[i]))
        entry2 = price - d * 0.3 * a[-1]
        if fvg:
            mid = (fvg[0] + fvg[1]) / 2
            if d * (price - mid) > 0:
                entry2 = mid
        return {"dir": d, "range": (float(rl), float(rh)), "extreme": float(ext), "cisd": float(level),
                "fvg": fvg, "risk": float(risk), "dist": float(dist), "entry2": float(entry2),
                "targets": [float(price + d * f * dist) for f in ICT_FRACS],
                "sl": float(ext - d * 0.3 * a[-1])}
    return None


# ---------------------------------------------------------------- Crabel: Opening Range Breakout (Stretch)
def crabel_all(df):
    """كيرجع لائحة الصفقات الصالحة (جلسة لندن/نيويورك): كل جلسة فيها اختراق Stretch والستوب ما تضربش وTP ما تضربش.
    كل صفقة كتبقى صالحة حتى الستوب/الـTP ولا آخر الجلسة."""
    n = len(df)
    out_ = []
    if n < 100:
        return out_
    t = pd.to_datetime(df["time"])
    t = t.dt.tz_localize("UTC") if t.dt.tz is None else t.dt.tz_convert("UTC")
    et = t.dt.tz_convert("America/New_York")
    hrs, mins, dates = et.dt.hour.values, et.dt.minute.values, et.dt.date.values
    o, h, l, c = (df[k].values for k in ("open", "high", "low", "close"))
    today = dates[-1]
    for sess in CRABEL_SESSIONS.split(","):
        h0, h1 = (int(x) for x in sess.strip().split("-"))
        if not (h0 <= hrs[-1] < h1):
            continue
        by_day = {}
        for i in np.where((hrs >= h0) & (hrs < h1))[0]:
            by_day.setdefault(dates[i], []).append(i)
        cur = by_day.get(today)
        if not cur or hrs[cur[0]] != h0 or mins[cur[0]] != 0:
            continue
        noise = []
        for d_ in sorted(by_day):
            ix = by_day[d_]
            if d_ >= today or hrs[ix[0]] != h0 or mins[ix[0]] != 0:
                continue
            op_ = o[ix[0]]
            noise.append(min(h[ix].max() - op_, op_ - l[ix].min()))
        if len(noise) < CRABEL_N:
            continue
        stretch = float(np.mean(noise[-CRABEL_N:])) * CRABEL_X
        if stretch <= 0:
            continue
        op = float(o[cur[0]])
        buy, sell = op + stretch, op - stretch
        k = next((i for i in cur if h[i] >= buy or l[i] <= sell), None)
        if k is None:
            continue
        if h[k] >= buy and l[k] <= sell:      # جوج د الأوامر فنفس الشمعة: غامض، كنتخطاو
            continue
        d = 1 if h[k] >= buy else -1
        entry, sl = (buy, sell) if d == 1 else (sell, buy)
        tp = float(entry + d * CRABEL_TP * stretch) if CRABEL_TP > 0 else None
        if any((d == 1 and l[i] <= sl) or (d == -1 and h[i] >= sl) for i in range(k + 1, n)):
            continue                          # الستوب تضرب
        if tp is not None and any((d == 1 and h[i] >= tp) or (d == -1 and l[i] <= tp) for i in range(k + 1, n)):
            continue                          # الـTP تضرب
        out_.append({"dir": d, "session": sess.strip(), "date": str(today), "open": op, "stretch": stretch,
                     "entry": float(entry), "sl": float(sl), "risk": float(abs(entry - sl)), "exit": h1,
                     "tp": tp, "bars_ago": int(n - 1 - k)})
    return out_


def crabel_setup(df):
    """الصفقة الأحدث (آخر اختراق) ولا None"""
    allc = crabel_all(df)
    return min(allc, key=lambda x: x["bars_ago"]) if allc else None


def crabel_result(res, cr):
    """نسخة من النتيجة كتمثل صفقة Crabel وحدة"""
    side, ent = cr["dir"], cr["entry"]
    r = dict(res)
    r.update(decision="trade", side=side, entry=ent, sl=cr["sl"],
             tp1=cr["tp"] if cr["tp"] else ent + side * cr["risk"],
             tp2=cr["tp"] if cr["tp"] else ent + side * 2 * cr["risk"],
             rr=1.0, risk=cr["risk"], entry2=ent, targets=None, crabel=cr)
    return r


# ---------------------------------------------------------------- حركة V كصفقة
def vtrade_setup(df):
    """V صاعد: شراء بعد الرجوع، الستوب تحت القاع، الأهداف نحو بداية النزول. V نازل: العكس."""
    va = v_shape(df)
    if not va:
        return None
    d = va["dir"]
    a = float(df["atr"].iloc[-1])
    price = float(df["close"].iloc[-1])
    ext = va["extreme"]
    start = ext + d * va["drop"]
    risk = abs(price - ext) + 0.3 * a
    dist = d * (start - price)
    if dist <= 0 or dist < V_MIN_RR * risk:
        return None
    return {"dir": d, "entry": price, "sl": float(ext - d * 0.3 * a), "risk": float(risk), "extreme": float(ext),
            "start": float(start), "targets": [float(price + d * f * dist) for f in V_FRACS]}


def vtrade_result(res, vt):
    r = dict(res)
    side, ent = vt["dir"], vt["entry"]
    r.update(decision="trade", side=side, entry=ent, sl=vt["sl"], tp1=vt["targets"][0], tp2=vt["targets"][-1],
             rr=float(abs(vt["targets"][0] - ent) / vt["risk"]), risk=vt["risk"], entry2=float(ent - side * 0.3 * float(res["atr"])),
             targets=vt["targets"], vtrade=vt)
    return r


# ---------------------------------------------------------------- Breakout
def breakout(df, look=20):
    c = df["close"].iloc[-1]
    prev = df.iloc[-look - 1:-1]
    body = abs(df["close"].iloc[-1] - df["open"].iloc[-1])
    strong = body > 0.8 * df["atr"].iloc[-1]
    if c > prev["high"].max() and strong:
        return 1, prev["high"].max()
    if c < prev["low"].min() and strong:
        return -1, prev["low"].min()
    return 0, None


# ---------------------------------------------------------------- Fibonacci / Retracement
def fib_zone(df, pv):
    h = [p for p in pv if p[2] == "H"]
    l = [p for p in pv if p[2] == "L"]
    if not h or not l:
        return None
    ph, pl = h[-1], l[-1]
    if ph[0] > pl[0]:   # موجة صاعدة -> ريتريس نازل
        lo, hi, d = pl[1], ph[1], 1
        zone = (hi - 0.786 * (hi - lo), hi - 0.5 * (hi - lo))
    else:               # موجة نازلة -> ريتريس طالع
        lo, hi, d = pl[1], ph[1], -1
        zone = (lo + 0.5 * (hi - lo), lo + 0.786 * (hi - lo))
    return {"dir": d, "zone": zone, "swing": (lo, hi)}


# ---------------------------------------------------------------- Macro (تضخم / بطالة / الفيدرالي)
def fred(series):
    r = requests.get("https://api.stlouisfed.org/fred/series/observations",
                     params={"series_id": series, "api_key": FRED_KEY, "file_type": "json",
                             "sort_order": "desc", "limit": 20}, timeout=20)
    obs = [float(o["value"]) for o in r.json()["observations"] if o["value"] != "."]
    return obs  # الأحدث أولا


def macro_bias():
    """+ = إيجابي للذهب ، - = سلبي للذهب"""
    notes, score = [], 0.0
    try:
        if FRED_KEY:
            cpi = fred("CPIAUCSL")
            yoy_now = cpi[0] / cpi[12] - 1 if len(cpi) > 12 else None
            yoy_old = cpi[3] / cpi[15] - 1 if len(cpi) > 15 else None
            if yoy_now is not None and yoy_old is not None:
                chg = yoy_now - yoy_old
                notes.append(f"التضخم CPI سنوي: {yoy_now*100:.2f}% ({'طالع' if chg > 0 else 'نازل'})")
                score += -0.5 if chg > 0 else 0.5
            un = fred("UNRATE")
            notes.append(f"البطالة: {un[0]:.1f}% (قبل 3 شهور {un[3]:.1f}%)")
            score += 0.5 if un[0] > un[3] else -0.5   # بطالة طالعة = فيدرالي أرحم = ذهب يستفاد
            ff = fred("FEDFUNDS")
            notes.append(f"فايدة الفيدرالي: {ff[0]:.2f}% (قبل 3 شهور {ff[3]:.2f}%)")
            score += -0.5 if ff[0] > ff[3] else (0.5 if ff[0] < ff[3] else 0)
        else:
            notes.append("ما لقيتش FRED_API_KEY -> تخطيت بيانات التضخم/البطالة/الفايدة")
        for name, tk, sign in (("الدولار DXY", "DX-Y.NYB", -1), ("عائد سندات 10Y", "^TNX", -1)):
            d = yf.download(tk, period="1mo", interval="1d", progress=False)
            if isinstance(d.columns, pd.MultiIndex):
                d.columns = d.columns.get_level_values(0)
            ch = d["Close"].iloc[-1] / d["Close"].iloc[-10] - 1
            notes.append(f"{name}: {ch*100:+.2f}% آخر 10 أيام")
            score += sign * np.sign(ch) * 0.5
    except Exception as e:
        notes.append(f"خطأ في بيانات الماكرو: {e}")
    return max(-2, min(2, score)), notes


def news_blocked(now=None):
    now = now if now is not None else pd.Timestamp.now(tz="UTC")
    for t in NEWS_BLACKOUT:
        ts = pd.Timestamp(t, tz="UTC")
        if abs((now - ts).total_seconds()) < 3600 * 1.0:
            return t
    return None


def in_trade_hours(df):
    """وقت القرار = سدان آخر شمعة. كيتحسب من الشمعة (ماشي من الساعة الحالية) باش الـ backtest يوافق الحي"""
    if TRADE_HOURS_ET.strip().lower() in ("", "off", "0"):
        return True
    a, b = (int(x) for x in TRADE_HOURS_ET.split("-"))
    t = pd.Timestamp(df["time"].iloc[-1])
    t = t.tz_localize("UTC") if t.tzinfo is None else t
    h = (t + TF_DELTA[ENTRY_TF]).tz_convert("America/New_York").hour
    return a <= h <= b


# ---------------------------------------------------------------- القرار
def _evaluate(df, dd, macro=0.0, macro_notes=None, verbose=True, now=None):
    """منطق القرار لوحدو (بلا تحميل بيانات). كيستعملو البوت الحي والـ backtest."""
    out = print if verbose else (lambda *args, **kwargs: None)
    macro_notes = macro_notes or []
    price, a = df["close"].iloc[-1], df["atr"].iloc[-1]

    d_trend, _, _ = market_structure(dd)
    trend, bos, pv = market_structure(df)
    zones = sr_zones(df, pv)
    sup, resi = nearest_zones(zones, price)
    fvgs = find_fvg(df)
    sweep = find_sweep(df, pv)
    bo, bo_lvl = breakout(df)
    vs = v_shape(df) if VSHAPE else None
    fib = fib_zone(df, pv)

    score, why, items = 0.0, [], []

    def add(v, txt):
        nonlocal score
        score += v
        why.append(f"{v:+.1f}  {txt}")
        items.append((float(v), txt))

    add(2 * d_trend, f"هيكل الفريم اليومي: {['نازل','محايد','صاعد'][d_trend+1]}")
    add(1 * trend, f"هيكل فريم {ENTRY_TF}: {['نازل','محايد','صاعد'][trend+1]}")
    if bos:
        add(1 * bos, f"BOS {'صاعد' if bos > 0 else 'نازل'}")
    if sweep:
        good = sweep["verdict"].startswith("حقيقي")
        add(2 * sweep["dir"] if good else 0,
            f"سحب سيولة {'تحت قاع' if sweep['dir']==1 else 'فوق قمة'} {sweep['level']:.1f} قبل {sweep['bars_ago']} شمعة -> {sweep['verdict']}")
    if vs:
        add(2 * vs["dir"], f"حركة V {'صاعدة' if vs['dir'] > 0 else 'نازلة'}: {vs['drop']:.1f} نقطة ثم رجوع {vs['reb']:.1f} فـ {vs['bars_ago']} شموع (القاع/القمة {vs['extreme']:.1f})")
    for lo, hi, d in fvgs[-3:]:
        if lo - 0.3 * a <= price <= hi + 0.3 * a:
            add(1 * d, f"السعر داخل/قريب FVG {'صاعد' if d>0 else 'نازل'} [{lo:.1f}-{hi:.1f}]")
            break
    if bo:
        add(1 * bo, f"اختراق مؤكد ديال {bo_lvl:.1f}")
    if sup and price - sup[1] < 0.7 * a:
        add(1, f"السعر فوق دعم [{sup[0]:.1f}-{sup[1]:.1f}] (لمسات {sup[2]})")
    if resi and resi[0] - price < 0.7 * a:
        add(-1, f"السعر تحت مقاومة [{resi[0]:.1f}-{resi[1]:.1f}] (لمسات {resi[2]})")
    if fib and fib["zone"][0] <= price <= fib["zone"][1]:
        add(1 * fib["dir"], f"السعر فمنطقة ريتريس 0.5-0.786 [{fib['zone'][0]:.1f}-{fib['zone'][1]:.1f}]")
    add(macro, "الماكرو (تضخم/بطالة/فيدرالي/دولار/عوائد)")

    out("=" * 60)
    out(f"الذهب ({SYMBOL})  السعر: {price:.2f}   ATR: {a:.2f}")
    out("=" * 60)
    for w in why:
        out(w)
    out("-" * 60)
    for n in macro_notes:
        out("•", n)
    out("-" * 60)
    out(f"مجموع النقاط: {score:+.1f}  (الحد الأدنى: شراء +{MIN_SCORE} | بيع -{MIN_SCORE + SELL_EXTRA})")

    try:  # وقت سدان آخر شمعة (UTC) = وقت الإشارة
        t_close = pd.Timestamp(df["time"].iloc[-1])
        t_close = (t_close.tz_localize("UTC") if t_close.tzinfo is None else t_close.tz_convert("UTC")) + TF_DELTA[ENTRY_TF]
        bar_close = t_close.isoformat()
    except Exception:
        bar_close = None
    res = {"v_alert": v_shape(df), "bar_close": bar_close, "price": float(price), "atr": float(a), "score": float(score), "min_score": MIN_SCORE,
           "items": items, "macro_notes": macro_notes, "decision": "wait", "side": None}
    if CRABEL and CRABEL_ONLY:   # Crabel بوحدو: بلا فلتر أخبار ولا ساعات ولا سكور
        crs = crabel_all(df)
        if crs:
            cr = min(crs, key=lambda x: x["bars_ago"])
            out(f"✅ [Crabel] {'BUY' if cr['dir'] == 1 else 'SELL'} @ {cr['entry']:.2f}  Stop {cr['sl']:.2f}  (جلسة {cr['session']}, Open {cr['open']:.2f}, Stretch {cr['stretch']:.2f})")
            res = crabel_result(res, cr)
            res["crabel_all"] = crs
            return res
        out("⏸  Crabel: ما كاينش اختراق Stretch.")
        return res
    blocked = news_blocked(now)
    if blocked:
        out(f"⛔ خبر قوي قريب ({blocked} UTC) -> ما كاينش دخول دابا.")
        res.update(decision="blocked", blocked=blocked)
        return res
    need = MIN_SCORE + (SELL_EXTRA if score < 0 else 0)
    if not in_trade_hours(df):
        out(f"⏸  خارج ساعات التداول ({TRADE_HOURS_ET} نيويورك) -> ما كاينش دخول دابا.")
        res.update(decision="off_hours")
        return res
    if VTRADE and VTRADE_ONLY:
        vt = vtrade_setup(df)
        if vt:
            out(f"✅ [V] {'BUY' if vt['dir'] == 1 else 'SELL'} @ {vt['entry']:.2f}  Stop {vt['sl']:.2f}  Targets {[round(x, 2) for x in vt['targets']]}")
            return vtrade_result(res, vt)
        out("⏸  V: ما كاينش حركة V صالحة.")
        return res
    if ICT:
        ict = ict_setup(df)
        if ict and ICT_HTF and d_trend == -ict["dir"]:
            out("⏸  ICT: ضد الاتجاه اليومي -> تخطيت.")
            ict = None
        if ict:
            side = ict["dir"]
            out(f"✅ [ICT] {'BUY' if side == 1 else 'SELL'} @ {price:.2f}  Stop {ict['sl']:.2f}  Targets {[round(x, 2) for x in ict['targets']]}")
            res.update(decision="trade", side=side, entry=float(price), sl=ict["sl"], tp1=ict["targets"][0],
                       tp2=ict["targets"][-1], rr=float(abs(ict["targets"][0] - price) / ict["risk"]),
                       risk=ict["risk"], entry2=ict["entry2"], targets=ict["targets"], ict=ict)
            return res
        if ICT_ONLY:
            out("⏸  ICT: ما كاينش setup (رينج -> سحب -> CISD).")
            return res
    if abs(score) < need:
        out("⏸  القرار: ما كاينش setup واضح. استنى.")
        return res

    side = 1 if score > 0 else -1
    if STYLE == "scalp":
        risk = SCALP_STOP_ATR * a
        sl = price - side * risk
        tg = [price + side * k * a for k in SCALP_TARGETS]
        out(f"✅ [scalp] {'BUY' if side==1 else 'SELL'} @ {price:.2f}  Stop {sl:.2f}  Targets {[round(t,2) for t in tg]}")
        res.update(decision="trade", side=side, entry=float(price), sl=float(sl), tp1=float(tg[0]),
                   tp2=float(tg[-1]), rr=float(abs(tg[0] - price) / risk), risk=float(risk),
                   entry2=float(price - side * 0.5 * a), targets=[float(t) for t in tg])
        return res
    # Stop Loss
    swing_lows = [p[1] for p in pv if p[2] == "L" and p[1] < price][-2:]
    swing_highs = [p[1] for p in pv if p[2] == "H" and p[1] > price][-2:]
    if side == 1:
        base = [x for x in swing_lows]
        if sweep and sweep["dir"] == 1:
            base.append(sweep["extreme"])
        sl = (min(base) if base else price - 1.5 * a) - 0.3 * a
        risk = price - sl
    else:
        base = [x for x in swing_highs]
        if sweep and sweep["dir"] == -1:
            base.append(sweep["extreme"])
        sl = (max(base) if base else price + 1.5 * a) + 0.3 * a
        risk = sl - price
    risk = min(max(risk, 0.8 * a), 3 * a)
    sl = price - side * risk
    tp1 = price + side * 2 * risk
    tp3 = price + side * 3 * risk
    target_zone = resi if side == 1 else sup
    if target_zone:
        tz = target_zone[0] if side == 1 else target_zone[1]
        if 1.5 * risk <= side * (tz - price) <= 2 * risk:  # ما نخليوش TP1 يفوت TP2
            tp1 = tz
    rr = abs(tp1 - price) / risk
    if rr < MIN_RR:
        out(f"⏸  RR ضعيف ({rr:.2f}) -> ما ندخلش.")
        res.update(decision="weak_rr", rr=float(rr))
        return res

    out(f"✅ القرار: {'BUY (شراء)' if side==1 else 'SELL (بيع)'}")
    out(f"   دخول  : {price:.2f}  (ولا ريتريس لـ {price - side*0.3*a:.2f})")
    out(f"   Stop  : {sl:.2f}   (مخاطرة {risk:.2f} نقطة)")
    out(f"   TP1   : {tp1:.2f}  (RR {rr:.2f}) -> سكّر النص وحرّك الستوب لنقطة الدخول")
    out(f"   TP2   : {tp3:.2f}  (RR 3.0)")
    out("   خاطر 0.5%-1% كحد أقصى من الحساب فكل صفقة.")
    res.update(decision="trade", side=side, entry=float(price), sl=float(sl), tp1=float(tp1),
               tp2=float(tp3), rr=float(rr), risk=float(risk),
               entry2=float(price - side * 0.3 * a))
    return res


def evaluate(df, dd, macro=0.0, macro_notes=None, verbose=True, now=None):
    res = _evaluate(df, dd, macro, macro_notes, verbose, now)
    if CRABEL and not CRABEL_ONLY:   # Crabel كيخدم بجنب البوت الأول، ماكيبدل والو فقراره
        res["crabel_all"] = crabel_all(df)
    if VTRADE and not VTRADE_ONLY and not news_blocked(now) and in_trade_hours(df):   # V كصفقة بجنب البوت الأول (نفس الساعات)
        res["vtrade_setup"] = vtrade_setup(df)
    return res


def analyze():
    df = get_data(ENTRY_TF, "59d" if ENTRY_TF == "15m" else "60d")
    dd = get_data(HTF, "1y")
    macro, macro_notes = macro_bias()
    return evaluate(df, dd, macro, macro_notes)


if __name__ == "__main__":
    try:
        analyze()
    except Exception as exc:
        print("خطأ:", exc)
        sys.exit(1)

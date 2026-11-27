//+------------------------------------------------------------------+
//| ClaudeSwingEA.mq5 - Claude Swing أوتوماتيك + تعدد الدخول (1h)      |
//| نفس منطق البوت: Donchian 20/10 + فلتر اتجاه EMA50/200 + ستوب      |
//| 2×ATR20 + هدف TP_R × المخاطرة. كيخدم غير على الشموع المسدودة.      |
//| حطو على شارت XAUUSD فريم H1. جربو ديمو أولاً. ما كاينش ضمان ربح.  |
//+------------------------------------------------------------------+
#property strict
#include <Trade/Trade.mqh>

input double Lots        = 0.01;   // لوت ثابت (إلا RiskPercent = 0)
input double RiskPercent = 0.0;    // إلا > 0: اللوت كيتحسب باش الخسارة فالستوب = هاد % من الرصيد
input double MaxLots     = 0.10;   // سقف اللوت
input int    N           = 20;     // قناة الدخول
input int    X           = 10;     // قناة الخروج
input int    AtrN        = 20;
input double StopATR     = 2.0;    // الستوب = StopATR × ATR
input double TP_R        = 0.0;    // هدف للصفقة الأولى = TP_R × المخاطرة (0 = بلا هدف: أحسن فالباكتيست مع تعدد الدخول)
input int    MaxUnits    = 2;      // أقصى عدد صفقات فنفس الاتجاه (1 = بلا تعدد). حساب Hedging خاصو
input double AddATR      = 0.5;    // نزيد صفقة ملي السعر يمشي هاد المرة × ATR من آخر دخول
input double MaxSpread   = 0.60;   // ما ندخلش إلا السبريد (دولار) كبر
input ulong  Magic       = 770022;

CTrade trade;
int hEma50, hEma200, hAtr;
datetime lastBar = 0;

int OnInit()
{
   trade.SetExpertMagicNumber(Magic);
   hEma50  = iMA(_Symbol, PERIOD_H1, 50,  0, MODE_EMA, PRICE_CLOSE);
   hEma200 = iMA(_Symbol, PERIOD_H1, 200, 0, MODE_EMA, PRICE_CLOSE);
   hAtr    = iATR(_Symbol, PERIOD_H1, AtrN);
   if(hEma50 == INVALID_HANDLE || hEma200 == INVALID_HANDLE || hAtr == INVALID_HANDLE) return INIT_FAILED;
   if(Period() != PERIOD_H1) Print("تنبيه: حطو الـEA على فريم H1");
   return INIT_SUCCEEDED;
}

int Units(long &type, double &lastOpen, double &firstOpen, double &firstSl)
{
   int n = 0; datetime tFirst = D'2099.01.01', tLast = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(PositionGetSymbol(i) != _Symbol || PositionGetInteger(POSITION_MAGIC) != (long)Magic) continue;
      n++; type = PositionGetInteger(POSITION_TYPE);
      datetime t = (datetime)PositionGetInteger(POSITION_TIME);
      if(t < tFirst) { tFirst = t; firstOpen = PositionGetDouble(POSITION_PRICE_OPEN); firstSl = PositionGetDouble(POSITION_SL); }
      if(t >= tLast) { tLast = t; lastOpen = PositionGetDouble(POSITION_PRICE_OPEN); }
   }
   return n;
}

void CloseAll()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(PositionGetSymbol(i) == _Symbol && PositionGetInteger(POSITION_MAGIC) == (long)Magic)
         trade.PositionClose(PositionGetInteger(POSITION_TICKET));
}

double HighestHigh(int from, int cnt) { double v = -1e18; for(int i = from; i < from + cnt; i++) v = MathMax(v, iHigh(_Symbol, PERIOD_H1, i)); return v; }
double LowestLow(int from, int cnt)   { double v =  1e18; for(int i = from; i < from + cnt; i++) v = MathMin(v, iLow(_Symbol, PERIOD_H1, i));  return v; }

double CalcLots(double risk)   // risk = مسافة الستوب بالسعر
{
   double l = Lots;
   if(RiskPercent > 0)
   {
      double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE), ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
      if(tv > 0 && ts > 0 && risk > 0)
         l = AccountInfoDouble(ACCOUNT_BALANCE) * RiskPercent / 100.0 / (risk / ts * tv);
   }
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP), mn = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   l = MathMin(MathMax(l, mn), MathMin(MaxLots, SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX)));
   return MathFloor(l / step) * step;
}

void OnTick()
{
   datetime bar = iTime(_Symbol, PERIOD_H1, 0);
   if(bar == lastBar) return;      // مرة وحدة فكل ساعة جديدة (الشمعة 1 هي آخر مسدودة)
   lastBar = bar;

   double e50[1], e200[1], a[1];
   if(CopyBuffer(hEma50, 0, 1, 1, e50) != 1 || CopyBuffer(hEma200, 0, 1, 1, e200) != 1 || CopyBuffer(hAtr, 0, 1, 1, a) != 1) return;
   double c = iClose(_Symbol, PERIOD_H1, 1);
   if(Bars(_Symbol, PERIOD_H1) < 260) return;

   long type = -1; double lastOpen = 0, firstOpen = 0, firstSl = 0;
   int n = Units(type, lastOpen, firstOpen, firstSl);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK), bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(n > 0)
   {   // خروج بالقناة: إغلاق كل الصفقات. الستوب (والهدف) عند الوسيط.
      if(type == POSITION_TYPE_BUY  && c < LowestLow(2, X))  { CloseAll(); return; }
      if(type == POSITION_TYPE_SELL && c > HighestHigh(2, X)) { CloseAll(); return; }
      // تعدد الدخول: نزيد صفقة ملي السعر يتقدم AddATR×ATR من آخر دخول
      double atr0 = MathAbs(firstOpen - firstSl) / StopATR;
      if(n < MaxUnits && atr0 > 0 && ask - bid <= MaxSpread)
      {
         double risk = StopATR * atr0;
         if(type == POSITION_TYPE_BUY && c - lastOpen >= AddATR * atr0)
            trade.Buy(CalcLots(risk), _Symbol, ask, NormalizeDouble(ask - risk, _Digits), 0, "ClaudeSwing+");
         if(type == POSITION_TYPE_SELL && lastOpen - c >= AddATR * atr0)
            trade.Sell(CalcLots(risk), _Symbol, bid, NormalizeDouble(bid + risk, _Digits), 0, "ClaudeSwing+");
      }
      return;
   }

   if(ask - bid > MaxSpread) return;

   bool up = c > e200[0] && e50[0] > e200[0];
   bool dn = c < e200[0] && e50[0] < e200[0];
   double risk = StopATR * a[0];

   if(up && c > HighestHigh(2, N))
   {
      double sl = NormalizeDouble(ask - risk, _Digits);
      double tp = TP_R > 0 ? NormalizeDouble(ask + risk * TP_R, _Digits) : 0;
      trade.Buy(CalcLots(risk), _Symbol, ask, sl, tp, "ClaudeSwing");
   }
   else if(dn && c < LowestLow(2, N))
   {
      double sl = NormalizeDouble(bid + risk, _Digits);
      double tp = TP_R > 0 ? NormalizeDouble(bid - risk * TP_R, _Digits) : 0;
      trade.Sell(CalcLots(risk), _Symbol, bid, sl, tp, "ClaudeSwing");
   }
}
//+------------------------------------------------------------------+

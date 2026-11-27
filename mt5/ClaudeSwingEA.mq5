//+------------------------------------------------------------------+
//| ClaudeSwingEA.mq5 - Claude Swing أوتوماتيك (شراء + بيع، فريم 1h)   |
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
input double TP_R        = 1.0;    // الهدف = TP_R × المخاطرة (0 = بلا هدف، خروج بالقناة غير)
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

bool GetPos(long &type, ulong &ticket)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(PositionGetSymbol(i) == _Symbol && PositionGetInteger(POSITION_MAGIC) == (long)Magic)
      { type = PositionGetInteger(POSITION_TYPE); ticket = PositionGetInteger(POSITION_TICKET); return true; }
   return false;
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

   long type; ulong tk;
   if(GetPos(type, tk))
   {   // خروج بالقناة: إغلاق تحت أدنى X شموع (شراء) / فوق أعلى X شموع (بيع). الستوب والهدف عند الوسيط.
      if(type == POSITION_TYPE_BUY  && c < LowestLow(2, X))  trade.PositionClose(tk);
      if(type == POSITION_TYPE_SELL && c > HighestHigh(2, X)) trade.PositionClose(tk);
      return;
   }

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK), bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
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

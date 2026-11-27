//+------------------------------------------------------------------+
//| StraddleScalper.mq5 - سكالب بأوامر معلقة (Buy Stop + Sell Stop)   |
//| فكرة: من بعد حركة سريعة فشمعة 1د، كنحطو أمر شراء فوق وأمر بيع    |
//| تحت السعر. اللي تنفذ كيبقى، والآخر كيتمسح. ستوب وهدف صغار.      |
//| تجريبي: جربو على حساب ديمو و0.01 لوت قبل أي شي.                  |
//| ما كاينش ضمان ربح. السبريد والانزلاق (slippage) كيقتلو هاد النوع. |
//+------------------------------------------------------------------+
#property strict
#include <Trade/Trade.mqh>

input double Lots           = 0.01;   // الحجم
input double SpikeATRx      = 1.5;    // شمعة 1د مسدودة مدى ديالها >= هاد المرة × ATR(14) = حركة سريعة
input double EntryOffset    = 0.30;   // البعد ديال الأوامر على السعر (بالدولار)
input double StopLoss       = 1.50;   // الستوب (دولار)
input double TakeProfit     = 1.50;   // الهدف (دولار)
input double BreakEvenAt    = 0.80;   // بعد هاد الربح نحركو الستوب للدخول (0 = طفي)
input int    PendingMinutes = 3;      // الأوامر كتتمسح من بعد هاد الدقايق
input double MaxSpread      = 0.40;   // ما نخدموش إلا السبريد (دولار) كبر من هادشي
input int    MaxTradesDay   = 40;     // أقصى صفقات فاليوم
input int    StartHour      = 0;      // ساعة البداية (وقت السيرفر)
input int    EndHour        = 24;     // ساعة النهاية (وقت السيرفر)
input ulong  Magic          = 990011;

CTrade trade;
int    atrH;
datetime lastBar = 0;
int    tradesToday = 0;
int    dayOfYear = -1;

int OnInit()
{
   trade.SetExpertMagicNumber(Magic);
   atrH = iATR(_Symbol, PERIOD_M1, 14);
   return(atrH == INVALID_HANDLE ? INIT_FAILED : INIT_SUCCEEDED);
}

bool HasPosition()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(PositionGetSymbol(i) == _Symbol && PositionGetInteger(POSITION_MAGIC) == (long)Magic) return true;
   return false;
}

int PendingCount()
{
   int n = 0;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong t = OrderGetTicket(i);
      if(OrderSelect(t) && OrderGetString(ORDER_SYMBOL) == _Symbol && OrderGetInteger(ORDER_MAGIC) == (long)Magic) n++;
   }
   return n;
}

void DeletePending()
{
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong t = OrderGetTicket(i);
      if(OrderSelect(t) && OrderGetString(ORDER_SYMBOL) == _Symbol && OrderGetInteger(ORDER_MAGIC) == (long)Magic)
         trade.OrderDelete(t);
   }
}

void ManageBreakEven()
{
   if(BreakEvenAt <= 0) return;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(PositionGetSymbol(i) != _Symbol || PositionGetInteger(POSITION_MAGIC) != (long)Magic) continue;
      double op = PositionGetDouble(POSITION_PRICE_OPEN), sl = PositionGetDouble(POSITION_SL), tp = PositionGetDouble(POSITION_TP);
      bool buy = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY;
      double px = buy ? SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double prof = buy ? px - op : op - px;
      bool already = buy ? sl >= op : (sl > 0 && sl <= op);
      if(prof >= BreakEvenAt && !already)
         trade.PositionModify(PositionGetInteger(POSITION_TICKET), NormalizeDouble(op, _Digits), tp);
   }
}

void OnTick()
{
   ManageBreakEven();

   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   if(dt.day_of_year != dayOfYear) { dayOfYear = dt.day_of_year; tradesToday = 0; }

   // إلا تنفذ أمر: نمسحو الأمر الآخر
   if(HasPosition() && PendingCount() > 0) { DeletePending(); tradesToday++; return; }
   if(HasPosition()) return;

   // نمسحو الأوامر القديمة
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong t = OrderGetTicket(i);
      if(OrderSelect(t) && OrderGetString(ORDER_SYMBOL) == _Symbol && OrderGetInteger(ORDER_MAGIC) == (long)Magic
         && TimeCurrent() - (datetime)OrderGetInteger(ORDER_TIME_SETUP) > PendingMinutes * 60)
         trade.OrderDelete(t);
   }

   datetime bar = iTime(_Symbol, PERIOD_M1, 0);
   if(bar == lastBar) return;          // مرة وحدة فكل شمعة 1د جديدة
   lastBar = bar;

   if(PendingCount() > 0 || tradesToday >= MaxTradesDay) return;
   if(dt.hour < StartHour || dt.hour >= EndHour) return;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK), bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(ask - bid > MaxSpread) return;

   double a[1];
   if(CopyBuffer(atrH, 0, 1, 1, a) != 1 || a[0] <= 0) return;
   double range = iHigh(_Symbol, PERIOD_M1, 1) - iLow(_Symbol, PERIOD_M1, 1);   // آخر شمعة مسدودة
   if(range < SpikeATRx * a[0]) return;

   double buyP  = NormalizeDouble(ask + EntryOffset, _Digits);
   double sellP = NormalizeDouble(bid - EntryOffset, _Digits);
   datetime exp = TimeCurrent() + PendingMinutes * 60;
   trade.BuyStop(Lots,  buyP,  _Symbol, NormalizeDouble(buyP - StopLoss, _Digits),  NormalizeDouble(buyP + TakeProfit, _Digits),  ORDER_TIME_SPECIFIED, exp, "straddle");
   trade.SellStop(Lots, sellP, _Symbol, NormalizeDouble(sellP + StopLoss, _Digits), NormalizeDouble(sellP - TakeProfit, _Digits), ORDER_TIME_SPECIFIED, exp, "straddle");
}
//+------------------------------------------------------------------+

import requests, pandas as pd
tests = {
 "stooq15": "https://stooq.com/q/d/l/?s=xauusd&i=15",
 "binance": "https://api.binance.com/api/v3/klines?symbol=PAXGUSDT&interval=15m&limit=3",
 "binance_us": "https://api.binance.us/api/v3/klines?symbol=PAXGUSDT&interval=15m&limit=3",
 "okx": "https://www.okx.com/api/v5/market/candles?instId=XAUT-USDT&bar=15m&limit=3",
 "bybit": "https://api.bybit.com/v5/market/kline?category=spot&symbol=XAUTUSDT&interval=15&limit=3",
 "kraken": "https://api.kraken.com/0/public/OHLC?pair=PAXGUSD&interval=15",
 "coinbase": "https://api.exchange.coinbase.com/products/PAXG-USD/candles?granularity=900",
}
for k, u in tests.items():
    try:
        r = requests.get(u, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        print("T", k, r.status_code, r.text[:260].replace("\n", " | "))
    except Exception as e:
        print("T", k, "err", type(e).__name__)

import ccxt
import pandas as pd
import pandas_ta as ta
import asyncio
import time
import os
from datetime import datetime
from telegram import Bot

# Railway Variables üzerinden bilgileri çeker
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
EXCHANGE_ID = 'mexc' 

class CryptoBot:
    def __init__(self):
        self.exchange = getattr(ccxt, EXCHANGE_ID)({
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        self.bot = Bot(token=TELEGRAM_TOKEN)

    async def get_data(self, symbol, timeframe):
        try:
            # Veri Çekme
            ohlcv = await asyncio.to_thread(self.exchange.fetch_ohlcv, symbol, timeframe, limit=100)
            df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
            
            # İndikatörler
            df['ema50'] = ta.ema(df['close'], length=50)
            df['ema200'] = ta.ema(df['close'], length=200)
            df['rsi'] = ta.rsi(df['close'], length=14)
            macd = ta.macd(df['close'])
            df['macd'] = macd['MACD_12_26_9']
            df['macd_s'] = macd['MACDs_12_26_9']
            
            return df
        except Exception as e:
            return None

    def calculate_targets(self, side, price):
        # %2 Kar Al, %1 Zarar Durdur (Kaldıraçsız oranlar)
        if side == "LONG":
            tp = price * 1.02
            sl = price * 0.99
        else:
            tp = price * 0.98
            sl = price * 1.01
        return round(tp, 6), round(sl, 6)

    async def check_signals(self):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Tarama başlatıldı...")
        try:
            markets = await asyncio.to_thread(self.exchange.load_markets)
            symbols = [s for s in markets if '/USDT' in s][:50] # İlk 50 hacimli coin

            for symbol in symbols:
                df_5m = await self.get_data(symbol, '5m')
                df_1h = await self.get_data(symbol, '1h')

                if df_5m is None or df_1h is None or len(df_5m) < 50: continue

                l5 = df_5m.iloc[-1]
                l1 = df_1h.iloc[-1]

                # Güvenlik Kontrolü (NoneType hatasını önler)
                if pd.isna(l5['rsi']) or pd.isna(l5['ema200']): continue

                side = None
                # LONG: 1H Trend Yukarı + 5M RSI 50-60 arası + MACD Kesişimi
                if l1['ema50'] > l1['ema200'] and l5['ema50'] > l5['ema200']:
                    if 45 < l5['rsi'] < 60 and l5['macd'] > l5['macd_s']:
                        side = "LONG"

                # SHORT: 1H Trend Aşağı + 5M RSI 40-50 arası + MACD Kesişimi
                elif l1['ema50'] < l1['ema200'] and l5['ema50'] < l5['ema200']:
                    if 40 < l5['rsi'] < 55 and l5['macd'] < l5['macd_s']:
                        side = "SHORT"

                if side:
                    tp, sl = self.calculate_targets(side, l5['close'])
                    msg = (f"🚀 **YENİ SİNYAL: {symbol}**\n"
                           f"🔹 **Yön:** {side}\n"
                           f"💰 **Giriş:** {l5['close']}\n"
                           f"🎯 **Hedef (TP):** {tp}\n"
                           f"🚫 **Stop (SL):** {sl}\n"
                           f"⏰ **Zaman:** {datetime.now().strftime('%H:%M')}")
                    await self.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')
                    print(f"✅ Sinyal gönderildi: {symbol}")
                    await asyncio.sleep(1) # Telegram spam engeli

        except Exception as e:
            print(f"❌ Döngü hatası: {e}")

    async def main(self):
        print("🤖 Bot MEXC üzerinde başlatıldı (TP/SL Aktif)...")
        while True:
            await self.check_signals()
            print("😴 Tarama bitti. 5 dakika bekleniyor...")
            await asyncio.sleep(300)

if __name__ == "__main__":
    asyncio.run(CryptoBot().main())
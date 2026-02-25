import ccxt
import pandas as pd
import pandas_ta as ta
import asyncio
import time
import os
import csv
from datetime import datetime
from telegram import Bot

# Railway Variables üzerinden bilgileri çeker
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
EXCHANGE_ID = 'mexc' # MEXC veya Gate.io için değiştirilebilir

class CryptoBot:
    def __init__(self):
        self.exchange = getattr(ccxt, EXCHANGE_ID)({
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        self.bot = Bot(token=TELEGRAM_TOKEN)
        self.daily_signal_count = 0
        self.last_reset_date = datetime.now().date()

    async def get_data(self, symbol, timeframe):
        try:
            # Veri Çekme
            ohlcv = await asyncio.to_thread(self.exchange.fetch_ohlcv, symbol, timeframe, limit=200)
            df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
            
            # İndikatör Hesaplamaları
            df['ema9'] = ta.ema(df['close'], length=9)
            df['ema50'] = ta.ema(df['close'], length=50)
            df['ema200'] = ta.ema(df['close'], length=200)
            df['rsi'] = ta.rsi(df['close'], length=14)
            df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
            df['vol_avg'] = ta.sma(df['volume'], length=20)
            
            macd = ta.macd(df['close'])
            df['macd'] = macd['MACD_12_26_9']
            df['macd_s'] = macd['MACDs_12_26_9']
            
            return df
        except Exception as e:
            return None

    def check_strategy(self, df_5m, df_1h):
        l_5m = df_5m.iloc[-1]
        l_1h = df_1h.iloc[-1]
        
        # Trend Onayı
        trend_up = l_1h['ema50'] > l_1h['ema200']
        trend_down = l_1h['ema50'] < l_1h['ema200']

        # LONG Şartları
        long_cond = (
            trend_up and l_5m['ema50'] > l_5m['ema200'] and
            45 <= l_5m['rsi'] <= 60 and l_5m['macd'] > l_5m['macd_s'] and
            l_5m['volume'] > l_5m['vol_avg']
        )

        # SHORT Şartları
        short_cond = (
            trend_down and l_5m['ema50'] < l_5m['ema200'] and
            40 <= l_5m['rsi'] <= 55 and l_5m['macd'] < l_5m['macd_s'] and
            l_5m['volume'] > l_5m['vol_avg']
        )

        if long_cond: return "LONG"
        if short_cond: return "SHORT"
        return None

    async def send_signal(self, data):
        msg = (
            f"━━━━━━━━━━━━━━━\n"
            f"🚀 **YENİ SİNYAL: {data['symbol']}**\n"
            f"📈 Yön: {data['side']}\n"
            f"🎯 Giriş: {data['entry']:.5f}\n"
            f"🏆 TP1: {data['tp1']:.5f} | TP2: {data['tp2']:.5f}\n"
            f"🛑 Stop Loss: {data['sl']:.5f}\n"
            f"📊 RSI: {data['rsi']:.1f}\n"
            f"⚖ Risk/Reward: 1:2.0\n"
            f"━━━━━━━━━━━━━━━"
        )
        try:
            await self.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')
            print(f"✅ Telegram sinyali gönderildi: {data['symbol']}")
        except Exception as e:
            print(f"❌ Mesaj hatası: {e}")

    async def run(self):
        print(f"🤖 Bot {EXCHANGE_ID.upper()} üzerinde başlatıldı...")
        while True:
            try:
                # Günlük sıfırlama
                if datetime.now().date() > self.last_reset_date:
                    self.daily_signal_count = 0
                    self.last_reset_date = datetime.now().date()

                # Marketleri al (Top 50 USDT-Perp)
                markets = await asyncio.to_thread(self.exchange.fetch_markets)
                symbols = [m['symbol'] for m in markets if m['active'] and m['linear']][:50]

                for symbol in symbols:
                    if self.daily_signal_count >= 6: break

                    df_5m = await self.get_data(symbol, '5m')
                    df_1h = await self.get_data(symbol, '1h')
                    
                    if df_5m is None or df_1h is None: continue

                    side = self.check_strategy(df_5m, df_1h)
                    
                    if side:
                        entry = df_5m['close'].iloc[-1]
                        atr = df_5m['atr'].iloc[-1]
                        sl_dist = atr * 1.5
                        
                        data = {
                            'symbol': symbol.split(':')[0],
                            'side': side,
                            'entry': entry,
                            'sl': entry - sl_dist if side == "LONG" else entry + sl_dist,
                            'tp1': entry + sl_dist if side == "LONG" else entry - sl_dist,
                            'tp2': entry + (sl_dist * 2) if side == "LONG" else entry - (sl_dist * 2),
                            'rsi': df_5m['rsi'].iloc[-1]
                        }
                        
                        await self.send_signal(data)
                        self.daily_signal_count += 1
                        await asyncio.sleep(2) # Spam koruması

                print(f"Tarama bitti. 5 dakika bekleniyor... ({datetime.now().strftime('%H:%M:%S')})")
                await asyncio.sleep(300)

            except Exception as e:
                print(f"Döngü hatası: {e}")
                await asyncio.sleep(60)

if __name__ == "__main__":
    bot = CryptoBot()
    asyncio.run(bot.run())
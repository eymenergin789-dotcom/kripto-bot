import ccxt
import pandas as pd
import asyncio
import time
import os
import requests
from datetime import datetime

# --- AYARLAR (Railway Değişkenlerinden Alır) ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
EXCHANGE = ccxt.mexc({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

VOL_THRESHOLD = 500000    # 24s Hacmi 500k USDT altı olanları taramaz
VOL_MULTIPLIER = 2.5      # Hacim, son 20 mumun ortalamasından 2.5 kat büyük olmalı
TP_PERCENT = 0.012        # %1.2 Kar Al
SL_PERCENT = 0.007        # %0.7 Zarar Durdur

import requests
import os

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_msg(message):
    if not TELEGRAM_TOKEN:
        print("HATA: TELEGRAM_TOKEN boş!")
        return

    if not TELEGRAM_CHAT_ID:
        print("HATA: TELEGRAM_CHAT_ID boş!")
        return

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

        payload = {
            "chat_id": int(TELEGRAM_CHAT_ID),   # int yapıyoruz garanti olsun
            "text": message,
            "parse_mode": "Markdown"
        }

        response = requests.post(url, json=payload, timeout=10)

        # Telegram cevabını log'a yaz
        print("Telegram Status Code:", response.status_code)
        print("Telegram Response:", response.text)

        # Eğer Telegram hata dönerse
        if response.status_code != 200:
            print("Telegram mesaj gönderilemedi!")

    except requests.exceptions.RequestException as e:
        print("Bağlantı Hatası:", e)

    except Exception as e:
        print("Genel Hata:", e)
        
def fiyat_format(fiyat):
    if fiyat < 0.0001: return f"{fiyat:.8f}"
    if fiyat < 1: return f"{fiyat:.6f}"
    return f"{fiyat:.4f}"

def performans_kontrol(df):
    success = 0
    trades = 0
    for i in range(20, len(df) - 30):
        v_spike = df['v'].iloc[i] > (df['v'].iloc[i-10:i].mean() * 1.5)
        if v_spike and df['c'].iloc[i] < df['c'].iloc[i-1]:
            entry = df['c'].iloc[i]
            tp, sl = entry * (1 + TP_PERCENT), entry * (1 - SL_PERCENT)
            trades += 1
            for j in range(i + 1, len(df)):
                if df['h'].iloc[j] >= tp: 
                    success += 1
                    break
                if df['l'].iloc[j] <= sl: 
                    break
        if trades >= 10: break 
    return success, trades

async def main():
    print("🎯 SNIPER ELITE v2.0 Başlatıldı...")
    send_telegram_msg("🎯 *SNIPER ELITE v2.0 Aktif!* \nStrateji: Hacim Patlaması + Başarı Karne Kontrolü")
    
    while True:
        try:
            markets = EXCHANGE.load_markets()
            tickers = EXCHANGE.fetch_tickers()
            pariteler = [s for s, d in tickers.items() if ':USDT' in s and d['quoteVolume'] > VOL_THRESHOLD]
            
            for s in pariteler[:100]: # İlk 100 hacimli parite
                try:
                    bars = EXCHANGE.fetch_ohlcv(s, timeframe='1m', limit=100) 
                    df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
                    avg_v = df['v'].rolling(window=20).mean().iloc[-1]
                    last, prev = df.iloc[-1], df.iloc[-2]

                    side = None
                    if last['v'] > (avg_v * VOL_MULTIPLIER):
                        if last['c'] < prev['c']: side = "LONG"
                        elif last['c'] > prev['c']: side = "SHORT"

                    if side:
                        tp_count, total_count = performans_kontrol(df)
                        # Başarı şartı: 10 işlemde en az 7 başarı (veya elindeki veriye göre)
                        if total_count >= 5 and tp_count >= 3:
                            p_s = fiyat_format(last['c'])
                            raw_tp = last['c']*(1+TP_PERCENT) if side == "LONG" else last['c']*(1-TP_PERCENT)
                            raw_sl = last['c']*(1-SL_PERCENT) if side == "LONG" else last['c']*(1+SL_PERCENT)
                            
                            emoji = "🚀" if side == "LONG" else "📉"
                            basari_yuzdesi = int((tp_count / total_count) * 100)
                            
                            tg_msg = (
                                f"🎯 *SNIPER SİNYAL ONAYLANDI*\n\n"
                                f"{emoji} *Parite:* {s}\n"
                                f"⚖️ *Yön:* {side}\n"
                                f"💰 *Giriş:* {p_s}\n"
                                f"━━━━━━━━━━━━━━━\n"
                                f"✅ *HEDEF (TP):* {fiyat_format(raw_tp)}\n"
                                f"❌ *STOP (SL):* {fiyat_format(raw_sl)}\n"
                                f"━━━━━━━━━━━━━━━\n"
                                f"📊 *Geçmiş Başarı:* %{basari_yuzdesi} ({tp_count}/{total_count})"
                            )
                            send_telegram_msg(tg_msg)
                            print(f"✅ Sinyal Gönderildi: {s}")
                            await asyncio.sleep(2) # Spam engeli
                except:
                    continue
            
            print("😴 Tarama tamamlandı, 1 dakika bekleniyor...")
            await asyncio.sleep(60) # 1 dakikada bir tara ( Sniper olduğu için daha hızlı)
            
        except Exception as e:
            print(f"Hata: {e}")
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())
async def main():
    print("🎯 SNIPER ELITE v2.0 Başlatıldı...")
    # BU TEST SATIRINI EKLE:
    send_telegram_msg("✅ Bot başarıyla bağlandı! Piyasayı tarıyorum...")








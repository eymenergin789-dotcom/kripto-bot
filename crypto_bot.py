import ccxt
import pandas as pd
import asyncio
import time
import os
import requests
from datetime import datetime

# --- AYARLAR ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
EXCHANGE = ccxt.mexc({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

VOL_THRESHOLD = 500000    
VOL_MULTIPLIER = 2.5      
TP_PERCENT = 0.005        
SL_PERCENT = 0.003        

# --- GLOBAL TAKİP DEĞİŞKENLERİ ---
aktif_islemler = {} # { 'BTC/USDT:USDT': {'side': 'LONG', 'entry': 50000, 'tp': 51000, 'sl': 49500} }
gunluk_stats = {"tp": 0, "sl": 0, "tarih": datetime.now().strftime("%Y-%m-%d")}

def send_telegram_msg(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("HATA: Telegram ayarları eksik!")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": int(TELEGRAM_CHAT_ID), "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Hatası: {e}")

def fiyat_format(fiyat):
    if fiyat < 0.0001: return f"{fiyat:.8f}"
    if fiyat < 1: return f"{fiyat:.6f}"
    return f"{fiyat:.4f}"

def performans_kontrol(df):
    success, trades = 0, 0
    for i in range(20, len(df) - 30):
        v_spike = df['v'].iloc[i] > (df['v'].iloc[i-10:i].mean() * 1.5)
        if v_spike:
            entry = df['c'].iloc[i]
            tp, sl = entry * (1 + TP_PERCENT), entry * (1 - SL_PERCENT)
            trades += 1
            for j in range(i + 1, len(df)):
                if df['h'].iloc[j] >= tp: 
                    success += 1
                    break
                if df['l'].iloc[j] <= sl: break
        if trades >= 10: break 
    return success, trades

async def takip_sistemi():
    """Aktif işlemleri anlık takip eder ve sonuçları bildirir."""
    global gunluk_stats
    while True:
        try:
            # Günlük istatistik sıfırlama (Gece yarısı)
            bugun = datetime.now().strftime("%Y-%m-%d")
            if bugun != gunluk_stats["tarih"]:
                report = f"📅 *GÜNLÜK RAPOR ({gunluk_stats['tarih']})*\n✅ Toplam TP: {gunluk_stats['tp']}\n❌ Toplam SL: {gunluk_stats['sl']}"
                send_telegram_msg(report)
                gunluk_stats = {"tp": 0, "sl": 0, "tarih": bugun}

            if not aktif_islemler:
                await asyncio.sleep(10)
                continue

            tickers = EXCHANGE.fetch_tickers(list(aktif_islemler.keys()))
            
            for sembol in list(aktif_islemler.keys()):
                islem = aktif_islemler[sembol]
                current_price = tickers[sembol]['last']
                
                tp_hit = (islem['side'] == "LONG" and current_price >= islem['tp']) or \
                         (islem['side'] == "SHORT" and current_price <= islem['tp'])
                
                sl_hit = (islem['side'] == "LONG" and current_price <= islem['sl']) or \
                         (islem['side'] == "SHORT" and current_price >= islem['sl'])

                if tp_hit:
                    gunluk_stats["tp"] += 1
                    msg = f"✅ *PROFIT (TP) ONAYLANDI!*\n💰 {sembol}\nFiyat: {fiyat_format(current_price)}\n📊 Günlük: {gunluk_stats['tp']} TP / {gunluk_stats['sl']} SL"
                    send_telegram_msg(msg)
                    del aktif_islemler[sembol]
                
                elif sl_hit:
                    gunluk_stats["sl"] += 1
                    msg = f"❌ *STOP LOSS (SL) OLDU!*\n📉 {sembol}\nFiyat: {fiyat_format(current_price)}\n📊 Günlük: {gunluk_stats['tp']} TP / {gunluk_stats['sl']} SL"
                    send_telegram_msg(msg)
                    del aktif_islemler[sembol]

            await asyncio.sleep(5) # 5 saniyede bir fiyat kontrolü
        except Exception as e:
            print(f"Takip Hatası: {e}")
            await asyncio.sleep(10)
async def tarama_dongusu():
    print("🎯 EYMEN ELITE Taramayı Başlattı...")
    send_telegram_msg("🚀 *Bot Aktif!* Piyasalar taranıyor ve işlemler takip ediliyor...")
    
    while True:
        try:
            print("🔍 Marketler yükleniyor...")
            EXCHANGE.load_markets()
            tickers = EXCHANGE.fetch_tickers()
            
            # Sadece vadeli (swap) ve USDT çiftlerini filtrele
            pariteler = [s for s, d in tickers.items() if ':USDT' in s and d['quoteVolume'] > VOL_THRESHOLD]
            print(f"📈 Kriterlere uyan {len(pariteler)} parite bulundu. İlk 100 taranıyor...")

            counter = 0
            for s in pariteler[:100]:
                if s in aktif_islemler: continue 

                try:
                    # Rate limit dostu küçük bir bekleme
                    await asyncio.sleep(0.1) 
                    
                    bars = EXCHANGE.fetch_ohlcv(s, timeframe='1m', limit=100) 
                    if not bars: continue
                    
                    df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
                    avg_v = df['v'].rolling(window=20).mean().iloc[-1]
                    last, prev = df.iloc[-1], df.iloc[-2]

                    side = None
                    if last['v'] > (avg_v * VOL_MULTIPLIER):
                        if last['c'] < prev['c']: side = "LONG"
                        elif last['c'] > prev['c']: side = "SHORT"

                    if side:
                        tp_count, total_count = performans_kontrol(df)
                        if total_count >= 5 and tp_count >= 3:
                            raw_tp = last['c']*(1+TP_PERCENT) if side == "LONG" else last['c']*(1-TP_PERCENT)
                            raw_sl = last['c']*(1-SL_PERCENT) if side == "LONG" else last['c']*(1+SL_PERCENT)
                            
                            aktif_islemler[s] = {'side': side, 'tp': raw_tp, 'sl': raw_sl, 'entry': last['c']}
                            
                            emoji = "🚀" if side == "LONG" else "📉"
                            basari_yuzdesi = int((tp_count / total_count) * 100)
                            
                            tg_msg = (
                                f"🎯 *YENİ SİNYAL*\n\n"
                                f"{emoji} *Parite:* {s}\n"
                                f"⚖️ *Yön:* {side}\n"
                                f"💰 *Giriş:* {fiyat_format(last['c'])}\n"
                                f"━━━━━━━━━━━━━━━\n"
                                f"✅ *HEDEF (TP):* {fiyat_format(raw_tp)}\n"
                                f"❌ *STOP (SL):* {fiyat_format(raw_sl)}\n"
                                f"📊 *Geçmiş Başarı:* %{basari_yuzdesi}"
                            )
                            send_telegram_msg(tg_msg)
                            print(f"\n✅ SİNYAL: {s} ({side})")
                    
                    counter += 1
                    if counter % 10 == 0:
                        print(f"🔄 {counter}/100 parite tarandı...")

                except Exception as e:
                    # Tekil parite hatası döngüyü bozmasın
                    continue
            
            print("😴 Tarama bitti. 1 dakika bekleniyor...")
            await asyncio.sleep(60)
            
        except Exception as e:
            print(f"🚨 Ana Tarama Hatası: {e}")
            await asyncio.sleep(10)


async def main():
    # Tarama ve Takip işlemlerini aynı anda (parallel) çalıştırır
    await asyncio.gather(tarama_dongusu(), takip_sistemi())

if __name__ == "__main__":
    asyncio.run(main())
        
        




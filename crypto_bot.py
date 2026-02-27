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
TP_PERCENT = 0.02        
SL_PERCENT = 0.01        

# --- GLOBAL TAKİP DEĞİŞKENLERİ ---
aktif_islemler = {} 
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

# --- YENİ: TAKİP SİSTEMİ ---
async def takip_sistemi():
    global gunluk_stats
    print("🛠 Takip Sistemi Başlatıldı...")
    while True:
        try:
            # Tarih değiştiyse istatistiği sıfırla ve rapor ver
            bugun = datetime.now().strftime("%Y-%m-%d")
            if bugun != gunluk_stats["tarih"]:
                msg = f"📅 *GÜNLÜK ÖZET ({gunluk_stats['tarih']})*\n✅ TP: {gunluk_stats['tp']}\n❌ SL: {gunluk_stats['sl']}"
                send_telegram_msg(msg)
                gunluk_stats = {"tp": 0, "sl": 0, "tarih": bugun}

            if aktif_islemler:
                semboller = list(aktif_islemler.keys())
                # Sadece takipteki paritelerin fiyatını çek
                tickers = EXCHANGE.fetch_tickers(semboller)
                
                for s in semboller:
                    if s not in tickers: continue
                    curr_price = tickers[s]['last']
                    islem = aktif_islemler[s]
                    
                    tp_oldu = (islem['side'] == "LONG" and curr_price >= islem['tp']) or \
                              (islem['side'] == "SHORT" and curr_price <= islem['tp'])
                    sl_oldu = (islem['side'] == "LONG" and curr_price <= islem['sl']) or \
                              (islem['side'] == "SHORT" and curr_price >= islem['sl'])

                    if tp_oldu:
                        gunluk_stats["tp"] += 1
                        send_telegram_msg(f"✅ *TP HEDEFİNE ULAŞILDI!*\n💰 *Parite:* {s}\n💵 *Fiyat:* {fiyat_format(curr_price)}\n📊 *Skor:* {gunluk_stats['tp']} TP / {gunluk_stats['sl']} SL")
                        aktif_islemler.pop(s)
                    elif sl_oldu:
                        gunluk_stats["sl"] += 1
                        send_telegram_msg(f"❌ *STOP-LOSS OLDU*\n📉 *Parite:* {s}\n💵 *Fiyat:* {fiyat_format(curr_price)}\n📊 *Skor:* {gunluk_stats['tp']} TP / {gunluk_stats['sl']} SL")
                        aktif_islemler.pop(s)
            
            await asyncio.sleep(2) # Takip hızı 2 saniye
        except Exception as e:
            print(f"Takip Hatası: {e}")
            await asyncio.sleep(5)

# --- ANA TARAMA DÖNGÜSÜ ---
async def tarama_dongusu():
    print("🎯 EYMEN ELITE Taramayı Başlattı...")
    send_telegram_msg("🚀 *Bot Başarıyla Bağlandı!* Piyasayı tarıyorum...")
    
    while True:
        try:
            print("🔍 Marketler yükleniyor...")
            EXCHANGE.load_markets()
            tickers = EXCHANGE.fetch_tickers()
            pariteler = [s for s, d in tickers.items() if ':USDT' in s and d['quoteVolume'] > VOL_THRESHOLD]
            print(f"📈 Kriterlere uyan {len(pariteler)} parite bulundu. İlk 100 taranıyor...")

            for s in pariteler[:100]:
                if s in aktif_islemler: continue # Zaten takipteyse atla
                try:
                    await asyncio.sleep(0.1) # Rate limit koruması
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
                        if total_count >= 5 and tp_count >= 3:
                            raw_tp = last['c']*(1+TP_PERCENT) if side == "LONG" else last['c']*(1-TP_PERCENT)
                            raw_sl = last['c']*(1-SL_PERCENT) if side == "LONG" else last['c']*(1+SL_PERCENT)
                            
                            # Takibe ekle
                            aktif_islemler[s] = {'side': side, 'tp': raw_tp, 'sl': raw_sl}
                            
                            emoji = "🚀" if side == "LONG" else "📉"
                            tg_msg = (
                                f"🎯 *YENİ SNIPER SİNYALİ*\n\n"
                                f"{emoji} *Parite:* {s}\n"
                                f"⚖️ *Yön:* {side}\n"
                                f"💰 *Giriş:* {fiyat_format(last['c'])}\n"
                                f"━━━━━━━━━━━━━━━\n"
                                f"✅ *HEDEF (TP):* {fiyat_format(raw_tp)}\n"
                                f"❌ *STOP (SL):* {fiyat_format(raw_sl)}\n"
                                f"📊 *Geçmiş Başarı:* %{int((tp_count / total_count) * 100)}"
                            )
                            send_telegram_msg(tg_msg)
                            print(f"✅ SİNYAL: {s} ({side})")
                except:
                    continue
            
            print("😴 Tarama bitti. 1 dakika bekleniyor...")
            await asyncio.sleep(60)
        except Exception as e:
            print(f"Tarama Hatası: {e}")
            await asyncio.sleep(10)

# --- BOTU BAŞLAT ---
async def main():
    # İkisini aynı anda çalıştırır
    await asyncio.gather(
        tarama_dongusu(),
        takip_sistemi()
    )

if __name__ == "__main__":
    asyncio.run(main())

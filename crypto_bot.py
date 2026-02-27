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

VOL_THRESHOLD = 50000     # Filtreyi iyice açtım, küçük hacimli ama hareketli pariteler gelsin
VOL_MULTIPLIER = 1.2      # Normalden biraz fazla hacim yeterli (Sinyal yağmuruna hazır ol)
TP_PERCENT = 0.02        
SL_PERCENT = 0.01        

# --- GLOBAL TAKİP DEĞİŞKENLERİ ---
aktif_islemler = {} 
gunluk_stats = {"tp": 0, "sl": 0, "tarih": datetime.now().strftime("%Y-%m-%d")}

def send_telegram_msg(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": int(TELEGRAM_CHAT_ID), "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=10)
    except: pass

def fiyat_format(fiyat):
    if fiyat < 0.0001: return f"{fiyat:.8f}"
    if fiyat < 1: return f"{fiyat:.6f}"
    return f"{fiyat:.4f}"

# --- TAKİP SİSTEMİ (TP/SL HABERCİSİ) ---
async def takip_sistemi():
    global gunluk_stats
    print("🛠 Takip Sistemi ve Gün Sonu Raporu Aktif.")
    while True:
        try:
            simdi = datetime.now()
            bugun_tarih = simdi.strftime("%Y-%m-%d")

            # Gün Sonu Raporu (00:00'da)
            if bugun_tarih != gunluk_stats["tarih"]:
                toplam = gunluk_stats['tp'] + gunluk_stats['sl']
                msg = f"📊 *GÜN SONU RAPORU*\n✅ TP: {gunluk_stats['tp']}\n❌ SL: {gunluk_stats['sl']}\n📈 Toplam İşlem: {toplam}"
                send_telegram_msg(msg)
                gunluk_stats = {"tp": 0, "sl": 0, "tarih": bugun_tarih}

            # TP/SL Kontrolü
            if aktif_islemler:
                tickers = EXCHANGE.fetch_tickers(list(aktif_islemler.keys()))
                for s in list(aktif_islemler.keys()):
                    if s not in tickers: continue
                    curr_price = tickers[s]['last']
                    islem = aktif_islemler[s]
                    
                    tp_hit = (islem['side'] == "LONG" and curr_price >= islem['tp']) or \
                             (islem['side'] == "SHORT" and curr_price <= islem['tp'])
                    sl_hit = (islem['side'] == "LONG" and curr_price <= islem['sl']) or \
                             (islem['side'] == "SHORT" and curr_price >= islem['sl'])

                    if tp_hit:
                        gunluk_stats["tp"] += 1
                        send_telegram_msg(f"✅ *KÂR ALINDI (TP)!*\n💰 *Parite:* {s}\n📊 *Günlük Skor:* {gunluk_stats['tp']} TP / {gunluk_stats['sl']} SL")
                        aktif_islemler.pop(s)
                    elif sl_hit:
                        gunluk_stats["sl"] += 1
                        send_telegram_msg(f"❌ *STOP OLDU (SL)*\n📉 *Parite:* {s}\n📊 *Günlük Skor:* {gunluk_stats['tp']} TP / {gunluk_stats['sl']} SL")
                        aktif_islemler.pop(s)
            
            await asyncio.sleep(2) # 2 saniyede bir fiyat kontrol et (Çok hızlı)
        except: await asyncio.sleep(5)

# --- TARAMA DÖNGÜSÜ (HIZLI MOD) ---
async def tarama_dongusu():
    print("🎯 SNIPER ELITE v2.3 Başlatıldı...")
    send_telegram_msg("🚀 *Bot v2.3 Aktif!* \nHızlı tarama ve anlık TP/SL habercisi devrede.")
    
    while True:
        try:
            EXCHANGE.load_markets()
            tickers = EXCHANGE.fetch_tickers()
            pariteler = [s for s, d in tickers.items() if ':USDT' in s and d['quoteVolume'] > VOL_THRESHOLD]
            
            for s in pariteler[:100]:
                if s in aktif_islemler: continue
                try:
                    await asyncio.sleep(0.05)
                    bars = EXCHANGE.fetch_ohlcv(s, timeframe='1m', limit=50) 
                    df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
                    avg_v = df['v'].rolling(window=10).mean().iloc[-1]
                    last, prev = df.iloc[-1], df.iloc[-2]

                    if last['v'] > (avg_v * VOL_MULTIPLIER):
                        side = "LONG" if last['c'] < prev['c'] else "SHORT"
                        
                        raw_tp = last['c']*(1+TP_PERCENT) if side == "LONG" else last['c']*(1-TP_PERCENT)
                        raw_sl = last['c']*(1-SL_PERCENT) if side == "LONG" else last['c']*(1+SL_PERCENT)
                        
                        # Takip listesine ekle
                        aktif_islemler[s] = {'side': side, 'tp': raw_tp, 'sl': raw_sl}
                        
                        # Giriş Sinyali Gönder
                        emoji = "🚀" if side == "LONG" else "📉"
                        send_telegram_msg(f"{emoji} *YENİ SİNYAL: {s}*\n⚖️ Yön: {side}\n💰 Giriş: {fiyat_format(last['c'])}\n🎯 Hedef: {fiyat_format(raw_tp)}")
                except: continue
            await asyncio.sleep(30)
        except: await asyncio.sleep(10)

async def main():
    await asyncio.gather(tarama_dongusu(), takip_sistemi())

if __name__ == "__main__":
    asyncio.run(main())

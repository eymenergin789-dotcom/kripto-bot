import ccxt
import pandas as pd
import asyncio
import os
import requests
from datetime import datetime
import pandas_ta as ta

# --- AYARLAR ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
EXCHANGE = ccxt.mexc({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

VOL_THRESHOLD = 500000    
VOL_MULTIPLIER = 3.0      
TP_PERCENT = 0.025        
SL_PERCENT = 0.015        

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

# --- TAKİP VE DETAYLI RAPORLAMA ---
async def takip_sistemi():
    global gunluk_stats
    while True:
        try:
            simdi = datetime.now()
            if simdi.strftime("%Y-%m-%d") != gunluk_stats["tarih"]:
                toplam = gunluk_stats['tp'] + gunluk_stats['sl']
                send_telegram_msg(f"📊 *GÜN SONU ÖZETİ*\n✅ TP: {gunluk_stats['tp']}\n❌ SL: {gunluk_stats['sl']}")
                gunluk_stats = {"tp": 0, "sl": 0, "tarih": simdi.strftime("%Y-%m-%d")}

            if aktif_islemler:
                tickers = EXCHANGE.fetch_tickers(list(aktif_islemler.keys()))
                for s in list(aktif_islemler.keys()):
                    if s not in tickers: continue
                    curr_price = tickers[s]['last']
                    islem = aktif_islemler[s]
                    
                    tp_hit = (islem['side'] == "LONG" and curr_price >= islem['tp']) or (islem['side'] == "SHORT" and curr_price <= islem['tp'])
                    sl_hit = (islem['side'] == "LONG" and curr_price <= islem['sl']) or (islem['side'] == "SHORT" and curr_price >= islem['sl'])

                    if tp_hit or sl_hit:
                        durum = "✅ KÂR ALINDI (TP)" if tp_hit else "❌ STOP OLUNDU (SL)"
                        if tp_hit: gunluk_stats["tp"] += 1
                        else: gunluk_stats["sl"] += 1
                        
                        # Yüzdelik Değişim Hesaplama
                        degisim = ((curr_price - islem['entry']) / islem['entry']) * 100
                        if islem['side'] == "SHORT": degisim = -degisim
                        
                        saat = datetime.now().strftime("%H:%M:%S")
                        
                        rapor_msg = (
                            f"{durum}\n"
                            f"━━━━━━━━━━━━━━━\n"
                            f"Parite: {s}\n"
                            f"Yön: {islem['side']}\n"
                            f"Giriş Fiyatı: {fiyat_format(islem['entry'])}\n"
                            f"Çıkış Fiyatı: {fiyat_format(curr_price)}\n"
                            f"Net Sonuç: %{degisim:.2f}\n"
                            f"Saat: {saat}\n"
                            f"━━━━━━━━━━━━━━━\n"
                            f"📊 Günlük Skor: {gunluk_stats['tp']} TP / {gunluk_stats['sl']} SL"
                        )
                        send_telegram_msg(rapor_msg)
                        aktif_islemler.pop(s)
            await asyncio.sleep(2)
        except: await asyncio.sleep(5)

async def tarama_dongusu():
    send_telegram_msg("🎯 *Sniper v2.5 Başlatıldı.*\nDetaylı raporlama ve RSI filtresi aktif.")
    while True:
        try:
            EXCHANGE.load_markets()
            tickers = EXCHANGE.fetch_tickers()
            pariteler = [s for s, d in tickers.items() if ':USDT' in s and d['quoteVolume'] > VOL_THRESHOLD]
            
            for s in pariteler[:100]:
                if s in aktif_islemler: continue
                try:
                    await asyncio.sleep(0.05)
                    bars = EXCHANGE.fetch_ohlcv(s, timeframe='1m', limit=100) 
                    df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
                    avg_v = df['v'].rolling(window=20).mean().iloc[-1]
                    rsi = ta.rsi(df['c'], length=14).iloc[-1]
                    last, prev = df.iloc[-1], df.iloc[-2]

                    if last['v'] > (avg_v * VOL_MULTIPLIER):
                        side = None
                        if last['c'] > prev['c'] and 45 < rsi < 65: side = "LONG"
                        elif last['c'] < prev['c'] and 35 < rsi < 55: side = "SHORT"

                        if side:
                            raw_tp = last['c']*(1+TP_PERCENT) if side == "LONG" else last['c']*(1-TP_PERCENT)
                            raw_sl = last['c']*(1-SL_PERCENT) if side == "LONG" else last['c']*(1+SL_PERCENT)
                            
                            aktif_islemler[s] = {
                                'side': side, 
                                'entry': last['c'], 
                                'tp': raw_tp, 
                                'sl': raw_sl
                            }
                            
                            send_telegram_msg(f"🚀 *SİNYAL:* {s}\nYön: {side}\nGiriş: {fiyat_format(last['c'])}\nRSI: {int(rsi)}")
                except: continue
            await asyncio.sleep(60)
        except: await asyncio.sleep(10)

async def main():
    await asyncio.gather(tarama_dongusu(), takip_sistemi())

if __name__ == "__main__":
    asyncio.run(main())

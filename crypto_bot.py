import ccxt
import pandas as pd
import asyncio
import os
import requests
from datetime import datetime, timedelta

# --- AYARLAR ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
EXCHANGE = ccxt.mexc({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

# MANUEL SAAT AYARI (Kazakistan GMT+5)
def get_kazak_time():
    # Sunucu saati üzerine 5 saat ekleyerek Kazakistan vaktini bulur
    return datetime.utcnow() + timedelta(hours=5)

VOL_THRESHOLD = 500000    
VOL_MULTIPLIER = 3.5      
SL_PERCENT = 0.03       

aktif_islemler = {} 
gunluk_stats = {"tp": 0, "sl": 0, "tarih": get_kazak_time().strftime("%Y-%m-%d")}

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

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs.iloc[-1]))

# --- TAKİP SİSTEMİ ---
async def takip_sistemi():
    global gunluk_stats
    print(f"[{get_kazak_time().strftime('%H:%M:%S')}] ✅ Takip Sistemi ve Manuel GMT+5 Ayarı Aktif.")
    while True:
        try:
            simdi = get_kazak_time()
            if simdi.strftime("%Y-%m-%d") != gunluk_stats["tarih"]:
                send_telegram_msg(f"📊 *GÜN SONU ÖZETİ*\n✅ TP: {gunluk_stats['tp']}\n❌ SL: {gunluk_stats['sl']}")
                gunluk_stats = {"tp": 0, "sl": 0, "tarih": simdi.strftime("%Y-%m-%d")}

            if aktif_islemler:
                tickers = EXCHANGE.fetch_tickers(list(aktif_islemler.keys()))
                for s in list(aktif_islemler.keys()):
                    if s not in tickers: continue
                    curr_price = tickers[s]['last']
                    islem = aktif_islemler[s]
                    
                    tp_hit = (islem['side'] == "LONG" and curr_price >= islem['tp_targets'][0]) or \
                             (islem['side'] == "SHORT" and curr_price <= islem['tp_targets'][0])
                    sl_hit = (islem['side'] == "LONG" and curr_price <= islem['sl']) or \
                             (islem['side'] == "SHORT" and curr_price >= islem['sl'])

                    if tp_hit or sl_hit:
                        if tp_hit: gunluk_stats["tp"] += 1
                        else: gunluk_stats["sl"] += 1
                        
                        degisim = ((curr_price - islem['entry']) / islem['entry']) * 100
                        if islem['side'] == "SHORT": degisim = -degisim
                        
                        rapor = (
                            f"{'✅ *HEDEF GÖRÜLDÜ (TP)*' if tp_hit else '❌ *STOP OLUNDU (SL)*'}\n"
                            f"━━━━━━━━━━━━━━━\n"
                            f"🪙 *Coin:* #{s.replace(':USDT', '')}\n"
                            f"💰 *Çıkış:* {fiyat_format(curr_price)}\n"
                            f"📈 *Net:* %{degisim:.2f}\n"
                            f"⏰ *Saat:* {simdi.strftime('%H:%M:%S')}\n"
                            f"📊 *Günlük:* {gunluk_stats['tp']} TP / {gunluk_stats['sl']} SL"
                        )
                        send_telegram_msg(rapor)
                        print(f"[{simdi.strftime('%H:%M:%S')}] 🔔 İşlem Kapandı: {s}")
                        aktif_islemler.pop(s)
            await asyncio.sleep(2)
        except: await asyncio.sleep(5)

# --- TARAMA DÖNGÜSÜ ---
async def tarama_dongusu():
    print(f"[{get_kazak_time().strftime('%H:%M:%S')}] 🚀 Sniper v3.0 Başlatıldı.")
    send_telegram_msg("🎯 *Sniper v3.0 Aktif!* \nSaat dilimi manuel GMT+5 olarak düzeltildi.")
    
    while True:
        try:
            print(f"[{get_kazak_time().strftime('%H:%M:%S')}] 🔍 Marketler taranıyor...")
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
                    rsi_val = calculate_rsi(df['c'])
                    last, prev = df.iloc[-1], df.iloc[-2]

                    if last['v'] > (avg_v * VOL_MULTIPLIER):
                        side = None
                        if last['c'] > prev['c'] and 45 < rsi_val < 65: side = "LONG"
                        elif last['c'] < prev['c'] and 35 < rsi_val < 55: side = "SHORT"

                        if side:
                            entry = last['c']
                            mult = 1 if side == "LONG" else -1
                            targets = [entry * (1 + (mult * p)) for p in [0.005, 0.01, 0.015, 0.02]]
                            sl = entry * (1 - (mult * SL_PERCENT))
                            
                            aktif_islemler[s] = {'side': side, 'entry': entry, 'tp_targets': targets, 'sl': sl}
                            
                            sinyal_msg = (
                                f"📊 *Coin:* #{s.replace(':USDT', '')} USDT\n"
                                f"{'📈' if side == 'LONG' else '📉'} *Yön:* {side}\n\n"
                                f"🔸 *Fiyat:* {fiyat_format(entry)}\n\n"
                                f"🎯 *TP1:* {fiyat_format(targets[0])}\n"
                                f"🎯 *TP2:* {fiyat_format(targets[1])}\n"
                                f"🎯 *TP3:* {fiyat_format(targets[2])}\n"
                                f"🎯 *TP4:* {fiyat_format(targets[3])}\n"
                                f"⛔️ *Stop:* {fiyat_format(sl)}\n\n"
                                f"📱 *RSI:* {int(rsi_val)}\n"
                                f"⏰ *Saat:* {get_kazak_time().strftime('%H:%M:%S')}"
                            )
                            send_telegram_msg(sinyal_msg)
                            print(f"[{get_kazak_time().strftime('%H:%M:%S')}] 🎯 Sinyal: {s}")
                except: continue
            
            print(f"[{get_kazak_time().strftime('%H:%M:%S')}] 😴 Beklemede...")
            await asyncio.sleep(60)
        except: await asyncio.sleep(10)

async def main():
    await asyncio.gather(tarama_dongusu(), takip_sistemi())

if __name__ == "__main__":
    asyncio.run(main())

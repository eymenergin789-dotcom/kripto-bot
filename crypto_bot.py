import ccxt
import pandas as pd
import asyncio
import os
import requests
import datetime
datetime.datetime.now(datetime.UTC)

# --- AYARLAR ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
EXCHANGE = ccxt.mexc({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

LEVERAGE = 20           
TEST_AMOUNT = 100       

def get_kazak_time():
    return datetime.utcnow() + timedelta(hours=5)

VOL_THRESHOLD = 500000    
VOL_MULTIPLIER = 3.5      
SL_PERCENT = 0.06      

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

# --- TAKİP SİSTEMİ (Kademeli & Zengin Raporlama) ---
async def takip_sistemi():
    global gunluk_stats
    while True:
        try:
            simdi = get_kazak_time()
            if aktif_islemler:
                tickers = EXCHANGE.fetch_tickers(list(aktif_islemler.keys()))
                for s in list(aktif_islemler.keys()):
                    if s not in tickers: continue
                    curr_price = tickers[s]['last']
                    islem = aktif_islemler[s]
                    
                    # Hedef Kontrolü (TP1, TP2, TP3)
                    for i in range(3): # İlk 3 hedef için ara rapor
                        tp_no = i + 1
                        target = islem['tp_targets'][i]
                        if tp_no not in islem['reached_tps']:
                            hit = (islem['side'] == "LONG" and curr_price >= target) or \
                                  (islem['side'] == "SHORT" and curr_price <= target)
                            if hit:
                                islem['reached_tps'].append(tp_no)
                                gunluk_stats["tp"] += 1
                                raw_degisim = ((curr_price - islem['entry']) / islem['entry'])
                                if islem['side'] == "SHORT": raw_degisim = -raw_degisim
                                k_yuzde = raw_degisim * LEVERAGE * 100
                                d_kazanc = (TEST_AMOUNT * raw_degisim * LEVERAGE)

                                msg = (
                                    f"🎯 *HEDEF {tp_no} VURULDU!* 🔥\n"
                                    f"━━━━━━━━━━━━━━━\n"
                                    f"🪙 *Coin:* #{s.replace(':USDT', '')}\n"
                                    f"📥 *Giriş:* {fiyat_format(islem['entry'])}\n"
                                    f"🏁 *Anlık:* {fiyat_format(curr_price)}\n"
                                    f"📈 *Kâr:* %{k_yuzde:.2f} ({d_kazanc:+.2f}$)\n"
                                    f"⚡ *Kaldıraç:* {LEVERAGE}x\n"
                                    f"🛰 *Durum:* Takip Sürüyor..."
                                )
                                send_telegram_msg(msg)

                    # Final Kontrol (TP4 veya Stop)
                    sl_hit = (islem['side'] == "LONG" and curr_price <= islem['sl']) or \
                             (islem['side'] == "SHORT" and curr_price >= islem['sl'])
                    tp4_target = islem['tp_targets'][3]
                    tp4_hit = (islem['side'] == "LONG" and curr_price >= tp4_target) or \
                              (islem['side'] == "SHORT" and curr_price <= tp4_target)

                    if sl_hit or tp4_hit:
                        if sl_hit:
                            header = "❌ *STOP OLUNDU (SL)*"
                            gunluk_stats["sl"] += 1
                        else:
                            header = "💀 *TÜM HEDEFLER İMHA EDİLDİ* 💀\n🏁 *OPERASYON TAMAMLANDI*"
                            gunluk_stats["tp"] += 1
                        
                        raw_degisim = ((curr_price - islem['entry']) / islem['entry'])
                        if islem['side'] == "SHORT": raw_degisim = -raw_degisim
                        k_yuzde = raw_degisim * LEVERAGE * 100
                        d_kazanc = (TEST_AMOUNT * raw_degisim * LEVERAGE)

                        rapor = (
                            f"{header}\n"
                            f"━━━━━━━━━━━━━━━\n"
                            f"🪙 *Coin:* #{s.replace(':USDT', '')}\n"
                            f"⚖️ *Yön:* {islem['side']}\n"
                            f"📥 *Giriş:* {fiyat_format(islem['entry'])}\n"
                            f"🏁 *Final:* {fiyat_format(curr_price)}\n"
                            f"⚡ *Kaldıraç:* {LEVERAGE}x\n"
                            f"📈 *Net:* %{k_yuzde:.2f} ({d_kazanc:+.2f}$)\n"
                            f"⏰ *Saat:* {simdi.strftime('%H:%M:%S')}\n"
                            f"📊 *Günlük Skor:* {gunluk_stats['tp']} TP / {gunluk_stats['sl']} SL"
                        )
                        send_telegram_msg(rapor)
                        aktif_islemler.pop(s)
            await asyncio.sleep(2)
        except: await asyncio.sleep(5)

# --- TARAMA DÖNGÜSÜ (Zengin Giriş Mesajı) ---
async def tarama_dongusu():
    send_telegram_msg("🚀 *Sniper Eymen Ava Başladı")
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
                            aktif_islemler[s] = {'side': side, 'entry': entry, 'tp_targets': targets, 'sl': sl, 'reached_tps': []}
                            
                            sinyal_msg = (
                                f"📊 *Coin:* #{s.replace(':USDT', '')} USDT\n"
                                f"{'📈' if side == 'LONG' else '📉'} *Yön:* {side}\n"
                                f"⚡ *Kaldıraç:* {LEVERAGE}x\n\n"
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
                except: continue
            await asyncio.sleep(60)
        except: await asyncio.sleep(10)

async def main():
    await asyncio.gather(tarama_dongusu(), takip_sistemi())

if __name__ == "__main__":
    asyncio.run(main())




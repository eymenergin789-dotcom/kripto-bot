import pandas as pd
import threading
import time
import requests
from datetime import datetime
import ccxt  # Bunu ekledim, senin kodda eksik olabilir

# --- KASA VE RİSK AYARLARI ---
TOTAL_WALLET = 400
RISK_PER_TRADE = 0.02
DEFAULT_LEVERAGE = 20

# --- STRATEJİ AYARLARI ---
EXCHANGE = ccxt.mexc({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
VOL_THRESHOLD = 3000000
VOL_MULTIPLIER = 2.5
TP_PERCENT = 0.02
SL_PERCENT = 0.01

# --- TELEGRAM ---
TELEGRAM_TOKEN = "TELEGRAM_TOKEN"
TELEGRAM_CHAT_ID = "TELEGRAM_CHAT_ID"

def send_telegram_msg(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=5)
    except Exception:
        pass

class CryptoApp:
    def __init__(self):
        # GUI kodu kaldırıldı, sadece veriler ve threadler çalışacak
        self.active_trades = []
        self.daily_report = {"TP": 0, "SL": 0, "profit": 0.0}

        threading.Thread(target=self.run_logic, daemon=True).start()
        threading.Thread(target=self.trade_takip, daemon=True).start()
        threading.Thread(target=self.gun_sonu_raporu_otomatik, daemon=True).start()

    def calculate_position(self, entry_price):
        risk_amount = TOTAL_WALLET * RISK_PER_TRADE
        position_size_usd = risk_amount / SL_PERCENT
        margin_needed = position_size_usd / DEFAULT_LEVERAGE
        return round(margin_needed, 2), DEFAULT_LEVERAGE

    def get_indicators(self, df):
        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs)).iloc[-1]

    def signal_ekle(self, symbol, side, price, karne, tp, sl, rsi):
        margin, lev = self.calculate_position(float(price))
        tg_msg = (
            f"🎯 *RİSK HESAPLANMIŞ 2R SİNYAL*\n\n"
            f"💰 *Parite:* {symbol} | *Yön:* {side}\n"
            f"💵 *Giriş Fiyatı:* `{price}`\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📝 *İŞLEM REHBERİ (400$ Kasa İçin):*\n"
            f"🔸 *Miktar (Margin):* `{margin} USD` (İzole)\n"
            f"🔸 *Kaldıraç:* `{lev}x`\n"
            f"🛑 *Zarar Durdur (SL):* `{sl}`\n"
            f"✅ *Kâr Al (TP):* `{tp}`\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 *Karne:* {karne} | *RSI:* {rsi:.2f}\n"
            f"💡 *Not:* Bu işleme girersen stop olduğunda sadece 8$ kaybedersin."
        )
        send_telegram_msg(tg_msg)
        self.active_trades.append({
            "symbol": symbol,
            "side": side,
            "entry": float(price),
            "tp": float(tp),
            "sl": float(sl),
            "locked": False
        })

    def run_logic(self):
        send_telegram_msg("🚀 *KASA YÖNETİMLİ BOT BAŞLATILDI*\nCüzdan: 400$ | Risk: %2")
        try:
            EXCHANGE.load_markets()
            tickers = EXCHANGE.fetch_tickers()
            pariteler = [s for s, d in tickers.items() if ':USDT' in s and d['quoteVolume'] > VOL_THRESHOLD]
        except:
            return

        while True:
            for s in pariteler:
                try:
                    bars = EXCHANGE.fetch_ohlcv(s, timeframe='1m', limit=500)
                    df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
                    avg_v = df['v'].rolling(window=20).mean().iloc[-1]
                    last = df.iloc[-1]
                    rsi_val = self.get_indicators(df)

                    if last['v'] > (avg_v * VOL_MULTIPLIER):
                        side = None
                        if last['c'] < df['c'].iloc[-2] and rsi_val < 45:
                            side = "LONG"
                        elif last['c'] > df['c'].iloc[-2] and rsi_val > 55:
                            side = "SHORT"

                        if side:
                            success, total = self.performans_kontrol(df)
                            if total >= 10 and success >= 8:
                                p_s = f"{last['c']:.6f}"
                                raw_tp = last['c']*(1+TP_PERCENT) if side == "LONG" else last['c']*(1-TP_PERCENT)
                                raw_sl = last['c']*(1-SL_PERCENT) if side == "LONG" else last['c']*(1+SL_PERCENT)
                                self.signal_ekle(s, side, p_s, f"{success}/{total}", f"{raw_tp:.6f}", f"{raw_sl:.6f}", rsi_val)
                except:
                    continue
                time.sleep(0.01)

    def performans_kontrol(self, df):
        success, trades = 0, 0
        for i in range(50, len(df) - 30):
            v_spike = df['v'].iloc[i] > (df['v'].iloc[i-20:i].mean() * 2.0)
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
            if trades >= 10:
                break
        return success, trades

    def trade_takip(self):
        while True:
            try:
                for trade in self.active_trades[:]:
                    if trade.get("locked", False):
                        continue

                    ticker = EXCHANGE.fetch_ticker(trade["symbol"])
                    current_price = ticker["last"]

                    profit_loss = 0
                    if trade["side"] == "LONG":
                        if current_price >= trade["tp"]:
                            profit_loss = (trade["tp"] - trade["entry"]) * DEFAULT_LEVERAGE
                            send_telegram_msg(f"✅ TP GELDİ: {trade['symbol']} | Kâr: {profit_loss:.2f}$")
                            trade["locked"] = True
                            self.daily_report["TP"] += 1
                            self.daily_report["profit"] += profit_loss
                            self.active_trades.remove(trade)
                        elif current_price <= trade["sl"]:
                            profit_loss = (trade["sl"] - trade["entry"]) * DEFAULT_LEVERAGE
                            send_telegram_msg(f"🛑 SL GELDİ: {trade['symbol']} | Zarar: {abs(profit_loss):.2f}$")
                            trade["locked"] = True
                            self.daily_report["SL"] += 1
                            self.daily_report["profit"] += profit_loss
                            self.active_trades.remove(trade)

                    elif trade["side"] == "SHORT":
                        if current_price <= trade["tp"]:
                            profit_loss = (trade["entry"] - trade["tp"]) * DEFAULT_LEVERAGE
                            send_telegram_msg(f"✅ TP GELDİ: {trade['symbol']} | Kâr: {profit_loss:.2f}$")
                            trade["locked"] = True
                            self.daily_report["TP"] += 1
                            self.daily_report["profit"] += profit_loss
                            self.active_trades.remove(trade)
                        elif current_price >= trade["sl"]:
                            profit_loss = (trade["entry"] - trade["sl"]) * DEFAULT_LEVERAGE
                            send_telegram_msg(f"🛑 SL GELDİ: {trade['symbol']} | Zarar: {abs(profit_loss):.2f}$")
                            trade["locked"] = True
                            self.daily_report["SL"] += 1
                            self.daily_report["profit"] += profit_loss
                            self.active_trades.remove(trade)
                time.sleep(5)
            except:
                time.sleep(5)

    def gun_sonu_raporu(self):
        msg = (
            f"📊 *GÜN SONU RAPORU*\n"
            f"✅ TP Sayısı: {self.daily_report['TP']}\n"
            f"🛑 SL Sayısı: {self.daily_report['SL']}\n"
            f"💵 Toplam Kâr/Zarar: {self.daily_report['profit']:.2f}$"
        )
        send_telegram_msg(msg)

    def gun_sonu_raporu_otomatik(self):
        while True:
            try:
                now = datetime.now()
                if now.hour == 23 and now.minute == 59:
                    self.gun_sonu_raporu()
                    time.sleep(60)
                time.sleep(10)
            except:
                time.sleep(10)


if __name__ == "__main__":
    app = CryptoApp()
    while True:
        time.sleep(1)











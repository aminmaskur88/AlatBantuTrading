import sqlite3
import logging
import datetime
import json
import time
import requests
from scraper import get_driver, scrape_stock_data, get_coingecko_data
from news_scraper import scrape_news
from formatter import clean_data, enrich_data
from utils import setup_logging, get_api_keys, move_key_to_bottom, save_json

# Konfigurasi Database & Bot (ONLY BTC - AGGRESSIVE SCALPER)
DB_PATH = "data/trades.db"
WATCHLIST = ["BTC-USD"]

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS portfolio (id INTEGER PRIMARY KEY, balance REAL DEFAULT 1000.0, initial_capital REAL DEFAULT 1000.0, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cur.execute("CREATE TABLE IF NOT EXISTS holdings (symbol TEXT PRIMARY KEY, quantity REAL DEFAULT 0, avg_price REAL DEFAULT 0.0, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cur.execute("CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, date TEXT, price REAL, lots REAL, reason TEXT, trade_type TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, message TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cur.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, target_price REAL, quantity REAL, side TEXT, reason TEXT, status TEXT DEFAULT 'PENDING', tp_price REAL, sl_price REAL)")
    
    cur.execute("PRAGMA table_info(orders)")
    columns = [column[1] for column in cur.fetchall()]
    if 'tp_price' not in columns: cur.execute("ALTER TABLE orders ADD COLUMN tp_price REAL")
    if 'sl_price' not in columns: cur.execute("ALTER TABLE orders ADD COLUMN sl_price REAL")

    cur.execute("INSERT OR IGNORE INTO portfolio (id, balance, initial_capital) VALUES (1, 1000.0, 1000.0)")
    conn.commit()
    conn.close()

def reset_sandbox_data():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # Reset Portfolio to 1000
    cur.execute("UPDATE portfolio SET balance = 1000.0, initial_capital = 1000.0 WHERE id = 1")
    # Clear other tables
    cur.execute("DELETE FROM holdings")
    cur.execute("DELETE FROM trades")
    cur.execute("DELETE FROM logs")
    cur.execute("DELETE FROM orders")
    conn.commit()
    conn.close()
    save_log("🔄 Sandbox has been reset to initial state.")

def save_log(message):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("INSERT INTO logs (message) VALUES (?)", (message,))
        conn.commit()
        conn.close()
    except: pass

async def get_portfolio():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT balance, initial_capital FROM portfolio WHERE id = 1")
        row = cur.fetchone()
        balance, initial_capital = row if row else (1000.0, 1000.0)
        cur.execute("SELECT symbol, quantity, avg_price FROM holdings WHERE quantity > 0")
        holdings_raw = cur.fetchall()
        conn.close()
        holdings = []
        for r in holdings_raw:
            symbol, qty, avg = r
            try:
                # get_coingecko_data is now async
                current_price, _, _ = await get_coingecko_data(symbol)
                if current_price is None: current_price = avg
            except: current_price = avg
            holdings.append({"symbol": symbol, "quantity": qty, "avg_price": avg, "current_price": current_price, "value": qty * current_price})
        return balance, initial_capital, holdings
    except: return 1000.0, 1000.0, []

def get_pending_orders():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, symbol, target_price, quantity, side, reason, tp_price, sl_price FROM orders WHERE status = 'PENDING'")
    orders = [{"id": r[0], "symbol": r[1], "target_price": r[2], "quantity": r[3], "side": r[4], "reason": r[5], "tp_price": r[6], "sl_price": r[7]} for r in cur.fetchall()]
    conn.close()
    return orders

def execute_trade(symbol, trade_type, price, quantity, reason):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT balance FROM portfolio WHERE id = 1")
    balance = cur.fetchone()[0]
    cur.execute("SELECT quantity, avg_price FROM holdings WHERE symbol = ?", (symbol,))
    holding = cur.fetchone()
    current_qty = holding[0] if holding else 0
    current_avg = holding[1] if holding else 0.0
    cost = price * quantity
    if trade_type.upper() == "BUY":
        if balance < cost: return False
        new_balance = balance - cost
        new_qty = current_qty + quantity
        new_avg = ((current_qty * current_avg) + cost) / new_qty
        cur.execute("UPDATE portfolio SET balance = ? WHERE id = 1", (new_balance,))
        cur.execute("INSERT OR REPLACE INTO holdings (symbol, quantity, avg_price, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)", (symbol, new_qty, new_avg))
    elif trade_type.upper() == "SELL":
        if current_qty < quantity: return False
        new_balance = balance + cost
        new_qty = current_qty - quantity
        cur.execute("UPDATE portfolio SET balance = ? WHERE id = 1", (new_balance,))
        if new_qty <= 0.00000001: cur.execute("DELETE FROM holdings WHERE symbol = ?", (symbol,))
        else: cur.execute("UPDATE holdings SET quantity = ?, updated_at = CURRENT_TIMESTAMP WHERE symbol = ?", (new_qty, symbol))
    cur.execute("INSERT INTO trades (symbol, date, price, lots, reason, trade_type) VALUES (?, ?, ?, ?, ?, ?)", (symbol, datetime.datetime.now().isoformat(), price, quantity, reason, trade_type.upper()))
    conn.commit()
    conn.close()
    return True

async def run_bot_iteration(watchlist=None):
    init_db()
    api_keys = get_api_keys()
    if not api_keys: return {"error": "API Key missing"}
    
    if not watchlist or not any(watchlist):
        watchlist = ["BTC-USD", "ETH-USD", "SOL-USD"]
        
    balance, _, holdings_list = await get_portfolio()
    holdings_dict = {h['symbol']: h for h in holdings_list}
    pending_orders = get_pending_orders()
    logs = []
    def add_log(msg):
        logs.append(msg); save_log(msg)
    
    headers = {"Content-Type": "application/json"}
    for symbol in watchlist:
        try:
            # scrape_stock_data is now async
            raw_data = await scrape_stock_data(symbol)
            current_price = float(raw_data.get('price', '0'))
            if current_price <= 0: continue
            
            # 1. Check Executions
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            for order in [o for o in pending_orders if o['symbol'] == symbol]:
                triggered = False
                if order['side'] == 'BUY' and current_price <= order['target_price']:
                    triggered = True; action_msg = f"✅ SCALP BUY! {symbol} at ${current_price:,.2f}"
                elif order['side'] == 'SELL':
                    if order['tp_price'] and current_price >= order['tp_price']:
                        triggered = True; action_msg = f"💰 SCALP PROFIT! {symbol} sold at ${current_price:,.2f}"
                    elif order['sl_price'] and current_price <= order['sl_price']:
                        triggered = True; action_msg = f"📉 SCALP STOP LOSS. {symbol} sold at ${current_price:,.2f}"
                if triggered:
                    if execute_trade(symbol, order['side'], current_price, order['quantity'], action_msg):
                        cur.execute("UPDATE orders SET status = 'FILLED' WHERE id = ?", (order['id'],)); add_log(action_msg)
            conn.commit(); conn.close()
            
            # 2. New Analysis
            if not any(o['symbol'] == symbol for o in get_pending_orders()):
                enriched = enrich_data(clean_data(raw_data))
                holding = holdings_dict.get(symbol, {})
                qty_owned = holding.get('quantity', 0)
                avg_price = holding.get('avg_price', 0)
                
                status_context = f"Owned: {qty_owned} units at avg price ${avg_price:,.2f}." if qty_owned > 0 else "No current position."
                
                prompt = (
                    f"ROLE: Professional Crypto Scalper. Balance: ${balance:,.2f}. Asset: {symbol}. {status_context} "
                    f"DATA: {json.dumps(enriched)}. "
                    "TASK: Analyze data and provide a trade plan. "
                    "If no position: Consider 'BUY' or 'NONE'. "
                    "If position exists: Consider 'SELL' (to take profit/cut loss) or 'NONE'. "
                    "Strategy: Scalping (Target 0.5-2.0% profit, 1.0% stop loss). "
                    "JSON OUTPUT ONLY: "
                    '{"side": "BUY/SELL/NONE", "target_price": float, "tp_price": float, "sl_price": float, "units": float, "analysis": "brief market overview", "reason": "logic for trade"}'
                )
                
                payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json"}}
                res_text = None
                
                async with aiohttp.ClientSession(headers=headers) as session:
                    for api_key in api_keys:
                        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
                        try:
                            async with session.post(url, json=payload, timeout=20) as response:
                                data = await response.json()
                                res_text = data['candidates'][0]['content']['parts'][0]['text']; break
                        except: continue
                
                if res_text:
                    plan = json.loads(res_text); side = plan.get("side", "NONE").upper()
                    
                    formatted_ai = {
                        "timestamp": datetime.datetime.now().isoformat(),
                        "data": enriched,
                        "ai_result": {
                            "signal": side,
                            "entry_price": plan.get("target_price", 0),
                            "target_price": plan.get("tp_price", 0),
                            "cut_loss_price": plan.get("sl_price", 0),
                            "analysis": plan.get("analysis", ""),
                            "reason": plan.get("reason", "")
                        }
                    }
                    save_json(f"data/result/{symbol.upper()}.json", formatted_ai)

                    if side == "SELL" and qty_owned <= 0: side = "NONE"
                    if side != "NONE":
                        units = plan.get('units', 0)
                        if side == "BUY":
                            max_units = (balance * 0.95) / current_price 
                            units = min(units, max_units)
                            
                        if units > 0:
                            conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
                            cur.execute("INSERT INTO orders (symbol, target_price, tp_price, sl_price, quantity, side, reason) VALUES (?, ?, ?, ?, ?, ?, ?)", (symbol, plan['target_price'], plan['tp_price'], plan['sl_price'], units, side, plan['reason']))
                            conn.commit(); conn.close(); add_log(f"📝 {symbol} Plan: {side} {units:,.4f} at ${plan['target_price']:,.2f}")
            await asyncio.sleep(0.5)
        except: continue
    return {"status": "success", "logs": logs}
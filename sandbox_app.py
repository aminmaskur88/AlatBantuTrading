from flask import Flask, render_template, jsonify, request
import sqlite3
import logging
import threading
import time
from sandbox_logic import get_portfolio, run_bot_iteration, init_db

app = Flask(__name__)
DB_PATH = "data/trades.db"

# Inisialisasi DB saat start
init_db()

# Auto-Pilot Global Variables
auto_pilot_enabled = False
auto_pilot_watchlist = ["BTC-USD", "ETH-USD", "SOL-USD"]
last_run_time = None

def auto_pilot_loop():
    global auto_pilot_enabled, auto_pilot_watchlist, last_run_time
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    while True:
        if auto_pilot_enabled:
            print(f"--- Auto-Pilot: Scanning Market for {', '.join(auto_pilot_watchlist)} ---")
            try:
                loop.run_until_complete(run_bot_iteration(watchlist=auto_pilot_watchlist))
                last_run_time = datetime.datetime.now().isoformat()
            except Exception as e:
                print(f"Auto-Pilot Error: {e}")
        time.sleep(60) 

import datetime
import asyncio
# Start background thread
threading.Thread(target=auto_pilot_loop, daemon=True).start()

@app.route("/")
def index():
    return render_template("sandbox.html")

@app.route("/api/portfolio")
async def portfolio_api():
    try:
        balance, initial_capital, holdings = await get_portfolio()
        return jsonify({
            "balance": balance,
            "initial_capital": initial_capital,
            "holdings": holdings
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/trades_history")
async def trades_history_api():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT trade_type, symbol, date, price, lots, reason FROM trades ORDER BY id DESC LIMIT 50")
        rows = cur.fetchall()
        conn.close()
        
        trades = []
        for r in rows:
            trades.append({
                "type": r[0],
                "symbol": r[1],
                "date": r[2],
                "price": r[3],
                "lots": r[4],
                "reason": r[5]
            })
        return jsonify(trades)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/orders")
async def orders_api():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT symbol, target_price, quantity, side, reason, tp_price, sl_price FROM orders WHERE status = 'PENDING'")
        orders = [{"symbol": r[0], "target_price": r[1], "quantity": r[2], "side": r[3], "reason": r[4], "tp_price": r[5], "sl_price": r[6]} for r in cur.fetchall()]
        conn.close()
        return jsonify(orders)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/logs")
async def logs_api():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT message, timestamp FROM logs ORDER BY id DESC LIMIT 100")
        rows = cur.fetchall()
        conn.close()
        logs = [{"message": r[0], "time": r[1]} for r in rows]
        return jsonify(logs[::-1])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/run_bot", methods=["POST"])
async def run_bot_api():
    try:
        data = request.json or {}
        watchlist = data.get("watchlist", [])
        result = await run_bot_iteration(watchlist=watchlist)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/auto_pilot", methods=["POST"])
async def toggle_auto_pilot():
    global auto_pilot_enabled, auto_pilot_watchlist
    data = request.json or {}
    auto_pilot_enabled = data.get("enabled", False)
    
    if "watchlist" in data and isinstance(data["watchlist"], list):
        auto_pilot_watchlist = [s.strip().upper() for s in data["watchlist"] if s.strip()]
    
    status = "Enabled" if auto_pilot_enabled else "Disabled"
    print(f"--- Auto-Pilot {status} for {auto_pilot_watchlist} ---")
    return jsonify({
        "status": "success", 
        "auto_pilot": auto_pilot_enabled, 
        "watchlist": auto_pilot_watchlist
    })

@app.route("/api/auto_pilot_status")
async def get_auto_pilot_status():
    global auto_pilot_enabled, auto_pilot_watchlist, last_run_time
    return jsonify({
        "enabled": auto_pilot_enabled, 
        "watchlist": auto_pilot_watchlist,
        "last_run": last_run_time
    })

@app.route("/api/reset_sandbox", methods=["POST"])
async def reset_sandbox_api():
    try:
        from sandbox_logic import reset_sandbox_data
        reset_sandbox_data()
        return jsonify({"status": "success", "message": "Sandbox reset complete"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/asset_analysis/<symbol>")
async def asset_analysis_api(symbol):
    try:
        import os
        import json
        result_path = f"data/result/{symbol.upper()}.json"
        if os.path.exists(result_path):
            with open(result_path, 'r') as f:
                data = json.load(f)
                return jsonify(data)
        return jsonify({"error": "No recent analysis found for this asset."}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Store chat histories per session/symbol
sandbox_chat_sessions = {}

@app.route("/api/sandbox_chat", methods=["POST"])
async def sandbox_chat_api():
    data = request.json
    symbol = data.get("symbol", "").strip().upper()
    message = data.get("message", "").strip()
    history = data.get("history", [])
    
    if not symbol or not message:
        return jsonify({"error": "Invalid request"}), 400
        
    from utils import get_api_keys
    from ai_analyzer import chat_with_gemini
    api_keys = get_api_keys()
    
    try:
        ai_reply = ""
        updated_history = history
        async for update in chat_with_gemini(api_keys, history, message):
            if "reply" in update:
                ai_reply = update["reply"]
                updated_history = update["history"]
        return jsonify({"reply": ai_reply, "history": updated_history})
    except Exception as e:
         return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    print("\n--- Sandbox Server Running ---")
    print("Akses di: http://localhost:5001")
    app.run(host="0.0.0.0", port=5001, debug=True)
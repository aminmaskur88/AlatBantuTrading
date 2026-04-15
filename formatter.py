import sqlite3
import os

def get_holdings(symbol):
    db_path = 'data/trades.db'
    if not os.path.exists(db_path):
        return []
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT date, price, lots, trade_type FROM trades WHERE symbol=?", (symbol,))
        rows = cursor.fetchall()
        conn.close()
        
        holdings = []
        for row in rows:
            holdings.append({
                "date": row[0],
                "price": row[1],
                "lots": row[2],
                "trade_type": row[3]
            })
        return holdings
    except Exception:
        return []

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return None
    
    deltas = [prices[i+1] - prices[i] for i in range(len(prices)-1)]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    if avg_loss == 0:
        return 100
        
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
    if avg_loss == 0:
        return 100
        
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_ma(prices, period=20):
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period

def clean_data(raw_data):
    clean = raw_data.copy()
    
    # Clean price
    price = raw_data.get('price')
    if price and isinstance(price, str):
        try:
            clean['price'] = float(price.replace(',', ''))
        except ValueError:
            pass
    
    # Clean change percentage
    change = raw_data.get('change')
    if change and isinstance(change, str):
        try:
            clean['change'] = float(change.replace('%', '').replace('+', '').replace('(', '').replace(')', '').replace(',', ''))
        except ValueError:
            pass
    
    clean['symbol'] = raw_data.get('symbol', 'UNKNOWN')
    # History data for technical analysis
    clean['history'] = raw_data.get('history', [])
    return clean

def enrich_data(clean_data):
    enriched = clean_data.copy()
    
    # Market trend simple logic
    change = enriched.get('change', 0)
    try:
        change_val = float(change)
        if change_val > 0:
            enriched['market_trend'] = 'naik'
        elif change_val < 0:
            enriched['market_trend'] = 'turun'
        else:
            enriched['market_trend'] = 'stagnan'
    except (ValueError, TypeError):
        enriched['market_trend'] = 'tidak diketahui'
    
    # Technical Analysis (RSI, MA)
    history = clean_data.get('history', [])
    if history:
        rsi = calculate_rsi(history)
        ma20 = calculate_ma(history, 20)
        
        if rsi is not None:
            enriched['rsi'] = round(rsi, 2)
            if rsi > 70:
                enriched['rsi_desc'] = 'Overbought (Jenuh Beli)'
            elif rsi < 30:
                enriched['rsi_desc'] = 'Oversold (Jenuh Jual)'
            else:
                enriched['rsi_desc'] = 'Netral'
        
        if ma20 is not None:
            enriched['ma20'] = round(ma20, 2)
            current_price = enriched.get('price')
            if current_price and current_price > ma20:
                enriched['ma_signal'] = 'Bullish (Diatas MA20)'
            elif current_price and current_price < ma20:
                enriched['ma_signal'] = 'Bearish (Dibawah MA20)'
            else:
                enriched['ma_signal'] = 'Netral'

    # Basic Sentiment logic from news
    positive_words = ['naik', 'untung', 'laba', 'growth', 'buy', 'positive', 'surge', 'jump', 'dividend', 'profit', 'bullish', 'optimis', 'meningkat', 'ekspansi', 'akuisisi', 'rekor', 'prospek']
    negative_words = ['turun', 'rugi', 'loss', 'sell', 'negative', 'drop', 'fall', 'slump', 'bearish', 'pesimis', 'melemah', 'suspend', 'pailit', 'waspada', 'resiko']
    
    sentiment_score = 0
    for news in enriched.get('news', []):
        title = news.get('title', '').lower()
        if any(word in title for word in positive_words):
            sentiment_score += 1
        if any(word in title for word in negative_words):
            sentiment_score -= 1
            
    if not enriched.get('news'):
        enriched['sentiment'] = 'tidak ada berita terbaru'
    elif sentiment_score > 0:
        enriched['sentiment'] = 'positif'
    elif sentiment_score < 0:
        enriched['sentiment'] = 'negatif'
    else:
        enriched['sentiment'] = 'netral'
        
    # Tambahkan data kepemilikan aset user jika ada
    symbol = enriched.get('symbol', '')
    if symbol:
        holdings = get_holdings(symbol)
        if holdings:
            enriched['user_holdings'] = holdings
            
    return enriched
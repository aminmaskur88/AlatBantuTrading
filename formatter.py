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

def calculate_ema(prices, period):
    if len(prices) < period:
        return None
    
    # Start with SMA as the first EMA value
    sma = sum(prices[:period]) / period
    multiplier = 2 / (period + 1)
    
    ema = sma
    for i in range(period, len(prices)):
        ema = (prices[i] - ema) * multiplier + ema
    return ema

def calculate_technical_indicators(prices, volumes=None):
    if len(prices) < 26: # Need at least 26 for MACD EMA
        return {}
    
    # 1. Support & Resistance (Pivot Points approximation)
    high = max(prices[-20:])
    low = min(prices[-20:])
    close = prices[-1]
    pivot = (high + low + close) / 3
    s1 = (2 * pivot) - high
    r1 = (2 * pivot) - low
    s2 = pivot - (high - low)
    r2 = pivot + (high - low)

    # 2. Bollinger Bands (20, 2)
    ma20 = calculate_ma(prices, 20)
    variance = sum([(p - ma20)**2 for p in prices[-20:]]) / 20
    std_dev = variance**0.5
    upper_band = ma20 + (std_dev * 2)
    lower_band = ma20 - (std_dev * 2)

    # 3. MACD (Standard EMA-based)
    # We need a series of EMAs to calculate the Signal Line
    ema12_list = []
    ema26_list = []
    
    # Helper to get EMA series
    def get_ema_series(data, period):
        if not data: return []
        series = []
        
        # Fallback: If data is shorter than period, use SMA of available data
        if len(data) < period:
            sma = sum(data) / len(data)
            return [sma]
            
        sma = sum(data[:period]) / period
        series.append(sma)
        multiplier = 2 / (period + 1)
        for i in range(period, len(data)):
            val = (data[i] - series[-1]) * multiplier + series[-1]
            series.append(val)
        return series

    ema12_series = get_ema_series(prices, 12)
    ema26_series = get_ema_series(prices, 26)
    
    # MACD Line = EMA12 - EMA26
    macd_series = []
    # Find the offset to align ema12 with ema26
    # ema12_series[0] is at index 11 of prices
    # ema26_series[0] is at index 25 of prices
    # offset = 25 - 11 = 14
    
    # If ema26 was a fallback SMA (len 1), we need to handle that
    if len(ema26_series) == 1 and len(ema12_series) > 1:
        macd_series = [ema12_series[-1] - ema26_series[0]]
    else:
        offset = 26 - 12
        for i in range(len(ema26_series)):
            if (i + offset) < len(ema12_series):
                macd_series.append(ema12_series[i + offset] - ema26_series[i])
    
    if not macd_series:
        macd_line = 0
    else:
        macd_line = macd_series[-1]
    
    # Signal Line = 9-day EMA of MACD Line
    signal_series = get_ema_series(macd_series, 9)
    signal_line = signal_series[-1] if signal_series else 0
    macd_histogram = macd_line - signal_line

    # 4. Fibonacci Levels (90 days range)
    high_90 = max(prices)
    low_90 = min(prices)
    diff = high_90 - low_90
    fib = {
        "fib_236": high_90 - (0.236 * diff),
        "fib_382": high_90 - (0.382 * diff),
        "fib_500": high_90 - (0.500 * diff),
        "fib_618": high_90 - (0.618 * diff),
        "fib_786": high_90 - (0.786 * diff)
    }
    
    results = {
        "support_1": round(s1, 2),
        "resistance_1": round(r1, 2),
        "support_2": round(s2, 2),
        "resistance_2": round(r2, 2),
        "bb_upper": round(upper_band, 2),
        "bb_lower": round(lower_band, 2),
        "macd": round(macd_line, 2),
        "macd_signal": round(signal_line, 2) if signal_line is not None else None,
        "macd_hist": round(macd_histogram, 2) if macd_histogram is not None else None
    }
    
    # 5. Volume Indicators
    if volumes and len(volumes) >= 20:
        vol_ma20 = sum(volumes[-20:]) / 20
        current_vol = volumes[-1]
        results["vol_ma20"] = round(vol_ma20, 0)
        results["vol_status"] = "High" if current_vol > vol_ma20 * 1.5 else "Normal"
        
        # Simple OBV (On-Balance Volume) trend
        obv_trend = "Neutral"
        if len(prices) >= 5 and len(volumes) >= 5:
            up_days = 0
            for i in range(-5, -1):
                if prices[i+1] > prices[i]: up_days += 1
            if up_days >= 4: obv_trend = "Accumulating"
            elif up_days <= 1: obv_trend = "Distributing"
        results["volume_trend"] = obv_trend

    # Round fib levels
    for k, v in fib.items():
        results[k] = round(v, 2)
        
    return results

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
    clean['volumes'] = raw_data.get('volumes', [])
    
    # Simple Ratio Extraction from context if exists
    context = raw_data.get('fundamental_context', '')
    if context:
        import re
        ratios = {}
        # Simple patterns for ROE, PER, PBV, DER
        patterns = {
            "roe": r"ROE\s*[:=]?\s*([\d\.,]+)%?",
            "per": r"PER\s*[:=]?\s*([\d\.,]+)x?",
            "pbv": r"PBV\s*[:=]?\s*([\d\.,]+)x?",
            "der": r"DER\s*[:=]?\s*([\d\.,]+)x?"
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, context, re.IGNORECASE)
            if match:
                ratios[key] = match.group(1)
        clean['ratios'] = ratios

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
    volumes = clean_data.get('volumes', [])
    
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
        
        # Add deep technical indicators
        deep_tech = calculate_technical_indicators(history, volumes=volumes)
        enriched.update(deep_tech)

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
import yfinance as yf
import json
import logging
import datetime

async def get_stock_price(symbol):
    """
    Mengambil harga saham terkini menggunakan library yfinance (Python).
    Metode ini lebih stabil daripada scraping atau Node.js library jika sering TMR.
    """
    if symbol.upper().replace("$", "") == "GENERAL":
        return {"error": "Invalid symbol: GENERAL", "symbol": symbol}

    if not symbol.endswith(".JK") and "." not in symbol:
        symbol = f"{symbol}.JK"
    
    try:
        stock = yf.Ticker(symbol)
        # Fast way to get price
        info = stock.fast_info
        
        price = info.last_price
        prev_close = info.previous_close
        
        change = price - prev_close
        change_percent = (change / prev_close) * 100 if prev_close else 0
        
        return {
            "symbol": symbol,
            "price": round(price, 2),
            "unit": "IDR",
            "change": round(change, 2),
            "change_percent": f"{round(change_percent, 2)}%",
            "high": round(info.day_high, 2),
            "low": round(info.day_low, 2),
            "volume": info.last_volume,
            "status": "success"
        }
    except Exception as e:
        logging.error(f"Error yfinance for {symbol}: {e}")
        return {"error": str(e), "symbol": symbol}

async def get_historical_stock_data(symbol, range_val="1y"):
    """Mengambil data historis menggunakan yfinance."""
    if symbol.upper().replace("$", "") == "GENERAL":
        return {"error": "Invalid symbol: GENERAL", "symbol": symbol}

    if not symbol.endswith(".JK") and "." not in symbol:
        symbol = f"{symbol}.JK"
        
    # Map range to yfinance period
    period_map = {
        "1mo": "1mo", "3mo": "3mo", "6mo": "6mo", "1y": "1y", "2y": "2y", "5y": "5y", "max": "max"
    }
    period = period_map.get(range_val, "1y")
    
    try:
        stock = yf.Ticker(symbol)
        hist = stock.history(period=period)
        
        data_points = []
        for date, row in hist.iterrows():
            data_points.append({
                "date": date.strftime("%Y-%m-%d"),
                "open": round(row["Open"], 2),
                "high": round(row["High"], 2),
                "low": round(row["Low"], 2),
                "close": round(row["Close"], 2),
                "volume": int(row["Volume"])
            })
            
        return {
            "symbol": symbol,
            "history": data_points,
            "status": "success"
        }
    except Exception as e:
        return {"error": str(e), "symbol": symbol}

async def get_fundamental_data(symbol):
    """Mengambil data fundamental menggunakan yfinance."""
    if symbol.upper().replace("$", "") == "GENERAL":
        return {"error": "Invalid symbol: GENERAL", "symbol": symbol}

    if not symbol.endswith(".JK") and "." not in symbol:
        symbol = f"{symbol}.JK"
        
    try:
        stock = yf.Ticker(symbol)
        info = stock.info
        
        return {
            "symbol": symbol,
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "dividend_yield": info.get("dividendYield"),
            "pb_ratio": info.get("priceToBook"),
            "high_52": info.get("fiftyTwoWeekHigh"),
            "low_52": info.get("fiftyTwoWeekLow"),
            "name": info.get("longName"),
            "status": "success"
        }
    except Exception as e:
        return {"error": str(e), "symbol": symbol}

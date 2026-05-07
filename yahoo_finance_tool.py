import logging
import aiohttp
import asyncio
import datetime

async def get_stock_price(symbol: str):
    """
    Mengambil harga saham terkini dari Yahoo Finance secara asinkron.
    """
    original_symbol_upper = symbol.upper()
    symbols_to_try = [original_symbol_upper]
    if len(original_symbol_upper) == 4 and original_symbol_upper.isalpha() and '.' not in original_symbol_upper:
        symbols_to_try.insert(0, f"{original_symbol_upper}.JK")

    headers = {'User-Agent': 'Mozilla/5.0'}
    
    async with aiohttp.ClientSession(headers=headers) as session:
        for current_symbol in symbols_to_try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{current_symbol}"
            try:
                async with session.get(url, timeout=10) as response:
                    if response.status == 404: continue
                    data = await response.json()
                
                if not data.get('chart') or not data['chart'].get('result'): continue
                result = data['chart']['result'][0]
                meta = result.get('meta', {})
                price = meta.get('regularMarketPrice')
                prev_close = meta.get('previousClose')
                
                change = "N/A"
                change_percent = "N/A"
                if price and prev_close:
                    raw_change = price - prev_close
                    change = f"{raw_change:+.2f}"
                    change_percent = f"{(raw_change/prev_close)*100:+.2f}%"

                return {
                    "symbol": original_symbol_upper,
                    "full_symbol": current_symbol,
                    "price": str(price),
                    "change": change,
                    "change_percent": change_percent,
                    "unit": meta.get('currency', 'USD')
                }
            except: continue
    return {"error": f"Gagal mengambil harga untuk {original_symbol_upper}"}

async def get_historical_stock_data(symbol: str, range_days: str = "90d"):
    """
    Mengambil data harga historis secara asinkron.
    """
    symbol_upper = symbol.upper()
    if len(symbol_upper) == 4 and '.' not in symbol_upper: symbol_upper += ".JK"
    
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol_upper}?interval=1d&range={range_days}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=15) as r:
                data = await r.json()
        
        result = data['chart']['result'][0]
        prices = result['indicators']['quote'][0]['close']
        volumes = result['indicators']['quote'][0].get('volume', [])
        timestamps = result['timestamp']
        
        history = []
        for i in range(len(prices)):
            if prices[i] is not None:
                date = datetime.datetime.fromtimestamp(timestamps[i]).strftime('%Y-%m-%d')
                vol = volumes[i] if i < len(volumes) else 0
                history.append({"date": date, "close": round(prices[i], 2), "volume": vol})
        
        return {"symbol": symbol_upper, "history": history}
    except Exception as e:
        return {"error": str(e)}

async def get_fundamental_data(symbol: str):
    """
    Mengambil data fundamental secara asinkron.
    """
    symbol_upper = symbol.upper()
    if len(symbol_upper) == 4 and '.' not in symbol_upper: symbol_upper += ".JK"
    
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol_upper}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=15) as r:
                data = await r.json()
                
        meta = data['chart']['result'][0]['meta']
        
        return {
            "symbol": symbol_upper,
            "market_cap": meta.get("marketCap"),
            "pe_ratio": "N/A",
            "price_hint": meta.get("priceHint"),
            "high_52w": meta.get("fiftyTwoWeekHigh"),
            "low_52w": meta.get("fiftyTwoWeekLow"),
            "currency": meta.get("currency"),
            "exchange": meta.get("exchangeName")
        }
    except Exception as e:
        return {"error": str(e)}


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    print(get_stock_price("BBCA"))
    print(get_historical_stock_data("GOTO"))
    print(get_fundamental_data("AAPL"))

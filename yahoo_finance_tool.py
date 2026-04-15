import logging
import requests

def get_stock_price(symbol: str):
    """
    Mengambil harga saham terkini dari Yahoo Finance untuk simbol tertentu menggunakan API chart.
    Mengembalikan dictionary {"symbol": "...", "price": "...", "change": "...", "unit": "..."} atau {"error": "..."}.
    """
    original_symbol_upper = symbol.upper()
    symbols_to_try = [original_symbol_upper]

    # Heuristik: Jika 4 huruf dan alpha, coba dengan .JK dulu
    if len(original_symbol_upper) == 4 and original_symbol_upper.isalpha() and '.' not in original_symbol_upper:
        symbols_to_try.insert(0, f"{original_symbol_upper}.JK") # Coba .JK dulu

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    for current_symbol_to_try in symbols_to_try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{current_symbol_to_try}"
        try:
            logging.info(f"Mencoba mencari harga di Yahoo Finance API untuk: {current_symbol_to_try}")
            response = requests.get(url, headers=headers, timeout=15)
            
            if response.status_code == 404:
                logging.warning(f"Simbol {current_symbol_to_try} tidak ditemukan di Yahoo Finance API (404).")
                continue
                
            response.raise_for_status()
            data = response.json()
            
            if not data.get('chart') or not data['chart'].get('result'):
                logging.warning(f"Data tidak ditemukan untuk {current_symbol_to_try} di Yahoo Finance API.")
                continue

            result = data['chart']['result'][0]
            meta = result.get('meta', {})
            
            price = meta.get('regularMarketPrice')
            if price is None:
                logging.warning(f"Tidak dapat menemukan harga untuk {current_symbol_to_try} di Yahoo Finance API.")
                continue

            prev_close = meta.get('previousClose')
            unit = meta.get('currency', 'USD')
            
            change = "N/A"
            change_percent = "N/A"
            
            if prev_close is not None and prev_close != 0:
                raw_change = price - prev_close
                raw_change_percent = (raw_change / prev_close) * 100
                change = f"{raw_change:+.2f}"
                change_percent = f"{raw_change_percent:+.2f}%"

            result_dict = {
                "symbol": original_symbol_upper,
                "full_symbol": current_symbol_to_try,
                "price": str(price),
                "change": change,
                "change_percent": change_percent,
                "unit": unit
            }
            logging.info(f"Hasil dari Yahoo Finance: {result_dict}")
            return result_dict

        except Exception as e:
            logging.error(f"Error saat mengakses Yahoo Finance API untuk {current_symbol_to_try}: {e}")
            if current_symbol_to_try == f"{original_symbol_upper}.JK" and f"{original_symbol_upper}.JK" in symbols_to_try:
                continue
            
    return {"error": f"Simbol saham '{original_symbol_upper}' tidak ditemukan atau gagal mengambil data dari Yahoo Finance."}

if __name__ == '__main__':
    # Contoh penggunaan
    logging.basicConfig(level=logging.INFO)
    print(get_stock_price("BBCA"))
    print(get_stock_price("AAPL"))
    print(get_stock_price("GOTO.JK"))
    print(get_stock_price("POWR.JK"))
    print(get_stock_price("NONEXISTENT"))
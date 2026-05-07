import csv
import logging

def screen_stocks(csv_file="indonesia.csv", sector=None, market=None, keyword=None, limit=None):
    """
    Fungsi untuk melakukan screening saham berdasarkan kriteria tertentu.    
    Args:
        csv_file (str): Path ke file CSV database saham (default: indonesia.csv).
        sector (str, optional): Filter berdasarkan sektor (misal: "Finance", "Energy minerals").
        market (str, optional): Filter berdasarkan pasar (misal: "IDX").
        keyword (str, optional): Pencarian berdasarkan nama perusahaan atau ticker.
        limit (int, optional): Membatasi jumlah hasil yang dikembalikan.

    Returns:
        list of dict: Daftar saham yang sesuai dengan kriteria.
    """
    results = []
    
    try:
        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                match = True
                
                # Filter berdasarkan sektor (case-insensitive)
                if sector and sector.lower() not in row.get("sector", "").lower():
                    match = False
                    
                # Filter berdasarkan market (case-insensitive)
                if market and market.lower() not in row.get("market", "").lower():
                    match = False
                    
                # Filter berdasarkan keyword pada nama atau ticker (case-insensitive)
                if keyword:
                    kw = keyword.lower()
                    name = row.get("name", "").lower()
                    ticker = row.get("ticker", "").lower()
                    if kw not in name and kw not in ticker:
                        match = False
                        
                if match:
                    results.append(row)
                    
                if limit and len(results) >= limit:
                    break
                    
    except FileNotFoundError:
        logging.error(f"File {csv_file} tidak ditemukan.")
        return []
    except Exception as e:
        logging.error(f"Terjadi kesalahan saat membaca {csv_file}: {e}")
        return []
        
    return results

if __name__ == "__main__":
    # Contoh Penggunaan:
    print("Mencari saham di sektor 'Finance':")
    finance_stocks = screen_stocks(sector="Finance", limit=5)
    for stock in finance_stocks:
        print(f"- {stock['ticker']}: {stock['name']} ({stock['sector']})")
        
    print("\nMencari saham yang mengandung kata 'Bank':")
    bank_stocks = screen_stocks(keyword="Bank", limit=5)
    for stock in bank_stocks:
        print(f"- {stock['ticker']}: {stock['name']} ({stock['sector']})")

import os
import json
import requests
import pandas as pd
from datetime import datetime, timedelta
import io
import logging
import yfinance as yf
import warnings

# Matikan warning parsing tanggal yang mengganggu
warnings.filterwarnings("ignore", category=UserWarning)

class IDXDataService:
    def __init__(self, base_dir=None):
        if base_dir is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        
        self.data_dir = os.path.join(base_dir, 'data', 'historical')
        self.metadata_dir = os.path.join(base_dir, 'data', 'metadata')
        
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.metadata_dir, exist_ok=True)
        
        self.raw_url = 'https://raw.githubusercontent.com/wildangunawan/Dataset-Saham-IDX/master'
        self.cache_ttl = timedelta(hours=12)

    def _get_cache_path(self, ticker):
        return os.path.join(self.data_dir, f"{ticker.upper()}.json")

    def _get_metadata_path(self, ticker):
        return os.path.join(self.metadata_dir, f"{ticker.upper()}.json")

    def download_stock_data(self, ticker):
        ticker = ticker.upper()
        for directory in ['LQ45', 'Semua']:
            url = f"{self.raw_url}/Saham/{directory}/{ticker}.csv"
            try:
                response = requests.get(url, timeout=15)
                if response.status_code == 200:
                    return response.text
            except:
                continue
        return None

    def parse_csv_data(self, csv_text, ticker):
        try:
            df = pd.read_csv(io.StringIO(csv_text))
            column_map = {
                'Tanggal': 'date', 'Terakhir': 'close', 'Pembukaan': 'open',
                'Tertinggi': 'high', 'Terendah': 'low', 'Vol.': 'volume'
            }
            df = df.rename(columns=column_map)
            
            def clean_volume(val):
                if isinstance(val, str):
                    val = val.replace('.', '').replace(',', '.')
                    if 'B' in val: return float(val.replace('B', '')) * 1_000_000_000
                    if 'M' in val: return float(val.replace('M', '')) * 1_000_000
                    if 'K' in val: return float(val.replace('K', '')) * 1_000
                try: return float(val)
                except: return 0

            if 'volume' in df.columns:
                df['volume'] = df['volume'].apply(clean_volume)
            
            # Coba parsing dengan deteksi otomatis format tanggal
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
            df = df.dropna(subset=['date'])
            df['date'] = df['date'].dt.strftime('%Y-%m-%d')
            
            df = df.sort_values('date')
            data_points = df.to_dict('records')
            
            if not data_points: return None

            return {
                "ticker": ticker,
                "startDate": df['date'].iloc[0],
                "endDate": df['date'].iloc[-1],
                "totalPoints": len(df),
                "dataPoints": data_points
            }
        except Exception as e:
            return None

    def update_with_latest_yahoo(self, ticker, existing_data):
        try:
            last_date_str = existing_data["endDate"].split('T')[0]
            last_date = datetime.strptime(last_date_str, "%Y-%m-%d")
            
            if (datetime.now() - last_date).days < 1:
                return existing_data, False

            yahoo_ticker = f"{ticker.upper()}.JK"
            stock = yf.Ticker(yahoo_ticker)
            start_fetch = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
            
            new_hist = stock.history(start=start_fetch)
            
            if new_hist.empty:
                return existing_data, False
            
            new_points = []
            for date, row in new_hist.iterrows():
                new_points.append({
                    "date": date.strftime("%Y-%m-%d"),
                    "open": round(float(row["Open"]), 2),
                    "high": round(float(row["High"]), 2),
                    "low": round(float(row["Low"]), 2),
                    "close": round(float(row["Close"]), 2),
                    "volume": int(row["Volume"])
                })
            
            combined_points = existing_data["dataPoints"] + new_points
            dedup = {p['date']: p for p in combined_points}
            sorted_points = [dedup[d] for d in sorted(dedup.keys())]
            
            updated_data = {
                "ticker": ticker.upper(),
                "startDate": sorted_points[0]["date"],
                "endDate": sorted_points[-1]["date"],
                "totalPoints": len(sorted_points),
                "dataPoints": sorted_points,
                "source": "Merged (GitHub + Yahoo)"
            }
            return updated_data, True
        except Exception:
            return existing_data, False

    def get_historical_data(self, ticker, period="1y", force_update=False):
        ticker = ticker.upper()
        cache_path = self._get_cache_path(ticker)
        data = None
        needs_save = False
        
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r') as f:
                    data = json.load(f)
            except:
                data = None
        
        if not data:
            csv_text = self.download_stock_data(ticker)
            if csv_text:
                data = self.parse_csv_data(csv_text, ticker)
                needs_save = True
        
        if not data:
            return {"success": False, "error": f"Ticker {ticker} tidak ditemukan."}

        # Update data sampai hari ini
        mtime = datetime.fromtimestamp(os.path.getmtime(cache_path)) if os.path.exists(cache_path) else datetime.min
        if force_update or (datetime.now() - mtime > self.cache_ttl) or needs_save:
            data, was_updated = self.update_with_latest_yahoo(ticker, data)
            if was_updated: needs_save = True

        if needs_save:
            with open(cache_path, 'w') as f:
                json.dump(data, f, indent=2)
            meta = {
                "ticker": ticker, "lastUpdated": datetime.now().isoformat(),
                "endDate": data["endDate"]
            }
            with open(self._get_metadata_path(ticker), 'w') as f:
                json.dump(meta, f, indent=2)

        # Filter period
        all_points = data["dataPoints"]
        if not all_points: return {"success": False, "error": "No data points found."}
        
        end_date_str = data["endDate"].split('T')[0]
        try:
            end_dt = datetime.strptime(end_date_str, "%Y-%m-%d")
        except:
            end_dt = datetime.now()

        delta_map = {"1y": 365, "2y": 365*2, "5y": 365*5, "6m": 180, "3m": 90}
        start_dt = end_dt - timedelta(days=delta_map.get(period, 365))
        start_str = start_dt.strftime("%Y-%m-%d")
        filtered_points = [p for p in all_points if p["date"] >= start_str]

        return {
            "success": True, "ticker": ticker,
            "dataPoints": filtered_points,
            "startDate": filtered_points[0]["date"] if filtered_points else "",
            "endDate": filtered_points[-1]["date"] if filtered_points else "",
            "source": data.get("source", "Local")
        }

if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "BBCA"
    service = IDXDataService()
    print(f"Syncing {ticker}...")
    res = service.get_historical_data(ticker, period="all", force_update=True)
    if res["success"]:
        print(f"Berhasil! Data {ticker} kini sampai: {res['endDate']}")
    else:
        print(f"Gagal: {res.get('error')}")

import logging
import requests
import os
import subprocess
import re
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

class ScraperDriver:
    """Wrapper untuk WebDriver yang bisa fallback ke subprocess Chromium jika Selenium macet."""
    def __init__(self, driver=None):
        self.driver = driver
        self.use_shell = driver is None
        self.binary = "/data/data/com.termux/files/usr/bin/chromium-browser"
        self._current_url = ""

    def get(self, url):
        self._current_url = url
        if not self.use_shell:
            try:
                self.driver.get(url)
                return True
            except Exception as e:
                logging.warning(f"Selenium get gagal, mencoba shell fallback: {e}")
                self.use_shell = True
        return True

    @property
    def page_source(self):
        if self.use_shell:
            try:
                # Gunakan --dump-dom untuk mendapatkan HTML hasil render
                cmd = [self.binary, "--headless", "--no-sandbox", "--disable-gpu", "--dump-dom", self._current_url]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                return result.stdout
            except Exception as e:
                logging.error(f"Shell dump-dom gagal: {e}")
                return ""
        return self.driver.page_source

    def find_elements(self, by, value):
        if self.use_shell:
            source = self.page_source
            results = []
            if "a" in value or "title" in value:
                # Regex robust untuk mencari judul berita di Bing News
                patterns = [
                    r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                    r'<h3[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?</h3>'
                ]
                
                seen_links = set()
                for pattern in patterns:
                    matches = re.findall(pattern, source, re.DOTALL)
                    for match in matches:
                        link = match[0] if isinstance(match, tuple) else ""
                        content = match[1] if isinstance(match, tuple) else ""
                        
                        clean_title = re.sub(r'<[^>]+>', '', content).strip()
                        if clean_title and len(clean_title) > 25 and link not in seen_links:
                            if "http" in link and "bing.com/news" not in link:
                                results.append(DummyElement(clean_title, link))
                                seen_links.add(link)
                return results
            return []
        return self.driver.find_elements(by, value)

    def quit(self):
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass

class DummyElement:
    def __init__(self, text, href):
        self._text = text
        self.href = href
    def get_attribute(self, name):
        if name == "href": return self.href
        return ""
    @property
    def text(self):
        return self._text

def get_coingecko_data(symbol):
    """Ambil data realtime dan history dari CoinGecko (Hanya untuk Crypto)"""
    try:
        coingecko_ids = {
            "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
            "BNB": "binancecoin", "DOGE": "dogecoin", "PEPE": "pepe",
            "AVAX": "avalanche-2", "XRP": "ripple", "USDT": "tether"
        }
        
        coin_id = None
        for key in coingecko_ids:
            if key == symbol.upper() or f"{key}-" in symbol.upper() or f"{key}USDT" in symbol.upper():
                coin_id = coingecko_ids[key]
                break
        
        if not coin_id:
            return None, None, None

        price_url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd&include_24hr_change=true"
        price_res = requests.get(price_url, timeout=10).json()
        
        if coin_id in price_res:
            price = float(price_res[coin_id]['usd'])
            change = float(price_res[coin_id].get('usd_24h_change', 0))

            hist_url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart?vs_currency=usd&days=30&interval=daily"
            hist_res = requests.get(hist_url, timeout=10).json()
            history = [h[1] for h in hist_res['prices']]

            return price, change, history
    except Exception as e:
        logging.error(f"CoinGecko Error for {symbol}: {e}")
    return None, None, None

def scrape_stock_data(symbol, driver_not_used=None, is_indo=False):
    """Fungsi utama pengambil data (Sekarang 100% API, tanpa Selenium)"""
    price, change, history = get_coingecko_data(symbol)
    
    if price is not None:
        return {
            "symbol": symbol, "price": str(price), "change": str(round(change, 2)),
            "currency": "USD", "source": "CoinGecko API", "history": history
        }
    
    try:
        yf_symbol = symbol
        currency = "USD"
        if is_indo:
            currency = "IDR"
            if not yf_symbol.endswith(".JK"):
                yf_symbol = f"{symbol}.JK"
            
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_symbol}?interval=1d&range=30d"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'}, timeout=10).json()
        
        if 'chart' in res and res['chart']['result']:
            result = res['chart']['result'][0]
            meta = result['meta']
            current_price = meta.get('regularMarketPrice')
            
            # Extract history for technical analysis
            adj_close = []
            if 'indicators' in result and 'adjclose' in result['indicators']:
                adj_close = [p for p in result['indicators']['adjclose'][0].get('adjclose', []) if p is not None]
            elif 'indicators' in result and 'quote' in result['indicators']:
                adj_close = [p for p in result['indicators']['quote'][0].get('close', []) if p is not None]
                
            currency = meta.get('currency', currency)
            
            # Prioritaskan daily previous close dari history jika tersedia
            # (History[-1] adalah harga saat ini, history[-2] adalah penutupan sebelumnya)
            prev_close = None
            if len(adj_close) >= 2:
                prev_close = adj_close[-2]
            
            if not prev_close:
                prev_close = meta.get('regularMarketPreviousClose')
            if not prev_close:
                prev_close = meta.get('previousClose')
            if not prev_close:
                prev_close = meta.get('chartPreviousClose')
            
            calc_change = 0
            if current_price and prev_close:
                calc_change = ((current_price - prev_close) / prev_close) * 100
                
            return {
                "symbol": symbol, 
                "price": str(current_price),
                "change": str(round(calc_change, 2)), 
                "currency": currency,
                "source": "Yahoo Finance API", 
                "history": adj_close
            }
        else:
            logging.warning(f"Yahoo Finance returned empty result for {yf_symbol}")
            return {"symbol": symbol, "price": "0", "change": "0", "currency": currency, "history": []}
            
    except Exception as e:
        logging.error(f"Yahoo Finance Error for {symbol}: {e}")
        return {"symbol": symbol, "price": "0", "change": "0", "currency": currency, "history": []}

def get_driver():
    """Inisialisasi Selenium WebDriver dengan opsi Termux (Optimasi Stabilitas)."""
    os.environ["DBUS_SESSION_BUS_ADDRESS"] = "/dev/null"
    
    options = Options()
    options.binary_location = "/data/data/com.termux/files/usr/bin/chromium-browser"
    
    # Argumen minimal tapi esensial untuk Termux
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-features=VizDisplayCompositor")
    options.add_argument("--remote-debugging-port=9222")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36")
    
    try:
        chromedriver_path = "/data/data/com.termux/files/usr/bin/chromedriver"
        service = Service(executable_path=chromedriver_path)
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(20)
        logging.info("Selenium WebDriver berhasil diinisialisasi.")
        return ScraperDriver(driver)
    except Exception as e:
        logging.error(f"Gagal inisialisasi driver Selenium (Fallback Aktif): {e}")
        return ScraperDriver(None)
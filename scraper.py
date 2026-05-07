import logging
import aiohttp
import asyncio
import json
import logging
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
            if "a" in value or "h2" in value or "h3" in value:
                # Regex robust untuk mencari judul dan link di Bing
                patterns = [
                    r'<h2[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?</h2>',
                    r'<h3[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?</h3>',
                    r'<a[^>]+class="title"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                    r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>'
                ]
                
                seen_links = set()
                for pattern in patterns:
                    matches = re.findall(pattern, source, re.DOTALL)
                    for match in matches:
                        link = match[0] if isinstance(match, tuple) else ""
                        content = match[1] if isinstance(match, tuple) else ""
                        
                        clean_title = re.sub(r'<[^>]+>', '', content).strip()
                        # Judul web bisa lebih pendek dari berita, tapi kita tetap butuh yang informatif
                        if clean_title and len(clean_title) > 15 and link not in seen_links:
                            if "http" in link and "bing.com/search" not in link and "bing.com/images" not in link:
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

async def get_coingecko_data(symbol):
    """Ambil data realtime dan history dari CoinGecko (Hanya untuk Crypto) menggunakan aiohttp."""
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
            return None, None, [], [], ""

        async with aiohttp.ClientSession() as session:
            price_url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd&include_24hr_change=true"
            async with session.get(price_url, timeout=10) as response:
                price_res = await response.json()
            
            if coin_id in price_res:
                price = float(price_res[coin_id]['usd'])
                change = float(price_res[coin_id].get('usd_24h_change', 0))

                hist_url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart?vs_currency=usd&days=30&interval=daily"
                async with session.get(hist_url, timeout=10) as response:
                    hist_res = await response.json()
                history = [h[1] for h in hist_res['prices']]
                volumes = [v[1] for v in hist_res.get('total_volumes', [])]
                
                # Fetch basic info for context
                info_url = f"https://api.coingecko.com/api/v3/coins/{coin_id}?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false&sparkline=false"
                fundamental_context = ""
                async with session.get(info_url, timeout=10) as response:
                    info_res = await response.json()
                    market_data = info_res.get('market_data', {})
                    fundamental_context = f"Coin: {info_res.get('name')}. Supply: {market_data.get('circulating_supply')} / {market_data.get('total_supply')}. ATH: {market_data.get('ath', {}).get('usd')}. Low 24h: {market_data.get('low_24h', {}).get('usd')}."

                return price, change, history, volumes, fundamental_context
    except Exception as e:
        logging.error(f"CoinGecko Error for {symbol}: {e}")
    return None, None, [], [], ""

async def scrape_stock_data(symbol, driver_not_used=None, is_indo=False):
    """Fungsi utama pengambil data (Sekarang 100% Async API)"""
    price, change, history, volumes, fundamental_context = await get_coingecko_data(symbol)
    
    if price is not None:
        return {
            "symbol": symbol, "price": str(price), "change": str(round(change, 2)),
            "currency": "USD", "source": "CoinGecko API", "history": history, 
            "volumes": volumes, "fundamental_context": fundamental_context
        }
    
    original_symbol_upper = symbol.upper()
    symbols_to_try = [original_symbol_upper]
    
    if is_indo:
        if not original_symbol_upper.endswith(".JK"):
            symbols_to_try.insert(0, f"{original_symbol_upper}.JK")
    elif len(original_symbol_upper) == 4 and original_symbol_upper.isalpha() and '.' not in original_symbol_upper:
        symbols_to_try.append(f"{original_symbol_upper}.JK")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    async with aiohttp.ClientSession(headers=headers) as session:
        for current_symbol in symbols_to_try:
            try:
                # 1. Fetch Chart & Price
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{current_symbol}?interval=1d&range=90d"
                async with session.get(url, timeout=10) as response:
                    if response.status == 404:
                        continue
                    res = await response.json()
                
                if 'chart' in res and res['chart']['result']:
                    result = res['chart']['result'][0]
                    meta = result['meta']
                    current_price = meta.get('regularMarketPrice')
                    
                    if current_price is None:
                        continue
                        
                    # 2. Fetch Deep Fundamentals from Yahoo Modules (New)
                    deep_fund = ""
                    ratios = {}
                    try:
                        modules_url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{current_symbol}?modules=summaryDetail,defaultKeyStatistics,financialData"
                        async with session.get(modules_url, timeout=10) as mod_res:
                            mod_data = await mod_res.json()
                            if 'quoteSummary' in mod_data and mod_data['quoteSummary']['result']:
                                q_res = mod_data['quoteSummary']['result'][0]
                                s_det = q_res.get('summaryDetail', {})
                                k_stat = q_res.get('defaultKeyStatistics', {})
                                f_data = q_res.get('financialData', {})
                                
                                ratios = {
                                    "per": s_det.get('trailingPE', {}).get('fmt'),
                                    "pbv": k_stat.get('priceToBook', {}).get('fmt'),
                                    "roe": f_data.get('returnOnEquity', {}).get('fmt'),
                                    "der": f_data.get('debtToEquity', {}).get('fmt')
                                }
                                deep_fund = f"Fundamental Stats: P/E: {ratios['per']}, P/B: {ratios['pbv']}, ROE: {ratios['roe']}, DER: {ratios['der']}. "
                                deep_fund += f"Forward P/E: {s_det.get('forwardPE', {}).get('fmt')}. Dividend Yield: {s_det.get('dividendYield', {}).get('fmt')}."
                    except Exception as fe:
                        logging.warning(f"Failed to fetch deep fundamentals from Yahoo: {fe}")

                    stats = {
                        "high_52": meta.get('fiftyTwoWeekHigh'),
                        "low_52": meta.get('fiftyTwoWeekLow'),
                        "prev_close": meta.get('previousClose'),
                        "market_cap": meta.get('marketCap'),
                        "currency": meta.get('currency')
                    }
                    # (rest of volumes and adj_close logic ...)


                    adj_close = []
                    volumes = []
                    if 'indicators' in result and 'quote' in result['indicators']:
                        quotes = result['indicators']['quote'][0]
                        adj_close = [p for p in quotes.get('close', []) if p is not None]
                        volumes = [v for v in quotes.get('volume', []) if v is not None]
                    
                    if not adj_close and 'indicators' in result and 'adjclose' in result['indicators']:
                        adj_close = [p for p in result['indicators']['adjclose'][0].get('adjclose', []) if p is not None]
                        
                    currency = meta.get('currency', 'IDR' if is_indo else 'USD')
                    
                    prev_close = None
                    if len(adj_close) >= 2:
                        prev_close = adj_close[-2]
                    
                    if not prev_close:
                        prev_close = meta.get('regularMarketPreviousClose') or meta.get('previousClose') or meta.get('chartPreviousClose')
                    
                    calc_change = 0
                    if current_price and prev_close:
                        calc_change = ((current_price - prev_close) / prev_close) * 100
                        
                    return {
                        "symbol": symbol, 
                        "price": str(current_price),
                        "change": str(round(calc_change, 2)), 
                        "currency": currency,
                        "source": "Yahoo Finance API", 
                        "history": adj_close,
                        "volumes": volumes,
                        "stats": stats,
                        "fundamental_context": deep_fund,
                        "ratios": ratios
                    }
            except Exception as e:
                logging.warning(f"Error scraping {current_symbol}: {e}")
                continue

    return {"symbol": symbol, "price": "0", "change": "0", "currency": "IDR" if is_indo else "USD", "history": []}

async def get_macro_data():
    """
    Mengambil data makroekonomi penting: Kurs USD/IDR, BI Rate, dan Komoditas Utama.
    """
    macro_data = {
        "usd_idr": "N/A",
        "bi_rate": "N/A",
        "gold": "N/A",
        "oil": "N/A"
    }
    
    headers = {'User-Agent': 'Mozilla/5.0'}
    async with aiohttp.ClientSession(headers=headers) as session:
        # 1. USD/IDR from Yahoo Finance
        try:
            url = "https://query1.finance.yahoo.com/v8/finance/chart/IDR=X?interval=1d&range=1d"
            async with session.get(url, timeout=10) as res:
                data = await res.json()
                price = data['chart']['result'][0]['meta']['regularMarketPrice']
                macro_data["usd_idr"] = f"Rp {round(price, 2)}"
        except: pass

        # 2. Gold and Oil from Yahoo Finance
        commodities = {"gold": "GC=F", "oil": "CL=F"}
        for key, ticker in commodities.items():
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
                async with session.get(url, timeout=10) as res:
                    data = await res.json()
                    price = data['chart']['result'][0]['meta']['regularMarketPrice']
                    macro_data[key] = f"${round(price, 2)}"
            except: pass

    # 3. BI Rate using Bing Search (Improved Regex & Strategy)
    try:
        from bing_search_tool import search_bing
        # Gunakan query yang lebih mengarah ke berita resmi/data
        search_res = await search_bing("BI Rate terbaru 2024 2025 2026")
        import re
        
        # Regex yang lebih fleksibel untuk menangkap angka persentase (misal: 6.00%, 6,25%, 6.25 %)
        # Mencari pola angka yang diikuti tanda % atau kata "persen"
        matches = re.findall(r"(\d[,\.]\d{1,2})\s?%", search_res)
        
        if matches:
            # Ambil angka yang paling sering muncul atau yang pertama (biasanya yang terbaru)
            macro_data["bi_rate"] = f"{matches[0]}%"
        else:
            # Fallback 2: Cari angka yang didahului kata "menjadi" atau "sebesar"
            match_alt = re.search(r"(?:menjadi|sebesar|di level)\s*(\d[,\.]\d{1,2})", search_res, re.IGNORECASE)
            if match_alt:
                macro_data["bi_rate"] = f"{match_alt.group(1)}%"
            else:
                macro_data["bi_rate"] = "6.00% - 6.25% (Estimasi)"
    except Exception as e:
        logging.warning(f"Error fetching BI Rate: {e}")
        macro_data["bi_rate"] = "6.25% (Ref)"

    return macro_data

async def get_foreign_flow(symbol):
    """
    Mendapatkan data Net Foreign Buy/Sell (Bandarmology) untuk saham Indonesia.
    Menggunakan pencarian cerdas sebagai metode utama karena data ini sering di-render via JS dinamis.
    """
    clean_symbol = symbol.replace('.JK', '').replace('.jk', '').upper()
    try:
        from bing_search_tool import search_bing
        # Query spesifik untuk mendapatkan angka net foreign terbaru
        query = f"net foreign buy sell {clean_symbol} hari ini terbaru stockbit idnfinancials"
        search_res = await search_bing(query)
        
        return f"DATA FOREIGN FLOW (NET BUY/SELL):\n{search_res}"
    except Exception as e:
        logging.error(f"Error fetching foreign flow for {clean_symbol}: {e}")
        return "Data arus kas asing tidak tersedia."

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
    options.add_argument("--blink-settings=imagesEnabled=false") # Jangan load gambar (Hemat RAM/Waktu)
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")
    
    # Eager strategy: Jangan tunggu gambar/css penuh, cukup DOM siap langsung eksekusi
    options.page_load_strategy = 'eager'
    
    try:
        chromedriver_path = "/data/data/com.termux/files/usr/bin/chromedriver"
        service = Service(executable_path=chromedriver_path)
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(30) # Naikkan ke 30 detik untuk Termux
        logging.info("Selenium WebDriver berhasil diinisialisasi.")
        return ScraperDriver(driver)
    except Exception as e:
        logging.error(f"Gagal inisialisasi driver Selenium (Fallback Aktif): {e}")
        return ScraperDriver(None)

def scrape_idnfinancials(symbol):
    """
    Scrape company profile and financial data from IDNFinancials using Selenium and BeautifulSoup.
    Improved to handle asynchronous loading and added a search fallback.
    """
    clean_symbol = symbol.replace('.JK', '').replace('.jk', '').upper()
    try:
        driver = get_driver()
        driver.get(f"https://www.idnfinancials.com/id/{clean_symbol}")
        
        # Wait for the specific financial summary or profile to load
        import time
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        # Increase wait time and look for specific indicators of content
        try:
            # Wait for any table or specific ID to appear
            WebDriverWait(driver.driver, 15).until(
                EC.presence_of_element_located((By.ID, "tab-fin-ove"))
            )
            # Give a bit more time for AJAX to populate tables
            time.sleep(5)
        except:
            logging.warning(f"Timeout waiting for IDNFinancials content for {clean_symbol}")
        
        html = driver.page_source
        driver.quit()
        
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        
        if soup.body:
            # Remove noise
            for script in soup(["script", "style", "nav", "header", "footer", "aside"]):
                script.extract()
            
            # Target sections that are more likely to have ratios
            fin_section = soup.find(id="financial-data")
            fin_text = fin_section.get_text(separator=' ', strip=True) if fin_section else ""
            
            profile_section = soup.find(class_="company-detail")
            profile_text = profile_section.get_text(separator=' ', strip=True) if profile_section else ""
            
            tables = soup.find_all('table')
            table_text = "\n".join([t.get_text(separator=' ', strip=True) for t in tables])
            
            combined = f"DATA TABEL:\n{table_text}\n\nIKHTISAR KEUANGAN:\n{fin_text}\n\nPROFIL:\n{profile_text}"
            
            # If we still have very little data, trigger fallback
            if len(combined) < 500:
                raise ValueError("Content too short")
                
            return combined[:12000]
            
    except Exception as e:
        logging.error(f"IDNFinancials scraper failed for {clean_symbol}: {e}")
    
    # FALLBACK: Use Bing Search to find ratios
    try:
        logging.info(f"Using Search Fallback for {clean_symbol} fundamental ratios...")
        from bing_search_tool import search_bing
        search_query = f"rasio keuangan {clean_symbol} ROE PER PBV DER idnfinancials stockbit"
        search_results = asyncio.run(search_bing(search_query))
        return f"DATA FUNDAMENTAL DARI PENCARIAN (Fallback):\n{search_results}"
    except Exception as e:
        logging.error(f"Search fallback failed: {e}")
        return "Gagal mendapatkan data fundamental."
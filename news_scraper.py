import logging
import time
from selenium.webdriver.common.by import By

import requests
from bs4 import BeautifulSoup

def scrape_article_content(url):
    """Membaca isi konten dari sebuah URL artikel berita."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Hapus elemen yang tidak perlu (iklan, script, nav)
        for s in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
            s.decompose()
            
        # Ambil teks dari paragraf
        paragraphs = soup.find_all('p')
        content = " ".join([p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 30])
        
        # Batasi panjang karakter agar tidak overload (max 3000 karakter)
        return content[:3000]
    except Exception as e:
        logging.warning(f"Gagal membaca konten dari {url}: {e}")
        return ""

def scrape_news(symbol, driver, is_indo=False, custom_query=None, company_name=None):
    if custom_query:
        query = custom_query
    elif is_indo:
        # Bersihkan nama perusahaan dari embel-embel hukum agar pencarian berita lebih luas
        clean_name = company_name if company_name else ""
        for suffix in ["(Persero)", "Tbk", "Class A", "Class B", "Seri A", "Seri B"]:
            clean_name = clean_name.replace(suffix, "")
        clean_name = clean_name.strip()
        
        # Gunakan kombinasi nama bersih dan ticker
        if clean_name and clean_name != symbol:
            query = f'"{clean_name}" OR "saham {symbol}" terbaru hari ini'
        else:
            query = f"saham {symbol} terbaru hari ini"
        
    else:
        query = f"{symbol} stock market news"
        
    url = f"https://www.bing.com/news/search?q={query}&qft=interval%3D%227%22"
    
    logging.info(f"Scraping news for {symbol} (is_indo: {is_indo}) from Bing News: {query}")
    try:
        driver.get(url)
        # Mencari berbagai elemen yang mungkin berisi judul berita
        # Bing sering pakai 'a.title', 'h3 a', atau link dalam div 'news-card'
        selectors = ["a.title", "h3 a", "div.news-card-body a", "a[data-m]"]
        news_list = []
        seen_titles = set()
        
        for selector in selectors:
            try:
                articles = driver.find_elements(By.CSS_SELECTOR, selector)
                for article in articles:
                    title = article.text.strip()
                    link = article.get_attribute("href")
                    
                    if title and len(title) > 25 and "http" in link and title not in seen_titles:
                        # Filter out internal/useless links
                        if any(x in link for x in ["bing.com/news", "microsoft.com", "javascript:void(0)"]):
                            continue
                            
                        news_list.append({"title": title, "link": link})
                        seen_titles.add(title)
                        
                        if len(news_list) >= 8: break
                if len(news_list) >= 8: break
            except:
                continue
            
        if not news_list:
            logging.warning(f"No news found for {symbol} using Bing News.")
            
        return news_list

    except Exception as e:
        logging.error(f"Error scraping news for {symbol}: {e}")
    
    return []
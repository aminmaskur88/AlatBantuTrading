import logging
import time
from selenium.webdriver.common.by import By

import requests
from bs4 import BeautifulSoup

def scrape_article_content(url: str, max_chars: int = 6000) -> str:
    """
    Mengambil teks utama dari URL manapun, tidak terbatas pada artikel berita.
    Menghapus elemen navigasi, script, dll., dan mengembalikan teks dari body.
    Jika gagal, mengembalikan pesan error.
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        logging.info(f"Mencoba scraping umum untuk URL: {url}")
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Hapus elemen yang tidak relevan
        for element in soup(["script", "style", "header", "footer", "nav", "aside", "form", "button"]):
            element.decompose()
        
        body = soup.find('body')
        if not body:
            logging.warning(f"Tag <body> tidak ditemukan di URL: {url}")
            return f"Gagal memuat konten dari URL: Tag <body> tidak ditemukan."

        # Ambil teks dari body, gunakan spasi sebagai pemisah, dan bersihkan whitespace
        body_text = body.get_text(separator=' ', strip=True)

        if not body_text:
            logging.warning(f"Tidak ada teks yang bisa diekstrak dari URL: {url}")
            return f"Gagal memuat konten dari URL: Tidak ada teks yang bisa diekstrak."
            
        # Bersihkan spasi berlebih dan gabungkan menjadi satu baris
        cleaned_text = ' '.join(body_text.split())
        
        logging.info(f"Berhasil scrape {len(cleaned_text)} karakter dari {url}")
        return cleaned_text[:max_chars]

    except requests.exceptions.HTTPError as e:
        logging.error(f"HTTP Error saat scraping umum dari {url}: {e}")
        return f"Gagal memuat konten dari URL karena HTTP Error: {e.response.status_code}"
    except Exception as e:
        logging.error(f"Error saat scraping umum dari {url}: {e}")
        return f"Gagal memuat konten dari URL karena error teknis: {str(e)}"

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
        # Selector yang lebih spesifik untuk berita asli
        selectors = ["a.title", "h3 a", "div.news-card-body a", "div.t_t a", "div.news-card-content a"]
        news_list = []
        seen_titles = set()
        
        for selector in selectors:
            try:
                articles = driver.find_elements(By.CSS_SELECTOR, selector)
                for article in articles:
                    title = article.text.strip()
                    link = article.get_attribute("href")
                    
                    # Filter tambahan: Pastikan bukan kode JS/CSS
                    if any(char in title for char in ["{", "}", "function(", "var ", ".querySelectorAll", "=="]):
                        continue

                    if title and len(title) > 25 and "http" in link and title not in seen_titles:
                        # Filter out internal/useless links
                        if any(x in link for x in ["bing.com/news", "microsoft.com", "javascript:void(0)", "twitter.com", "facebook.com"]):
                            continue
                            
                        # Skor relevansi sederhana (semakin banyak kata kunci, semakin baik)
                        score = 0
                        keywords = [symbol.lower()]
                        if company_name:
                            keywords.extend(company_name.lower().split())
                        
                        for kw in keywords:
                            if len(kw) > 2 and kw in title.lower():
                                score += 1
                        
                        news_list.append({"title": title, "link": link, "score": score})
                        seen_titles.add(title)
                        
                if len(news_list) >= 15: break # Ambil lebih banyak dulu untuk di-sort
            except:
                continue
            
        if not news_list:
            logging.warning(f"No news found for {symbol} using Bing News.")
            
        # Sort berdasarkan skor relevansi
        news_list.sort(key=lambda x: x['score'], reverse=True)
        return news_list[:10] # Ambil 10 terbaik

    except Exception as e:
        logging.error(f"Error scraping news for {symbol}: {e}")
    
    return []
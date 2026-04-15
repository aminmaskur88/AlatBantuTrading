import logging
import time
import urllib.parse
from selenium.webdriver.common.by import By
from scraper import get_driver

def search_bing(query):
    """
    Melakukan pencarian di Bing menggunakan Chromium (via ScraperDriver) dan mengembalikan 5 hasil teratas.
    """
    driver = None
    try:
        driver = get_driver() # Mengembalikan ScraperDriver (bisa Selenium atau shell)
        encoded_query = urllib.parse.quote_plus(query)
        url = f"https://www.bing.com/news/search?q={encoded_query}&qft=interval%3D%228%22"
        
        logging.info(f"AI menjalankan pencarian Berita Bing via Chromium: '{query}'")
        driver.get(url)
        time.sleep(3)
        
        selectors = ["a.title", "h3 a", "div.news-card-body a"]
        extracted = []
        seen_titles = set()
        
        for selector in selectors:
            try:
                results = driver.find_elements(By.CSS_SELECTOR, selector)
                for res in results:
                    title = res.text.strip()
                    link = res.get_attribute("href")
                    if title and len(title) > 20 and title not in seen_titles:
                        if "bing.com/news" in link: continue
                        extracted.append({
                            "title": title,
                            "link": link
                        })
                        seen_titles.add(title)
                    if len(extracted) >= 5: break
                if len(extracted) >= 5: break
            except:
                continue
                
        return extracted
    except Exception as e:
        logging.error(f"Error pada tool pencarian Bing: {e}")
        return [{"error": str(e)}]
    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":
    # Test
    res = search_bing("Harga emas hari ini")
    print(res)

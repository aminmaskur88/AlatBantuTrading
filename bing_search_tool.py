import logging
import time
import urllib.parse
from selenium.webdriver.common.by import By
from scraper import get_driver

def search_bing(query, search_type="web"):
    """
    Melakukan pencarian di Bing menggunakan Chromium (via ScraperDriver) dan mengembalikan 5 hasil teratas.
    search_type: "web" (default) atau "news"
    """
    driver = None
    try:
        driver = get_driver() # Mengembalikan ScraperDriver (bisa Selenium atau shell)
        encoded_query = urllib.parse.quote_plus(query)
        
        if search_type == "news":
            url = f"https://www.bing.com/news/search?q={encoded_query}&qft=interval%3D%228%22"
        else:
            url = f"https://www.bing.com/search?q={encoded_query}"
        
        logging.info(f"AI menjalankan pencarian {search_type} Bing via Chromium: '{query}'")
        driver.get(url)
        time.sleep(3)
        
        # Selectors for both web and news
        selectors = [
            "li.b_algo h2 a",      # General Web
            "a.title",             # News
            "h3 a",                # Both
            "div.news-card-body a" # News
        ]
        extracted = []
        seen_links = set()
        
        for selector in selectors:
            try:
                results = driver.find_elements(By.CSS_SELECTOR, selector)
                for res in results:
                    title = res.text.strip()
                    link = res.get_attribute("href")
                    
                    if not link or "http" not in link: continue
                    if "bing.com/" in link and "/search" in link: continue
                    
                    if title and len(title) > 10 and link not in seen_links:
                        extracted.append({
                            "title": title,
                            "link": link
                        })
                        seen_links.add(link)
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

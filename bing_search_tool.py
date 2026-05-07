import logging
import aiohttp
import asyncio
import re
from bs4 import BeautifulSoup

async def search_bing(query, search_type="web"):
    """
    Mencari informasi di Bing secara asinkron tanpa Selenium.
    """
    if search_type == "news":
        url = f"https://www.bing.com/news/search?q={query}"
    else:
        url = f"https://www.bing.com/search?q={query}"
        
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=10) as response:
                html = await response.text()
                
        soup = BeautifulSoup(html, 'html.parser')
        results = []
        
        if search_type == "news":
            selectors = ["a.title", "h3 a"]
        else:
            selectors = ["li.b_algo h2 a", "li.b_algo h3 a"]
            
        for sel in selectors:
            for item in soup.select(sel):
                text = item.get_text().strip()
                link = item.get('href', '')
                if text and link.startswith("http"):
                    results.append(f"- {text}: {link}")
                    
        if not results:
            # Fallback regex if selectors fail
            links = re.findall(r'href="(https?://[^"]+)"', html)
            for link in links[:5]:
                if "bing.com" not in link and "microsoft.com" not in link:
                    results.append(f"- Link Terkait: {link}")
                    
        return "\n".join(results[:10]) if results else "Tidak ada hasil ditemukan."
    except Exception as e:
        logging.error(f"Error async search_bing: {e}")
        return f"Error melakukan pencarian: {str(e)}"

if __name__ == "__main__":
    # Test
    res = search_bing("Harga emas hari ini")
    print(res)

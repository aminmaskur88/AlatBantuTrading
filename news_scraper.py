import logging
import time
import aiohttp
import asyncio
from bs4 import BeautifulSoup

async def scrape_article_content(url: str, max_chars: int = 6000) -> str:
    """
    Mengambil teks utama dari URL secara asinkron.
    Menghapus elemen navigasi, script, dll.
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
        logging.info(f"Mencoba scraping asinkron untuk URL: {url}")
        
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=20) as response:
                response.raise_for_status()
                html = await response.text()
        
        soup = BeautifulSoup(html, 'html.parser')
        
        for element in soup(["script", "style", "header", "footer", "nav", "aside", "form", "button"]):
            element.decompose()
        
        body = soup.find('body')
        if not body:
            return f"Gagal memuat konten dari URL: Tag <body> tidak ditemukan."

        body_text = body.get_text(separator=' ', strip=True)
        cleaned_text = ' '.join(body_text.split())
        
        return cleaned_text[:max_chars]

    except Exception as e:
        logging.error(f"Error asinkron scraping {url}: {e}")
        return f"Gagal memuat konten dari URL karena error: {str(e)}"

async def summarize_top_news(news_list, max_articles=3):
    """
    Mengambil isi konten dari top N berita dan menggabungkannya untuk dianalisis AI.
    """
    if not news_list:
        return ""
    
    top_news = news_list[:max_articles]
    tasks = [scrape_article_content(n['link']) for n in top_news if n.get('link')]
    
    if not tasks:
        return ""
        
    contents = await asyncio.gather(*tasks)
    
    summary_parts = []
    for i, content in enumerate(contents):
        if content and not content.startswith("Gagal memuat"):
            title = top_news[i]['title']
            date = top_news[i].get('date', 'Baru-baru ini')
            # Limit each article to 2000 chars for the summary prompt
            summary_parts.append(f"BERITA: {title}\nDI-POSTING: {date}\nISI KONTEN: {content[:2000]}...")
            
    return "\n\n---\n\n".join(summary_parts)

async def scrape_news(symbol, driver=None, is_indo=False, custom_query=None, company_name=None):
    """
    Mencari berita secara asinkron tanpa Selenium (menggunakan aiohttp).
    """
    if custom_query:
        query = custom_query
    elif is_indo:
        clean_name = company_name if company_name else ""
        for suffix in ["(Persero)", "Tbk", "Class A", "Class B", "Seri A", "Seri B"]:
            clean_name = clean_name.replace(suffix, "")
        clean_name = clean_name.strip()
        
        if clean_name and clean_name != symbol:
            query = f'"{clean_name}" OR "saham {symbol}" terbaru hari ini'
        else:
            query = f"saham {symbol} terbaru hari ini"
    else:
        query = f"{symbol} stock market news"
        
    url = f"https://www.bing.com/news/search?q={query}&qft=interval%3D%227%22"
    
    logging.info(f"Async scraping news for {symbol} from Bing: {query}")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=15) as response:
                html = await response.text()
        
        soup = BeautifulSoup(html, 'html.parser')
        news_list = []
        seen_titles = set()
        
        # Bing News selectors (asinkron BeautifulSoup lebih cepat dari Selenium)
        articles = soup.select("div.news-card, div.infocard, .news-item")
        if not articles: # Fallback to generic links if card structure fails
             selectors = ["a.title", "h3 a", "div.news-card-body a", "div.t_t a", "div.news-card-content a"]
             for sel in selectors:
                for article_link in soup.select(sel):
                    title = article_link.get_text().strip()
                    link = article_link.get('href', '')
                    # Simple date search in parent
                    parent = article_link.find_parent('div')
                    date_text = "Baru-baru ini"
                    if parent:
                        date_el = parent.find(class_=re.compile(r'time|date|tm')) or parent.find('span', string=re.compile(r'ago|jam|hari|menit'))
                        if date_el: date_text = date_el.get_text().strip()
                    
                    if title and len(title) > 25 and link.startswith("http") and title not in seen_titles:
                        news_list.append({"title": title, "link": link, "date": date_text, "score": 0})
                        seen_titles.add(title)
        else:
            for article in articles:
                title_el = article.select_one("a.title, h3 a, h4 a")
                if not title_el: continue
                
                title = title_el.get_text().strip()
                link = title_el.get('href', '')
                
                # Extract date/time
                date_el = article.select_one("span.sn_tm, .metadata span, .news-card-footer span, .time")
                date_text = date_el.get_text().strip() if date_el else "Baru-baru ini"

                if title and len(title) > 25 and link.startswith("http") and title not in seen_titles:
                    if any(x in link for x in ["bing.com/news", "microsoft.com"]): continue
                    news_list.append({"title": title, "link": link, "date": date_text, "score": 0})
                    seen_titles.add(title)

        # Re-calculate scores with keywords
        for item in news_list:
            score = 0
            keywords = [symbol.lower()]
            if company_name: keywords.extend(company_name.lower().split())
            for kw in keywords:
                if len(kw) > 2 and kw in item['title'].lower(): score += 1
            item['score'] = score

        news_list.sort(key=lambda x: x['score'], reverse=True)
        return news_list[:10]

    except Exception as e:
        logging.error(f"Error async news scraping {symbol}: {e}")
    
    return []
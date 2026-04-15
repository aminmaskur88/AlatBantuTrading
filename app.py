from flask import Flask, render_template, request, jsonify
import logging
import time
import datetime
import csv
from utils import setup_logging, save_json, get_api_keys
from scraper import get_driver, scrape_stock_data
from news_scraper import scrape_news
from formatter import clean_data, enrich_data
from ai_analyzer import analyze_with_gemini, chat_with_gemini

app = Flask(__name__)
setup_logging()

# Load all stocks for reference
all_stocks = {}
try:
    with open("indonesia.csv", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            all_stocks[row["ticker"].upper()] = row["name"]
except FileNotFoundError:
    logging.warning("indonesia.csv tidak ditemukan, validasi nama perusahaan dilewati.")

# Store chat histories per session/symbol
chat_sessions = {}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/analyze", methods=["POST"])
def analyze():
    data = request.json
    symbol = data.get("symbol", "").strip().upper()
    
    if not symbol:
        return jsonify({"error": "Kode saham tidak boleh kosong"}), 400

    company_name = all_stocks.get(symbol, "Perusahaan Tidak Diketahui")
    api_keys = get_api_keys()
    
    if not api_keys:
        return jsonify({"error": "API Key tidak ditemukan"}), 500

    driver = None
    try:
        logging.info(f"Mulai analisis web untuk: {symbol} ({company_name})")
        driver = get_driver()
        
        # Scrape
        is_indo = symbol in all_stocks
        raw_data = scrape_stock_data(symbol, driver, is_indo=is_indo)
        news = scrape_news(symbol, driver, is_indo=is_indo, company_name=company_name)
        raw_data["news"] = news
        raw_data["company_name"] = company_name
        
        save_json(f"data/raw/{symbol}.json", raw_data)
        
        # Format
        cleaned = clean_data(raw_data)
        save_json(f"data/clean/{symbol}.json", cleaned)
        enriched = enrich_data(cleaned)
        
        # AI
        logging.info(f"Mengirim data {symbol} ke Gemini API...")
        ai_result = None
        retry = 0
        while not ai_result and retry < 3:
            ai_result = analyze_with_gemini(api_keys, enriched)
            if not ai_result:
                retry += 1
                logging.warning(f"AI gagal, retry ({retry}/3)...")
                time.sleep(2)
        
        if not ai_result:
            return jsonify({"error": "Gagal mendapatkan hasil AI"}), 500
            
        final_result = {
            "timestamp": datetime.datetime.now().isoformat(),
            "data": enriched,
            "ai_result": ai_result
        }
        save_json(f"data/result/{symbol}.json", final_result)
        
        # Setup Chat Context
        import json
        initial_context = f"Kita sedang membahas saham {symbol} ({company_name}). Harga: {enriched.get('price')}. Tren: {enriched.get('market_trend')}. Sentimen: {enriched.get('sentiment')}. Berita: {json.dumps(enriched.get('news', []))}."
        chat_sessions[symbol] = [
            {"role": "user", "parts": [{"text": initial_context}]},
            {"role": "model", "parts": [{"text": "Baik, saya mengerti konteks saham ini. Silakan tanyakan apa saja."}]}
        ]
        
        return jsonify(final_result)
        
    except Exception as e:
        logging.error(f"Error di backend: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        if driver:
            driver.quit()

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    symbol = data.get("symbol", "").strip().upper()
    message = data.get("message", "").strip()
    
    if not symbol or not message:
        return jsonify({"error": "Invalid request"}), 400
        
    history = chat_sessions.get(symbol)
    if not history:
        return jsonify({"error": "Sesi chat untuk saham ini belum dimulai. Silakan analisis ulang terlebih dahulu."}), 404
        
    api_keys = get_api_keys()
    if not api_keys:
        return jsonify({"error": "API Key tidak ditemukan"}), 500
        
    try:
        ai_reply, updated_history = chat_with_gemini(api_keys, history, message)
        chat_sessions[symbol] = updated_history
        return jsonify({"reply": ai_reply})
    except Exception as e:
         return jsonify({"error": str(e)}), 500

@app.route("/api/more_news", methods=["POST"])
def more_news():
    logging.info("Request masuk ke /api/more_news")
    data = request.json
    symbol = data.get("symbol", "").strip().upper()
    
    if not symbol:
        return jsonify({"error": "Kode saham tidak boleh kosong"}), 400

    api_keys = get_api_keys()
    if not api_keys:
        return jsonify({"error": "API Key tidak ditemukan"}), 500

    driver = None
    try:
        logging.info(f"Mulai Auto-Research Mendalam untuk: {symbol}")
        driver = get_driver()
        
        is_indo = symbol in all_stocks
        company_name = all_stocks.get(symbol, symbol)
        
        # 1. Cari berita tambahan dengan query bervariasi
        if is_indo:
            variant_query = f'berita terbaru "saham {symbol}" "{company_name}" prospek analisa'
        else:
            variant_query = f"latest {symbol} {company_name} stock news price analysis"
            
        news = scrape_news(symbol, driver, is_indo=is_indo, custom_query=variant_query)
        
        # 2. DEEP READING: Baca isi tiap artikel
        from news_scraper import scrape_article_content
        article_contents = []
        for n in news[:3]: # Baca 3 berita teratas agar tidak terlalu lama
            if n.get('link'):
                logging.info(f"Deep Reading: {n['link']}")
                content = scrape_article_content(n['link'])
                if content:
                    article_contents.append(f"SUMBER: {n['title']}\nISI: {content}")
        
        history = chat_sessions.get(symbol)
        if not history:
             return jsonify({"error": "Sesi chat tidak ditemukan"}), 404

        # 3. Kirim hasil Deep Reading ke Gemini untuk diringkas dan diolah
        all_news_text = "\n\n---\n\n".join(article_contents)
        prompt_1 = (
            f"Saya telah membaca isi dari {len(article_contents)} berita terbaru untuk {symbol}. "
            f"Berikut isi teks mentahnya:\n\n{all_news_text}\n\n"
            "Tugasmu:\n"
            "1. Ringkas poin-poin paling krusial dari berita tersebut (buang 'sampah' informasi).\n"
            "2. Berdasarkan ringkasan ini, sebutkan 2-3 data spesifik lain yang masih kamu butuhkan (misal: rasio keuangan tertentu)."
        )
        
        summary_reply, history = chat_with_gemini(api_keys, history, prompt_1)
        
        # 4. OTOMATIS: Riset Lanjutan (Sesuai permintaan Gemini)
        import re
        search_queries = re.findall(r'^- (.*)', summary_reply, re.MULTILINE)
        
        research_results = []
        if search_queries:
            from bing_search_tool import search_bing
            for q in search_queries[:2]:
                query = f"{symbol} {q}"
                res = search_bing(query)
                research_results.append(f"INFO '{q}':\n{res}")

        # 5. Final: Minta Gemini Output JSON + Chat Reply Akhir
        ai_result = None
        display_reply = summary_reply
        
        if research_results:
            final_research_data = "\n\n".join(research_results)
            prompt_2 = (
                f"HASIL RISET LANJUTAN:\n{final_research_data}\n\n"
                "Sekarang berikan ANALISA FINAL yang tajam. Kamu WAJIB memberikan respon dalam format JSON di akhir pesanmu "
                "dengan tag <JSON>...</JSON> agar saya bisa update dashboard. "
                "JSON harus mencerminkan analisa terbaru dari isi web yang dibaca tadi."
            )
            final_ai_reply, history = chat_with_gemini(api_keys, history, prompt_2)
            chat_sessions[symbol] = history
            
            json_match = re.search(r'<JSON>(.*?)</JSON>', final_ai_reply, re.DOTALL)
            if not json_match:
                json_match = re.search(r'(\{.*?\})', final_ai_reply, re.DOTALL)
            
            if json_match:
                try:
                    import json
                    ai_result = json.loads(json_match.group(1))
                    display_reply = f"<b>Ringkasan Isi Berita:</b><br>{summary_reply}<br><br><b>Analisis Final:</b><br>{final_ai_reply.replace(json_match.group(0), '').strip()}"
                except:
                    display_reply = final_ai_reply
            else:
                display_reply = final_ai_reply

        return jsonify({
            "news": news,
            "ai_reply": display_reply,
            "ai_result": ai_result
        })
        
    except Exception as e:
        logging.error(f"Error Auto-Research: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
import logging
import asyncio
import datetime
import csv
import json
import sqlite3
import os
from utils import setup_logging, save_json, get_api_keys
from scraper import get_driver, scrape_stock_data, scrape_idnfinancials, get_macro_data, get_foreign_flow
from news_scraper import scrape_news, summarize_top_news
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

# Store chat histories per session/symbol using SQLite
os.makedirs('data', exist_ok=True)
def init_db():
    conn = sqlite3.connect('data/chat.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS chat_sessions (symbol TEXT PRIMARY KEY, history TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS analysis_results (symbol TEXT PRIMARY KEY, result TEXT, updated_at DATETIME)''')
    c.execute('''CREATE TABLE IF NOT EXISTS news_archive (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, url TEXT, title TEXT, added_at DATETIME)''')
    conn.commit()
    conn.close()

init_db()

# --- DATABASE HELPERS ---

def get_analysis_result(symbol):
    try:
        conn = sqlite3.connect('data/chat.db', check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT result FROM analysis_results WHERE symbol=?", (symbol,))
        row = c.fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
    except Exception as e:
        logging.error(f"DB Error getting analysis: {e}")
    return None

def save_analysis_result(symbol, result):
    try:
        conn = sqlite3.connect('data/chat.db', check_same_thread=False)
        c = conn.cursor()
        c.execute("REPLACE INTO analysis_results (symbol, result, updated_at) VALUES (?, ?, ?)", 
                  (symbol, json.dumps(result), datetime.datetime.now().isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"DB Error saving analysis: {e}")

def get_chat_history(symbol):
    try:
        conn = sqlite3.connect('data/chat.db', check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT history FROM chat_sessions WHERE symbol=?", (symbol,))
        row = c.fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
    except Exception as e:
        logging.error(f"DB Error: {e}")
    return None

def save_chat_history(symbol, history):
    try:
        conn = sqlite3.connect('data/chat.db', check_same_thread=False)
        c = conn.cursor()
        c.execute("REPLACE INTO chat_sessions (symbol, history) VALUES (?, ?)", (symbol, json.dumps(history)))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"DB Error: {e}")

def clear_chat_history(symbol):
    try:
        conn = sqlite3.connect('data/chat.db', check_same_thread=False)
        c = conn.cursor()
        c.execute("DELETE FROM chat_sessions WHERE symbol=?", (symbol,))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"DB Error: {e}")

def save_news_archive(symbol, url, title=""):
    try:
        conn = sqlite3.connect('data/chat.db', check_same_thread=False)
        c = conn.cursor()
        c.execute("INSERT INTO news_archive (symbol, url, title, added_at) VALUES (?, ?, ?, ?)", 
                  (symbol, url, title, datetime.datetime.now().isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"DB Error saving news archive: {e}")

def get_news_archive(symbol):
    try:
        conn = sqlite3.connect('data/chat.db', check_same_thread=False)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM news_archive WHERE symbol=? ORDER BY added_at DESC", (symbol,))
        rows = c.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        logging.error(f"DB Error getting news archive: {e}")
    return []

# --- CORE LOGIC ---

async def run_full_analysis(symbol):
    """Runs the full analysis pipeline for a given stock symbol asynchronously."""
    company_name = all_stocks.get(symbol, "Perusahaan Tidak Diketahui")
    api_keys = get_api_keys()
    
    if not api_keys:
        raise ConnectionError("API Key tidak ditemukan")

    logging.info(f"Mulai analisis web (Async) untuk: {symbol} ({company_name})")
    is_indo = symbol in all_stocks
    
    # PARALLEL FETCH: Ambil data harga, berita, dan makro secara bersamaan
    raw_data_task = scrape_stock_data(symbol, is_indo=is_indo)
    news_task = scrape_news(symbol, is_indo=is_indo, company_name=company_name)
    macro_task = get_macro_data()
    
    raw_data, news, macro = await asyncio.gather(raw_data_task, news_task, macro_task)
    
    # NEW: Fetch Deep Fundamental Data for Indo Stocks
    idn_data_task = asyncio.to_thread(scrape_idnfinancials, symbol) if is_indo else asyncio.sleep(0, result="")
    
    # NEW: Deep Reading - Summarize top news contents
    deep_news_task = summarize_top_news(news)
    
    # NEW: Fetch Foreign Flow (Bandarmology) for Indo Stocks
    foreign_task = get_foreign_flow(symbol) if is_indo else asyncio.sleep(0, result="Data foreign flow hanya tersedia untuk saham Indonesia.")
    
    idn_data, deep_news_context, foreign_data = await asyncio.gather(idn_data_task, deep_news_task, foreign_task)

    raw_data["news"] = news
    raw_data["company_name"] = company_name
    raw_data["symbol"] = symbol
    raw_data["fundamental_context"] = idn_data
    raw_data["deep_news_context"] = deep_news_context
    raw_data["macro_data"] = macro
    raw_data["foreign_flow"] = foreign_data
    
    save_json(f"data/raw/{symbol}.json", raw_data)
    
    cleaned = clean_data(raw_data)
    save_json(f"data/clean/{symbol}.json", cleaned)
    enriched = enrich_data(cleaned)
    enriched["macro_data"] = macro 
    enriched["foreign_flow"] = foreign_data
    
    history = get_chat_history(symbol)
    
    logging.info(f"Mengirim data {symbol} ke Gemini API (Async)...")
    ai_result = None
    retry = 0
    while not ai_result and retry < 3:
        ai_result = await analyze_with_gemini(api_keys, enriched, history=history)
        if not ai_result:
            retry += 1
            logging.warning(f"AI gagal, retry ({retry}/3)...")
            await asyncio.sleep(2)
    
    if not ai_result:
        raise RuntimeError("Gagal mendapatkan hasil AI setelah beberapa kali mencoba")
        
    final_result = {
        "timestamp": datetime.datetime.now().isoformat(),
        "data": enriched,
        "ai_result": ai_result
    }
    save_json(f"data/result/{symbol}.json", final_result)
    save_analysis_result(symbol, final_result)
    
    # Setup Chat Context
    now_str = datetime.datetime.now().strftime("%A, %d %B %Y %H:%M:%S")
    profile_info = f"Nama: {company_name}. Ticker: {symbol}."
    if is_indo:
        profile_info += f" Ini adalah perusahaan yang terdaftar di Bursa Efek Indonesia (BEI)."
    
    initial_context = (
        f"WAKTU SEKARANG: {now_str}\n"
        f"Konteks Analisis: {profile_info}\n"
        f"Data Pasar Saat Ini: Harga {enriched.get('price')} ({enriched.get('change')}%). Tren {enriched.get('market_trend')}, Sentimen {enriched.get('sentiment')}.\n"
        f"Indikator Teknikal: Support1: {enriched.get('support_1')}, Resistance1: {enriched.get('resistance_1')}, BB Upper: {enriched.get('bb_upper')}, BB Lower: {enriched.get('bb_lower')}, MACD: {enriched.get('macd')}.\n"
        f"Fibonacci (90D): 61.8%: {enriched.get('fib_618')}, 50%: {enriched.get('fib_500')}, 38.2%: {enriched.get('fib_382')}.\n"
        f"Fundamental/Stats: High 52W: {enriched.get('stats', {}).get('high_52')}, Low 52W: {enriched.get('stats', {}).get('low_52')}, Cap: {enriched.get('stats', {}).get('market_cap')}.\n"
        f"Berita Terbaru: {json.dumps(enriched.get('news', []))}.\n"
        "Tugasmu adalah menjadi analis saham profesional. Gunakan data teknikal dan fundamental presisi di atas. JANGAN katakan kamu tidak bisa atau tidak punya info hari ini, karena data di atas adalah data TERBARU (real-time)."
    )

    existing_history = get_chat_history(symbol)
    now_time = datetime.datetime.now().strftime("%H:%M")
    
    if existing_history:
        # Cari pesan konteks terakhir dan perbarui, atau tambahkan pesan update baru
        # Agar tidak menghapus history tanya jawab user
        update_msg = {"role": "user", "time": now_time, "parts": [{"text": f"[PEMBERITAHUAN SISTEM]: Data pasar telah diperbarui secara real-time.\n{initial_context}"}]}
        model_ack = {"role": "model", "time": now_time, "parts": [{"text": "Sistem: Saya telah menerima data pasar terbaru. Silakan ajukan pertanyaan berdasarkan kondisi saat ini."}]}
        
        # Tambahkan ke history yang sudah ada tanpa menghapus yang lama
        existing_history.append(update_msg)
        existing_history.append(model_ack)
        save_chat_history(symbol, existing_history)
    else:
        # Jika benar-benar baru
        save_chat_history(symbol, [
            {"role": "user", "time": now_time, "parts": [{"text": initial_context}]},
            {"role": "model", "time": now_time, "parts": [{"text": "Baik, saya mengerti konteks saham ini. Silakan tanyakan apa saja."}]}
        ])
    
    return final_result

# --- ROUTES ---

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/news_archive", methods=["POST"])
async def add_news_archive():
    data = request.json
    symbol = data.get("symbol", "").strip().upper()
    url = data.get("url", "").strip()
    title = data.get("title", "").strip()
    if not symbol or not url:
        return jsonify({"error": "Symbol dan URL tidak boleh kosong"}), 400
    save_news_archive(symbol, url, title)
    return jsonify({"status": "ok", "message": "URL berhasil diarsipkan"})

@app.route("/api/news_archive/<symbol>", methods=["GET"])
async def list_news_archive(symbol):
    symbol = symbol.upper()
    archives = get_news_archive(symbol)
    return jsonify({"archives": archives})

@app.route("/api/news_archive/<int:archive_id>", methods=["DELETE"])
def delete_news_archive(archive_id):
    try:
        conn = sqlite3.connect('data/chat.db', check_same_thread=False)
        c = conn.cursor()
        c.execute("DELETE FROM news_archive WHERE id=?", (archive_id,))
        conn.commit()
        conn.close()
        return jsonify({"status": "ok", "message": "Arsip berhasil dihapus"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/analyze", methods=["POST"])
async def analyze():
    data = request.json
    symbol = data.get("symbol", "").strip().upper()
    if not symbol:
        return jsonify({"error": "Kode saham tidak boleh kosong"}), 400
    try:
        final_result = await run_full_analysis(symbol)
        return jsonify(final_result)
    except Exception as e:
        logging.error(f"Error di backend saat analisis {symbol}: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/chat", methods=["POST"])
async def chat():
    data = request.json
    symbol = data.get("symbol", "").strip().upper() or "GENERAL"
    message = data.get("message", "").strip()
    client_history = data.get("history")
    if not message:
        return jsonify({"error": "Pesan tidak boleh kosong"}), 400

    def generate_chat_stream():
        async def stream():
            history = client_history if client_history else get_chat_history(symbol)
            if not history:
                if symbol == "GENERAL":
                    now_str = datetime.datetime.now().strftime("%A, %d %B %Y %H:%M:%S")
                    history = [
                        {"role": "user", "parts": [{"text": f"WAKTU SEKARANG: {now_str}\nKamu adalah asisten AI serba bisa yang terintegrasi dengan mesin pencari. Kamu bisa membantu menjawab pertanyaan apa saja, melakukan riset di internet, dan memberikan analisis. Gunakan Bahasa Indonesia."}]},
                        {"role": "model", "parts": [{"text": "Halo! Saya asisten AI Anda. Ada yang bisa saya bantu hari ini? Saya bisa mencari informasi apa pun di internet untuk Anda."}]}
                    ]
                    save_chat_history("GENERAL", history)
                else:
                    yield f"data: {json.dumps({'status': 'Error: Sesi chat belum dimulai.', 'error': 'Sesi chat belum dimulai.', 'done': True})}\n\n"
                    return
                
            api_keys = get_api_keys()
            if not api_keys:
                yield f"data: {json.dumps({'status': 'Error: API Key tidak ditemukan.', 'error': 'API Key tidak ditemukan.', 'done': True})}\n\n"
                return

            processed_message = message
            try:
                import re
                urls = re.findall(r'((?:https?://|www\.)[^\s]+)', message)
                if urls:
                    yield f"data: {json.dumps({'status': 'Sistem: URL terdeteksi. Mengambil konten secara asinkron...'})}\n\n"
                    extracted_contents = []
                    from news_scraper import scrape_article_content
                    tasks = [scrape_article_content(url if url.startswith('http') else f'http://{url}') for url in urls]
                    results = await asyncio.gather(*tasks)
                    for i, content in enumerate(results):
                        extracted_contents.append(f"KONTEN DARI URL {urls[i]}:\n{content[:3000]}")
                    processed_message = f"{message}\n\n[Sistem: Konten URL terlampir]\n" + "\n\n".join(extracted_contents)

                if "arsip" in message.lower() and symbol != "GENERAL":
                    archives = get_news_archive(symbol)
                    if archives:
                        archive_text = "\n".join([f"- {a['title']} ({a['url']})" for a in archives])
                        processed_message += f"\n\n[Sistem: Pengguna menanyakan arsip berita. Berikut adalah daftar URL arsip yang tersimpan untuk {symbol}:\n{archive_text}\nSebutkan arsip ini kepada pengguna dan tanyakan apakah mereka ingin Anda menganalisis salah satu dari tautan tersebut secara mendalam.]"
                    else:
                        processed_message += f"\n\n[Sistem: Pengguna menanyakan arsip, namun saat ini belum ada arsip berita yang tersimpan untuk {symbol}. Beritahu pengguna.]"

                async for update in chat_with_gemini(api_keys, history, processed_message):
                    if "status" in update:
                        yield f"data: {json.dumps({'status': update['status']})}\n\n"
                    if "reply" in update:
                        save_chat_history(symbol, update["history"])
                        yield f"data: {json.dumps({'reply': update['reply'], 'history': update['history'], 'done': True})}\n\n"
            except Exception as e:
                logging.error(f"Error di backend chat stream: {str(e)}")
                yield f"data: {json.dumps({'status': f'Error: {str(e)}', 'error': str(e), 'done': True})}\n\n"
        
        loop = asyncio.new_event_loop()
        gen = stream()
        try:
            while True:
                try:
                    val = loop.run_until_complete(gen.__anext__())
                    yield val
                except StopAsyncIteration:
                    break
        finally:
            loop.close()

    return Response(stream_with_context(generate_chat_stream()), mimetype='text/event-stream')

@app.route("/api/chat/sync", methods=["POST"])
async def sync_chat():
    data = request.json
    symbol = data.get("symbol", "").strip().upper()
    if not symbol:
        return jsonify({"error": "Symbol is required"}), 400
    if symbol == "GENERAL":
        now_str = datetime.datetime.now().strftime("%A, %d %B %Y %H:%M:%S")
        now_time = datetime.datetime.now().strftime("%H:%M")
        save_chat_history("GENERAL", [
            {"role": "user", "time": now_time, "parts": [{"text": f"WAKTU SEKARANG: {now_str}\nKamu adalah asisten AI serba bisa yang terintegrasi dengan mesin pencari. Kamu bisa membantu menjawab pertanyaan apa saja, melakukan riset di internet, dan memberikan analisis. Gunakan Bahasa Indonesia."}]},
            {"role": "model", "time": now_time, "parts": [{"text": "Halo! Saya asisten AI Anda. Ada yang bisa saya bantu hari ini? Saya bisa mencari informasi apa pun di internet untuk Anda."}]}
        ])
        return jsonify({"status": "ok"})
    company_name = all_stocks.get(symbol, "Perusahaan Tidak Diketahui")
    is_indo = symbol in all_stocks
    fresh_data = await scrape_stock_data(symbol, is_indo=is_indo)
    try:
        with open(f"data/clean/{symbol}.json", "r") as f:
            enriched = json.load(f)
        if fresh_data and fresh_data.get("price") != "0":
            enriched["price"] = fresh_data["price"]
            enriched["change"] = fresh_data["change"]
    except:
        enriched = fresh_data if fresh_data else {}
    now_str = datetime.datetime.now().strftime("%A, %d %B %Y %H:%M:%S")
    profile_info = f"Nama: {company_name}. Ticker: {symbol}."
    if is_indo:
        profile_info += f" Ini adalah perusahaan yang terdaftar di Bursa Efek Indonesia (BEI)."
    initial_context = (
        f"WAKTU SEKARANG: {now_str}\n"
        f"Konteks Analisis: {profile_info}\n"
        f"Data Pasar Saat Ini: Harga {enriched.get('price')} ({enriched.get('change')}%). Tren {enriched.get('market_trend')}, Sentimen {enriched.get('sentiment')}.\n"
        f"Indikator Teknikal: Support1: {enriched.get('support_1')}, Resistance1: {enriched.get('resistance_1')}, BB Upper: {enriched.get('bb_upper')}, BB Lower: {enriched.get('bb_lower')}, MACD: {enriched.get('macd')}.\n"
        f"Fibonacci (90D): 61.8%: {enriched.get('fib_618')}, 50%: {enriched.get('fib_500')}, 38.2%: {enriched.get('fib_382')}.\n"
        f"Fundamental/Stats: High 52W: {enriched.get('stats', {}).get('high_52')}, Low 52W: {enriched.get('stats', {}).get('low_52')}, Cap: {enriched.get('stats', {}).get('market_cap')}.\n"
        "Tugasmu adalah menjadi analis saham profesional. Gunakan data teknikal dan fundamental presisi di atas. JANGAN katakan kamu tidak punya info hari ini."
    )
    now_time = datetime.datetime.now().strftime("%H:%M")
    save_chat_history(symbol, [
        {"role": "user", "time": now_time, "parts": [{"text": initial_context}]},
        {"role": "model", "time": now_time, "parts": [{"text": "Baik, saya mengerti konteks saham ini. Silakan tanyakan apa saja."}]}
    ])
    return jsonify({"status": "ok"})

@app.route("/api/chat/clear", methods=["POST"])
async def api_clear_chat():
    data = request.json
    symbol = data.get("symbol", "").strip().upper()
    if symbol:
        clear_chat_history(symbol)
        return jsonify({"status": "ok"})
    return jsonify({"error": "Symbol is required"}), 400

@app.route("/api/history/list", methods=["GET"])
async def list_history():
    try:
        conn = sqlite3.connect('data/chat.db', check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT symbol FROM chat_sessions")
        symbols = [row[0] for row in c.fetchall()]
        conn.close()
        results = []
        for s in symbols:
            if s == "GENERAL": continue
            name = s
            try:
                with open(f"data/result/{s}.json", "r") as f:
                    res_data = json.load(f)
                    name = res_data.get("data", {}).get("company_name", s)
            except: pass
            results.append({"symbol": s, "name": name})
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/history/get/<symbol>", methods=["GET"])
async def get_history_detail(symbol):
    symbol = symbol.upper()
    history = get_chat_history(symbol)
    if not history:
        return jsonify({"error": "Not found"}), 404
    analysis_data = get_analysis_result(symbol)
    if not analysis_data:
        try:
            with open(f"data/result/{symbol}.json", "r") as f:
                analysis_data = json.load(f)
        except: pass
    try:
        if analysis_data:
            is_indo = symbol in all_stocks
            fresh_data = await scrape_stock_data(symbol, is_indo=is_indo)
            if fresh_data and fresh_data.get("price") != "0":
                analysis_data["data"]["price"] = fresh_data["price"]
                analysis_data["data"]["change"] = fresh_data["change"]
                save_json(f"data/result/{symbol}.json", analysis_data)
                save_analysis_result(symbol, analysis_data)
    except Exception as e:
        logging.warning(f"Failed to update price for {symbol} on history load: {e}")
    return jsonify({"history": history, "analysis": analysis_data})

@app.route("/api/refresh_analysis", methods=["POST"])
async def refresh_analysis():
    data = request.json
    symbol = data.get("symbol", "").strip().upper()
    if not symbol:
        return jsonify({"error": "Symbol is required"}), 400
    try:
        final_result = await run_full_analysis(symbol)
        return jsonify(final_result)
    except Exception as e:
        logging.error(f"Error refreshing analysis for {symbol}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/refresh_news", methods=["POST"])
async def refresh_news():
    data = request.json
    symbol = data.get("symbol", "").strip().upper()
    if not symbol:
        return jsonify({"error": "Kode saham tidak boleh kosong"}), 400
    try:
        is_indo = symbol in all_stocks
        company_name = all_stocks.get(symbol, symbol)
        news = await scrape_news(symbol, is_indo=is_indo, company_name=company_name)
        return jsonify({"news": news})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/more_news", methods=["POST"])
async def more_news():
    data = request.json
    symbol = data.get("symbol", "").strip().upper()
    if not symbol:
        return jsonify({"error": "Kode saham tidak boleh kosong"}), 400
    def generate():
        async def stream():
            api_keys = get_api_keys()
            if not api_keys:
                yield f"data: {json.dumps({'error': 'API Key tidak ditemukan'})}\n\n"
                return
            try:
                yield f"data: {json.dumps({'status': 'Mencari berita terbaru secara asinkron...'})}\n\n"
                is_indo = symbol in all_stocks
                company_name = all_stocks.get(symbol, symbol)
                variant_query = f'berita terbaru "saham {symbol}" "{company_name}" prospek analisa' if is_indo else f"latest {symbol} {company_name} stock news price analysis"
                news = await scrape_news(symbol, is_indo=is_indo, company_name=company_name, custom_query=variant_query)
                if not news:
                    yield f"data: {json.dumps({'status': 'Tidak ada berita baru ditemukan.'})}\n\n"
                else:
                    yield f"data: {json.dumps({'status': f'Berhasil menemukan {len(news)} berita baru.', 'news': news})}\n\n"
                from news_scraper import scrape_article_content
                article_contents = []
                tasks = [scrape_article_content(n['link']) for n in news[:3] if n.get('link')]
                yield f"data: {json.dumps({'status': f'Sedang membaca {len(tasks)} artikel berita secara paralel...'})}\n\n"
                contents = await asyncio.gather(*tasks)
                for i, content in enumerate(contents):
                    if content: article_contents.append(f"SUMBER: {news[i]['title']}\nISI: {content}")
                if not article_contents:
                     yield f"data: {json.dumps({'status': 'Gagal mengambil isi konten berita.'})}\n\n"
                     return
                history = get_chat_history(symbol)
                yield f"data: {json.dumps({'status': 'Sedang merangkum isi berita dan mengevaluasi data...'})}\n\n"
                all_news_text = "\n\n---\n\n".join(article_contents)
                prompt_1 = f"Teks mentah berita {symbol}:\n\n{all_news_text}\n\nTugas: Ringkas poin krusial dan sebutkan data tambahan yang dibutuhkan."
                summary_reply = ""
                async for update in chat_with_gemini(api_keys, history, prompt_1):
                    if "reply" in update:
                        summary_reply = update["reply"]
                        history = update["history"]
                yield f"data: {json.dumps({'status': 'Menganalisis kebutuhan data tambahan...', 'summary': summary_reply})}\n\n"
                import re
                search_queries = re.findall(r'^- (.*)', summary_reply, re.MULTILINE)
                research_results = []
                if search_queries:
                    from bing_search_tool import search_bing
                    for q in search_queries[:2]:
                        yield f"data: {json.dumps({'status': f'Mencari data tambahan: {q[:30]}...'})}\n\n"
                        research_results.append(f"INFO '{q}':\n{await search_bing(f'{symbol} {q}')}")
                yield f"data: {json.dumps({'status': 'Memberikan analisa akhir yang tajam...'})}\n\n"
                ai_result, display_reply = None, summary_reply
                if research_results:
                    final_research_data = "\n\n".join(research_results)
                    prompt_2 = f"HASIL RISET LANJUTAN:\n{final_research_data}\n\nBerikan ANALISA FINAL dalam format JSON di akhir pesan dengan tag <JSON>...</JSON>."
                    final_ai_reply = ""
                    async for update in chat_with_gemini(api_keys, history, prompt_2):
                        if "reply" in update:
                            final_ai_reply = update["reply"]
                            history = update["history"]
                    save_chat_history(symbol, history)
                    json_match = re.search(r'<JSON>(.*?)</JSON>', final_ai_reply, re.DOTALL) or re.search(r'(\{.*\})', final_ai_reply, re.DOTALL)
                    if json_match:
                        try:
                            ai_result = json.loads(json_match.group(1))
                            display_reply = f"<b>Analisis:</b><br>{final_ai_reply.replace(json_match.group(0), '').strip()}"
                        except: display_reply = final_ai_reply
                yield f"data: {json.dumps({'status': 'Selesai!', 'ai_reply': display_reply, 'ai_result': ai_result, 'done': True})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
        loop = asyncio.new_event_loop()
        gen = stream()
        try:
            while True:
                try: yield loop.run_until_complete(gen.__anext__())
                except StopAsyncIteration: break
        finally: loop.close()
    return Response(stream_with_context(generate()), mimetype='text/event-stream')

@app.route("/api/price/<symbol>")
async def get_quick_price(symbol):
    try:
        data = await scrape_stock_data(symbol.strip().upper(), is_indo=(symbol.upper() in all_stocks))
        return jsonify({"price": data.get("price"), "change": data.get("change"), "currency": data.get("currency")})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route("/api/analysis/<symbol>", methods=["GET"])
async def get_analysis_only(symbol):
    symbol = symbol.upper()
    res = get_analysis_result(symbol)
    if not res:
        try:
            with open(f"data/result/{symbol}.json", "r") as f: res = json.load(f)
        except: return jsonify({"error": "Analysis not found"}), 404
    return jsonify(res)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
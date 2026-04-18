from flask import Flask, render_template, request, jsonify, Response, stream_with_context
import logging
import time
import datetime
import csv
import json
import sqlite3
import os
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

# Store chat histories per session/symbol using SQLite
os.makedirs('data', exist_ok=True)
def init_db():
    conn = sqlite3.connect('data/chat.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS chat_sessions (symbol TEXT PRIMARY KEY, history TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS analysis_results (symbol TEXT PRIMARY KEY, result TEXT, updated_at DATETIME)''')
    conn.commit()
    conn.close()

init_db()

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

@app.route("/")
def index():
    return render_template("index.html")

def run_full_analysis(symbol):
    """Runs the full analysis pipeline for a given stock symbol."""
    company_name = all_stocks.get(symbol, "Perusahaan Tidak Diketahui")
    api_keys = get_api_keys()
    
    if not api_keys:
        raise ConnectionError("API Key tidak ditemukan")

    driver = None
    try:
        logging.info(f"Mulai analisis web untuk: {symbol} ({company_name})")
        driver = get_driver()
        
        is_indo = symbol in all_stocks
        raw_data = scrape_stock_data(symbol, driver, is_indo=is_indo)
        news = scrape_news(symbol, driver, is_indo=is_indo, company_name=company_name)
        raw_data["news"] = news
        raw_data["company_name"] = company_name
        raw_data["symbol"] = symbol # Ensure symbol is in the data
        
        save_json(f"data/raw/{symbol}.json", raw_data)
        
        cleaned = clean_data(raw_data)
        save_json(f"data/clean/{symbol}.json", cleaned)
        enriched = enrich_data(cleaned)
        
        # Ambil history chat untuk konteks analisis mendalam
        history = get_chat_history(symbol)
        
        logging.info(f"Mengirim data {symbol} ke Gemini API...")
        ai_result = None
        retry = 0
        while not ai_result and retry < 3:
            ai_result = analyze_with_gemini(api_keys, enriched, history=history)
            if not ai_result:
                retry += 1
                logging.warning(f"AI gagal, retry ({retry}/3)...")
                time.sleep(2)
        
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
        if existing_history and len(existing_history) >= 2:
            # Jika history ada, perbarui context di pesan pertama tanpa menghapus sisanya
            if "WAKTU SEKARANG:" in existing_history[0]['parts'][0].get('text', ''):
                existing_history[0]['parts'][0]['text'] = initial_context
                logging.info(f"Updated initial context for {symbol} while preserving history.")
            else:
                # Fallback: jika struktur berbeda, sisipkan context baru di awal
                existing_history.insert(0, {"role": "model", "parts": [{"text": "Sistem: Data analisis telah diperbarui ke versi terbaru."}]})
                existing_history.insert(0, {"role": "user", "parts": [{"text": initial_context}]})
            save_chat_history(symbol, existing_history)
        else:
            save_chat_history(symbol, [
                {"role": "user", "parts": [{"text": initial_context}]},
                {"role": "model", "parts": [{"text": "Baik, saya mengerti konteks saham ini. Silakan tanyakan apa saja."}]}
            ])
        
        return final_result
        
    finally:
        if driver:
            driver.quit()

@app.route("/api/analyze", methods=["POST"])
def analyze():
    data = request.json
    symbol = data.get("symbol", "").strip().upper()
    
    if not symbol:
        return jsonify({"error": "Kode saham tidak boleh kosong"}), 400

    try:
        final_result = run_full_analysis(symbol)
        return jsonify(final_result)
    except (ConnectionError, RuntimeError, Exception) as e:
        logging.error(f"Error di backend saat analisis {symbol}: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    symbol = data.get("symbol", "").strip().upper() or "GENERAL"
    message = data.get("message", "").strip()
    # Terima history dari client jika ada
    client_history = data.get("history")
    
    if not message:
        return jsonify({"error": "Pesan tidak boleh kosong"}), 400

    def generate_chat_stream():
        # Gunakan history dari client, jika tidak ada baru ambil dari memori server
        history = client_history if client_history else get_chat_history(symbol)
        
        if not history:
            if symbol == "GENERAL":
                # Initialize a general chat session if it doesn't exist
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
            # Regex yang lebih inklusif untuk mendeteksi URL (termasuk yang diawali www.)
            urls = re.findall(r'((?:https?://|www\.)[^\s]+)', message)
            
            # If a URL is detected, use a full browser to scrape it
            if urls:
                yield f"data: {json.dumps({'status': 'Sistem: URL terdeteksi. Membuka browser untuk membaca konten...'})}\n\n"
                extracted_contents = []
                driver = None
                try:
                    from scraper import get_driver
                    from bs4 import BeautifulSoup
                    import time
                    driver = get_driver()
                    for url in urls:
                        full_url = url if url.startswith('http') else f'http://{url}'
                        yield f"data: {json.dumps({'status': f'Sistem: Membaca konten dari {url}...'})}\n\n"
                        try:
                            driver.get(full_url)
                            time.sleep(3) 
                            page_source = driver.page_source
                            soup = BeautifulSoup(page_source, 'html.parser')
                            for element in soup(["script", "style", "header", "footer", "nav", "aside", "form", "button"]):
                                element.decompose()
                            body = soup.find('body')
                            if body:
                                body_text = body.get_text(separator=' ', strip=True)
                                cleaned_text = ' '.join(body_text.split())
                                extracted_contents.append(f"KONTEN DARI URL {url}:\n{cleaned_text[:3000]}")
                            else:
                                extracted_contents.append(f"KONTEN DARI URL {url}:\n[Gagal memuat: Tag <body> tidak ditemukan]")
                        except Exception as e:
                            extracted_contents.append(f"KONTEN DARI URL {url}:\n[Gagal memuat: {str(e)}]")
                finally:
                    if driver: driver.quit()

                processed_message = f"{message}\n\n[Sistem: Konten URL terlampir]\n" + "\n\n".join(extracted_contents)

            # Iterate through the generator from ai_analyzer.py
            for update in chat_with_gemini(api_keys, history, processed_message):
                if "status" in update:
                    yield f"data: {json.dumps({'status': update['status']})}\n\n"
                if "reply" in update:
                    save_chat_history(symbol, update["history"])
                    yield f"data: {json.dumps({'reply': update['reply'], 'history': update['history'], 'done': True})}\n\n"

        except Exception as e:
            logging.error(f"Error di backend chat stream: {str(e)}")
            yield f"data: {json.dumps({'status': f'Error: {str(e)}', 'error': str(e), 'done': True})}\n\n"
    
    return Response(stream_with_context(generate_chat_stream()), mimetype='text/event-stream')

@app.route("/api/chat/sync", methods=["POST"])
def sync_chat():
    data = request.json
    symbol = data.get("symbol", "").strip().upper()
    if not symbol:
        return jsonify({"error": "Symbol is required"}), 400

    if symbol == "GENERAL":
        now_str = datetime.datetime.now().strftime("%A, %d %B %Y %H:%M:%S")
        save_chat_history("GENERAL", [
            {"role": "user", "parts": [{"text": f"WAKTU SEKARANG: {now_str}\nKamu adalah asisten AI serba bisa yang terintegrasi dengan mesin pencari. Kamu bisa membantu menjawab pertanyaan apa saja, melakukan riset di internet, dan memberikan analisis. Gunakan Bahasa Indonesia."}]},
            {"role": "model", "parts": [{"text": "Halo! Saya asisten AI Anda. Ada yang bisa saya bantu hari ini? Saya bisa mencari informasi apa pun di internet untuk Anda."}]}
        ])
        logging.info("General chat session has been synced/re-initialized.")
        return jsonify({"status": "ok"})

    company_name = all_stocks.get(symbol, "Perusahaan Tidak Diketahui")
    is_indo = symbol in all_stocks
    
    # Update fresh price data for initial context
    fresh_data = scrape_stock_data(symbol, is_indo=is_indo)
    
    # Attempt to load latest enriched data to provide some context
    try:
        with open(f"data/clean/{symbol}.json", "r") as f:
            enriched = json.load(f)
        if fresh_data and fresh_data.get("price") != "0":
            enriched["price"] = fresh_data["price"]
            enriched["change"] = fresh_data["change"]
    except:
        enriched = fresh_data if fresh_data else {}

    # Logic to re-create the initial context, same as in /api/analyze
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
    save_chat_history(symbol, [
        {"role": "user", "parts": [{"text": initial_context}]},
        {"role": "model", "parts": [{"text": "Baik, saya mengerti konteks saham ini. Silakan tanyakan apa saja."}]}
    ])
    logging.info(f"Chat session for {symbol} has been synced/re-initialized.")
    return jsonify({"status": "ok"})

@app.route("/api/chat/clear", methods=["POST"])
def api_clear_chat():
    data = request.json
    symbol = data.get("symbol", "").strip().upper()
    if symbol:
        clear_chat_history(symbol)
        return jsonify({"status": "ok"})
    return jsonify({"error": "Symbol is required"}), 400

@app.route("/api/history/list", methods=["GET"])
def list_history():
    try:
        conn = sqlite3.connect('data/chat.db', check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT symbol FROM chat_sessions")
        symbols = [row[0] for row in c.fetchall()]
        conn.close()
        
        results = []
        for s in symbols:
            if s == "GENERAL": continue
            # Cari nama perusahaan dari file result jika ada
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
def get_history_detail(symbol):
    symbol = symbol.upper()
    history = get_chat_history(symbol)
    if not history:
        return jsonify({"error": "Not found"}), 404
        
    # Ambil juga data analisis terakhir (utamakan dari DB)
    analysis_data = get_analysis_result(symbol)
    if not analysis_data:
        try:
            with open(f"data/result/{symbol}.json", "r") as f:
                analysis_data = json.load(f)
        except: pass
    
    # Update harga terbaru saat memuat chat
    try:
        if analysis_data:
            is_indo = symbol in all_stocks
            fresh_data = scrape_stock_data(symbol, is_indo=is_indo)
            if fresh_data and fresh_data.get("price") != "0":
                analysis_data["data"]["price"] = fresh_data["price"]
                analysis_data["data"]["change"] = fresh_data["change"]
                # JANGAN update timestamp root di sini karena ini cuma refresh harga, bukan refresh analisis Gemini
                save_json(f"data/result/{symbol}.json", analysis_data)
                save_analysis_result(symbol, analysis_data)
                logging.info(f"Price updated for {symbol} while loading history.")
    except Exception as e:
        logging.warning(f"Failed to update price for {symbol} on history load: {e}")
    
    return jsonify({
        "history": history,
        "analysis": analysis_data
    })

@app.route("/api/refresh_analysis", methods=["POST"])
def refresh_analysis():
    data = request.json
    symbol = data.get("symbol", "").strip().upper()
    if not symbol:
        return jsonify({"error": "Symbol is required"}), 400
    try:
        final_result = run_full_analysis(symbol)
        return jsonify(final_result)
    except Exception as e:
        logging.error(f"Error refreshing analysis for {symbol}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/analysis/<symbol>", methods=["GET"])
def get_analysis_only(symbol):
    symbol = symbol.upper()
    analysis_data = get_analysis_result(symbol)
    if not analysis_data:
        try:
            with open(f"data/result/{symbol}.json", "r") as f:
                analysis_data = json.load(f)
        except:
            return jsonify({"error": "Analysis not found"}), 404
    return jsonify(analysis_data)

@app.route("/api/refresh_news", methods=["POST"])
def refresh_news():
    data = request.json
    symbol = data.get("symbol", "").strip().upper()
    
    if not symbol:
        return jsonify({"error": "Kode saham tidak boleh kosong"}), 400

    driver = None
    try:
        logging.info(f"Refreshing news for {symbol}")
        driver = get_driver()
        is_indo = symbol in all_stocks
        company_name = all_stocks.get(symbol, symbol)
        
        news = scrape_news(symbol, driver, is_indo=is_indo, company_name=company_name)
        
        return jsonify({"news": news})
        
    except Exception as e:
        logging.error(f"Error refreshing news: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        if driver:
            driver.quit()

@app.route("/api/more_news", methods=["POST"])
def more_news():
    data = request.json
    symbol = data.get("symbol", "").strip().upper()
    
    if not symbol:
        return jsonify({"error": "Kode saham tidak boleh kosong"}), 400

    def generate():
        api_keys = get_api_keys()
        if not api_keys:
            yield f"data: {json.dumps({'error': 'API Key tidak ditemukan'})}\n\n"
            return

        driver = None
        try:
            yield f"data: {json.dumps({'status': 'Sedang membuka browser dan mencari berita terbaru...'})}\n\n"
            driver = get_driver()
            
            is_indo = symbol in all_stocks
            company_name = all_stocks.get(symbol, symbol)
            
            # 1. Cari berita tambahan
            if is_indo:
                variant_query = f'berita terbaru "saham {symbol}" "{company_name}" prospek analisa'
            else:
                variant_query = f"latest {symbol} {company_name} stock news price analysis"
                
            news = scrape_news(symbol, driver, is_indo=is_indo, company_name=company_name, custom_query=variant_query)
            
            if not news:
                yield f"data: {json.dumps({'status': 'Tidak ada berita baru ditemukan.'})}\n\n"
            else:
                yield f"data: {json.dumps({'status': f'Berhasil menemukan {len(news)} berita baru.', 'news': news})}\n\n"

            # 2. DEEP READING
            from news_scraper import scrape_article_content
            article_contents = []
            max_read = 3
            for i, n in enumerate(news[:max_read]):
                if n.get('link'):
                    title_part = n.get('title', '')[:50]
                    msg = f"Sedang membaca artikel {i+1}/{max_read}: {title_part}..."
                    yield f"data: {json.dumps({'status': msg})}\n\n"
                    content = scrape_article_content(n['link'])
                    if content:
                        article_contents.append(f"SUMBER: {n['title']}\nISI: {content}")
            
            if not article_contents:
                 yield f"data: {json.dumps({'status': 'Gagal mengambil isi konten berita.'})}\n\n"
                 return

            history = get_chat_history(symbol)
            if not history:
                yield f"data: {json.dumps({'error': 'Sesi chat tidak ditemukan'})}\n\n"
                return

            # 3. Kirim hasil Deep Reading ke Gemini
            yield f"data: {json.dumps({'status': 'Sedang merangkum isi berita dan mengevaluasi data...'})}\n\n"
            
            all_news_text = "\n\n---\n\n".join(article_contents)
            prompt_1 = (
                f"Saya telah membaca isi dari {len(article_contents)} berita terbaru untuk {symbol}. "
                f"Berikut isi teks mentahnya:\n\n{all_news_text}\n\n"
                "Tugasmu:\n"
                "1. Ringkas poin-poin paling krusial dari berita tersebut (buang 'sampah' informasi).\n"
                "2. Berdasarkan ringkasan ini, sebutkan 2-3 data spesifik lain yang masih kamu butuhkan (misal: rasio keuangan tertentu)."
            )
            
            summary_reply, history = chat_with_gemini(api_keys, history, prompt_1)
            yield f"data: {json.dumps({'status': 'Menganalisis kebutuhan data tambahan...', 'summary': summary_reply})}\n\n"
            
            # 4. OTOMATIS: Riset Lanjutan
            import re
            search_queries = re.findall(r'^- (.*)', summary_reply, re.MULTILINE)
            
            research_results = []
            if search_queries:
                from bing_search_tool import search_bing
                for i, q in enumerate(search_queries[:2]):
                    yield f"data: {json.dumps({'status': f'Mencari data tambahan {i+1}/2: {q[:30]}...'})}\n\n"
                    query = f"{symbol} {q}"
                    res = search_bing(query)
                    research_results.append(f"INFO '{q}':\n{res}")

            # 5. Final
            yield f"data: {json.dumps({'status': 'Memberikan analisa akhir yang tajam...'})}\n\n"
            
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
                save_chat_history(symbol, history)
                
                json_match = re.search(r'<JSON>(.*?)</JSON>', final_ai_reply, re.DOTALL)
                if not json_match:
                    json_match = re.search(r'(\{.*?\})', final_ai_reply, re.DOTALL)
                
                if json_match:
                    try:
                        ai_result = json.loads(json_match.group(1))
                        display_reply = f"<b>Ringkasan Berita:</b><br>{summary_reply}<br><br><b>Analisis Final:</b><br>{final_ai_reply.replace(json_match.group(0), '').strip()}"
                    except:
                        display_reply = final_ai_reply
                else:
                    display_reply = final_ai_reply

            yield f"data: {json.dumps({'status': 'Selesai!', 'ai_reply': display_reply, 'ai_result': ai_result, 'done': True})}\n\n"
            
        except Exception as e:
            logging.error(f"Error Auto-Research: {str(e)}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            if driver:
                driver.quit()

    return Response(stream_with_context(generate()), mimetype='text/event-stream')

@app.route("/api/price/<symbol>")
def get_quick_price(symbol):
    symbol = symbol.strip().upper()
    is_indo = symbol in all_stocks
    from scraper import scrape_stock_data
    try:
        data = scrape_stock_data(symbol, is_indo=is_indo)
        return jsonify({
            "price": data.get("price"),
            "change": data.get("change"),
            "currency": data.get("currency")
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

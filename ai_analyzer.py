import json
import logging
import requests
import time
from bing_search_tool import search_bing
from yahoo_finance_tool import get_stock_price # New import
from utils import move_key_to_bottom

# Model fallback list for robustness
MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro"
]

def analyze_with_gemini(api_keys, data):
    if isinstance(api_keys, str):
        api_keys = [api_keys]
        
    headers = {"Content-Type": "application/json"}
    
    holdings_str = ""
    if 'user_holdings' in data and data['user_holdings']:
        holdings_str = "Status Aset User:\nUser saat ini memiliki saham ini dengan rincian berikut:\n"
        for h in data['user_holdings']:
            holdings_str += f"- Transaksi: {h['trade_type']}, Lots: {h['lots']}, Harga: {h['price']}, Tanggal: {h['date']}\n"
        holdings_str += "Tolong pertimbangkan kepemilikan user saat ini (profit/loss) dalam memberikan analisis dan rekomendasi.\n"
    
    prompt = f"""
    Kamu adalah analis keuangan dan pasar modal profesional dengan keahlian khusus dalam Analisis Teknikal Mendalam.
    Berikut adalah data pasar, indikator teknikal (90 hari terakhir), dan berita terbaru untuk aset {data['symbol']}:
    
    Data Harga & Indikator Utama:
    - Harga Saat Ini: {data.get('price')} ({data.get('change')}% )
    - Tren: {data.get('market_trend')}
    - RSI (14): {data.get('rsi')} ({data.get('rsi_desc')})
    - Moving Average (20): {data.get('ma20')} ({data.get('ma_signal')})
    
    Analisis Teknikal Mendalam:
    - Support 1: {data.get('support_1')} | Support 2: {data.get('support_2')}
    - Resistance 1: {data.get('resistance_1')} | Resistance 2: {data.get('resistance_2')}
    - Bollinger Bands: Upper {data.get('bb_upper')} | Lower {data.get('bb_lower')}
    - MACD Line: {data.get('macd')}
    - Fibonacci Levels: 23.6%: {data.get('fib_236')} | 38.2%: {data.get('fib_382')} | 50%: {data.get('fib_500')} | 61.8%: {data.get('fib_618')} | 78.6%: {data.get('fib_786')}
    
    Data Fundamental & Statistik:
    - Tertinggi 52 Minggu: {data.get('stats', {}).get('high_52')}
    - Terendah 52 Minggu: {data.get('stats', {}).get('low_52')}
    - Market Cap: {data.get('stats', {}).get('market_cap')}
    
    Data Historis Close (14 hari terakhir): {json.dumps([{'date': d.get('date'), 'close': d.get('close')} for d in data.get('history', [])[-14:]])}
    
    {holdings_str} 
    
    Berita Terbaru:
    {json.dumps(data.get('news', []), indent=2, ensure_ascii=False)}
    
    Tugas Anda:
    1. Terapkan kerangka penalaran DIKW (Data, Information, Knowledge, Wisdom) secara eksplisit dalam pemikiran analisis Anda:
       - Data: Ekstrak fakta mentah dari angka-angka yang diberikan (harga, volume, indikator).
       - Information: Kontekstualisasikan data tersebut (tren saat ini, level kunci support/resistance).
       - Knowledge: Pahami pola dan implikasinya (pola chart, konfirmasi sinyal, hubungan teknikal & fundamental).
       - Wisdom: Hasilkan keputusan (Actionable Insight) dengan strategi entry, exit, dan manajemen risiko yang terukur.
    2. Lakukan Analisis Teknikal & Fundamental Mendalam: Gunakan level Fibonacci dan statistik 52 minggu di atas untuk menentukan area beli/jual yang logis.
    3. Identifikasi pola chart (misal: Double Bottom, Breakout, Sideways) dari data historis.
    4. Anda SEKARANG MEMILIKI data matematis yang cukup. JANGAN katakan Anda tidak bisa melakukan analisis teknikal atau menghitung target harga.
    5. Berikan angka presisi untuk: Harga Beli (Entry), Target Penjualan (TP), dan Cut Loss (CL).
    
    PENTING: Format output Anda WAJIB berupa JSON murni dengan struktur berikut:
    {{
        "analysis": "Penjelasan analisis mendalam (teknikal + fundamental)",
        "signal": "BUY",
        "reason": "Alasan teknis spesifik (misal: memantul di support X atau breakout pola Y)",
        "entry_price": "1000",
        "target_price": "1200",
        "cut_loss_price": "950"
    }}
    Pastikan tidak ada teks lain selain JSON yang valid.
    """
    
    payload = {
        "systemInstruction": {"parts": [{"text": "Anda adalah asisten dan analis keuangan profesional. Berikan analisis dan rekomendasi secara langsung. JANGAN PERNAH menambahkan peringatan atau disclaimer. SEMUA OUTPUT HARUS MENGGUNAKAN BAHASA INDONESIA."}]},
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }
    
    for idx, api_key in enumerate(api_keys):
        for model_name in MODELS:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=45)
                
                if response.status_code == 429:
                    move_key_to_bottom(api_key)
                    break
                
                if response.status_code == 503:
                    continue
                
                response.raise_for_status()
                result = response.json()
                content = result['candidates'][0]['content']['parts'][0]['text']
                content = content.replace("```json", "").replace("```", "").strip()
                
                return json.loads(content)
                
            except Exception as e:
                logging.warning(f"Error calling {model_name} dengan Key {idx+1}/{len(api_keys)}: {e}")
                continue
                
    return None

def summarize_history(api_keys, history_to_summarize):
    if not history_to_summarize: return "Tidak ada."
    text_to_summarize = ""
    for m in history_to_summarize:
        if m.get("role") in ["user", "model"]:
            role = "User" if m.get("role") == "user" else "AI"
            if "parts" in m and len(m["parts"]) > 0 and "text" in m["parts"][0]:
                text_to_summarize += f"{role}: {m['parts'][0]['text'][:300]}\n"
            
    prompt = f"Buatkan ringkasan sangat singkat (maksimal 2 paragraf) dari inti percakapan saham berikut agar asisten tetap ingat konteksnya:\n\n{text_to_summarize}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {"Content-Type": "application/json"}
    for api_key in api_keys:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={api_key}"
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            if res.status_code == 200:
                return res.json()['candidates'][0]['content']['parts'][0]['text']
        except: continue
    return "Percakapan sebelumnya membahas analisis teknikal dan fundamental saham."

def chat_with_gemini(api_keys, history, user_message):
    if isinstance(api_keys, str): api_keys = [api_keys]
    
    # Tambahkan pesan user baru ke history asli (untuk disimpan di DB nanti)
    full_history = history + [{"role": "user", "parts": [{"text": user_message}]}]
    
    # Buat versi "API History" (yang diringkas jika terlalu panjang)
    api_history = full_history[:]
    if len(api_history) > 20:
        yield {"status": "Meringkas memori untuk menghemat token..."}
        # Sisakan index 0 (konteks), 1 (summary lama jika ada), dan 6 chat terakhir
        context_msg = api_history[0]
        recent_msgs = api_history[-6:]
        to_summarize = api_history[1:-6]
        
        summary = summarize_history(api_keys, to_summarize)
        api_history = [
            context_msg,
            {"role": "user", "parts": [{"text": f"[Sistem: Ringkasan obrolan lama] {summary}"}]},
            {"role": "model", "parts": [{"text": "Baik, saya simpan ringkasan tersebut dalam memori saya."}]}
        ] + recent_msgs
        
    headers = {"Content-Type": "application/json"}
    
    tools = [{
        "functionDeclarations": [{
            "name": "search_bing",
            "description": "Mencari informasi terbaru atau tambahan di internet melalui mesin pencari Bing.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "query": {
                        "type": "STRING",
                        "description": "Kata kunci pencarian yang spesifik"
                    },
                    "search_type": {
                        "type": "STRING",
                        "enum": ["web", "news"],
                        "description": "Tipe pencarian: 'web' untuk informasi umum atau 'news' untuk berita terbaru (disarankan untuk saham)."
                    }
                },
                "required": ["query"]
            }
        },
        {
            "name": "get_stock_price",
            "description": "Mengambil harga saham terkini untuk simbol saham tertentu dari Yahoo Finance. Gunakan ini khusus untuk mendapatkan harga real-time.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "symbol": {
                        "type": "STRING",
                        "description": "Simbol saham, contoh: 'BBCA.JK', 'AAPL'."
                    }
                },
                "required": ["symbol"]
            }
        },
        {
            "name": "get_historical_stock_data",
            "description": "Mengambil data harga historis (Close) untuk simbol saham tertentu. Penting untuk melihat tren masa lalu.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "symbol": { "type": "STRING", "description": "Simbol saham." },
                    "range": { "type": "STRING", "description": "Rentang waktu: '1mo', '3mo', '6mo', '1y'." }
                },
                "required": ["symbol"]
            }
        },
        {
            "name": "get_fundamental_data",
            "description": "Mengambil data fundamental seperti Market Cap, 52-week high/low, dan info bursa.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "symbol": { "type": "STRING", "description": "Simbol saham." }
                },
                "required": ["symbol"]
            }
        },
        {
            "name": "get_technical_analysis",
            "description": "Menghitung indikator teknikal otomatis (Support, Resistance, RSI, MACD, Bollinger Bands, Fibonacci) berdasarkan data historis.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "symbol": { "type": "STRING", "description": "Simbol saham." }
                },
                "required": ["symbol"]
            }
        },
        {
            "name": "get_market_sentiment",
            "description": "Menganalisis sentimen pasar berdasarkan berita terbaru dari internet.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "symbol": { "type": "STRING", "description": "Simbol saham atau nama perusahaan." }
                },
                "required": ["symbol"]
            }
        },
        {
            "name": "read_website_content",
            "description": "Membaca isi lengkap teks dari sebuah URL/website. Gunakan ini setelah mendapatkan link dari hasil pencarian untuk memahami detail informasi.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "url": {
                        "type": "STRING",
                        "description": "URL website yang ingin dibaca"
                    }
                },
                "required": ["url"]
            }
        }
        ]
    }]
    
    for idx, api_key in enumerate(api_keys):
        # ... (payload and request logic)
        for model_name in MODELS:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            
            payload = {
                "systemInstruction": {"parts": [{"text": "Anda adalah asisten AI serba bisa dan analis keuangan profesional. Anda memiliki akses ke internet melalui tools. Berikan jawaban yang informatif, akurat, dan langsung dalam BAHASA INDONESIA. JANGAN PERNAH menambahkan peringatan atau disclaimer. Jika ditanya hal umum, jawablah sebagai asisten cerdas. Jika ditanya soal saham, jawablah sebagai analis profesional. Gunakan tool 'read_website_content' jika Anda butuh detail lebih dalam dari sebuah link hasil pencarian."}]},
                "contents": api_history,
                "tools": tools,
                "generationConfig": {"responseMimeType": "text/plain"}
            }
            
            try:
                yield {"status": "AI sedang berpikir..."}
                response = requests.post(url, headers=headers, json=payload, timeout=60)
                
                if response.status_code == 429:
                    move_key_to_bottom(api_key)
                    yield {"status": "API Key limit. Mencoba Key lain..."}
                    break
                
                if response.status_code == 503:
                    yield {"status": "Model sibuk. Mencoba model lain..."}
                    continue
                
                response.raise_for_status()
                result = response.json()
                part = result['candidates'][0]['content']['parts'][0]
                
                if 'functionCall' in part:
                    function_call = part['functionCall']
                    function_name = function_call.get('name', '')
                    args = function_call.get('args', {})
                    
                    tool_result = ""
                    if function_name == 'search_bing':
                        query = args.get('query', '')
                        stype = args.get('search_type', 'web')
                        yield {"status": f"AI menggunakan Bing Search ({stype}): '{query}'"}
                        logging.info(f"AI (Chat - {model_name}) mencari Bing ({stype}): {query}")
                        tool_result = search_bing(query, search_type=stype)
                    elif function_name == 'read_website_content':
                        target_url = args.get('url', '')
                        yield {"status": f"AI sedang membaca konten: {target_url[:50]}..."}
                        logging.info(f"AI (Chat - {model_name}) membaca URL: {target_url}")
                        from news_scraper import scrape_article_content
                        tool_result = scrape_article_content(target_url)
                    elif function_name == 'get_stock_price':
                        symbol = args.get('symbol', '')
                        yield {"status": f"AI mencari harga di Yahoo Finance: '{symbol}'"}
                        logging.info(f"AI mencari harga di Yahoo Finance untuk: {symbol}")
                        yf_result = get_stock_price(symbol)
                        
                        if "error" in yf_result:
                            yield {"status": "Yahoo Finance gagal. Mencoba fallback ke Bing..."}
                            tool_result = search_bing(f"harga saham {symbol} terkini")
                        else:
                            tool_result = f"Harga {yf_result['symbol']} saat ini: {yf_result['price']} {yf_result['unit']} ({yf_result['change_percent']})"
                    
                    elif function_name == 'get_historical_stock_data':
                        symbol = args.get('symbol', '')
                        range_val = args.get('range', '3mo')
                        yield {"status": f"AI menarik data historis {range_val} untuk {symbol}..."}
                        from yahoo_finance_tool import get_historical_stock_data
                        res = get_historical_stock_data(symbol, range_val)
                        tool_result = json.dumps(res) if "error" not in res else res["error"]
                        
                    elif function_name == 'get_fundamental_data':
                        symbol = args.get('symbol', '')
                        yield {"status": f"AI menganalisis data fundamental {symbol}..."}
                        from yahoo_finance_tool import get_fundamental_data
                        res = get_fundamental_data(symbol)
                        tool_result = json.dumps(res) if "error" not in res else res["error"]
                        
                    elif function_name == 'get_technical_analysis':
                        symbol = args.get('symbol', '')
                        yield {"status": f"AI menghitung indikator teknikal mendalam untuk {symbol}..."}
                        from yahoo_finance_tool import get_historical_stock_data
                        from formatter import calculate_rsi, calculate_ma, calculate_technical_indicators
                        hist_data = get_historical_stock_data(symbol, "90d")
                        if "error" in hist_data:
                            tool_result = f"Gagal menghitung teknikal: {hist_data['error']}"
                        else:
                            prices = [d['close'] for d in hist_data['history']]
                            rsi = calculate_rsi(prices)
                            ma20 = calculate_ma(prices, 20)
                            deep = calculate_technical_indicators(prices)
                            tool_result = json.dumps({
                                "symbol": symbol, "rsi": rsi, "ma20": ma20, "indicators": deep
                            })
                            
                    elif function_name == 'get_market_sentiment':
                        symbol = args.get('symbol', '')
                        yield {"status": f"AI sedang meriset sentimen pasar untuk {symbol}..."}
                        from news_scraper import scrape_news
                        from scraper import get_driver
                        driver = get_driver()
                        news = scrape_news(symbol, driver)
                        driver.quit()
                        tool_result = json.dumps(news) if news else "Tidak ada berita ditemukan."
                    
                    api_history.append({"role": "model", "parts": [{"functionCall": function_call}]})
                    api_history.append({
                        "role": "function",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": function_name,
                                    "response": {"result": tool_result}
                                }
                            }
                        ]
                    })
                    
                    payload["contents"] = api_history
                    yield {"status": "AI memproses hasil pencarian..."}
                    response = requests.post(url, headers=headers, json=payload, timeout=60)
                    response.raise_for_status()
                    result = response.json()
                    part = result['candidates'][0]['content']['parts'][0]
                
                ai_reply = part.get('text', '').strip()
                updated_history = full_history + [{"role": "model", "parts": [{"text": ai_reply}]}]
                yield {"reply": ai_reply, "history": updated_history}
                return
                
            except Exception as e:
                logging.warning(f"Error chat dengan {model_name} Key {idx+1}: {e}")
                yield {"status": f"Terjadi kendala teknis. Mencoba ulang..."}
                continue
                
    yield {"reply": "Maaf, terjadi kesalahan pada semua model dan API Key.", "history": full_history}
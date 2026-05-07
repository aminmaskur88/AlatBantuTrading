import json
import logging
import aiohttp
import asyncio
import datetime
import re # Add this line
from bing_search_tool import search_bing
from yahoo_finance_tool import get_stock_price 
from utils import move_key_to_bottom

# Model fallback list for robustness
MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro"
]

async def analyze_with_gemini(api_keys, data, history=None):
    if isinstance(api_keys, str):
        api_keys = [api_keys]
        
    headers = {"Content-Type": "application/json"}
    
    chat_context = ""
    if history and len(history) > 1:
        relevant_history = history[-6:]
        chat_context = "Konteks Obrolan Sebelumnya (untuk referensi preferensi user):\n"
        for m in relevant_history:
            role = "User" if m.get("role") == "user" else "AI"
            text = m["parts"][0].get("text", "") if m.get("parts") else ""
            if text and not text.startswith("WAKTU SEKARANG:") and not text.startswith("[Sistem:"):
                chat_context += f"- {role}: {text[:200]}\n"
        chat_context += "\n"

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
    - MACD: Line {data.get('macd')} | Signal {data.get('macd_signal')} | Hist {data.get('macd_hist')}
    - Volume: MA20 {data.get('vol_ma20')} | Status {data.get('vol_status')} | Trend {data.get('volume_trend')}
    - Fibonacci Levels: 23.6%: {data.get('fib_236')} | 38.2%: {data.get('fib_382')} | 50%: {data.get('fib_500')} | 61.8%: {data.get('fib_618')} | 78.6%: {data.get('fib_786')}
    
    Konteks Makroekonomi & Sektoral:
    - Kurs USD/IDR: {data.get('macro_data', {}).get('usd_idr', 'N/A')}
    - BI Rate: {data.get('macro_data', {}).get('bi_rate', 'N/A')}
    - Harga Emas: {data.get('macro_data', {}).get('gold', 'N/A')}
    - Harga Minyak (WTI): {data.get('macro_data', {}).get('oil', 'N/A')}
    
    Data Foreign Flow (Bandarmology - Khusus Indo):
    {data.get('foreign_flow', 'Data tidak tersedia.')}
    
    Data Fundamental & Statistik:
    - Tertinggi 52 Minggu: {data.get('stats', {}).get('high_52')}
    - Terendah 52 Minggu: {data.get('stats', {}).get('low_52')}
    - Market Cap: {data.get('stats', {}).get('market_cap')}
    - Ratios (Extracted): {json.dumps(data.get('ratios', {}))}
    
    Konteks Fundamental Tambahan (Deep Analysis):
    {data.get('fundamental_context', 'Tidak ada data tambahan.')[:8000]}
    
    Data Historis Close (14 hari terakhir): {json.dumps(data.get('history', [])[-14:])}
    
    {chat_context}
    {holdings_str} 
    
    Berita Terbaru (Judul):
    {json.dumps(data.get('news', []), indent=2, ensure_ascii=False)}

    Deep Reading News (Isi Artikel Lengkap):
    {data.get('deep_news_context', 'Tidak ada konten berita mendalam yang tersedia.')[:10000]}
    
    Tugas Anda:
    1. Terapkan kerangka penalaran DIKW (Data, Information, Knowledge, Wisdom) secara eksplisit dalam pemikiran analisis Anda:
       - Data: Ekstrak fakta mentah dari angka-angka yang diberikan (harga, volume, indikator).
       - Information: Kontekstualisasikan data tersebut (tren saat ini, level kunci support/resistance).
       - Knowledge: Pahami pola dan implikasinya (pola chart, konfirmasi sinyal, hubungan teknikal & fundamental).
       - Wisdom: Hasilkan keputusan (Actionable Insight) dengan strategi entry, exit, dan manajemen risiko yang terukur.
    2. Lakukan Analisis Teknikal & Fundamental Mendalam.
    3. Lakukan Analisis Sentimen "Deep Reading": Baca isi artikel lengkap di atas. bedakan mana berita yang hanya Clickbait/Rumor dan mana yang merupakan Berita Material. PERHATIKAN tanggal "DI-POSTING" pada setiap berita; berikan bobot lebih besar pada berita yang paling baru (misal: "2 jam yang lalu" lebih relevan daripada "5 hari yang lalu").
    4. Identifikasi pola chart (misal: Double Bottom, Breakout, Sideways) dari data historis.
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
    
    async with aiohttp.ClientSession(headers=headers) as session:
        for idx, api_key in enumerate(api_keys):
            for model_name in MODELS:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
                try:
                    async with session.post(url, json=payload, timeout=45) as response:
                        if response.status == 429:
                            move_key_to_bottom(api_key)
                            break
                        
                        if response.status == 503:
                            continue
                        
                        response.raise_for_status()
                        result = await response.json()
                        raw_content = result['candidates'][0]['content']['parts'][0]['text']
                        
                        # Use regex to extract the JSON block if wrapped in markers
                        json_match = re.search(r'```json\n(.*?)```', raw_content, re.DOTALL)
                        if json_match:
                            content = json_match.group(1).strip()
                        else:
                            # Fallback: try to clean common issues and use the whole content
                            content = raw_content.replace("```json", "").replace("```", "").strip()
                        
                        # Attempt to parse the content as JSON
                        try:
                            return json.loads(content)
                        except json.JSONDecodeError as e:
                            logging.error(f"Failed to decode JSON from AI: {e}. Raw content: {raw_content[:500]}...")
                            # If direct parse fails, try to find a JSON object within the text
                            # This is a last resort and might not always work for complex cases
                            json_str_match = re.search(r'\{.*\}', content, re.DOTALL)
                            if json_str_match:
                                try:
                                    return json.loads(json_str_match.group(0))
                                except json.JSONDecodeError:
                                    pass
                            raise
                        
                except Exception as e:
                    logging.warning(f"Error calling {model_name} dengan Key {idx+1}/{len(api_keys)}: {e}")
                    continue
                
    return None

async def summarize_history(api_keys, history_to_summarize):
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
    
    async with aiohttp.ClientSession(headers=headers) as session:
        for api_key in api_keys:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={api_key}"
            try:
                async with session.post(url, json=payload, timeout=10) as res:
                    if res.status == 200:
                        data = await res.json()
                        return data['candidates'][0]['content']['parts'][0]['text']
            except: continue
    return "Percakapan sebelumnya membahas analisis teknikal dan fundamental saham."

async def chat_with_gemini(api_keys, history, user_message):
    if isinstance(api_keys, str): api_keys = [api_keys]
    
    now_ui_str = datetime.datetime.now().strftime("%H:%M")
    now_api_str = datetime.datetime.now().strftime("%d %b %Y %H:%M")
    full_history = history + [{"role": "user", "time": now_ui_str, "api_time": now_api_str, "parts": [{"text": user_message}]}]
    
    api_history = []
    for msg in full_history:
        api_parts = []
        for p in msg.get("parts", []):
            if "text" in p:
                t_prefix = msg.get("api_time", msg.get("time", ""))
                if t_prefix and not p["text"].startswith(f"[{t_prefix}]") and not p["text"].startswith("WAKTU SEKARANG:"):
                    api_parts.append({"text": f"[{t_prefix}] {p['text']}"})
                else:
                    api_parts.append({"text": p["text"]})
            else:
                api_parts.append(p)
        api_history.append({"role": msg["role"], "parts": api_parts})
        
    if len(api_history) > 40:
        yield {"status": "Meringkas memori (setiap 20 chat) untuk menghemat token..."}
        context_msg = api_history[0]
        recent_msgs = api_history[-20:]
        to_summarize = api_history[1:-20]
        
        summary = await summarize_history(api_keys, to_summarize)
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
        },
        {
            "name": "get_idnfinancials_data",
            "description": "Membaca profil perusahaan, data keuangan, dividen, dan metrik penting lainnya langsung dari IDNFinancials menggunakan Selenium. Sangat direkomendasikan untuk analisis fundamental mendalam.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "symbol": {
                        "type": "STRING",
                        "description": "Simbol saham, contoh: 'BBCA', 'TLKM'."
                    }
                },
                "required": ["symbol"]
            }
        }
        ]
    }]
    
    async with aiohttp.ClientSession(headers=headers) as session:
        for idx, api_key in enumerate(api_keys):
            for model_name in MODELS:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
                
                payload = {
                    "systemInstruction": {"parts": [{"text": "Anda adalah asisten AI serba bisa dan analis keuangan profesional. Anda memiliki akses ke internet melalui tools. Berikan jawaban yang informatif, akurat, dan langsung dalam BAHASA INDONESIA. JANGAN PERNAH menambahkan peringatan atau disclaimer. Jika ditanya hal umum, jawablah sebagai asisten cerdas. Jika ditanya soal saham, jawablah sebagai analis profesional. Gunakan tool 'read_website_content' jika Anda butuh detail lebih dalam dari sebuah link hasil pencarian. PENTING: JANGAN PERNAH menyertakan stempel waktu (seperti [HH:MM] atau [Tanggal]) di awal balasan Anda, meskipun Anda melihatnya dalam sejarah percakapan. Stempel waktu tersebut hanya untuk konteks kronologis Anda. PENTING: Jika Anda butuh data (seperti IDNFinancials, harga, dsb), LANGSUNG PANGGIL TOOL yang relevan. JANGAN PERNAH merespons dengan kata-kata seperti 'Mohon tunggu', 'Saya sedang mengambil data', atau sejenisnya. Anda harus langsung mengaktifkan tool tersebut!"}]},
                    "contents": api_history,
                    "tools": tools,
                    "generationConfig": {"responseMimeType": "text/plain"}
                }
                
                try:
                    yield {"status": "AI sedang berpikir..."}
                    async with session.post(url, json=payload, timeout=60) as response:
                        if response.status == 429:
                            move_key_to_bottom(api_key)
                            yield {"status": "API Key limit. Mencoba Key lain..."}
                            break
                        
                        if response.status == 503:
                            yield {"status": "Model sibuk. Mencoba model lain..."}
                            continue
                        
                        response.raise_for_status()
                        result = await response.json()
                        parts = result['candidates'][0]['content']['parts']
                        
                        function_call = None
                        for p in parts:
                            if 'functionCall' in p:
                                function_call = p['functionCall']
                                break
                        
                        if function_call:
                            function_name = function_call.get('name', '')
                            args = function_call.get('args', {})
                            
                            tool_result = ""
                            if function_name == 'search_bing':
                                query = args.get('query', '')
                                stype = args.get('search_type', 'web')
                                yield {"status": f"AI menggunakan Bing Search ({stype}): '{query}'"}
                                tool_result = await search_bing(query, search_type=stype)
                            elif function_name == 'read_website_content':
                                target_url = args.get('url', '')
                                yield {"status": f"AI sedang membaca konten: {target_url[:50]}..."}
                                from news_scraper import scrape_article_content
                                tool_result = await scrape_article_content(target_url)
                            elif function_name == 'get_stock_price':
                                symbol = args.get('symbol', '')
                                yield {"status": f"AI mencari harga di Yahoo Finance: '{symbol}'"}
                                yf_result = await get_stock_price(symbol)
                                
                                if "error" in yf_result:
                                    yield {"status": "Yahoo Finance gagal. Mencoba fallback ke Bing..."}
                                    tool_result = await search_bing(f"harga saham {symbol} terkini")
                                else:
                                    tool_result = f"Harga {yf_result['symbol']} saat ini: {yf_result['price']} {yf_result['unit']} ({yf_result['change_percent']})"
                            
                            elif function_name == 'get_historical_stock_data':
                                symbol = args.get('symbol', '')
                                range_val = args.get('range', '3mo')
                                yield {"status": f"AI menarik data historis {range_val} untuk {symbol}..."}
                                from yahoo_finance_tool import get_historical_stock_data
                                res = await get_historical_stock_data(symbol, range_val)
                                tool_result = json.dumps(res) if "error" not in res else res["error"]
                                
                            elif function_name == 'get_fundamental_data':
                                symbol = args.get('symbol', '')
                                yield {"status": f"AI menganalisis data fundamental {symbol}..."}
                                from yahoo_finance_tool import get_fundamental_data
                                res = await get_fundamental_data(symbol)
                                tool_result = json.dumps(res) if "error" not in res else res["error"]
                                
                            elif function_name == 'get_technical_analysis':
                                symbol = args.get('symbol', '')
                                yield {"status": f"AI menghitung indikator teknikal mendalam untuk {symbol}..."}
                                from yahoo_finance_tool import get_historical_stock_data
                                from formatter import calculate_rsi, calculate_ma, calculate_technical_indicators
                                hist_data = await get_historical_stock_data(symbol, "90d")
                                if "error" in hist_data:
                                    tool_result = f"Gagal menghitung teknikal: {hist_data['error']}"
                                else:
                                    prices = [d['close'] for d in hist_data['history']]
                                    volumes = [d.get('volume', 0) for d in hist_data['history']]
                                    rsi = calculate_rsi(prices)
                                    ma20 = calculate_ma(prices, 20)
                                    deep = calculate_technical_indicators(prices, volumes=volumes)
                                    tool_result = json.dumps({
                                        "symbol": symbol, "rsi": rsi, "ma20": ma20, "indicators": deep
                                    })
                                    
                            elif function_name == 'get_market_sentiment':
                                symbol = args.get('symbol', '')
                                yield {"status": f"AI sedang meriset sentimen pasar untuk {symbol}..."}
                                from news_scraper import scrape_news
                                news = await scrape_news(symbol)
                                tool_result = json.dumps(news) if news else "Tidak ada berita ditemukan."
                                
                            elif function_name == 'get_idnfinancials_data':
                                symbol = args.get('symbol', '')
                                yield {"status": f"AI sedang membaca data IDNFinancials untuk {symbol} melalui Selenium..."}
                                from scraper import scrape_idnfinancials
                                clean_symbol = symbol.replace('.JK', '').replace('.jk', '')
                                tool_result = scrape_idnfinancials(clean_symbol)
                            
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
                            async with session.post(url, json=payload, timeout=60) as res_final:
                                res_final.raise_for_status()
                                result = await res_final.json()
                                parts = result['candidates'][0]['content']['parts']
                        
                        ai_reply = "".join([p.get('text', '') for p in parts]).strip()
                        now_str_model = datetime.datetime.now().strftime("%H:%M")
                        updated_history = full_history + [{"role": "model", "time": now_str_model, "api_time": now_api_str, "parts": [{"text": ai_reply}]}]
                        yield {"reply": ai_reply, "history": updated_history}
                        return
                        
                except Exception as e:
                    logging.warning(f"Error chat dengan {model_name} Key {idx+1}: {e}")
                    yield {"status": f"Terjadi kendala teknis. Mencoba ulang..."}
                    continue
                    
    yield {"reply": "Maaf, terjadi kesalahan pada semua model dan API Key.", "history": full_history}
import json
import logging
import aiohttp
import asyncio
import datetime
import re # Add this line
from bing_search_tool import search_bing
from yahoo_finance_tool import get_stock_price 
from utils import move_key_to_bottom
from projection_bridge import get_smart_projections
try:
    from idx_data_service import IDXDataService
    idx_service = IDXDataService()
except ImportError:
    idx_service = None

# Model fallback list for robustness
MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro"
]

async def _call_gemini_api(api_keys, payload, use_json=True):
    headers = {"Content-Type": "application/json"}
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
                        
                        if not use_json:
                            return raw_content

                        # Use regex to extract the JSON block if wrapped in markers
                        json_match = re.search(r'```json\n(.*?)```', raw_content, re.DOTALL)
                        if json_match:
                            content = json_match.group(1).strip()
                        else:
                            content = raw_content.replace("```json", "").replace("```", "").strip()
                        
                        try:
                            return json.loads(content)
                        except json.JSONDecodeError:
                            json_str_match = re.search(r'\{.*\}', content, re.DOTALL)
                            if json_str_match:
                                try:
                                    return json.loads(json_str_match.group(0))
                                except: pass
                            raise
                except Exception as e:
                    logging.warning(f"Error calling {model_name} dengan Key {idx+1}/{len(api_keys)}: {e}")
                    continue
    return None

async def _run_executor(api_keys, data, history_text, holdings_text, error_feedback=""):
    projections = get_smart_projections(data["symbol"], data)
    now_str = datetime.datetime.now().strftime("%d %B %Y %H:%M:%S")
    official_name = data.get('company_name', 'Nama Perusahaan Tidak Diketahui')
    
    correction_instruction = ""
    if error_feedback:
        correction_instruction = f"\n\n[PENTING - KOREKSI SEBELUMNYA]:\nValidator menemukan kesalahan pada draf Anda sebelumnya:\n{error_feedback}\nHarap perbaiki angka-angka tersebut agar sesuai dengan data mentah JSON di bawah."

    prompt = f"""
    [PERAN: AGEN EXECUTOR / ANALIS DATA]
    WAKTU ANALISIS SEKARANG: {now_str}
    NAMA RESMI PERUSAHAAN: {official_name}
    SIMBOL: {data['symbol']}
    
    Tugas Anda adalah membuat draf analisis teknikal dan fundamental mendalam untuk {official_name} ({data['symbol']}).
    PENTING: Gunakan NAMA RESMI PERUSAHAAN yang diberikan di atas ({official_name}). JANGAN menggunakan nama perusahaan lain meskipun Anda merasa simbolnya mirip.
    PENTING: Gunakan TANGGAL SEKARANG ({now_str}) sebagai referensi waktu analisis.
    PENTING: Berikan target harga dan strategi trading secara langsung tanpa memberikan disclaimer atau penafian risiko investasi.
    
    Gunakan HANYA data mentah di bawah ini. Jangan menebak angka.{correction_instruction}
    
    Data Mentah:
    - Harga: {data.get('price')} ({data.get('change')}%)
    - Trend: {data.get('market_trend')}
    - RSI: {data.get('rsi')} | MA20: {data.get('ma20')}
    - S/R: S1:{data.get('support_1')}, R1:{data.get('resistance_1')}
    - MACD: {data.get('macd')} | BB: {data.get('bb_upper')}/{data.get('bb_lower')}
    - Fibonacci 61.8%: {data.get('fib_618')}
    - Macro: USD/IDR {data.get('macro_data', {}).get('usd_idr')}, BI Rate {data.get('macro_data', {}).get('bi_rate')}
    - Fundamental: Cap {data.get('stats', {}).get('market_cap')}, Ratios: {json.dumps(data.get('ratios', {}))}
    - Context: {data.get('fundamental_context', '')[:5000]}
    - News: {json.dumps(data.get('news', []))[:2000]}
    
    {history_text}
    {holdings_text}
    {projections}

    Format output WAJIB JSON:
    {{
        "analysis": "Draf analisis narasi",
        "signal": "BUY/SELL/HOLD",
        "entry_price": "angka",
        "target_price": "angka",
        "cut_loss_price": "angka"
    }}
    """
    
    payload = {
        "systemInstruction": {"parts": [{"text": "Anda adalah Agen Executor. Fokus pada pembuatan draf analisis berbasis data mentah. Gunakan Bahasa Indonesia. Dilarang berhalusinasi angka. Berikan analisis dan strategi secara langsung tanpa penafian."}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]
    }
    return await _call_gemini_api(api_keys, payload)

async def _run_validator(api_keys, draft, data):
    raw_summary = {
        "price": data.get('price'),
        "change": data.get('change'),
        "ratios": data.get('ratios'),
        "support_1": data.get('support_1'),
        "resistance_1": data.get('resistance_1'),
        "market_cap": data.get('stats', {}).get('market_cap')
    }
    
    prompt = f"""
    [PERAN: AGEN VALIDATOR / PEMERIKSA FAKTA]
    Bandingkan draf analisis di bawah dengan Data Mentah (Ground Truth).
    Tugas Anda: Pastikan SEMUA angka (harga, rasio, target) dalam draf sesuai dengan Data Mentah.
    
    Data Mentah (Ground Truth):
    {json.dumps(raw_summary)}
    
    Draf Analisis:
    {json.dumps(draft)}
    
    Jika ada angka yang tidak cocok atau berhalusinasi, berikan status FAILED dan sebutkan kesalahannya secara spesifik.
    Jika semua angka cocok (toleransi pembulatan 1%), berikan status PASSED.
    
    Format output WAJIB JSON:
    {{
        "status": "PASSED atau FAILED",
        "errors": ["list kesalahan jika ada"]
    }}
    """
    
    payload = {
        "systemInstruction": {"parts": [{"text": "Anda adalah Agen Validator. Tugas Anda HANYA memvalidasi angka vs data mentah. Jangan menulis analisis baru."}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]
    }
    return await _call_gemini_api(api_keys, payload)

async def _run_critic(api_keys, draft, data):
    now_str = datetime.datetime.now().strftime("%d %B %Y")
    official_name = data.get('company_name', 'Nama Perusahaan Tidak Diketahui')
    prompt = f"""
    [PERAN: AGEN CRITIC / EDITOR SENIOR]
    WAKTU SEKARANG: {now_str}
    NAMA RESMI PERUSAHAAN: {official_name}
    
    Anda menerima draf analisis yang sudah divalidasi datanya untuk {official_name} ({data['symbol']}).
    Tugas Anda:
    1. Poles bahasa agar sangat profesional (standar analis pasar modal).
    2. Pastikan alasan (reason) logis dan kuat.
    3. Wajib cantumkan sumber data (Grounding) secara eksplisit (Yahoo Finance, IDNFinancials, dll).
    4. PENTING: Gunakan NAMA RESMI PERUSAHAAN ({official_name}) secara konsisten. JANGAN tertukar dengan nama perusahaan lain.
    5. PENTING: Gunakan tanggal hari ini ({now_str}) dalam laporan. JANGAN menyebutkan tanggal atau tahun dari masa lalu sebagai waktu analisis saat ini.
    6. PENTING: Jangan memberikan disclaimer atau penafian mengenai risiko investasi atau saran keuangan. Berikan opini dan strategi secara langsung.
    
    Draf Terverifikasi:
    {json.dumps(draft)}
    
    Format output WAJIB JSON:
    {{
        "analysis": "Hasil akhir narasi profesional untuk {official_name} dengan sumber data dan tanggal {now_str}",
        "signal": "{draft.get('signal')}",
        "reason": "Alasan strategis utama",
        "entry_price": "{draft.get('entry_price')}",
        "target_price": "{draft.get('target_price')}",
        "cut_loss_price": "{draft.get('cut_loss_price')}"
    }}
    """
    
    payload = {
        "systemInstruction": {"parts": [{"text": "Anda adalah Agen Critic. Fokus pada kualitas narasi, nada profesional, dan grounding data. Gunakan Bahasa Indonesia. Berikan opini dan strategi secara langsung tanpa penafian."}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]
    }
    return await _call_gemini_api(api_keys, payload)

async def analyze_with_gemini(api_keys, data, history=None):
    if isinstance(api_keys, str): api_keys = [api_keys]
    
    agent_trail = []
    chat_context = ""
    if history and len(history) > 1:
        relevant_history = history[-6:]
        chat_context = "Konteks Obrolan Sebelumnya:\n"
        for m in relevant_history:
            role = "User" if m.get("role") == "user" else "AI"
            text = m["parts"][0].get("text", "") if m.get("parts") else ""
            if text and not text.startswith("WAKTU SEKARANG:"):
                chat_context += f"- {role}: {text[:200]}\n"

    holdings_str = ""
    if 'user_holdings' in data and data['user_holdings']:
        holdings_str = "Status Aset User:\n"
        for h in data['user_holdings']:
            holdings_str += f"- {h['trade_type']}, Lots: {h['lots']}, Harga: {h['price']}\n"

    # MULTI-AGENT WORKFLOW
    logging.info(f"Multi-Agent: Menjalankan Executor untuk {data['symbol']}...")
    draft = await _run_executor(api_keys, data, chat_context, holdings_str)
    if not draft: return None
    agent_trail.append({"agent": "Executor", "output": draft})
    
    # Validation Loop (Self-Correction)
    max_retries = 2
    final_draft = draft
    for i in range(max_retries):
        logging.info(f"Multi-Agent: Menjalankan Validator (Percobaan {i+1})...")
        validation = await _run_validator(api_keys, final_draft, data)
        agent_trail.append({"agent": "Validator", "iteration": i+1, "output": validation})
        
        if validation and validation.get("status") == "PASSED":
            logging.info("Multi-Agent: Validasi LULUS.")
            break
        else:
            errors = ", ".join(validation.get("errors", [])) if validation else "Gagal validasi data."
            logging.warning(f"Multi-Agent: Validasi GAGAL. Kesalahan: {errors}")
            if i < max_retries - 1:
                logging.info("Multi-Agent: Meminta Executor memperbaiki draf...")
                final_draft = await _run_executor(api_keys, data, chat_context, holdings_str, error_feedback=errors)
                if not final_draft: return None
                agent_trail.append({"agent": "Executor (Correction)", "iteration": i+1, "output": final_draft})
            else:
                logging.error("Multi-Agent: Validasi gagal setelah percobaan maksimal.")

    logging.info("Multi-Agent: Menjalankan Critic untuk finalisasi...")
    final_report = await _run_critic(api_keys, final_draft, data)
    if final_report:
        final_report["agent_trail"] = agent_trail
    return final_report

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
        },
        {
            "name": "get_idx_historical_data_2019_2025",
            "description": "Mendapatkan data historis saham Indonesia yang sangat lengkap (Open, High, Low, Close, Volume) dari tahun 2019 hingga 2025. Gunakan ini untuk analisis tren jangka panjang (2-5 tahun).",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "symbol": { "type": "STRING", "description": "Simbol saham (misal: BBCA, TLKM)." },
                    "period": { "type": "STRING", "description": "Rentang waktu: 1y, 2y, atau 5y.", "enum": ["1y", "2y", "5y"] }
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
                
                # Iterative multi-turn tool calling loop
                current_api_history = list(api_history)
                
                try:
                    for turn_idx in range(5): # Max 5 turns of tool calling
                        payload = {
                            "systemInstruction": {"parts": [{"text": "Anda adalah analis keuangan profesional yang dilarang keras menggunakan pengetahuan internal atau data pelatihan Anda untuk menyebutkan harga saham, rasio keuangan, atau berita. Selalu gunakan data yang disediakan dalam konteks atau panggil alat (tools) yang tersedia. Jika data tidak ada dalam konteks, Anda WAJIB memanggil tool yang relevan. PENTING: JANGAN PERNAH menjelaskan rencana Anda atau menyebutkan nama fungsi yang akan Anda panggil dalam pesan teks. JANGAN PERNAH merespons dengan kata-kata seperti 'Saya akan menggunakan...', 'Mohon tunggu', 'Saya sedang mencari...', atau sejenisnya. Anda harus LANGSUNG memanggil tool tersebut tanpa teks pendahuluan. Jika Anda sudah memanggil tool, berikan jawaban berdasarkan hasilnya. Selalu cantumkan sumber data (Grounding) dalam jawaban Anda. PENTING: Jangan pernah memberikan peringatan atau disclaimer standar mengenai saran keuangan, strategi trading, atau risiko investasi. Pengguna adalah investor berpengalaman yang sudah memahami risiko. Berikan analisis, saran strategi, dan opini profesional Anda secara langsung dan tajam tanpa basa-basi penafian."}]},
                            "contents": current_api_history,
                            "tools": tools,
                            "generationConfig": {"responseMimeType": "text/plain"},
                            "safetySettings": [
                                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
                            ]
                        }
                        
                        yield {"status": f"AI sedang memproses... (Turn {turn_idx+1})"}
                        async with session.post(url, json=payload, timeout=60) as response:
                            if response.status == 429:
                                move_key_to_bottom(api_key)
                                yield {"status": "API Key limit. Mencoba Key lain..."}
                                break # Next API Key
                            
                            if response.status == 503:
                                yield {"status": "Model sibuk. Mencoba model lain..."}
                                continue # Next Model
                                
                            response.raise_for_status()
                            result = await response.json()
                            
                            if 'candidates' not in result or not result['candidates']:
                                break
                                
                            candidate = result['candidates'][0]
                            model_message = candidate['content']
                            parts = model_message.get('parts', [])
                            
                            # Add model response to history
                            current_api_history.append(model_message)
                            
                            # Check for all function calls in this turn
                            function_calls = [p['functionCall'] for p in parts if 'functionCall' in p]
                            
                            if not function_calls:
                                # No tools called, this is the final response
                                ai_reply = "".join([p.get('text', '') for p in parts]).strip()
                                now_str_model = datetime.datetime.now().strftime("%H:%M")
                                # Note: updated_history only contains the final text for compatibility with app.py
                                updated_history = full_history + [{"role": "model", "time": now_str_model, "api_time": now_api_str, "parts": [{"text": ai_reply}]}]
                                yield {"reply": ai_reply, "history": updated_history}
                                return # DONE!
                            
                            # Execute all tools called in this turn
                            new_function_responses = []
                            for fc in function_calls:
                                function_name = fc.get('name', '')
                                args = fc.get('args', {})
                                
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
                                        tool_result = json.dumps({"symbol": symbol, "rsi": calculate_rsi(prices), "ma20": calculate_ma(prices, 20), "indicators": calculate_technical_indicators(prices, volumes=volumes)})
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
                                    tool_result = await scrape_idnfinancials(symbol.replace('.JK', '').replace('.jk', ''))
                                elif function_name == 'get_idx_historical_data_2019_2025':
                                    symbol = args.get('symbol', '').replace('.JK', '').replace('.jk', '')
                                    period = args.get('period', '1y')
                                    yield {'status': f'AI mengakses Database Historis 2019-2025 untuk {symbol}...'}
                                    if idx_service:
                                        res = idx_service.get_historical_data(symbol, period)
                                        tool_result = json.dumps(res) if res['success'] else res['error']
                                    else:
                                        tool_result = 'Fitur database historis local belum terpasang dengan benar.'
                                
                                new_function_responses.append({
                                    "role": "function",
                                    "parts": [{"functionResponse": {"name": function_name, "response": {"result": tool_result}}}]
                                })
                            
                            # Add all tool responses to history for next turn
                            current_api_history.extend(new_function_responses)
                            yield {"status": "AI memproses hasil pencarian..."}
                            # Continues to the next turn_idx iteration to send history back to Gemini
                except Exception as e:
                    logging.warning(f"Error chat dengan {model_name} Key {idx+1}: {e}")
                    yield {"status": f"Terjadi kendala teknis. Mencoba ulang..."}
                    continue

                    
    yield {"reply": "Maaf, terjadi kesalahan pada semua model dan API Key.", "history": full_history}
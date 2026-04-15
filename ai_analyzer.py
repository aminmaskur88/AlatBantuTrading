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
    
    Data Historis Close (90 hari): {json.dumps(data.get('history', [])[-30:])} (ditampilkan 30 hari terakhir)
    
    {holdings_str} 
    
    Berita Terbaru:
    {json.dumps(data.get('news', []), indent=2, ensure_ascii=False)}
    
    Tugas Anda:
    1. Lakukan Analisis Teknikal & Fundamental Mendalam: Gunakan level Fibonacci dan statistik 52 minggu di atas untuk menentukan area beli/jual yang logis.
    2. Identifikasi pola chart (misal: Double Bottom, Breakout, Sideways) dari data historis.
    3. Anda SEKARANG MEMILIKI data matematis yang cukup. JANGAN katakan Anda tidak bisa melakukan analisis teknikal atau menghitung target harga.
    4. Berikan angka presisi untuk: Harga Beli (Entry), Target Penjualan (TP), dan Cut Loss (CL).
    
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

def chat_with_gemini(api_keys, history, user_message):
    if isinstance(api_keys, str):
        api_keys = [api_keys]
        
    headers = {"Content-Type": "application/json"}
    current_history = history + [{"role": "user", "parts": [{"text": user_message}]}]
    
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
                    }
                },
                "required": ["query"]
            }
        },
        {
            "name": "get_stock_price",
            "description": "Mengambil harga saham terkini untuk simbol saham tertentu dari Yahoo Finance. Gunakan ini khusus untuk mendapatkan harga real-time, misal 'harga BBCA sekarang'. Simbol saham Indonesia biasanya diakhiri dengan '.JK' (misal: 'BBCA.JK'), pastikan format ini jika mencari saham Indonesia. Jika user menyebutkan nama perusahaan Indonesia tanpa '.JK', tambahkan secara otomatis.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "symbol": {
                        "type": "STRING",
                        "description": "Simbol saham yang akan dicari, contoh: 'BBCA.JK', 'AAPL', 'MSFT'."
                    }
                },
                "required": ["symbol"]
            }
        }
        ]
    }]
    
    for idx, api_key in enumerate(api_keys):
        for model_name in MODELS:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            
            payload = {
                "systemInstruction": {"parts": [{"text": "Anda adalah asisten dan analis keuangan profesional. Berikan analisis dan jawaban secara langsung dalam BAHASA INDONESIA. JANGAN PERNAH menambahkan peringatan atau disclaimer."}]},
                "contents": current_history,
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
                        yield {"status": f"AI menggunakan Bing Search: '{query}'"}
                        logging.info(f"AI (Chat - {model_name}) mencari Bing: {query}")
                        tool_result = search_bing(query)
                    elif function_name == 'get_stock_price':
                        symbol = args.get('symbol', '')
                        yield {"status": f"AI mencari harga di Yahoo Finance: '{symbol}'"}
                        logging.info(f"AI (Chat - {model_name}) mencari harga di Yahoo Finance untuk: {symbol}")
                        yf_result = get_stock_price(symbol)
                        
                        if "error" in yf_result:
                            yield {"status": "Yahoo Finance gagal. Mencoba fallback ke Bing..."}
                            bing_query = f"harga saham {symbol} terkini"
                            bing_search_result = search_bing(bing_query)
                            tool_result = f"Gagal mendapatkan harga dari Yahoo Finance: {yf_result['error']}. Hasil pencarian Bing: {bing_search_result}"
                        else:
                            tool_result = f"Harga {yf_result['symbol']} saat ini: {yf_result['price']} {yf_result['unit']} ({yf_result['change_percent']})"
                    
                    current_history.append({"role": "model", "parts": [{"functionCall": function_call}]})
                    current_history.append({
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
                    
                    payload["contents"] = current_history
                    yield {"status": "AI memproses hasil pencarian..."}
                    response = requests.post(url, headers=headers, json=payload, timeout=60)
                    response.raise_for_status()
                    result = response.json()
                    part = result['candidates'][0]['content']['parts'][0]
                
                ai_reply = part.get('text', '').strip()
                updated_history = current_history + [{"role": "model", "parts": [{"text": ai_reply}]}]
                yield {"reply": ai_reply, "history": updated_history}
                return
                
            except Exception as e:
                logging.warning(f"Error chat dengan {model_name} Key {idx+1}: {e}")
                yield {"status": f"Terjadi kendala teknis. Mencoba ulang..."}
                continue
                
    yield {"reply": "Maaf, terjadi kesalahan pada semua model dan API Key.", "history": current_history}

import json
import logging
import requests
import time
from bing_search_tool import search_bing
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
    Kamu adalah analis keuangan dan pasar modal profesional.
    Berikut adalah data pasar, indikator teknikal, dan berita terbaru untuk aset {data['symbol']}:
    
    Data Harga & Teknikal:
    - Harga Saat Ini: {data.get('price')}
    - Perubahan: {data.get('change')}% 
    - Tren Pasar: {data.get('market_trend')}
    - RSI (14): {data.get('rsi')} ({data.get('rsi_desc')})
    - Moving Average (20): {data.get('ma20')} ({data.get('ma_signal')})
    - Sentimen Berita: {data.get('sentiment')}
    
    {holdings_str} 
    
    Berita Terbaru:
    {json.dumps(data.get('news', []), indent=2, ensure_ascii=False)}
    
    Tugas Anda:
    1. Berikan analisis singkat yang menggabungkan data teknikal (RSI, MA) dan sentimen berita.
    2. Berikan rekomendasi (BUY / HOLD / SELL).
    3. Berikan alasan yang kuat berdasarkan indikator teknikal dan fundamental/berita.
    4. Berikan angka spesifik untuk: Harga Beli (Entry), Harga Target Penjualan (Target/TP), dan Harga Jual Rugi (Cut Loss/CL).
    
    PENTING: Format output Anda WAJIB berupa JSON murni dengan struktur berikut:
    {{
        "analysis": "Penjelasan singkat",
        "signal": "BUY",
        "reason": "Alasan rekomendasi",
        "entry_price": "1000",
        "target_price": "1200",
        "cut_loss_price": "950"
    }}
    Pastikan tidak ada teks lain selain JSON yang valid. Outputkan string JSON saja.
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
        }]
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
                response = requests.post(url, headers=headers, json=payload, timeout=60)
                
                if response.status_code == 429:
                    move_key_to_bottom(api_key)
                    break
                
                if response.status_code == 503:
                    continue
                
                response.raise_for_status()
                result = response.json()
                part = result['candidates'][0]['content']['parts'][0]
                
                if 'functionCall' in part:
                    function_call = part['functionCall']
                    query = function_call.get('args', {}).get('query', '')
                    logging.info(f"AI (Chat - {model_name}) mencari: {query}")
                    
                    current_history.append({"role": "model", "parts": [{"functionCall": function_call}]})
                    search_result = search_bing(query)
                    current_history.append({
                        "role": "function",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": "search_bing",
                                    "response": {"result": search_result}
                                }
                            }
                        ]
                    })
                    
                    payload["contents"] = current_history
                    response = requests.post(url, headers=headers, json=payload, timeout=60)
                    response.raise_for_status()
                    result = response.json()
                    part = result['candidates'][0]['content']['parts'][0]
                
                ai_reply = part.get('text', '').strip()
                updated_history = current_history + [{"role": "model", "parts": [{"text": ai_reply}]}]
                return ai_reply, updated_history
                
            except Exception as e:
                logging.warning(f"Error chat dengan {model_name} Key {idx+1}: {e}")
                continue
                
    return "Maaf, terjadi kesalahan pada semua model dan API Key.", history

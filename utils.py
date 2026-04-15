import os
import json
import logging
import time

def setup_logging():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def save_json(filepath, data):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def load_json(filepath):
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def get_api_keys():
    try:
        keys = []
        with open("gemini_key.txt", "r") as f:
            for line in f:
                key = line.strip()
                if key:
                    keys.append(key)
            if not keys:
                logging.error("gemini_key.txt is empty. Please add your Gemini API keys.")
                return []
            return keys
    except FileNotFoundError:
        logging.error("gemini_key.txt not found. Please create it and paste your Gemini API keys (one per line).")
        return []

def move_key_to_bottom(bad_key):
    keys = get_api_keys()
    if bad_key in keys:
        keys.remove(bad_key)
        keys.append(bad_key)
        try:
            with open("gemini_key.txt", "w") as f:
                for k in keys:
                    f.write(f"{k}\n")
            logging.info(f"API Key dipindahkan ke antrean bawah karena limit/error.")
        except Exception as e:
            logging.error(f"Gagal memindahkan API Key: {e}")
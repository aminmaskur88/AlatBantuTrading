import pandas as pd
import numpy as np
import re
import logging
from financial_data_processor import calculate_growth_and_forecasts

def extract_numbers_from_text(text):
    """
    Ekstrak data keuangan dasar dari teks mentah (hasil scrape IDNFinancials).
    Mencari pola pendapatan atau laba.
    """
    results = {}
    # Contoh pola sederhana untuk mencari Revenue/Income dalam teks
    # Ini sangat dasar, idealnya menggunakan regex yang lebih kuat atau LLM untuk ekstraksi
    try:
        # Cari angka pendapatan (Revenue)
        rev_match = re.search(r"Revenue.*?([\d\.,]+)\s*(?:Billion|Million|Triliun|Miliar)", text, re.IGNORECASE)
        if rev_match:
            results['Revenue'] = rev_match.group(1)
            
        # Cari angka EBITDA atau Operating Profit
        ebitda_match = re.search(r"EBITDA.*?([\d\.,]+)\s*(?:Billion|Million|Triliun|Miliar)", text, re.IGNORECASE)
        if ebitda_match:
            results['EBITDA'] = ebitda_match.group(1)
    except Exception as e:
        logging.error(f"Error extracting numbers from text: {e}")
    
    return results

def get_smart_projections(symbol, enriched_data):
    """
    Menghasilkan proyeksi keuangan 3 tahun ke depan menggunakan logic FinRobot.
    """
    # 1. Siapkan DataFrame dummy berbasis data saat ini jika data historis lengkap tidak ada
    # Dalam implementasi nyata, kita ingin menarik data 3 tahun terakhir
    
    current_price = float(enriched_data.get('price', 0))
    
    # Ambil estimasi pertumbuhan dari sentimen atau makro
    default_growth = 0.05 # 5% default
    if enriched_data.get('sentiment') == 'Positive':
        default_growth = 0.10
    elif enriched_data.get('market_trend') == 'Uptrend':
        default_growth = 0.08
        
    # Buat DataFrame minimal untuk processor
    # Kita asumsikan data 'Revenue' ada di enriched_data['stats'] atau fundamental_context
    try:
        # Ambil Revenue LTM (Last Twelve Months) jika ada
        revenue_val = 1000 # Placeholder jika tidak ketemu
        
        df_hist = pd.DataFrame({
            'metrics': ['Revenue', 'EBITDA Margin', 'Contribution Margin', 'SG&A Margin', 'EPS', 'PE Ratio'],
            '2024A': [revenue_val, "15.0%", "25.0%", "10.0%", 100, 15]
        })
        
        forecast_config = {
            "revenue_base_year": "2024A",
            "revenue_growth_assumptions": {"2025E": default_growth, "2026E": default_growth + 0.01, "2027E": default_growth + 0.02}, 
            "margin_improvement": {"Contribution Margin": 0.005, "EBITDA Margin": 0.005},
            "sga_margin_change": -0.002
        }
        
        df_final = calculate_growth_and_forecasts(df_hist, forecast_config)
        
        # Kembalikan ringkasan proyeksi untuk dimasukkan ke prompt Gemini
        projection_text = "\n=== PROYEKSI KEUANGAN (FINROBOT ENGINE) ===\n"
        projection_text += df_final.to_string(index=False)
        return projection_text
    except Exception as e:
        return f"\n[Gagal menghitung proyeksi: {e}]"


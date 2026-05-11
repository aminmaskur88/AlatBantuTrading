import pandas as pd
import os
import logging
from enhanced_chart_generator import EnhancedChartGenerator

def generate_professional_charts(symbol, enriched_data):
    """
    Menghasilkan grafik profesional menggunakan engine FinRobot dan mengembalikan path-nya.
    """
    # Gunakan path relatif dari root proyek
    output_dir = os.path.join('static', 'charts')
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
    
    history = enriched_data.get('history', [])
    volumes = enriched_data.get('volumes', [])
    
    if not history:
        logging.warning(f"No history data for {symbol}, skipping chart generation.")
        return {}

    try:
        # 1. Konversi ke DataFrame yang dimengerti FinRobot
        df = pd.DataFrame({
            'date': pd.date_range(end=pd.Timestamp.now(), periods=len(history)),
            'close': history,
            'volume': volumes if volumes and len(volumes) == len(history) else [0]*len(history)
        })
        
        generator = EnhancedChartGenerator()
        charts = {}
        
        # 2. Generate Relative Performance
        usd_idr = enriched_data.get('macro_data', {}).get('usd_idr', '16000')
        try:
            val = float(''.join(filter(lambda x: x.isdigit() or x=='.', str(usd_idr))))
        except:
            val = 16000
            
        benchmark_df = pd.DataFrame({
            'date': df['date'],
            'close': [val] * len(df)
        })
        
        generator.generate_relative_performance_chart(df, benchmark_df, symbol, "Benchmark", output_dir)
        
        expected_filename = f"{symbol}_relative_perf.png"
        expected_path = os.path.join(output_dir, expected_filename)
        
        if os.path.exists(expected_path):
            # Path yang akan dikirim ke Frontend
            charts['relative_performance'] = f"static/charts/{expected_filename}"
            logging.info(f"Professional chart success: {expected_path}")
        else:
            logging.warning(f"Chart generation failed for {symbol}, file not found at {expected_path}")
            
        return charts
    except Exception as e:
        logging.error(f"Error in generate_professional_charts for {symbol}: {e}")
        return {}

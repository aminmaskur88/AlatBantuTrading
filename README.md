# 📈 AI Stock Analyzer Pro

Aplikasi analisis saham berbasis AI (Gemini API) yang mampu mengambil data pasar secara real-time, menganalisis berita terkini (Deep Reading), dan memberikan rekomendasi investasi (BUY/HOLD/SELL) dengan target harga yang presisi.

---

## ✨ Fitur Utama

- **📊 Analisis Pasar Real-Time**: Mengambil harga saham terkini dari Yahoo Finance (Saham Indo/Global) dan CoinGecko (Crypto).
- **📰 Deep Reading AI News**: Secara otomatis mencari berita terbaru melalui Bing News, membaca isi artikel secara mendalam, dan merangkum poin-poin krusial.
- **🤖 Rekomendasi Investasi AI**: Menggunakan Gemini AI untuk memberikan analisis teknikal (RSI, MA20), sentimen, serta target harga (*Entry, Target Price, Cut Loss*).
- **💬 Dialog Chat Interaktif**: Fitur tanya-jawab langsung dengan AI tentang kondisi saham tertentu dengan konteks data terbaru.
- **🖼️ Chart Teknikal Terintegrasi**: Grafik TradingView real-time yang tertanam langsung di dashboard.
- **🛠️ Auto-Research Otomatis**: Fitur "Tambah Berita" yang memicu AI untuk melakukan riset mandalam di internet jika data yang ada dirasa kurang.

---

## 🚀 Cara Instalasi (Termux/Linux)

### 1. Persiapan Lingkungan
Pastikan Anda sudah menginstal Python dan Chromium:
```bash
pkg install python chromium-browser
```

### 2. Instalasi Dependensi
Clone repositori ini dan instal library yang dibutuhkan:
```bash
pip install flask requests beautifulsoup4 selenium
```

### 3. Konfigurasi API Key
Buat file bernama `gemini_key.txt` di direktori akar dan masukkan API Key Gemini Anda (satu per baris jika memiliki lebih dari satu untuk fitur rotasi key):
```text
ISI_API_KEY_ANDA_DISINI
```

### 4. Menjalankan Aplikasi
Jalankan server Flask:
```bash
python app.py
```
Akses dashboard melalui browser di: `http://localhost:5000`

---

## 📂 Struktur Proyek

- `app.py`: Entry point server Flask dan API backend.
- `scraper.py`: Mesin pengambil data harga (Yahoo Finance & CoinGecko).
- `news_scraper.py`: Mesin pencari dan pembaca artikel berita (Bing News).
- `ai_analyzer.py`: Logika integrasi dengan Gemini API untuk analisis & chat.
- `formatter.py`: Pembersihan data dan penghitungan indikator teknikal (RSI/MA).
- `templates/`: Folder tampilan antarmuka (UI).
- `data/`: Folder penyimpanan cache analisis dan database portofolio.

---

## ⚖️ Disclaimer
Aplikasi ini hanya alat bantu analisis dan **bukan merupakan saran investasi keuangan**. Segala keputusan jual/beli saham sepenuhnya adalah tanggung jawab pengguna. Selalu lakukan riset mandiri (*DYOR*) sebelum mengambil keputusan finansial.

---

**Dibuat oleh: Gemini CLI Agent**  
*Update Terakhir: 15 April 2026*

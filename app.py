from flask import Flask, render_template, request
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import json
import sys

# -----------------
# 1. KAZIMA AYARLARI VE GLOBAL DEĞİŞKENLER
# -----------------
_visited_urls = set()
_base_domain = ""
_MAX_PAGES_TO_SCRAPE = 10 # Maksimum kazınacak sayfa sayısı

# -----------------
# 2. YARDIMCI VE KAZIMA FONKSİYONLARI
# -----------------
def is_valid(url):
    """URL'nin geçerli şema (http/https) ve domain içerip içermediğini kontrol eder."""
    parsed = urlparse(url)
    return bool(parsed.netloc) and bool(parsed.scheme)

def is_internal(url, base_url):
    """URL'nin ana domain'de (dış link değil) olup olmadığını kontrol eder."""
    base_domain = urlparse(base_url).netloc
    target_domain = urlparse(url).netloc
    return base_domain == target_domain

def sanitize_text(text):
    """Metni JSON uyumlu hale getirir: Tırnakları ve satır sonlarını temizler."""
    # JSON'ı bozabilecek çift tırnakları tek tırnağa çevirir, yeni satırları boşlukla değiştirir.
    return text.replace('"', "'").replace('\n', ' ').replace('\r', ' ').replace('\t', ' ').strip()

def scrape_text_from_url(url):
    """Verilen URL'den metinleri çeker ve takip edilecek linkleri döndürür."""
    page_texts = [] # [ ["url", "metin"], ... ] formatında veri tutar
    links_to_follow = []
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status() 
    except requests.exceptions.RequestException as e:
        print(f"Hata: {url} adresine ulaşılamadı. {e}", file=sys.stderr)
        return [], []

    soup = BeautifulSoup(response.content, 'html.parser')

    # İçerik Etiketleri: Ana metinleri (paragraf, başlıklar, liste öğeleri) hedef alıyoruz.
    content_tags = ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li']
    
    # 1. Metin ayıklama ve filtreleme
    for tag in content_tags:
        for element in soup.find_all(tag):
            raw_text = element.get_text(strip=True)
            
            # Ana metin filtresi: 40 karakterden uzun olan metinleri kabul et
            if len(raw_text) > 40: 
                clean_text = sanitize_text(raw_text)
                # İstenen JSON formatı: [ "sayfa_adresi", "metin" ]
                page_texts.append([url, clean_text])

    # 2. Linkleri yakalama (Sadece dahili linkler)
    for a_tag in soup.find_all('a', href=True):
        href = a_tag.get('href')
        full_url = urljoin(url, href) 
        
        # Linkin parametresiz ve temizlenmiş versiyonunu al
        clean_url = urljoin(full_url, urlparse(full_url).path).strip('/')
        
        # Geçerli, aynı domain'de ve henüz ziyaret edilmemiş mi?
        if is_valid(full_url) and is_internal(full_url, _base_domain) and clean_url not in _visited_urls:
            links_to_follow.append(clean_url)
    
    # Kazınan URL'yi ziyaret edilmiş olarak işaretle
    # strip('/') ile sondaki '/' işaretini kaldırarak aynı URL'nin farklı formlarını tek sayarız.
    _visited_urls.add(urljoin(url, urlparse(url).path).strip('/'))

    return page_texts, links_to_follow


def start_crawl(start_url):
    """Ana kazıma işlemini başlatır ve linkleri takip eder (Crawler)."""
    global _visited_urls, _base_domain
    _visited_urls.clear() 
    _base_domain = start_url
    
    clean_start_url = urljoin(start_url, urlparse(start_url).path).strip('/')
    queue = [clean_start_url]
    all_json_data = [] # Tüm sayfalardan toplanan JSON verileri

    while queue and len(_visited_urls) < _MAX_PAGES_TO_SCRAPE:
        current_url = queue.pop(0) 
        
        if current_url in _visited_urls:
            continue

        print(f"Kazınıyor: {current_url}")
        
        texts, new_links = scrape_text_from_url(current_url)
        
        # Toplanan metinleri ana listeye ekle
        all_json_data.extend(texts)
        
        for link in new_links:
            # Maksimum sayfa sayısına ulaşılmamışsa, kuyruğa ekle
            if len(_visited_urls) + len(queue) < _MAX_PAGES_TO_SCRAPE and link not in _visited_urls and link not in queue:
                queue.append(link)

    return all_json_data

# -----------------
# 3. FLASK ROUTE
# -----------------
app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    json_results = None
    url_input = ""
    error = None 
    
    if request.method == 'POST':
        url_input = request.form.get('url_address', '').strip()
        
        if not url_input:
            error = "Lütfen bir web adresi girin."
        else:
            # Protokol ekleme (Eğer kullanıcı sadece domain girerse)
            if not url_input.startswith(('http://', 'https://')):
                url_input = 'http://' + url_input

            if not is_valid(url_input):
                error = "Lütfen geçerli bir web adresi girin (örn: https://turnateknoloji.com)."
            
            if not error:
                print(f"\n--- Kazıma Başlatılıyor: {url_input} ---")
                
                scraped_json_list = start_crawl(url_input)
                
                if scraped_json_list:
                    # Python listesini JSON formatında string'e dönüştür
                    # indent=4 ile çıktıyı okunabilir formatta yaparız.
                    # ensure_ascii=False ile Türkçe karakterlerin bozulmasını önleriz.
                    json_results = json.dumps(scraped_json_list, indent=4, ensure_ascii=False)
                else:
                    error = f"'{url_input}' adresinden metin ayıklanamadı. (Ziyaret edilen sayfa sayısı: {len(_visited_urls)})"

    # Sonuçları (JSON string'i) ve hataları şablona gönder
    return render_template('index.html', json_results=json_results, url_input=url_input, error=error)

# -----------------
# 4. UYGULAMA BAŞLANGICI
# -----------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

import streamlit as st
import requests
from bs4 import BeautifulSoup
from io import BytesIO
import re
from urllib.parse import quote
import zipfile
import math
import time

# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# --- 1. CONFIGURATIE ---
st.set_page_config(page_title="Cover Hunter Pro", page_icon="🟢", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #121212; color: white; }
    div.stButton > button { background-color: #1DB954; color: white; border-radius: 50px; border: none; font-weight: bold; width: 100%; }
    div.stButton > button:hover { background-color: #1ed760; color: white; transform: scale(1.05); }
    .stTextInput > div > div > input { background-color: #282828; color: white; border-radius: 20px; border: 1px solid #333; }
    h1, h2, h3 { color: white !important; }
    a { color: #1DB954 !important; text-decoration: none; }
    .stProgress > div > div > div > div { background-color: #1DB954; }
</style>
""", unsafe_allow_html=True)

# --- 2. SELENIUM SETUP ---
def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    return webdriver.Chrome(options=options)

headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"}

# --- 3. HELPER FUNCTIES ---

def clean_title_from_url(url):
    # Haalt "Band - Album" uit de URL
    # Voorbeeld: .../posts/91890-inverecund-doctrine-of-damnation-2026-ep
    slug = url.split('/')[-1]
    # Verwijder ID aan begin (91890-)
    slug = re.sub(r'^\d+-', '', slug)
    # Vervang streepjes door spaties
    title = slug.replace('-', ' ')
    
    # Schoonmaak
    trash = ['mp3', 'flac', '320kbps', 'rar', 'zip', 'download', 'full album', 'web', '24bit', 'hi-res']
    for t in trash: title = re.sub(fr'\b{t}\b', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\b20\d{2}\b', '', title) # Jaartal weg
    return re.sub(' +', ' ', title).strip()

# --- 4. ZOEKMACHINES ---

def search_itunes(term):
    try:
        r = requests.get("https://itunes.apple.com/search", params={"term": term, "media": "music", "entity": "album", "limit": 1}, timeout=5)
        d = r.json()
        if d['resultCount'] > 0:
            item = d['results'][0]
            img = item['artworkUrl100'].replace('100x100bb', '10000x10000bb')
            return img, "iTunes (4K)", item['artistName']
    except: pass
    return None, None, None

def search_bandcamp(term):
    try:
        search_url = f"https://bandcamp.com/search?q={quote(term)}&item_type=a"
        r = requests.get(search_url, headers=headers, timeout=5)
        soup = BeautifulSoup(r.text, 'html.parser')
        result = soup.find('li', class_='searchresult')
        if result:
            img_div = result.find('div', class_='art')
            if img_div and img_div.find('img'):
                src = img_div.find('img')['src'].replace('_7.jpg', '_0.jpg')
                subhead = result.find('div', class_='subhead')
                artist = subhead.text.strip().replace('by ', '') if subhead else None
                return src, "Bandcamp (Org)", artist
    except: pass
    return None, None, None

def get_best_artwork_and_artist(term):
    img, src, artist = search_itunes(term)
    if img: return img, src, artist
    img, src, artist = search_bandcamp(term)
    if img: return img, src, artist
    return None, None, None

# --- 5. RECOMMENDATIONS ---
def get_similar_artists(artist_name, api_key):
    if not api_key or not artist_name: return []
    try:
        clean = artist_name.split(' feat')[0].split(' (')[0].strip()
        url = "http://ws.audioscrobbler.com/2.0/"
        params = {"method": "artist.getsimilar", "artist": clean, "api_key": api_key, "format": "json", "limit": 4}
        r = requests.get(url, params=params, timeout=3)
        data = r.json()
        recs = []
        if 'similarartists' in data and 'artist' in data['similarartists']:
            for art in data['similarartists']['artist']:
                img, _, _ = get_best_artwork_and_artist(art['name']) 
                recs.append({"name": art['name'], "image": img if img else "https://via.placeholder.com/300x300.png?text=No+Image"})
        return recs
    except: return []

# --- 6. UI LOGICA ---

if 'found_items' not in st.session_state:
    st.session_state['found_items'] = []

with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/1/19/Spotify_logo_without_text.svg/2048px-Spotify_logo_without_text.svg.png", width=50)
    st.title("Cover Hunter")
    
    source_site = st.radio("Bron:", ["CoreRadio", "DeathGrind.club"])
    api_key_input = st.text_input("Last.fm API Key", type="password")
    
    with st.form("search_form"):
        submitted = st.form_submit_button("Start Search")
        if source_site == "DeathGrind.club":
            st.caption("Gebruikt nu de SITEMAP XML (Anti-Block Mode)")

if not submitted and not st.session_state['found_items']:
    st.markdown("### 👋 Welkom bij Cover Hunter")
    st.write(f"Je zoekt nu op: **{source_site}**.")

if submitted or st.session_state['found_items']:
    tab1, tab2 = st.tabs(["🎵 Gevonden Albums", "🔥 Recommendations"])

    if submitted:
        st.session_state['found_items'] = [] 
        status_text = st.empty()
        bar = st.progress(0)
        
        processed_names = set()
        temp_results = []
        
        with tab1:
            live_grid = st.container()
            
        cols_per_row = 4
        current_col_idx = 0
        current_row_cols = None
        total_found = 0

        # --- SCRAPER LOGICA ---
        status_text.write("🔄 Verbinden met bron...")
        
        try:
            items_to_process = []

            # === CORERADIO (Selenium) ===
            if source_site == "CoreRadio":
                driver = get_driver()
                try:
                    driver.get("https://coreradio.online")
                    time.sleep(3)
                    soup = BeautifulSoup(driver.page_source, 'html.parser')
                    for a in soup.find_all('a'):
                        h = a.get('href')
                        if h and "coreradio.online" in h and re.search(r'/\d+-', h):
                            items_to_process.append({"name": clean_title_from_url(h), "fallback": None})
                finally:
                    driver.quit()

            # === DEATHGRIND (SITEMAP XML HACK) ===
            elif source_site == "DeathGrind.club":
                # We pakken de post-sitemap.xml direct!
                # Dit omzeilt de hele HTML pagina structuur
                sitemap_url = "https://deathgrind.club/post-sitemap.xml"
                
                # Probeer met requests
                r = requests.get(sitemap_url, headers=headers, timeout=10)
                
                # Als requests faalt, probeer Selenium voor de XML
                if r.status_code != 200:
                    driver = get_driver()
                    driver.get(sitemap_url)
                    time.sleep(2)
                    content = driver.page_source
                    driver.quit()
                else:
                    content = r.content

                # Parse XML
                soup = BeautifulSoup(content, 'xml') # XML parser gebruiken
                urls = soup.find_all('url')
                
                # Pak de laatste 20 posts
                for url in urls[:25]:
                    loc = url.find('loc')
                    if loc:
                        link = loc.text
                        # Check of er een image in de sitemap staat
                        img_node = url.find('image:loc')
                        fallback_src = img_node.text if img_node else None
                        
                        items_to_process.append({
                            "name": clean_title_from_url(link),
                            "fallback": fallback_src
                        })

            # --- VERWERKING ---
            total_items = len(items_to_process)
            if total_items == 0:
                st.error("Kon geen data ophalen. De bron blokkeert waarschijnlijk ook de Sitemap.")
            
            for i, item in enumerate(items_to_process):
                search_term = item['name']
                if len(search_term) < 3 or search_term in processed_names: continue
                processed_names.add(search_term)
                
                status_text.write(f"🔎 Zoeken: {search_term}")
                
                # 1. Zoek cover via API
                img_url, src, clean_artist = get_best_artwork_and_artist(search_term)
                
                # 2. Fallback: Gebruik sitemap image (vaak hoge kwaliteit op DG!)
                if not img_url and item.get('fallback'):
                    img_url = item['fallback']
                    src = f"{source_site} (Org)"
                    # Gok artiest uit de naam
                    clean_artist = search_term.split(' - ')[0] if ' - ' in search_term else search_term

                if img_url:
                    try:
                        img_data = requests.get(img_url, timeout=3).content
                        item_data = {
                            "name": search_term, 
                            "clean_artist": clean_artist if clean_artist else search_term, 
                            "image_url": img_url, 
                            "image_data": img_data, 
                            "source": src
                        }
                        temp_results.append(item_data)
                        
                        with live_grid:
                            if current_col_idx % cols_per_row == 0:
                                current_row_cols = st.columns(cols_per_row)
                            with current_row_cols[current_col_idx % cols_per_row]:
                                st.image(img_url, use_container_width=True)
                                st.caption(f"**{search_term}**\n*{src}*")
                            current_col_idx += 1
                    except: pass
                
                bar.progress((i + 1) / total_items)

        except Exception as e:
            st.error(f"Fout: {e}")

        st.session_state['found_items'] = temp_results
        status_text.empty()
        bar.empty()
        
        if len(temp_results) > 0:
             st.rerun()

    else:
        # --- STATISCHE WEERGAVE ---
        valid_items = st.session_state['found_items']
        
        if valid_items:
            zip_buf = BytesIO()
            with zipfile.ZipFile(zip_buf, "w") as zf:
                for item in valid_items:
                    safe_name = re.sub(r'[\\/*?:"<>|]', "", item['name'])
                    zf.writestr(f"{safe_name}.jpg", item['image_data'])
            st.download_button("📥 DOWNLOAD ALLES (ZIP)", data=zip_buf.getvalue(), file_name="covers.zip", mime="application/zip", type="primary")

        with tab1:
            st.subheader(f"Gevonden: {len(valid_items)} albums")
            cols_per_row = 4
            rows = math.ceil(len(valid_items) / cols_per_row)
            for i in range(rows):
                cols = st.columns(cols_per_row)
                for j in range(cols_per_row):
                    idx = i * cols_per_row + j
                    if idx < len(valid_items):
                        item = valid_items[idx]
                        with cols[j]:
                            st.image(item['image_url'], use_container_width=True)
                            st.caption(f"**{item['name']}**\n\n*{item['source']}*")
        
        with tab2:
            if not api_key_input:
                st.warning("⚠️ Vul je Last.fm API Key in om suggesties te zien.")
            else:
                st.subheader("🔥 Recommendations")
                seeds = []
                seen = set()
                for x in valid_items:
                    art = x.get('clean_artist')
                    if art and art not in seen:
                        seeds.append(x)
                        seen.add(art)
                        if len(seeds) >= 5: break
                
                for seed in seeds:
                    artist_name = seed['clean_artist']
                    recs = get_similar_artists(artist_name, api_key_input)
                    if recs:
                        st.markdown(f"### Omdat je houdt van: *{artist_name}*")
                        rec_cols = st.columns(4)
                        for k, rec in enumerate(recs):
                            with rec_cols[k]:
                                st.image(rec['image'], use_container_width=True)
                                st.write(f"**{rec['name']}**")
                        st.markdown("---")

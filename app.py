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
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- 1. CONFIGURATIE & CSS ---
st.set_page_config(page_title="Cover Hunter Pro", page_icon="🟢", layout="wide")

spotify_css = """
<style>
    .stApp { background-color: #121212; color: white; }
    div.stButton > button {
        background-color: #1DB954; color: white; border-radius: 50px; border: none;
        padding: 10px 24px; font-weight: bold; width: 100%;
    }
    div.stButton > button:hover { background-color: #1ed760; color: white; transform: scale(1.05); }
    .stTextInput > div > div > input { background-color: #282828; color: white; border-radius: 20px; border: 1px solid #333; }
    h1, h2, h3 { color: white !important; font-family: 'Circular', sans-serif; }
    a { color: #1DB954 !important; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .stRadio > div { color: white; }
    .stProgress > div > div > div > div { background-color: #1DB954; }
    .stAlert { background-color: #333; color: white; border: 1px solid #555; }
</style>
"""
st.markdown(spotify_css, unsafe_allow_html=True)

# --- 2. SELENIUM STEALTH SETUP ---
def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    
    # CRUCIAAL: Dit verbergt dat we een robot zijn voor Cloudflare
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    
    return webdriver.Chrome(options=options)

headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"}

# --- 3. HELPER FUNCTIES ---

def clean_title_general(title):
    # Verwijder specifieke woorden
    trash = ['mp3', 'flac', '320kbps', 'rar', 'zip', 'download', 'full album', 'web', '24bit', 'hi-res']
    for t in trash: title = re.sub(fr'\b{t}\b', '', title, flags=re.IGNORECASE)
    
    # Verwijder jaartallen
    title = re.sub(r'\b20\d{2}\b', '', title)
    return re.sub(' +', ' ', title).strip()

def clean_coreradio_link(url_part):
    slug = url_part.split('/')[-1].replace('.html', '')
    slug = re.sub(r'^\d+-', '', slug)
    return slug.replace('-', ' ')

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

def search_amazon(term):
    # Amazon slaan we even over om de scraper sneller te maken
    return None, None, None 

def search_deezer(term):
    try:
        r = requests.get("https://api.deezer.com/search", params={"q": term, "limit": 1}, timeout=5)
        d = r.json()
        if 'data' in d and len(d['data']) > 0:
            item = d['data'][0]
            artist = item['artist']['name']
            if 'cover_xl' in item: return item['cover_xl'].replace('1000x1000','1400x1400'), "Deezer (HQ)", artist
    except: pass
    return None, None, None

def search_musicbrainz(term):
    try:
        mb_headers = {"User-Agent": "CoverHunterApp/1.0 ( contact@example.com )"}
        mb_search = f"https://musicbrainz.org/ws/2/release/?query=release:{quote(term)}&fmt=json"
        r = requests.get(mb_search, headers=mb_headers, timeout=5)
        d = r.json()
        if 'releases' in d and len(d['releases']) > 0:
            release = d['releases'][0]
            artist = release['artist-credit'][0]['name'] if 'artist-credit' in release else None
            cover_url = f"https://coverartarchive.org/release/{release['id']}/front"
            if requests.head(cover_url).status_code in [200, 302, 307]:
                 return cover_url, "MusicBrainz", artist
    except: pass
    return None, None, None

def get_best_artwork_and_artist(term):
    img, src, artist = search_itunes(term)
    if img: return img, src, artist
    img, src, artist = search_bandcamp(term)
    if img: return img, src, artist
    img, src, artist = search_deezer(term)
    if img: return img, src, artist
    img, src, artist = search_musicbrainz(term)
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

# Sidebar
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/1/19/Spotify_logo_without_text.svg/2048px-Spotify_logo_without_text.svg.png", width=50)
    st.title("Cover Hunter")
    
    st.subheader("Selecteer Bron:")
    source_site = st.radio("Waar wil je zoeken?", ["CoreRadio", "DeathGrind.club"])
    api_key_input = st.text_input("Last.fm API Key", type="password")
    
    with st.form("search_form"):
        ph = "coreradio.online" if source_site == "CoreRadio" else "deathgrind.club"
        url_input = st.text_input(f"Zoek URL (Optioneel)", placeholder=ph)
        pages = st.slider("Aantal pagina's", 1, 5, 1)
        submitted = st.form_submit_button("Start Search")

# --- APP START ---

if not submitted and not st.session_state['found_items']:
    st.markdown("### 👋 Welkom bij Cover Hunter")
    st.write(f"Je zoekt nu op: **{source_site}**.")

if submitted or st.session_state['found_items']:
    tab1, tab2 = st.tabs(["🎵 Gevonden Albums", "🔥 Recommendations"])

    if submitted:
        st.session_state['found_items'] = [] 
        status_text = st.empty()
        bar = st.progress(0)
        
        # URL Logic
        urls = []
        if source_site == "CoreRadio":
            base_url = "https://coreradio.online"
            target = url_input.strip() if url_input else base_url
            if "page" not in target and len(target) > 35: urls = [target]
            else:
                for i in range(1, pages + 1):
                    urls.append(base_url if i == 1 else f"{base_url}/page/{i}/")
        
        elif source_site == "DeathGrind.club":
            # DeathGrind URL logic - we proberen base en page urls
            base_url = "https://deathgrind.club"
            target = url_input.strip() if url_input else base_url
            
            # Als directe link, gebruik die
            if "posts" in target or len(target) > 30: 
                urls = [target]
            else:
                # Als hoofdpagina, gebruik paginering
                # LET OP: DeathGrind heeft geen /page/1, dat is gewoon /
                urls = [base_url] # Page 1
                for i in range(2, pages + 1): # Page 2 en verder
                    # Veel SPA's gebruiken query params, laten we de URL clean houden voor de scraper
                    urls.append(base_url) 

        processed_names = set()
        temp_results = []
        
        with tab1:
            live_grid = st.container()
            
        cols_per_row = 4
        current_col_idx = 0
        current_row_cols = None
        total_found = 0

        # --- START SELENIUM ---
        status_text.write("🔄 Browser starten met Stealth Mode...")
        try:
            driver = get_driver()
            
            for i, u in enumerate(urls):
                status_text.write(f"🕵️ Bezoeken van {source_site}...")
                
                try:
                    driver.get(u)
                    # WACHTEN: Geef de site tijd om te laden (SPA)
                    time.sleep(5)
                    
                    # Scrollen helpt soms om lazy-load images te activeren
                    driver.execute_script("window.scrollTo(0, 1000);")
                    time.sleep(2)

                    # Parse de gerenderde HTML
                    soup = BeautifulSoup(driver.page_source, 'html.parser')
                    items_to_process = []

                    if source_site == "CoreRadio":
                        links = soup.find_all('a')
                        for a in links:
                            h = a.get('href')
                            if h and "coreradio.online" in h and re.search(r'/\d+-', h):
                                name = h.split('/')[-1].replace('.html', '').replace('-', ' ')
                                name = re.sub(r'^\d+ ', '', name)
                                items_to_process.append({"name": name, "artist": None, "fallback_img": None})
                    
                    elif source_site == "DeathGrind.club":
                        # === NIEUWE LOGICA OP BASIS VAN JOUW HTML ===
                        # We zoeken naar de <article> tag, dat is de container
                        articles = soup.find_all('article')
                        
                        if not articles:
                            # Fallback: Zoek naar figures als articles niet gevonden worden
                            articles = soup.find_all('figure')

                        for art in articles:
                            try:
                                # 1. TITEL: Zoek een link die naar /posts/ gaat
                                # We gebruiken partial matching want classes kunnen veranderen
                                title_link = art.find('a', href=re.compile(r'/posts/\d+'))
                                if not title_link: continue # Geen titel = skip
                                
                                title_text = title_link.text.strip()
                                
                                # 2. ARTIEST: Zoek een link die naar /bands/ gaat
                                artist_link = art.find('a', href=re.compile(r'/bands/\d+'))
                                artist_text = artist_link.text.strip() if artist_link else ""
                                
                                # 3. COVER: Zoek het plaatje (src bevat cdn.deathgrind)
                                img_tag = art.find('img')
                                fallback_src = None
                                if img_tag and 'src' in img_tag.attrs:
                                    fallback_src = img_tag['src']
                                
                                # Als we een titel hebben, voegen we hem toe
                                if title_text:
                                    # Maak een mooie zoekterm: "Band - Album"
                                    full_query = f"{artist_text} {title_text}" if artist_text else title_text
                                    
                                    items_to_process.append({
                                        "name": clean_title_general(full_query),
                                        "artist": artist_text,
                                        "fallback_img": fallback_src
                                    })
                            except Exception as e:
                                print(f"Parse error: {e}")
                                continue

                    # --- VERWERKING ---
                    for item in items_to_process:
                        search_term = item['name']
                        if search_term in processed_names: continue
                        processed_names.add(search_term)
                        total_found += 1
                        
                        # Zoek betere kwaliteit cover
                        img_url, src, clean_artist = get_best_artwork_and_artist(search_term)
                        
                        # Als iTunes/Bandcamp niks vinden, pakken we de DeathGrind CDN cover
                        if not img_url and item.get('fallback_img'):
                            img_url = item['fallback_img']
                            src = "DeathGrind (Original)"
                            clean_artist = item['artist']
                        
                        if img_url:
                            try:
                                # Downloaden
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
                            
                except Exception as e:
                    st.error(f"Browser fout: {e}")

                bar.progress((i + 1) / len(urls))
            
            driver.quit()
            
        except Exception as e:
            st.error(f"Kon browser niet starten: {e}")

        st.session_state['found_items'] = temp_results
        status_text.empty()
        bar.empty()
        
        if total_found == 0:
             st.warning("Geen albums gevonden. Als de pagina rood blijft (Timeout), blokkeert Cloudflare ons IP.")
        else:
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

import streamlit as st
import requests
from bs4 import BeautifulSoup
from io import BytesIO
import re
from urllib.parse import quote
import zipfile
import math

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
</style>
"""
st.markdown(spotify_css, unsafe_allow_html=True)

# --- 2. API KEYS & INSTELLINGEN ---
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
}

# --- 3. HELPER FUNCTIES ---

def clean_coreradio_name(url_part):
    name = url_part.split('/')[-1].replace('.html', '')
    name = re.sub(r'^\d+-', '', name).replace('-', ' ')
    trash = ['deluxe edition', 'remastered', '2024', '2025', '2026', 'web', 'flac', '320', 'kbps', 'ep', 'single', 'full album']
    for t in trash: name = re.sub(fr'\b{t}\b', '', name, flags=re.IGNORECASE)
    return re.sub(' +', ' ', name).strip()

def clean_deathgrind_title(title):
    # Verwijder alles tussen [] en ()
    clean = re.sub(r'\[.*?\]', '', title)
    clean = re.sub(r'\(.*?\)', '', clean)
    # Verwijder specifieke woorden
    trash = ['mp3', 'flac', '320kbps', 'rar', 'zip', 'download']
    for t in trash: clean = re.sub(fr'\b{t}\b', '', clean, flags=re.IGNORECASE)
    # Vervang streepjes
    clean = clean.replace('–', '-').replace('—', '-')
    return re.sub(' +', ' ', clean).strip()

# --- ZOEKMACHINES ---

def search_itunes(term):
    try:
        r = requests.get("https://itunes.apple.com/search", params={"term": term, "media": "music", "entity": "album", "limit": 1}, timeout=5)
        d = r.json()
        if d['resultCount'] > 0:
            item = d['results'][0]
            img = item['artworkUrl100'].replace('100x100bb', '10000x10000bb')
            artist = item['artistName']
            return img, "iTunes (4K)", artist
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
                artist_div = result.find('div', class_='subhead')
                artist = artist_div.text.strip().replace('by ', '') if artist_div else None
                return src, "Bandcamp (Original)", artist
    except: pass
    return None, None, None

def search_amazon(term):
    try:
        url = f"https://www.amazon.com/s?k={quote(term)}&i=digital-music-album"
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            img = soup.find('img', class_='s-image')
            if img and 'src' in img.attrs:
                src = re.sub(r'\._AC_.*?\.', '.', img['src'])
                return src, "Amazon Music (HQ)", None
    except: pass
    return None, None, None

def search_deezer(term):
    try:
        r = requests.get("https://api.deezer.com/search", params={"q": term, "limit": 1}, timeout=5)
        d = r.json()
        if 'data' in d and len(d['data']) > 0:
            item = d['data'][0]
            artist = item['artist']['name']
            if 'cover_xl' in item: return item['cover_xl'].replace('1000x1000','1400x1400'), "Deezer (HQ)", artist
            if 'album' in item: return item['album']['cover_xl'].replace('1000x1000','1400x1400'), "Deezer (HQ)", artist
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
                 return cover_url, "MusicBrainz (Archive)", artist
    except: pass
    return None, None, None

def get_best_artwork_and_artist(term):
    img, src, artist = search_itunes(term)
    if img: return img, src, artist
    
    img, src = search_bandcamp(term)
    if img: return img, src, artist
    
    img, src = search_amazon(term)
    if img: return img, src, None 
    
    img, src = search_deezer(term)
    if img: return img, src, artist
    
    img, src = search_musicbrainz(term)
    if img: return img, src, artist

    return None, None, None

# --- RECOMMENDATIONS ---
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

# --- UI LOGICA ---

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
        url_input = st.text_input(f"{source_site} URL", placeholder=ph)
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
        if source_site == "CoreRadio":
            base_url = "https://coreradio.online"
            target = url_input.strip() if url_input else base_url
            if not target.startswith("http"): target = "https://" + target
            urls = [target] if "page" not in target and len(target) > 30 else [f"{base_url}/page/{i}/" for i in range(1, pages+1)]
        else:
            base_url = "https://deathgrind.club"
            target = url_input.strip() if url_input else base_url
            if not target.startswith("http"): target = "https://" + target
            urls = [target] if "page" not in target and len(target) > 30 else [f"{base_url}/page/{i}/" for i in range(1, pages+1)]
        
        processed_names = set()
        temp_results = []
        
        with tab1:
            live_grid = st.container()
            
        cols_per_row = 4
        current_col_idx = 0
        current_row_cols = None

        total_items_found = 0

        for i, u in enumerate(urls):
            status_text.write(f"🕵️ Scannen van {source_site} (Pagina {i+1})...")
            try:
                r = requests.get(u, headers=headers, timeout=10)
                
                if r.status_code != 200:
                    st.error(f"Fout bij laden pagina: {r.status_code}")
                    continue

                soup = BeautifulSoup(r.text, 'html.parser')
                items_to_process = []

                # === SCRAPING LOGICA ===
                if source_site == "CoreRadio":
                    for a in soup.find_all('a'):
                        h = a.get('href')
                        if h and "coreradio.online" in h and re.search(r'/\d+-', h):
                            name = clean_coreradio_name(h)
                            items_to_process.append({"name": name})
                
                elif source_site == "DeathGrind.club":
                    # UPDATE: Zoek breder naar H2 en H3 tags, want entry-title werkt soms niet
                    headings = soup.find_all(['h2', 'h3'])
                    for h in headings:
                        # Vaak zit de titel in een <a> tag in de heading
                        link = h.find('a')
                        if link:
                            raw_title = link.text.strip()
                        else:
                            raw_title = h.text.strip()
                        
                        if raw_title and len(raw_title) > 5: # Filter lege titels
                            clean_t = clean_deathgrind_title(raw_title)
                            items_to_process.append({"name": clean_t})

                # === VERWERKING ===
                if not items_to_process:
                    st.warning(f"Geen titels gevonden op pagina {i+1}. De sitestructuur is misschien anders of geblokkeerd.")
                
                for item in items_to_process:
                    search_term = item['name']
                    if search_term in processed_names: continue
                    processed_names.add(search_term)
                    total_items_found += 1
                    
                    img_url, src, clean_artist = get_best_artwork_and_artist(search_term)
                    
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
            except Exception as e:
                st.error(f"Verbindingsfout: {e}")

            bar.progress((i + 1) / len(urls))
        
        st.session_state['found_items'] = temp_results
        status_text.empty()
        bar.empty()
        
        if total_items_found == 0:
            st.error("⚠️ De scraper kon helemaal geen albums vinden. Mogelijk blokkeert de site onze toegang (Cloudflare/Bot protectie).")
        else:
            st.rerun()

    else:
        valid_items = st.session_state['found_items']
        
        if valid_items:
            zip_buf = BytesIO()
            with zipfile.ZipFile(zip_buf, "w") as zf:
                for item in valid_items:
                    zf.writestr(f"{item['name']}.jpg", item['image_data'])
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
                    if x['clean_artist'] not in seen:
                        seeds.append(x)
                        seen.add(x['clean_artist'])
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

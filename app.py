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

# Spotify-achtige styling
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
</style>
"""
st.markdown(spotify_css, unsafe_allow_html=True)

# --- 2. API KEYS & INSTELLINGEN ---
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"}

# --- 3. HELPER FUNCTIES (NU MET ARTIEST DETECTIE) ---

def clean_name(url_part):
    name = url_part.split('/')[-1].replace('.html', '')
    name = re.sub(r'^\d+-', '', name).replace('-', ' ')
    trash = ['deluxe edition', 'remastered', '2024', '2025', '2026', 'web', 'flac', '320', 'kbps', 'ep', 'single']
    for t in trash: name = re.sub(fr'\b{t}\b', '', name, flags=re.IGNORECASE)
    return re.sub(' +', ' ', name).strip()

def search_itunes(term):
    try:
        r = requests.get("https://itunes.apple.com/search", params={"term": term, "media": "music", "entity": "album", "limit": 1}, timeout=5)
        d = r.json()
        if d['resultCount'] > 0:
            item = d['results'][0]
            img = item['artworkUrl100'].replace('100x100bb', '10000x10000bb')
            artist = item['artistName'] # We pakken de echte artiestennaam!
            return img, "iTunes (4K)", artist
    except: pass
    return None, None, None

def search_deezer(term):
    try:
        r = requests.get("https://api.deezer.com/search", params={"q": term, "limit": 1}, timeout=5)
        d = r.json()
        if 'data' in d and len(d['data']) > 0:
            item = d['data'][0]
            artist = item['artist']['name'] # Echte artiestennaam
            if 'cover_xl' in item: return item['cover_xl'].replace('1000x1000','1400x1400'), "Deezer (HQ)", artist
            if 'album' in item: return item['album']['cover_xl'].replace('1000x1000','1400x1400'), "Deezer (HQ)", artist
    except: pass
    return None, None, None

def search_bandcamp(term):
    # Bandcamp geeft lastig de losse artiest terug in search, dus we gokken hier niet
    try:
        search_url = f"https://bandcamp.com/search?q={quote(term)}&item_type=a"
        r = requests.get(search_url, headers=headers, timeout=5)
        soup = BeautifulSoup(r.text, 'html.parser')
        result = soup.find('li', class_='searchresult')
        if result:
            img_div = result.find('div', class_='art')
            if img_div and img_div.find('img'):
                src = img_div.find('img')['src'].replace('_7.jpg', '_0.jpg')
                # Probeer artiest te vinden in tekst
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
                return src, "Amazon Music (HQ)", None # Amazon geeft geen makkelijke artiest info
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
            release_id = release['id']
            # Artiest pakken
            artist = release['artist-credit'][0]['name'] if 'artist-credit' in release else None
            
            cover_url = f"https://coverartarchive.org/release/{release_id}/front"
            head_req = requests.head(cover_url)
            if head_req.status_code in [200, 302, 307]:
                 return cover_url, "MusicBrainz (Archive)", artist
    except: pass
    return None, None, None

def get_best_artwork_and_artist(term):
    # Probeer iTunes (Beste metadata)
    img, src, artist = search_itunes(term)
    if img: return img, src, artist
    
    # Probeer Deezer
    img, src, artist = search_deezer(term)
    if img: return img, src, artist
    
    # Probeer MusicBrainz
    img, src, artist = search_musicbrainz(term)
    if img: return img, src, artist

    # Probeer Bandcamp (Vaak goede plaatjes, soms artiest)
    img, src, artist = search_bandcamp(term)
    if img: return img, src, artist # Artist kan None zijn
    
    # Probeer Amazon (Goede plaatjes, geen artiest info)
    img, src, artist = search_amazon(term)
    if img: return img, src, None 
    
    return None, None, None

# --- 4. RECOMMENDATION ENGINE ---

def get_similar_artists(artist_name, api_key):
    if not api_key or not artist_name: return []
    try:
        url = "http://ws.audioscrobbler.com/2.0/"
        params = {"method": "artist.getsimilar", "artist": artist_name, "api_key": api_key, "format": "json", "limit": 4}
        r = requests.get(url, params=params, timeout=3)
        data = r.json()
        recs = []
        if 'similarartists' in data and 'artist' in data['similarartists']:
            for art in data['similarartists']['artist']:
                # We zoeken snel een plaatje voor de recommendation (alleen plaatje, artiest boeit niet)
                img, _, _ = get_best_artwork_and_artist(art['name']) 
                recs.append({"name": art['name'], "image": img if img else "https://via.placeholder.com/300x300.png?text=No+Image"})
        return recs
    except: return []

# --- 5. UI LOGICA ---

if 'found_items' not in st.session_state:
    st.session_state['found_items'] = []

# Sidebar
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/1/19/Spotify_logo_without_text.svg/2048px-Spotify_logo_without_text.svg.png", width=50)
    st.title("Cover Hunter")
    api_key_input = st.text_input("Last.fm API Key", type="password") # Hier plakken!
    
    with st.form("search_form"):
        url_input = st.text_input("CoreRadio URL", placeholder="coreradio.online")
        pages = st.slider("Pagina's", 1, 5, 1)
        submitted = st.form_submit_button("Start Search")

# --- APP START ---

if not submitted and not st.session_state['found_items']:
    st.markdown("### 👋 Welkom bij Cover Hunter")
    st.write("Vul links je Last.fm Key in en start het zoeken!")

if submitted or st.session_state['found_items']:
    tab1, tab2 = st.tabs(["🎵 Gevonden Albums", "🔥 Recommendations"])

    if submitted:
        st.session_state['found_items'] = [] 
        status_text = st.empty()
        bar = st.progress(0)
        
        target = url_input.strip() if url_input else "https://coreradio.online"
        if not target.startswith("http"): target = "https://" + target
        urls = [target] if "page" not in target and len(target) > 30 else [f"https://coreradio.online/page/{i}/" for i in range(1, pages+1)]
        
        processed_links = set()
        temp_results = []
        
        with tab1:
            live_grid = st.container()
            
        cols_per_row = 4
        current_col_idx = 0
        current_row_cols = None

        for i, u in enumerate(urls):
            status_text.write(f"🕵️ Scannen van pagina {i+1}...")
            try:
                r = requests.get(u, headers=headers)
                soup = BeautifulSoup(r.text, 'html.parser')
                page_links = [a.get('href') for a in soup.find_all('a') if a.get('href') and "coreradio.online" in a.get('href') and re.search(r'/\d+-', a.get('href'))]
                
                for link in page_links:
                    if link in processed_links: continue
                    processed_links.add(link)
                    
                    name = clean_name(link) # Dit is "Artiest Album" (rommelig)
                    
                    # Hier gebeurt de magie: we krijgen nu ook de SCHONE artiest terug!
                    img_url, src, clean_artist = get_best_artwork_and_artist(name)
                    
                    if img_url:
                        try:
                            img_data = requests.get(img_url, timeout=3).content
                            # Sla de schone artiest op voor straks!
                            item_data = {
                                "name": name, 
                                "clean_artist": clean_artist if clean_artist else name, # Fallback naar zoekterm als niks gevonden
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
                                    st.caption(f"**{name}**\n*{src}*")
                                current_col_idx += 1
                        except: pass
            except: pass
            bar.progress((i + 1) / len(urls))
        
        st.session_state['found_items'] = temp_results
        status_text.empty()
        bar.empty()
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
                st.warning("⚠️ Vul je Last.fm API Key in de zijbalk in om suggesties te zien.")
            else:
                st.subheader("🔥 Recommendations (op basis van gevonden artiesten)")
                
                # We pakken alleen items waar we een 'clean_artist' van hebben
                seeds = [x for x in valid_items if x.get('clean_artist')][:5]
                
                if not seeds:
                    st.info("Geen duidelijke artiesten gevonden om recommendations op te baseren.")
                
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

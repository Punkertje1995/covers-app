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
    /* Algemene achtergrond */
    .stApp {
        background-color: #121212;
        color: white;
    }
    /* Knoppen (Spotify Groen) */
    div.stButton > button {
        background-color: #1DB954;
        color: white;
        border-radius: 50px;
        border: none;
        padding: 10px 24px;
        font-weight: bold;
        transition: transform 0.2s;
        width: 100%;
    }
    div.stButton > button:hover {
        background-color: #1ed760;
        color: white;
        transform: scale(1.05);
        border: none;
    }
    /* Input velden */
    .stTextInput > div > div > input {
        background-color: #282828;
        color: white;
        border-radius: 20px;
        border: 1px solid #333;
    }
    /* Headers */
    h1, h2, h3 {
        color: white !important;
        font-family: 'Circular', sans-serif;
    }
    /* Expander styling */
    .streamlit-expanderHeader {
        background-color: #181818;
        color: white;
    }
</style>
"""
st.markdown(spotify_css, unsafe_allow_html=True)

# --- 2. API KEYS & INSTELLINGEN ---
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"}

# --- 3. HELPER FUNCTIES (CLEANING & SEARCH) ---

def clean_name(url_part):
    name = url_part.split('/')[-1].replace('.html', '')
    name = re.sub(r'^\d+-', '', name).replace('-', ' ')
    trash = ['deluxe edition', 'remastered', '2024', '2025', '2026', 'web', 'flac', '320', 'kbps', 'ep', 'single', 'full album']
    for t in trash: name = re.sub(fr'\b{t}\b', '', name, flags=re.IGNORECASE)
    return re.sub(' +', ' ', name).strip()

def search_itunes(term):
    try:
        r = requests.get("https://itunes.apple.com/search", params={"term": term, "media": "music", "entity": "album", "limit": 1}, timeout=5)
        d = r.json()
        if d['resultCount'] > 0:
            return d['results'][0]['artworkUrl100'].replace('100x100bb', '10000x10000bb'), "iTunes (4K)"
    except: pass
    return None, None

def search_bandcamp(term):
    try:
        search_url = f"https://bandcamp.com/search?q={quote(term)}&item_type=a"
        r = requests.get(search_url, headers=headers, timeout=5)
        soup = BeautifulSoup(r.text, 'html.parser')
        result = soup.find('li', class_='searchresult')
        if result:
            img_div = result.find('div', class_='art')
            if img_div and img_div.find('img'):
                return img_div.find('img')['src'].replace('_7.jpg', '_0.jpg'), "Bandcamp (Original)"
    except: pass
    return None, None

def search_deezer(term):
    try:
        r = requests.get("https://api.deezer.com/search", params={"q": term, "limit": 1}, timeout=5)
        d = r.json()
        if 'data' in d and len(d['data']) > 0:
            item = d['data'][0]
            if 'cover_xl' in item: return item['cover_xl'].replace('1000x1000','1400x1400'), "Deezer (HQ)"
            if 'album' in item: return item['album']['cover_xl'].replace('1000x1000','1400x1400'), "Deezer (HQ)"
    except: pass
    return None, None

def search_amazon(term):
    """Probeert Amazon Digital Music te scrapen voor covers"""
    try:
        # Zoek specifiek in de categorie digitale muziek albums
        url = f"https://www.amazon.com/s?k={quote(term)}&i=digital-music-album"
        r = requests.get(url, headers=headers, timeout=5)
        
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            # Amazon verandert classes vaak, maar s-image is vrij stabiel
            img = soup.find('img', class_='s-image')
            
            if img and 'src' in img.attrs:
                src = img['src']
                # Amazon images hebben vaak resize parameters zoals ._AC_UY218_
                # We halen alles tussen de laatste punt en de extensie weg voor de full-size
                # Voorbeeld: ...images/I/81abcde._AC_UY218_.jpg -> ...images/I/81abcde.jpg
                
                # Regex om de resize parameters te verwijderen
                clean_src = re.sub(r'\._AC_.*?\.', '.', src)
                
                return clean_src, "Amazon Music (High Res)"
    except: pass
    return None, None

def search_musicbrainz(term):
    try:
        mb_headers = {"User-Agent": "CoverHunterApp/1.0 ( contact@example.com )"}
        mb_search = f"https://musicbrainz.org/ws/2/release/?query=release:{quote(term)}&fmt=json"
        r = requests.get(mb_search, headers=mb_headers, timeout=5)
        d = r.json()
        if 'releases' in d and len(d['releases']) > 0:
            release_id = d['releases'][0]['id']
            cover_url = f"https://coverartarchive.org/release/{release_id}/front"
            head_req = requests.head(cover_url)
            if head_req.status_code in [200, 302, 307]:
                 return cover_url, "MusicBrainz (Archive)"
    except: pass
    return None, None

def get_best_artwork(term):
    # De nieuwe volgorde inclusief Amazon
    img, src = search_itunes(term)
    if img: return img, src
    
    img, src = search_bandcamp(term)
    if img: return img, src
    
    img, src = search_amazon(term)  # NIEUW
    if img: return img, src
    
    img, src = search_deezer(term)
    if img: return img, src
    
    img, src = search_musicbrainz(term)
    if img: return img, src
    
    return None, None

# --- 4. RECOMMENDATION ENGINE (LAST.FM) ---

def get_similar_artists(artist_name, api_key):
    if not api_key: return []
    
    try:
        clean_artist = artist_name.split(" - ")[0] if " - " in artist_name else artist_name
        url = "http://ws.audioscrobbler.com/2.0/"
        params = {
            "method": "artist.getsimilar",
            "artist": clean_artist,
            "api_key": api_key,
            "format": "json",
            "limit": 4
        }
        r = requests.get(url, params=params, timeout=3)
        data = r.json()
        
        recs = []
        if 'similarartists' in data and 'artist' in data['similarartists']:
            for art in data['similarartists']['artist']:
                img, _ = get_best_artwork(art['name']) 
                recs.append({
                    "name": art['name'],
                    "image": img if img else "https://via.placeholder.com/300x300.png?text=No+Image"
                })
        return recs
    except: return []

# --- 5. UI LOGICA ---

if 'found_items' not in st.session_state:
    st.session_state['found_items'] = []
if 'scan_done' not in st.session_state:
    st.session_state['scan_done'] = False

# Sidebar
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/1/19/Spotify_logo_without_text.svg/2048px-Spotify_logo_without_text.svg.png", width=50)
    st.title("Cover Hunter")
    
    # Input voor Last.fm API Key
    api_key_input = st.text_input("Last.fm API Key (Optioneel)", type="password", help="Plak hier je key voor recommendations.")
    
    with st.form("search_form"):
        url_input = st.text_input("CoreRadio URL", placeholder="coreradio.online")
        pages = st.slider("Pagina's", 1, 5, 1)
        submitted = st.form_submit_button("Start Search")

# Scrape Logica
if submitted:
    st.session_state['found_items'] = []
    status_text = st.empty()
    bar = st.progress(0)
    
    target = url_input.strip() if url_input else "https://coreradio.online"
    if not target.startswith("http"): target = "https://" + target
    
    urls = [target] if "page" not in target and len(target) > 30 else [f"https://coreradio.online/page/{i}/" for i in range(1, pages+1)]
    
    processed_links = set()
    temp_results = []
    
    for i, u in enumerate(urls):
        status_text.write(f"🕵️ Scannen van pagina {i+1}...")
        try:
            r = requests.get(u, headers=headers)
            soup = BeautifulSoup(r.text, 'html.parser')
            
            page_links = []
            for a in soup.find_all('a'):
                h = a.get('href')
                if h and "coreradio.online" in h and re.search(r'/\d+-', h):
                    page_links.append(h)
            
            for link in page_links:
                if link in processed_links: continue
                processed_links.add(link)
                
                name = clean_name(link)
                img_url, src = get_best_artwork(name)
                
                if img_url:
                    try:
                        img_data = requests.get(img_url, timeout=3).content
                        temp_results.append({
                            "name": name,
                            "image_url": img_url,
                            "image_data": img_data,
                            "source": src
                        })
                    except: pass
                else:
                    temp_results.append({
                        "name": name,
                        "image_url": None,
                        "image_data": None,
                        "source": "Niet gevonden"
                    })
        except: pass
        bar.progress((i + 1) / len(urls))
    
    st.session_state['found_items'] = temp_results
    st.session_state['scan_done'] = True
    status_text.empty()
    bar.empty()

# --- 6. HET HOOFDSCHERM (TABS) ---

if st.session_state['scan_done']:
    valid_items = [x for x in st.session_state['found_items'] if x['image_url']]
    
    if valid_items:
        zip_buf = BytesIO()
        with zipfile.ZipFile(zip_buf, "w") as zf:
            for item in valid_items:
                zf.writestr(f"{item['name']}.jpg", item['image_data'])
        
        st.download_button("📥 DOWNLOAD ALLES (ZIP)", data=zip_buf.getvalue(), file_name="covers.zip", mime="application/zip", type="primary")

    tab1, tab2 = st.tabs(["🎵 Gevonden Albums", "🔥 Recommendations"])

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
        st.subheader("Op basis van je zoekopdracht vind je dit misschien ook tof:")
        
        if not api_key_input:
            st.warning("⚠️ Vul je Last.fm API Key in de zijbalk in om suggesties te zien.")
        else:
            seed_artists = valid_items[:5] 
            
            for seed in seed_artists:
                recs = get_similar_artists(seed['name'], api_key_input)
                if recs:
                    st.markdown(f"### Omdat je zocht naar: *{seed['name']}*")
                    rec_cols = st.columns(4)
                    for k, rec in enumerate(recs):
                        with rec_cols[k]:
                            st.image(rec['image'], use_container_width=True)
                            st.write(f"**{rec['name']}**")
                    st.markdown("---")

else:
    st.markdown("### 👋 Welkom bij Cover Hunter")
    st.write("Gebruik het menu links om te beginnen met scannen.")

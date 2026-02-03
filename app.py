import streamlit as st
import requests
from bs4 import BeautifulSoup
from io import BytesIO
import re
from urllib.parse import quote
import zipfile
import math
import cloudscraper

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
    /* Groene voortgangsbalk */
    .stProgress > div > div > div > div { background-color: #1DB954; }
    /* Meldingen styling */
    .stAlert { background-color: #282828; color: white; border: 1px solid #444; }
</style>
"""
st.markdown(spotify_css, unsafe_allow_html=True)

# --- 2. INSTELLINGEN ---
# We gebruiken cloudscraper voor de images en requests voor de feed
scraper = cloudscraper.create_scraper(browser='chrome')
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# --- 3. HELPER FUNCTIES (TITELS SCHOONMAKEN) ---

def clean_title_general(title):
    """Universele schoonmaker voor titels"""
    # Verwijder alles tussen [] en ()
    clean = re.sub(r'\[.*?\]', '', title)
    clean = re.sub(r'\(.*?\)', '', clean)
    
    # Verwijder specifieke onzin woorden
    trash = ['mp3', 'flac', '320kbps', 'rar', 'zip', 'download', 'full album', 'web', '24bit', 'hi-res']
    for t in trash: clean = re.sub(fr'\b{t}\b', '', clean, flags=re.IGNORECASE)
    
    # Verwijder jaartallen (bijv 2023, 2024)
    clean = re.sub(r'\b20\d{2}\b', '', clean)
    
    # Vervang rare streepjes en dubbele spaties
    clean = clean.replace('–', '-').replace('—', '-').replace('_', ' ')
    return re.sub(' +', ' ', clean).strip()

def clean_coreradio_link(url_part):
    # CoreRadio specifiek: haal info uit de URL
    slug = url_part.split('/')[-1].replace('.html', '')
    slug = re.sub(r'^\d+-', '', slug) # ID weg
    return slug.replace('-', ' ')

# --- 4. ZOEKMACHINES (SOURCE) ---

def search_itunes(term):
    try:
        # iTunes is streng, soms helpt het om de requests library te gebruiken
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
        # Bandcamp zoekpagina scrapen
        search_url = f"https://bandcamp.com/search?q={quote(term)}&item_type=a"
        r = requests.get(search_url, headers=headers, timeout=5)
        soup = BeautifulSoup(r.text, 'html.parser')
        result = soup.find('li', class_='searchresult')
        if result:
            img_div = result.find('div', class_='art')
            if img_div and img_div.find('img'):
                src = img_div.find('img')['src'].replace('_7.jpg', '_0.jpg') # _0 is full size
                
                # Artiest proberen te vinden
                artist = None
                subhead = result.find('div', class_='subhead')
                if subhead:
                    artist = subhead.text.strip().replace('by ', '')
                
                return src, "Bandcamp (Org)", artist
    except: pass
    return None, None, None

def search_amazon(term):
    try:
        # Amazon via cloudscraper
        url = f"https://www.amazon.com/s?k={quote(term)}&i=digital-music-album"
        r = scraper.get(url)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            img = soup.find('img', class_='s-image')
            if img and 'src' in img.attrs:
                # Verwijder resize parameters
                src = re.sub(r'\._AC_.*?\.', '.', img['src'])
                return src, "Amazon (HQ)", None
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
            # Check of plaatje bestaat (head request)
            if requests.head(cover_url).status_code in [200, 302, 307]:
                 return cover_url, "MusicBrainz", artist
    except: pass
    return None, None, None

def get_best_artwork_and_artist(term):
    # 1. iTunes (Vaak beste kwaliteit)
    img, src, artist = search_itunes(term)
    if img: return img, src, artist
    
    # 2. Bandcamp (Geweldig voor metal/underground)
    img, src, artist = search_bandcamp(term)
    if img: return img, src, artist
    
    # 3. Amazon (Hoge res backup)
    img, src, artist = search_amazon(term)
    if img: return img, src, None 
    
    # 4. MusicBrainz (Laatste redmiddel)
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
    st.info("Tip: DeathGrind.club wordt gescand via de RSS feed om blokkades te voorkomen.")

if submitted or st.session_state['found_items']:
    tab1, tab2 = st.tabs(["🎵 Gevonden Albums", "🔥 Recommendations"])

    if submitted:
        st.session_state['found_items'] = [] 
        status_text = st.empty()
        bar = st.progress(0)
        
        # --- URL GENERATIE ---
        urls = []
        if source_site == "CoreRadio":
            base_url = "https://coreradio.online"
            target = url_input.strip() if url_input else base_url
            if "page" not in target and len(target) > 35: # Directe link
                urls = [target]
            else:
                for i in range(1, pages + 1):
                    urls.append(base_url if i == 1 else f"{base_url}/page/{i}/")
        
        elif source_site == "DeathGrind.club":
            # TRUC: Gebruik de RSS Feed! (?paged=1, ?paged=2)
            base_feed = "https://deathgrind.club/feed"
            for i in range(1, pages + 1):
                urls.append(f"{base_feed}/?paged={i}")

        processed_names = set()
        temp_results = []
        
        with tab1:
            live_grid = st.container()
            
        cols_per_row = 4
        current_col_idx = 0
        current_row_cols = None
        total_found = 0

        # --- DE HOOFD LOOP ---
        for i, u in enumerate(urls):
            status_text.write(f"🕵️ Analyseren van bron... (Pagina {i+1})")
            
            items_to_process = []
            
            try:
                # CoreRadio is HTML, DeathGrind is XML (RSS)
                if source_site == "CoreRadio":
                    r = requests.get(u, headers=headers, timeout=10)
                    if r.status_code == 200:
                        soup = BeautifulSoup(r.text, 'html.parser')
                        for a in soup.find_all('a'):
                            h = a.get('href')
                            if h and "coreradio.online" in h and re.search(r'/\d+-', h):
                                name = clean_coreradio_link(h)
                                items_to_process.append(clean_title_general(name))
                
                elif source_site == "DeathGrind.club":
                    # RSS FEED PARSEN (Veel stabieler!)
                    r = requests.get(u, headers=headers, timeout=15)
                    if r.status_code == 200:
                        # XML parsing met BeautifulSoup
                        soup = BeautifulSoup(r.content, 'xml') # 'xml' parser gebruiken
                        items = soup.find_all('item')
                        for item in items:
                            title = item.find('title').text
                            items_to_process.append(clean_title_general(title))
                    else:
                        st.warning(f"Kon RSS feed niet lezen: {r.status_code}")

            except Exception as e:
                print(f"Error scraping {u}: {e}")

            # --- ITEMS VERWERKEN ---
            for search_term in items_to_process:
                if len(search_term) < 3: continue # Skip lege onzin
                if search_term in processed_names: continue
                processed_names.add(search_term)
                total_found += 1
                
                # Zoek de cover
                img_url, src, clean_artist = get_best_artwork_and_artist(search_term)
                
                if img_url:
                    try:
                        # Download plaatje
                        img_req = requests.get(img_url, timeout=5)
                        if img_req.status_code == 200:
                            img_data = img_req.content
                            item_data = {
                                "name": search_term, 
                                "clean_artist": clean_artist if clean_artist else search_term, 
                                "image_url": img_url, 
                                "image_data": img_data, 
                                "source": src
                            }
                            temp_results.append(item_data)
                            
                            # Live renderen
                            with live_grid:
                                if current_col_idx % cols_per_row == 0:
                                    current_row_cols = st.columns(cols_per_row)
                                with current_row_cols[current_col_idx % cols_per_row]:
                                    st.image(img_url, use_container_width=True)
                                    st.caption(f"**{search_term}**\n*{src}*")
                                current_col_idx += 1
                    except: pass
            
            bar.progress((i + 1) / len(urls))
        
        st.session_state['found_items'] = temp_results
        status_text.empty()
        bar.empty()
        
        if total_found == 0:
             st.error(f"Geen albums gevonden op {source_site}. De bron is mogelijk offline of blokkeert ons volledig.")
        else:
             st.rerun()

    else:
        # --- STATISCHE WEERGAVE NA ZOEKEN ---
        valid_items = st.session_state['found_items']
        
        if valid_items:
            zip_buf = BytesIO()
            with zipfile.ZipFile(zip_buf, "w") as zf:
                for item in valid_items:
                    # Bestandsnaam veilig maken
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
                # Pak unieke artiesten
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

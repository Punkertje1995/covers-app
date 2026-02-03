import streamlit as st
import cloudscraper
from bs4 import BeautifulSoup
from io import BytesIO
import re
from urllib.parse import quote
import zipfile
import math
import requests

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
</style>
"""
st.markdown(spotify_css, unsafe_allow_html=True)

# --- 2. SCRAPER INSTELLINGEN (Cloudscraper) ---
# We maken een scraper aan die Cloudflare probeert te omzeilen
scraper = cloudscraper.create_scraper(browser='chrome')

# --- 3. HELPER FUNCTIES ---

def clean_title_from_link(url):
    """Haalt een leesbare titel uit de URL (werkt voor zowel CoreRadio als DeathGrind)"""
    # URL format is vaak: domein.com/12345-band-album-naam.html
    # Stap 1: Pak het laatste deel
    slug = url.split('/')[-1].replace('.html', '')
    # Stap 2: Verwijder de ID aan het begin (cijfers + streepje)
    slug = re.sub(r'^\d+-', '', slug)
    # Stap 3: Vervang streepjes door spaties
    title = slug.replace('-', ' ')
    
    # Stap 4: Schoonmaak (woorden die we niet willen in de zoekopdracht)
    trash = ['deluxe edition', 'remastered', '2024', '2025', '2026', 'web', 'flac', '320', 'kbps', 'ep', 'single', 'full album', 'mp3', 'rar', 'zip', 'download']
    for t in trash: title = re.sub(fr'\b{t}\b', '', title, flags=re.IGNORECASE)
    
    return re.sub(' +', ' ', title).strip()

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
        # Bandcamp search werkt prima met gewone requests
        search_url = f"https://bandcamp.com/search?q={quote(term)}&item_type=a"
        r = requests.get(search_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
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
        # Amazon heeft headers nodig, cloudscraper is hier ook handig voor
        r = scraper.get(url)
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
            urls = [target] if "page" not in target and len(target) > 35 else [f"{base_url}/page/{i}/" for i in range(1, pages+1)]
        else:
            base_url = "https://deathgrind.club"
            target = url_input.strip() if url_input else base_url
            if not target.startswith("http"): target = "https://" + target
            urls = [target] if "page" not in target and len(target) > 35 else [f"{base_url}/page/{i}/" for i in range(1, pages+1)]
        
        processed_names = set()
        temp_results = []
        
        with tab1:
            live_grid = st.container()
            
        cols_per_row = 4
        current_col_idx = 0
        current_row_cols = None
        total_found = 0

        for i, u in enumerate(urls):
            status_text.write(f"🕵️ Scannen van {source_site} (Pagina {i+1})...")
            try:
                # GEBRUIK HIER DE CLOUDSCRAPER
                r = scraper.get(u)
                
                if r.status_code != 200:
                    # Als 404, probeer zonder /page/X/ als het pagina 1 is
                    st.warning(f"Pagina {i+1} niet bereikbaar ({r.status_code}).")
                    continue

                soup = BeautifulSoup(r.text, 'html.parser')
                page_links = []

                # UNIVERSELE LINK ZOEKER
                # We zoeken naar ELKE link die lijkt op een album (bevat getallen en .html)
                # Dit werkt voor CoreRadio, DeathGrind en vele anderen.
                all_links = soup.find_all('a')
                for a in all_links:
                    h = a.get('href')
                    if h and ".html" in h and re.search(r'/\d+-', h):
                        # Extra check: moet wel van de juiste site zijn (of relatief)
                        if source_site == "CoreRadio" and "coreradio.online" in h:
                            page_links.append(h)
                        elif source_site == "DeathGrind.club" and ("deathgrind.club" in h or h.startswith("/")):
                            # Soms zijn links relatief
                            if h.startswith("/"): h = base_url + h
                            page_links.append(h)

                for link in page_links:
                    name = clean_title_from_link(link)
                    
                    if name in processed_names: continue
                    processed_names.add(name)
                    total_found += 1
                    
                    img_url, src, clean_artist = get_best_artwork_and_artist(name)
                    
                    if img_url:
                        try:
                            # Gebruik requests voor image download (sneller dan cloudscraper voor simpele jpg)
                            img_data = requests.get(img_url, timeout=3).content
                            item_data = {
                                "name": name, 
                                "clean_artist": clean_artist if clean_artist else name, 
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
            except Exception as e:
                st.error(f"Fout: {e}")

            bar.progress((i + 1) / len(urls))
        
        st.session_state['found_items'] = temp_results
        status_text.empty()
        bar.empty()
        
        if total_found == 0:
             st.error("Geen albums gevonden. De site blokkeert ons waarschijnlijk of de structuur is anders.")
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

import streamlit as st
import requests
from bs4 import BeautifulSoup
from io import BytesIO
import re
from urllib.parse import quote
import zipfile

# --- APP CONFIGURATIE ---
st.set_page_config(page_title="Cover Hunter Pro", page_icon="🎵", layout="centered")

# Verberg standaard menu items
hide_menu_style = """
        <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        </style>
        """
st.markdown(hide_menu_style, unsafe_allow_html=True)

# --- FUNCTIES ---
# We gebruiken een specifieke User-Agent om blokkades te voorkomen
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"}

def clean_name(url_part):
    name = url_part.split('/')[-1].replace('.html', '')
    name = re.sub(r'^\d+-', '', name).replace('-', ' ')
    trash = ['deluxe edition', 'remastered', '2024', '2025', '2026', 'web', 'flac', '320', 'kbps', 'ep', 'single']
    for t in trash: name = re.sub(fr'\b{t}\b', '', name, flags=re.IGNORECASE)
    return re.sub(' +', ' ', name).strip()

# --- ZOEKMACHINES ---

def search_itunes(term):
    """Zoekt op iTunes (tot 4000x4000px)"""
    try:
        r = requests.get("https://itunes.apple.com/search", params={"term": term, "media": "music", "entity": "album", "limit": 1}, timeout=5)
        d = r.json()
        if d['resultCount'] > 0:
            # Trick: 100x100bb vervangen door een absurd hoog getal geeft het origineel terug
            return d['results'][0]['artworkUrl100'].replace('100x100bb', '10000x10000bb'), "iTunes (4K)"
    except: pass
    return None, None

def search_deezer(term):
    """Zoekt op Deezer (1000px - 1400px)"""
    try:
        r = requests.get("https://api.deezer.com/search", params={"q": term, "limit": 1}, timeout=5)
        d = r.json()
        if 'data' in d and len(d['data']) > 0:
            item = d['data'][0]
            if 'cover_xl' in item: return item['cover_xl'].replace('1000x1000','1400x1400'), "Deezer (HQ)"
            if 'album' in item: return item['album']['cover_xl'].replace('1000x1000','1400x1400'), "Deezer (HQ)"
    except: pass
    return None, None

def search_bandcamp(term):
    """Zoekt op Bandcamp (Vaak originelen)"""
    try:
        # We scrapen de zoekpagina van Bandcamp
        search_url = f"https://bandcamp.com/search?q={quote(term)}&item_type=a" # item_type=a zorgt dat we alleen albums zoeken
        r = requests.get(search_url, headers=headers, timeout=5)
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # Pak het eerste resultaat
        result = soup.find('li', class_='searchresult')
        if result:
            img_div = result.find('div', class_='art')
            if img_div and img_div.find('img'):
                img_src = img_div.find('img')['src']
                # Bandcamp thumbnails eindigen vaak op _7.jpg (klein). _0.jpg is vaak full size.
                hq_src = img_src.replace('_7.jpg', '_0.jpg')
                return hq_src, "Bandcamp (Original)"
    except: pass
    return None, None

def search_musicbrainz(term):
    """Zoekt in de Cover Art Archive (Open Database)"""
    try:
        # MusicBrainz vereist een beleefde User-Agent met contactinfo
        mb_headers = {"User-Agent": "CoverHunterApp/1.0 ( contact@example.com )"}
        # 1. Zoek de Release Group ID
        mb_search = f"https://musicbrainz.org/ws/2/release/?query=release:{quote(term)}&fmt=json"
        r = requests.get(mb_search, headers=mb_headers, timeout=5)
        d = r.json()
        
        if 'releases' in d and len(d['releases']) > 0:
            release_id = d['releases'][0]['id']
            # 2. Vraag cover art op bij CoverArtArchive
            cover_url = f"https://coverartarchive.org/release/{release_id}/front"
            # Checken of de link bestaat (geen 404 geeft)
            head_req = requests.head(cover_url)
            if head_req.status_code == 200: # Als 302 redirect is het ook goed, requests volgt dit meestal
                 return cover_url, "MusicBrainz (Archive)"
    except: pass
    return None, None

def get_best_artwork(term):
    # Dit is de volgorde van kwaliteit/voorkeur
    # 1. iTunes (Vaak hoogste resolutie en cleanste scan)
    img, src = search_itunes(term)
    if img: return img, src

    # 2. Bandcamp (Geweldig voor niche/metal/indie die op CoreRadio staat)
    img, src = search_bandcamp(term)
    if img: return img, src

    # 3. Deezer (Goede backup)
    img, src = search_deezer(term)
    if img: return img, src

    # 4. MusicBrainz (Laatste redmiddel)
    img, src = search_musicbrainz(term)
    if img: return img, src
    
    return None, None

# --- DE INTERFACE ---
st.title("🎵 Cover Hunter Pro")
st.write("Vind albumhoezen via **iTunes, Bandcamp, Deezer & MusicBrainz**.")

with st.form("search_form"):
    url_input = st.text_input("CoreRadio Link (of laat leeg)", placeholder="coreradio.online")
    pages = st.slider("Aantal pagina's om te scannen", 1, 5, 1)
    submitted = st.form_submit_button("🚀 START ZOEKEN")

if submitted:
    status_text = st.empty()
    progress_bar = st.progress(0)
    
    base_url = "https://coreradio.online"
    urls = []
    
    target = url_input.strip()
    if target and not target.startswith("http"):
        target = "https://" + target

    if "coreradio" in target and "page" not in target and len(target) > 30:
        urls.append(target)
    else:
        for i in range(1, pages + 1):
            urls.append(base_url if i == 1 else f"{base_url}/page/{i}/")

    found_items = []
    processed = set()
    total_urls = len(urls)

    for i, u in enumerate(urls):
        status_text.text(f"Scannen van pagina {i+1}...")
        try:
            r = requests.get(u, headers=headers)
            soup = BeautifulSoup(r.text, 'html.parser')
            links = []
            
            if u == target: links.append(u)
            else:
                for a in soup.find_all('a'):
                    h = a.get('href')
                    if h and base_url in h and re.search(r'/\d+-', h): links.append(h)
            
            for link in links:
                if link in processed: continue
                processed.add(link)
                name = clean_name(link)
                
                # HIER ROEPEN WE DE NIEUWE ZOEKFUNCTIE AAN
                img_url, src = get_best_artwork(name)
                
                img_data = None
                if img_url:
                    try:
                        img_data = requests.get(img_url, timeout=5).content
                    except: pass

                if img_data:
                    found_items.append({"name": name, "data": img_data, "source": src, "manual": None})
                else:
                    man = f"https://covers.musichoarders.xyz/?artist={quote(name)}&sources=amazonmusic,deezer,qobuz,tidal,spotify,apple"
                    found_items.append({"name": name, "data": None, "source": "FAIL", "manual": man})
        except: pass
        progress_bar.progress((i + 1) / total_urls)

    status_text.empty()
    progress_bar.empty()

    if found_items:
        valid_items = [x for x in found_items if x['data']]
        st.success(f"{len(valid_items)} covers gevonden!")
        
        if valid_items:
            zip_buf = BytesIO()
            with zipfile.ZipFile(zip_buf, "w") as zf:
                for item in valid_items:
                    zf.writestr(f"{item['name']}.jpg", item['data'])
            
            st.download_button(
                label="📥 DOWNLOAD ALLES (ZIP)",
                data=zip_buf.getvalue(),
                file_name="covers.zip",
                mime="application/zip",
                type="primary"
            )

        st.write("---")
        cols = st.columns(2)
        for idx, item in enumerate(found_items):
            with cols[idx % 2]:
                if item['data']:
                    st.image(item['data'], use_container_width=True)
                    st.caption(f"{item['name']} | {item['source']}")
                else:
                    st.error("Niet gevonden")
                    st.markdown(f"[{item['name']}]({item['manual']})")
                    st.markdown(f"[ZOEK HANDMATIG]({item['manual']})")
    else:
        st.warning("Geen resultaten gevonden.")

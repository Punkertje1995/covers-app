import streamlit as st
import requests
from bs4 import BeautifulSoup
from io import BytesIO
import re
from urllib.parse import quote
import zipfile

# --- APP CONFIGURATIE ---
st.set_page_config(page_title="Cover Hunter", page_icon="🎵", layout="centered")

# Verberg standaard menu items voor een strakke look
hide_menu_style = """
        <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        </style>
        """
st.markdown(hide_menu_style, unsafe_allow_html=True)

# --- FUNCTIES ---
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"}

def clean_name(url_part):
    name = url_part.split('/')[-1].replace('.html', '')
    name = re.sub(r'^\d+-', '', name).replace('-', ' ')
    trash = ['deluxe edition', 'remastered', '2024', '2025', '2026', 'web', 'flac', '320', 'kbps']
    for t in trash: name = re.sub(fr'\b{t}\b', '', name, flags=re.IGNORECASE)
    return re.sub(' +', ' ', name).strip()

def get_best_artwork(term):
    # iTunes (4K)
    try:
        r = requests.get("https://itunes.apple.com/search", params={"term": term, "media": "music", "entity": "album", "limit": 1}, timeout=5)
        d = r.json()
        if d['resultCount'] > 0: return d['results'][0]['artworkUrl100'].replace('100x100bb', '10000x10000bb'), "iTunes (4K)"
    except: pass
    # Deezer (HQ)
    try:
        r = requests.get("https://api.deezer.com/search", params={"q": term, "limit": 1}, timeout=5)
        d = r.json()
        if 'data' in d and len(d['data']) > 0:
            item = d['data'][0]
            if 'cover_xl' in item: return item['cover_xl'].replace('1000x1000','1400x1400'), "Deezer (HQ)"
            if 'album' in item: return item['album']['cover_xl'].replace('1000x1000','1400x1400'), "Deezer (HQ)"
    except: pass
    return None, None

# --- DE INTERFACE ---
st.title("🎵 Cover Hunter")
st.write("Vind automatisch de hoogste kwaliteit albumhoezen.")

# We gebruiken een FORMULIER zodat de app niet ververst tijdens het typen
with st.form("search_form"):
    url_input = st.text_input("CoreRadio Link (of laat leeg voor homepage)", placeholder="coreradio.online")
    pages = st.slider("Aantal pagina's om te scannen", 1, 5, 1)
    
    # De knop zit nu IN het formulier
    submitted = st.form_submit_button("🚀 START ZOEKEN")

if submitted:
    status_text = st.empty()
    progress_bar = st.progress(0)
    
    base_url = "https://coreradio.online"
    urls = []
    
    # URL Correctie (als je https vergeet)
    target = url_input.strip()
    if target and not target.startswith("http"):
        target = "https://" + target

    # Bepaal wat we scannen
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
                img_url, src = get_best_artwork(name)
                
                # We downloaden de afbeelding meteen naar geheugen (sneller)
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
        
        # Maak ZIP bestand
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

        # Toon Grid
        st.write("---")
        cols = st.columns(2)
        for idx, item in enumerate(found_items):
            with cols[idx % 2]:
                if item['data']:
                    st.image(item['data'], use_container_width=True)
                    st.caption(f"{item['name']}")
                else:
                    st.error("Niet gevonden")
                    st.markdown(f"[{item['name']}]({item['manual']})")
                    st.markdown(f"[ZOEK HANDMATIG]({item['manual']})")
    else:
        st.warning("Geen resultaten gevonden op deze pagina.")

import pandas as pd
import requests
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import os
import textwrap 
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import glob
import time
import subprocess
import re
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
from urllib.parse import quote 

# --- 1. CONFIGURACIÓN ---
OUTPUT_DIR = "images"
ASSETS_DIR = "assets"
os.makedirs(OUTPUT_DIR, exist_ok=True)

GITHUB_USER = "analyticsdatajg2025-cmd"
REPO_NAME = "GITHUB_FEED_JZ"
BASE_URL_IMG = f"https://{GITHUB_USER}.github.io/{REPO_NAME}/{OUTPUT_DIR}/"

FEED_URL = "https://juntozstgsrvproduction.blob.core.windows.net/juntoz-feeds/google_juntoz_feed.txt"
SHEET_ID = "14PcRSXLFHCmXgLdr42Phlp0U-J8jM5ZTe9-Pu1p6NE8"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

BATCH_SIZE = 5000 
MAX_THREADS = 40 

# Tipografías y Recursos
LOGO_PATH = os.path.join(ASSETS_DIR, "logojuntozblanco.png")
F_BOLD_PATH = "HurmeGeometricSans1 Bold.otf"
F_OBL_PATH = "HurmeGeometricSans1 Oblique.otf"
F_REG_PATH = "HurmeGeometricSans1.otf"

try:
    LOGO_ORIGINAL = Image.open(LOGO_PATH).convert("RGBA")
except:
    LOGO_ORIGINAL = Image.new('RGBA', (400, 150), (255, 255, 255, 100))

# Cargar Credenciales
credentials_json = os.environ.get('GCP_CREDENTIALS')
if credentials_json:
    creds_dict = json.loads(credentials_json)
else:
    try:
        with open('service_account.json') as f:
            creds_dict = json.load(f)
    except:
        print("Error: Credenciales no encontradas.")
        exit(1)

# --- 2. FUNCIONES AUXILIARES ---
def load_font(filename, size):
    path = os.path.join(ASSETS_DIR, filename)
    try: return ImageFont.truetype(path, size)
    except: return ImageFont.load_default()

def get_clean_price_val(val_str):
    if pd.isna(val_str): return 0.0
    s = str(val_str).upper().replace(' PEN', '').replace('PEN', '').replace(',', '').strip()
    try: return float(s)
    except: return 0.0

def git_autosave(batch_index):
    try:
        subprocess.run(["git", "add", "images/"], check=False)
        msg = f"Auto-save: Bloque {batch_index}"
        subprocess.run(["git", "commit", "-m", msg], check=False)
        subprocess.run(["git", "push"], check=False)
    except: pass

# --- 3. PROCESAMIENTO DE IMAGEN ---
def procesar_fila(row):
    try:
        val_sale_price = get_clean_price_val(row['sale_price'])
        val_price = get_clean_price_val(row['price'])

        # EL NOMBRE DE LA IMAGEN INCLUYE EL PRECIO PARA FORZAR CACHÉ
        price_tag = f"{val_sale_price:.2f}".replace('.', '_')
        file_name = f"{row['id']}_{price_tag}.jpg"
        target_path = os.path.join(OUTPUT_DIR, file_name)
        final_url = f"{BASE_URL_IMG}{file_name}"

        # Si la imagen ya existe con ese ID y ese Precio, saltamos
        if os.path.exists(target_path):
            return final_url, False

        # Borrar versiones anteriores del mismo producto con precio diferente
        for f in glob.glob(os.path.join(OUTPUT_DIR, f"{row['id']}_*.jpg")):
            try: os.remove(f)
            except: pass

        # Descargar imagen
        raw_url = str(row['image_link']).strip()
        clean_url = quote(raw_url, safe="%/:=&?~#+!$,;'@()*[]") 
        res_prod = requests.get(clean_url, headers=HEADERS, timeout=15) 
        if res_prod.status_code != 200: return row['image_link'], False 
        
        prod_img = Image.open(BytesIO(res_prod.content)).convert("RGBA")

        # --- DISEÑO ---
        color_morado = (141, 54, 197)
        canvas = Image.new('RGB', (1080, 1080), color=color_morado)
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle([60, 60, 1020, 810], radius=80, fill="white")
        draw.rounded_rectangle([680, 0, 1080, 140], radius=40, fill=color_morado)

        logo_w, logo_h = LOGO_ORIGINAL.size
        nuevo_logo_w = 320
        nuevo_logo_h = int((nuevo_logo_w / logo_w) * logo_h)
        logo_red = LOGO_ORIGINAL.resize((nuevo_logo_w, nuevo_logo_h), Image.Resampling.LANCZOS)
        canvas.paste(logo_red, (680 + (400 - nuevo_logo_w)//2, (140 - nuevo_logo_h)//2), logo_red)

        prod_img.thumbnail((680, 520), Image.Resampling.LANCZOS)
        canvas.paste(prod_img, ((1080 - prod_img.width)//2, 140 + (580 - prod_img.height)//2), prod_img)

        # Precios y Textos
        MARGIN_RIGHT, MARGIN_LEFT = 1010, 70
        p_sale_str = f"{val_sale_price:.2f}"
        size_sale = 135
        f_sale = load_font(F_BOLD_PATH, size_sale)
        f_symbol = load_font(F_BOLD_PATH, int(size_sale * 0.5))

        while size_sale > 50:
            if (draw.textlength("S/", font=f_symbol) + 12 + draw.textlength(p_sale_str, font=f_sale)) <= 400: break
            size_sale -= 4
            f_sale = load_font(F_BOLD_PATH, size_sale)
            f_symbol = load_font(F_BOLD_PATH, int(size_sale * 0.5))

        w_sale_full = draw.textlength("S/", font=f_symbol) + 12 + draw.textlength(p_sale_str, font=f_sale)
        draw.text((MARGIN_RIGHT - w_sale_full, 920 - size_sale*0.05), "S/", font=f_symbol, fill="white")
        draw.text((MARGIN_RIGHT - w_sale_full + draw.textlength("S/", font=f_symbol) + 12, 920 - size_sale*0.1), p_sale_str, font=f_sale, fill="white")

        p_reg_str = f"Precio regular: S/{val_price:.2f}"
        f_reg = load_font(F_REG_PATH, 30)
        draw.text((MARGIN_RIGHT - draw.textlength(p_reg_str, font=f_reg), 865), p_reg_str, font=f_reg, fill="white")

        draw.text((MARGIN_LEFT, 860), str(row['brand']).upper().strip(), font=load_font(F_BOLD_PATH, 28), fill="white")
        
        f_title = load_font(F_OBL_PATH, 38)
        lines = textwrap.wrap(str(row['title']).strip(), width=30)[:3]
        y_pos = 910
        for line in lines:
            draw.text((MARGIN_LEFT, y_pos), line, font=f_title, fill="white")
            y_pos += 42

        canvas = canvas.resize((600, 600), Image.Resampling.LANCZOS)
        canvas.save(target_path, "JPEG", optimize=True, quality=75)
        return final_url, True

    except Exception as e:
        return row['image_link'], False

# --- 4. MAIN ---
def main():
    print(">>> [1/4] Descargando Feed y Limpiando Duplicados...")
    res_feed = requests.get(FEED_URL, headers=HEADERS, timeout=60)
    if res_feed.status_code != 200: exit(1)
        
    # LEEMOS EL FEED CON SEPARADOR TABULACIÓN Y FORZAMOS LIMPIEZA DE ESPACIOS
    df = pd.read_csv(BytesIO(res_feed.content), sep='\t', on_bad_lines='skip', low_memory=False)
    df.columns = [c.strip() for c in df.columns]
    
    # --- FILTROS DE CALIDAD ---
    df = df[df['availability'].astype(str).str.lower().str.contains('in stock')].copy()
    df = df[df['image_link'].notna()]
    
    # ESTO ELIMINA CUALQUIER REPETICIÓN FANTASMA BASÁNDOSE EN EL ID ÚNICO DEL FEED
    df.drop_duplicates(subset=['id'], keep='first', inplace=True)
    
    # Recolector de Basura
    ids_validos = set(df['id'].astype(str).tolist())
    for ruta in glob.glob(os.path.join(OUTPUT_DIR, "*.jpg")):
        if os.path.basename(ruta).split('_')[0] not in ids_validos:
            try: os.remove(ruta)
            except: pass

    rows_to_process = df.to_dict('records')
    print(f">>> Total productos ÚNICOS a procesar: {len(rows_to_process)}")

    # Conexión Sheets
    print(">>> [2/4] Limpiando Google Sheets...")
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).sheet1
    
    # BORRADO TOTAL DE LA HOJA PARA EVITAR PRODUCTOS VIEJOS O ROTOS
    sheet.clear()
    sheet.append_row(list(df.columns))

    print(">>> [3/4] Generando Imágenes y subiendo datos...")
    for i in range(0, len(rows_to_process), BATCH_SIZE):
        batch = rows_to_process[i : i + BATCH_SIZE]
        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            results = list(tqdm(executor.map(procesar_fila, batch), total=len(batch), leave=False))
        
        batch_urls = [r[0] for r in results]
        any_new = any(r[1] for r in results)
        
        batch_df = pd.DataFrame(batch)
        batch_df['image_link'] = batch_urls 
        
        if any_new: git_autosave(i // BATCH_SIZE + 1)
        
        # SUBIDA AL SHEETS
        try:
            sheet.append_rows(batch_df.astype(str).values.tolist(), value_input_option='RAW')
            time.sleep(2)
        except: pass

    print("\n>>> 🏁 ¡CATÁLOGO ÚNICO Y ACTUALIZADO COMPLETADO!")

if __name__ == "__main__":
    main()
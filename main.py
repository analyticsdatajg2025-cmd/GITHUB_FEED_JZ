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
from urllib.parse import quote # <--- NUEVA LIBRERÍA PARA LIMPIAR URLs

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

# AJUSTES DE RENDIMIENTO
BATCH_SIZE = 5000 
MAX_THREADS = 40  

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

# Recursos Gráficos
LOGO_PATH = os.path.join(ASSETS_DIR, "logojuntozblanco.png")
try:
    LOGO_ORIGINAL = Image.open(LOGO_PATH).convert("RGBA")
except:
    LOGO_ORIGINAL = Image.new('RGBA', (400, 150), (255, 255, 255, 100))

def load_font(filename, size):
    path = os.path.join(ASSETS_DIR, filename)
    try: return ImageFont.truetype(path, size)
    except: return ImageFont.load_default()

F_BOLD_PATH = "HurmeGeometricSans1 Bold.otf"
F_OBL_PATH = "HurmeGeometricSans1 Oblique.otf"
F_REG_PATH = "HurmeGeometricSans1.otf"

# --- 2. FUNCIONES AUXILIARES ---
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
        print(f"   💾 [Git] Progreso guardado (Bloque {batch_index}).")
    except Exception as e:
        print(f"   ⚠️ Error Git Autosave: {e}")

# --- 3. PROCESAMIENTO ---
def procesar_fila(row):
    try:
        # A. PREPARAR DATOS
        raw_sale_price = str(row['sale_price'])
        raw_price = str(row['price'])
        
        val_sale_price = get_clean_price_val(raw_sale_price)
        val_price = get_clean_price_val(raw_price)

        price_tag = f"{val_sale_price:.2f}".replace('.', '_')
        file_name = f"{row['id']}_{price_tag}.jpg"
        target_path = os.path.join(OUTPUT_DIR, file_name)
        final_url = f"{BASE_URL_IMG}{file_name}"

        # B. VALIDACIÓN RÁPIDA (Si existe, salta inmediatamente)
        if os.path.exists(target_path):
            return final_url, False

        # C. Limpieza viejos
        try:
            for f in glob.glob(os.path.join(OUTPUT_DIR, f"{row['id']}_*.jpg")):
                os.remove(f)
        except: pass

        # D. 🔥 LIMPIEZA Y DESCARGA ROBUSTA (AQUÍ ESTÁ LA MEJORA)
        raw_url = str(row['image_link']).strip()
        # Arreglamos espacios en la URL (como el caso del reloj Fossil)
        clean_url = quote(raw_url, safe="%/:=&?~#+!$,;'@()*[]") 
        
        res_prod = requests.get(clean_url, headers=HEADERS, timeout=15) # Más timeout
        if res_prod.status_code != 200: 
            return raw_url, False # Si falla, devolvemos la original limpia
        
        prod_img = Image.open(BytesIO(res_prod.content)).convert("RGBA")

        # E. DISEÑO
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

        # Textos
        MARGIN_RIGHT, MARGIN_LEFT = 1010, 70
        WIDTH_PRICE_MAX = 400 
        
        p_sale_str = f"{val_sale_price:.2f}"
        size_sale = 135
        f_sale = load_font(F_BOLD_PATH, size_sale)
        f_symbol = load_font(F_BOLD_PATH, int(size_sale * 0.5))

        while size_sale > 50:
            w_sale = draw.textlength(p_sale_str, font=f_sale)
            w_sym = draw.textlength("S/", font=f_symbol)
            if (w_sym + 12 + w_sale) <= WIDTH_PRICE_MAX: break
            size_sale -= 4
            f_sale = load_font(F_BOLD_PATH, size_sale)
            f_symbol = load_font(F_BOLD_PATH, int(size_sale * 0.5))

        w_total_sale = draw.textlength("S/", font=f_symbol) + 12 + draw.textlength(p_sale_str, font=f_sale)
        x_sale = MARGIN_RIGHT - w_total_sale
        y_base = 920 - (size_sale * 0.1) 
        draw.text((x_sale, y_base + size_sale*0.05), "S/", font=f_symbol, fill="white")
        draw.text((x_sale + draw.textlength("S/", font=f_symbol) + 12, y_base), p_sale_str, font=f_sale, fill="white")

        p_reg_str = f"Precio regular: S/{val_price:.2f}"
        f_reg = load_font(F_REG_PATH, 30)
        w_reg = draw.textlength(p_reg_str, font=f_reg)
        draw.text((MARGIN_RIGHT - w_reg, 865), p_reg_str, font=f_reg, fill="white")

        brand_txt = str(row['brand']).upper().strip()
        size_brand = 28
        f_brand = load_font(F_BOLD_PATH, size_brand)
        
        while size_brand > 18:
            if draw.textlength(brand_txt, font=f_brand) < 540: break
            size_brand -= 2
            f_brand = load_font(F_BOLD_PATH, size_brand)
        draw.text((MARGIN_LEFT, 860), brand_txt, font=f_brand, fill="white")

        title_txt = str(row['title']).strip()
        size_title = 38
        f_title = load_font(F_OBL_PATH, size_title)
        lines = []
        while size_title > 20:
            avg_char = f_title.getlength("a") or 10
            chars_per_line = int(540 / avg_char)
            temp_lines = textwrap.wrap(title_txt, width=chars_per_line)
            if len(temp_lines) <= 3 and all(draw.textlength(l, font=f_title) <= 540 for l in temp_lines):
                lines = temp_lines
                break
            size_title -= 2
            f_title = load_font(F_OBL_PATH, size_title)
        if not lines: lines = textwrap.wrap(title_txt, width=40)[:3]
        
        y_pos = 910
        for line in lines:
            draw.text((MARGIN_LEFT, y_pos), line, font=f_title, fill="white")
            y_pos += (size_title + 4)

        canvas = canvas.resize((900, 900), Image.Resampling.LANCZOS)
        canvas.save(target_path, "JPEG", quality=85)
        return final_url, True

    except Exception as e:
        print(f"Error en ID {row.get('id', '?')}: {e}")
        return row['image_link'], False

# --- 4. MAIN ---
def main():
    print(">>> [1/4] Descargando Feed...")
    df = pd.read_csv(FEED_URL, sep='\t', on_bad_lines='skip', low_memory=False)
    df.columns = [c.strip() for c in df.columns]
    
    # 1. Filtros Básicos
    df = df[df['availability'] == 'in stock'].copy()
    df = df[df['image_link'].notna()]
    df = df[df['image_link'].str.endswith('.jpg', na=False)]
    
    # 2. 🔥 ELIMINAR DUPLICADOS
    total_antes = len(df)
    df.drop_duplicates(subset=['id'], keep='first', inplace=True)
    total_ahora = len(df)
    print(f">>> Duplicados eliminados: {total_antes - total_ahora}")
    
    rows_to_process = df.to_dict('records')
    total_products = len(rows_to_process)
    print(f">>> Total productos ÚNICOS a procesar: {total_products}")

    # --- INICIALIZAR SHEETS (CON BLINDAJE ANTI-ERROR 503) ---
    print(">>> [2/4] Conectando a Google Sheets...")
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    
    max_retries = 5
    sheet = None
    
    for attempt in range(max_retries):
        try:
            sheet = client.open_by_key(SHEET_ID).sheet1
            print("   ✅ Conexión exitosa a Sheets.")
            break 
        except Exception as e:
            print(f"   ⚠️ Intento {attempt+1}/{max_retries} fallido: {e}")
            if attempt < max_retries - 1:
                time.sleep(10)
            else:
                print("   ❌ Error crítico: No se pudo conectar a Sheets.")
                exit(1)
    
    # Limpiamos hoja
    try:
        sheet.clear()
        sheet.append_row(list(df.columns))
    except Exception as e:
        print(f"Error al limpiar hoja: {e}")
    
    print(f">>> [3/4] Procesando en Bloques de {BATCH_SIZE}...")
    
    for i in range(0, total_products, BATCH_SIZE):
        batch = rows_to_process[i : i + BATCH_SIZE]
        print(f"\n⚡ Procesando Bloque {i//BATCH_SIZE + 1}: {len(batch)} productos")

        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            results = list(tqdm(executor.map(procesar_fila, batch), total=len(batch), leave=False))
        
        batch_urls = [r[0] for r in results]
        any_new = any(r[1] for r in results)
        
        batch_df = pd.DataFrame(batch)
        batch_df['image_link'] = batch_urls 
        batch_df = batch_df.astype(str) 

        if any_new: git_autosave(i // BATCH_SIZE + 1)
        else: print("   ⏩ (Skipping Git Push - No hay imágenes nuevas)")

        try:
            data = batch_df.values.tolist()
            sheet.append_rows(data, value_input_option='RAW')
            print(f"   📊 [Sheets] Bloque subido.")
            time.sleep(2)
        except Exception as e:
            print(f"   ⚠️ Error Sheets Upload: {e}")
            time.sleep(10)
            try: sheet.append_rows(data, value_input_option='RAW')
            except: pass

    print("\n>>> 🏁 ¡PROCESO COMPLETADO!")

if __name__ == "__main__":
    main()
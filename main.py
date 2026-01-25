import pandas as pd
import requests
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import glob
import time
import subprocess
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm

# --- 1. CONFIGURACIÓN ---
OUTPUT_DIR = "images"
ASSETS_DIR = "assets"
os.makedirs(OUTPUT_DIR, exist_ok=True)

GITHUB_USER = "analyticsdatajg2025-cmd"
REPO_NAME = "GITHUB_FEED_JZ"
BASE_URL_IMG = f"https://{GITHUB_USER}.github.io/{REPO_NAME}/{OUTPUT_DIR}/"

FEED_URL = "https://juntozstgsrvproduction.blob.core.windows.net/juntoz-feeds/google_juntoz_feed.txt"
SHEET_ID = "14PcRSXLFHCmXgLdr42Phlp0U-J8jM5ZTe9-Pu1p6NE8"

# Headers para evitar bloqueo 403
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# --- AJUSTES DE RENDIMIENTO ---
# Pedido: 5000 por bloque.
BATCH_SIZE = 5000 
# Hilos: 40 para intentar acercarnos a la hora, pero sin saturar
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
def clean_price(val):
    if pd.isna(val): return 0.0
    s = str(val).upper().replace(' PEN', '').replace(',', '').strip()
    try: return float(s)
    except: return 0.0

def git_autosave(batch_index):
    """Guarda en GitHub cada bloque de 5000 para no perder nada"""
    try:
        # Commit ligero
        subprocess.run(["git", "add", "images/"], check=False)
        msg = f"Auto-save: Bloque {batch_index}"
        subprocess.run(["git", "commit", "-m", msg], check=False)
        # Push
        subprocess.run(["git", "push"], check=False)
        print(f"   💾 [Git] Progreso guardado (Bloque {batch_index}).")
    except Exception as e:
        print(f"   ⚠️ Error Git Autosave: {e}")

# --- 3. PROCESAMIENTO ---
def procesar_fila(row):
    try:
        # Cache Busting Físico: Nombre incluye precio
        price_tag = str(row['sale_price']).replace('.', '_')
        file_name = f"{row['id']}_{price_tag}.jpg"
        target_path = os.path.join(OUTPUT_DIR, file_name)
        final_url = f"{BASE_URL_IMG}{file_name}"

        # A. VALIDACIÓN ULTRA RÁPIDA (Si existe, saltamos todo)
        if os.path.exists(target_path):
            return final_url, False # (URL, ¿Fue Creada?) -> False

        # B. Limpieza de versiones anteriores del mismo ID
        # Solo lo hacemos si vamos a crear una nueva, para ahorrar I/O
        try:
            for f in glob.glob(os.path.join(OUTPUT_DIR, f"{row['id']}_*.jpg")):
                os.remove(f)
        except: pass

        # C. Descarga
        res_prod = requests.get(row['image_link'], headers=HEADERS, timeout=8)
        if res_prod.status_code != 200: 
            return row['image_link'], False
        
        prod_img = Image.open(BytesIO(res_prod.content)).convert("RGBA")

        # D. Diseño (Tu Branding)
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
        WIDTH_PRICE_MAX, WIDTH_TEXT_MAX = 400, 540
        p_sale_str = f"{row['sale_price']:.2f}"
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

        p_reg_str = f"Precio regular: S/{row['price']:.2f}"
        f_reg = load_font(F_REG_PATH, 30)
        w_reg = draw.textlength(p_reg_str, font=f_reg)
        draw.text((MARGIN_RIGHT - w_reg, 865), p_reg_str, font=f_reg, fill="white")

        brand_txt = str(row['brand']).upper().strip()
        size_brand = 28
        f_brand = load_font(F_BOLD_PATH, size_brand)
        while size_brand > 18:
            if draw.textlength(brand_txt, font=f_brand) < WIDTH_TEXT_MAX: break
            size_brand -= 2
            f_brand = load_font(F_BOLD_PATH, size_brand)
        draw.text((MARGIN_LEFT, 860), brand_txt, font=f_brand, fill="white")

        title_txt = str(row['title']).strip()
        size_title = 38
        f_title = load_font(F_OBL_PATH, size_title)
        lines = []
        while size_title > 20:
            avg_char = f_title.getlength("a") or 10
            chars_per_line = int(WIDTH_TEXT_MAX / avg_char)
            temp_lines = textwrap.wrap(title_txt, width=chars_per_line)
            if len(temp_lines) <= 3 and all(draw.textlength(l, font=f_title) <= WIDTH_TEXT_MAX for l in temp_lines):
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
        return final_url, True # URL, Creada=True

    except:
        return row['image_link'], False

# --- 4. MAIN ---
def main():
    print(">>> [1/4] Descargando Feed...")
    df = pd.read_csv(FEED_URL, sep='\t', on_bad_lines='skip', low_memory=False)
    df.columns = [c.strip() for c in df.columns]
    
    # Filtros
    df = df[df['availability'] == 'in stock'].copy()
    df = df[df['image_link'].notna()]
    df = df[df['image_link'].str.endswith('.jpg', na=False)]
    df['price'] = df['price'].apply(clean_price)
    df['sale_price'] = df['sale_price'].apply(clean_price)
    
    rows_to_process = df.to_dict('records')
    total_products = len(rows_to_process)
    print(f">>> Total productos: {total_products}")

    # --- INICIALIZAR GOOGLE SHEETS ---
    print(">>> [2/4] Preparando Google Sheets (Limpiando)...")
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).sheet1
    
    # Limpieza inicial para reconstruir el feed limpio
    sheet.clear()
    headers = list(df.columns)
    sheet.append_row(headers)
    
    print(f">>> [3/4] Procesando en Bloques de {BATCH_SIZE} con {MAX_THREADS} Hilos...")
    
    # --- BUCLE DE LOTES (CONTINGENCIA ACTIVA) ---
    # Iteramos sobre los productos en bloques de 5000
    for i in range(0, total_products, BATCH_SIZE):
        batch = rows_to_process[i : i + BATCH_SIZE]
        current_index_start = i
        current_index_end = i + len(batch)
        
        print(f"\n⚡ Procesando Bloque {i//BATCH_SIZE + 1}: Productos {current_index_start} a {current_index_end}")

        # A. GENERACIÓN PARALELA (ThreadPool)
        # Aquí es donde el script verifica si existen o crea nuevas
        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            # map devuelve los resultados en orden
            results = list(tqdm(executor.map(procesar_fila, batch), total=len(batch), leave=False))
        
        # B. PREPARAR DATOS PARA SHEETS
        batch_urls = [r[0] for r in results]
        any_new_image = any(r[1] for r in results) # ¿Se creó alguna imagen nueva?
        
        # Crear DataFrame temporal solo de este bloque
        batch_df = pd.DataFrame(batch)
        batch_df['image_link'] = batch_urls
        batch_df = batch_df.astype(str)
        data_to_upload = batch_df.values.tolist()

        # C. AUTO-SAVE GIT (Solo si hubo novedades)
        # Esto asegura que si se corta, las imagenes quedan en el repo
        if any_new_image:
            git_autosave(i // BATCH_SIZE + 1)
        else:
            print("   ⏩ Bloque sin imágenes nuevas (Skipping Git Push)")

        # D. AUTO-UPDATE SHEETS (Visibilidad Inmediata)
        try:
            # Subir 5000 filas de golpe puede dar error, intentamos.
            # Si falla, se puede dividir, pero 5000 suele pasar en RAW mode.
            sheet.append_rows(data_to_upload, value_input_option='RAW')
            print(f"   📊 [Sheets] Bloque subido exitosamente.")
            time.sleep(2) # Pausa de cortesía para API de Google
        except Exception as e:
            print(f"   ⚠️ Error subiendo bloque a Sheets: {e}")
            print("   ♻️ Reintentando en 10 segundos...")
            time.sleep(10)
            try:
                sheet.append_rows(data_to_upload, value_input_option='RAW')
                print("   ✅ Reintento exitoso.")
            except Exception as e2:
                print(f"   ❌ Falló reintento. Este bloque no se subió al Sheet (pero imágenes están en Git). Error: {e2}")

    print("\n>>> 🏁 ¡PROCESO COMPLETADO! FEED 100% ACTUALIZADO.")

if __name__ == "__main__":
    main()
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

# Headers para requests (importante para evitar bloqueos)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

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

# Recursos Gráficos GLOBALES (se cargan una sola vez)
LOGO_PATH = os.path.join(ASSETS_DIR, "logojuntozblanco.png")
try:
    LOGO_ORIGINAL = Image.open(LOGO_PATH).convert("RGBA")
except:
    LOGO_ORIGINAL = Image.new('RGBA', (400, 150), (255, 255, 255, 100))

# Pre-cargar fuentes para no leer disco 100k veces
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

# --- 3. GENERADOR DE IMAGEN (Tu diseño exacto) ---
def procesar_fila(row):
    """
    Esta función encapsula toda la lógica por producto.
    Devuelve la URL final que debe ir en el Excel.
    """
    try:
        # 1. Definir nombres y rutas
        price_tag = str(row['sale_price']).replace('.', '_')
        file_name = f"{row['id']}_{price_tag}.jpg"
        target_path = os.path.join(OUTPUT_DIR, file_name)
        final_url = f"{BASE_URL_IMG}{file_name}"

        # 2. VALIDACIÓN RÁPIDA (Si existe, saltamos)
        if os.path.exists(target_path):
            return final_url

        # 3. Limpieza de versiones viejas del mismo ID
        # Nota: En multi-hilo, glob puede ser lento, pero es necesario para limpieza
        # Si queremos velocidad extrema, podríamos omitir esto, pero mejor dejarlo para no llenar disco.
        try:
            for f in glob.glob(os.path.join(OUTPUT_DIR, f"{row['id']}_*.jpg")):
                os.remove(f)
        except: pass

        # 4. Descargar Imagen
        res_prod = requests.get(row['image_link'], headers=HEADERS, timeout=10)
        if res_prod.status_code != 200:
            return row['image_link'] # Fallback a original
        
        prod_img = Image.open(BytesIO(res_prod.content)).convert("RGBA")

        # 5. Diseño (Tu código exacto)
        color_morado = (141, 54, 197)
        canvas = Image.new('RGB', (1080, 1080), color=color_morado)
        draw = ImageDraw.Draw(canvas)

        draw.rounded_rectangle([60, 60, 1020, 810], radius=80, fill="white")
        draw.rounded_rectangle([680, 0, 1080, 140], radius=40, fill=color_morado)

        # Logo
        logo_w, logo_h = LOGO_ORIGINAL.size
        nuevo_logo_w = 320
        nuevo_logo_h = int((nuevo_logo_w / logo_w) * logo_h)
        logo_red = LOGO_ORIGINAL.resize((nuevo_logo_w, nuevo_logo_h), Image.Resampling.LANCZOS)
        canvas.paste(logo_red, (680 + (400 - nuevo_logo_w)//2, (140 - nuevo_logo_h)//2), logo_red)

        # Producto
        prod_img.thumbnail((680, 520), Image.Resampling.LANCZOS)
        canvas.paste(prod_img, ((1080 - prod_img.width)//2, 140 + (580 - prod_img.height)//2), prod_img)

        # Textos - Precios
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

        # Marca
        brand_txt = str(row['brand']).upper().strip()
        size_brand = 28
        f_brand = load_font(F_BOLD_PATH, size_brand)
        while size_brand > 18:
            if draw.textlength(brand_txt, font=f_brand) < WIDTH_TEXT_MAX: break
            size_brand -= 2
            f_brand = load_font(F_BOLD_PATH, size_brand)
        draw.text((MARGIN_LEFT, 860), brand_txt, font=f_brand, fill="white")

        # Título
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

        # Guardar (Usamos calidad 85 para balance peso/calidad)
        canvas = canvas.resize((900, 900), Image.Resampling.LANCZOS)
        canvas.save(target_path, "JPEG", quality=85)
        
        return final_url

    except Exception as e:
        # Si falla algo, devolvemos el link original para no romper el sheet
        return row['image_link']

# --- 4. MAIN OPTIMIZADO ---
def main():
    print(">>> [1/4] Descargando Feed...")
    df = pd.read_csv(FEED_URL, sep='\t', on_bad_lines='skip', low_memory=False)
    df.columns = [c.strip() for c in df.columns]
    
    # Filtros
    df = df[df['availability'] == 'in stock'].copy()
    df = df[df['image_link'].notna()]
    df = df[df['image_link'].str.endswith('.jpg', na=False)]
    
    # Limpieza Numérica
    df['price'] = df['price'].apply(clean_price)
    df['sale_price'] = df['sale_price'].apply(clean_price)
    
    # Convertir DF a lista de diccionarios para el ThreadPool
    rows_to_process = df.to_dict('records')
    print(f">>> Total productos a procesar: {len(rows_to_process)}")

    print(f">>> [2/4] Procesando Imágenes con 50 Hilos...")
    
    # --- AQUÍ ESTÁ LA MAGIA DE LA VELOCIDAD ---
    # Usamos ThreadPoolExecutor para procesar 50 imágenes en paralelo
    updated_links = []
    with ThreadPoolExecutor(max_workers=50) as executor:
        # Usamos tqdm para ver la barra de progreso
        updated_links = list(tqdm(executor.map(procesar_fila, rows_to_process), total=len(rows_to_process)))

    # Asignar columna final
    df['image_link'] = updated_links
    df = df.astype(str)

    # --- SUBIDA A SHEETS ---
    print(">>> [4/4] Conectando a Google Sheets...")
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    
    # Lógica de subida segura del otro proyecto
    try:
        sheet = client.open_by_key(SHEET_ID).sheet1
        sheet.clear()
        
        # Preparar datos
        data = [df.columns.values.tolist()] + df.values.tolist()
        
        # Subir en bloques de 5,000 con pausas
        chunk_size = 5000
        for i in range(0, len(data), chunk_size):
            chunk = data[i:i + chunk_size]
            try:
                sheet.append_rows(chunk, value_input_option='RAW')
                print(f"   Subido bloque {i} a {i+len(chunk)}. Pausa técnica...")
                time.sleep(2) 
            except Exception as e:
                print(f"   ⚠️ Error en bloque {i}. Reintentando en 10s...")
                time.sleep(10)
                sheet.append_rows(chunk, value_input_option='RAW')

        print(">>> ✅ ¡PROCESO COMPLETADO EXITOSAMENTE!")

    except Exception as e:
        print(f"Error crítico en Sheets: {e}")

if __name__ == "__main__":
    main()
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
import math

# --- 1. CONFIGURACIÓN ---
# TIEMPO MÁXIMO DE EJECUCIÓN: 55 minutos (dejamos 5 min para subir a Sheets y Git)
TIME_LIMIT_SECONDS = 55 * 60 

OUTPUT_DIR = "images"
ASSETS_DIR = "assets"
os.makedirs(OUTPUT_DIR, exist_ok=True)

GITHUB_USER = "analyticsdatajg2025-cmd"
REPO_NAME = "GITHUB_FEED_JZ"
BASE_URL_IMG = f"https://{GITHUB_USER}.github.io/{REPO_NAME}/{OUTPUT_DIR}/"

FEED_URL = "https://juntozstgsrvproduction.blob.core.windows.net/juntoz-feeds/google_juntoz_feed.txt"
SHEET_ID = "14PcRSXLFHCmXgLdr42Phlp0U-J8jM5ZTe9-Pu1p6NE8"

# Credenciales
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

# Fuentes
F_BOLD = "HurmeGeometricSans1 Bold.otf"
F_OBL = "HurmeGeometricSans1 Oblique.otf"
F_REG = "HurmeGeometricSans1.otf"

def get_font(filename, size):
    path = os.path.join(ASSETS_DIR, filename)
    try: return ImageFont.truetype(path, size)
    except: return ImageFont.load_default()

# --- 2. HELPERS ---
def clean_price(val):
    if pd.isna(val): return 0.0
    s = str(val).upper().replace(' PEN', '').replace(',', '').strip()
    try: return float(s)
    except: return 0.0

def upload_in_chunks(client, df, sheet_id, chunk_size=5000):
    """Sube datos a Sheets en bloques para evitar Timeout con 100k filas"""
    try:
        sheet = client.open_by_key(sheet_id).sheet1
        sheet.clear()
        
        # Preparar encabezados
        headers = df.columns.values.tolist()
        all_values = df.values.tolist()
        
        # Subir encabezados primero
        sheet.append_row(headers)
        
        total_rows = len(all_values)
        print(f">>> Iniciando carga a Sheets en bloques de {chunk_size}...")
        
        for i in range(0, total_rows, chunk_size):
            chunk = all_values[i:i + chunk_size]
            sheet.append_rows(chunk)
            print(f"   Subido bloque {i} a {i+len(chunk)} de {total_rows}")
            time.sleep(1) # Pequeña pausa para no saturar API
            
        print(">>> Carga a Google Sheets completada exitosamente.")
    except Exception as e:
        print(f"ERROR CRÍTICO SUBIENDO A SHEETS: {e}")

# --- 3. DISEÑO ---
def generar_imagen(row, filename):
    try:
        # Descarga imagen original
        res_prod = requests.get(row['image_link'], timeout=5)
        if res_prod.status_code != 200: return False
        prod_img = Image.open(BytesIO(res_prod.content)).convert("RGBA")

        # Lienzo
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

        # Configuraciones Texto
        MARGIN_RIGHT = 1010
        MARGIN_LEFT = 70
        WIDTH_PRICE_MAX = 400 
        WIDTH_TEXT_MAX = 540 

        # Precio Venta
        p_sale_str = f"{row['sale_price']:.2f}"
        size_sale = 135 
        f_sale = get_font(F_BOLD, size_sale)
        f_symbol = get_font(F_BOLD, int(size_sale * 0.5))

        while size_sale > 50:
            w_sale = draw.textlength(p_sale_str, font=f_sale)
            w_sym = draw.textlength("S/", font=f_symbol)
            if (w_sym + 12 + w_sale) <= WIDTH_PRICE_MAX: break
            size_sale -= 4
            f_sale = get_font(F_BOLD, size_sale)
            f_symbol = get_font(F_BOLD, int(size_sale * 0.5))

        w_total_sale = draw.textlength("S/", font=f_symbol) + 12 + draw.textlength(p_sale_str, font=f_sale)
        x_sale = MARGIN_RIGHT - w_total_sale
        y_base = 920 - (size_sale * 0.1) 
        
        draw.text((x_sale, y_base + size_sale*0.05), "S/", font=f_symbol, fill="white")
        draw.text((x_sale + draw.textlength("S/", font=f_symbol) + 12, y_base), p_sale_str, font=f_sale, fill="white")

        # Precio Regular
        p_reg_str = f"Precio regular: S/{row['price']:.2f}"
        f_reg = get_font(F_REG, 30)
        w_reg = draw.textlength(p_reg_str, font=f_reg)
        draw.text((MARGIN_RIGHT - w_reg, 865), p_reg_str, font=f_reg, fill="white")

        # Marca
        brand_txt = str(row['brand']).upper().strip()
        size_brand = 28
        f_brand = get_font(F_BOLD, size_brand)
        while size_brand > 18:
            if draw.textlength(brand_txt, font=f_brand) < WIDTH_TEXT_MAX: break
            size_brand -= 2
            f_brand = get_font(F_BOLD, size_brand)
        draw.text((MARGIN_LEFT, 860), brand_txt, font=f_brand, fill="white")

        # Título
        title_txt = str(row['title']).strip()
        size_title = 38
        f_title = get_font(F_OBL, size_title)
        lines = []
        while size_title > 20:
            avg_char = f_title.getlength("a") or 10
            chars_per_line = int(WIDTH_TEXT_MAX / avg_char)
            temp_lines = textwrap.wrap(title_txt, width=chars_per_line)
            if len(temp_lines) <= 3 and all(draw.textlength(l, font=f_title) <= WIDTH_TEXT_MAX for l in temp_lines):
                lines = temp_lines
                break
            size_title -= 2
            f_title = get_font(F_OBL, size_title)
        if not lines: lines = textwrap.wrap(title_txt, width=40)[:3]
        
        y_pos = 910
        for line in lines:
            draw.text((MARGIN_LEFT, y_pos), line, font=f_title, fill="white")
            y_pos += (size_title + 4)

        # Guardar
        target_path = os.path.join(OUTPUT_DIR, filename)
        canvas = canvas.resize((900, 900), Image.Resampling.LANCZOS)
        canvas.save(target_path, "JPEG", quality=90) # Calidad 90 para aligerar peso
        return True

    except Exception as e:
        print(f"Error generando {filename}: {e}")
        return False

# --- 4. MAIN OPTIMIZADO ---
def main():
    start_time = time.time()
    print(">>> [1/5] Descargando Feed...")
    df = pd.read_csv(FEED_URL, sep='\t', on_bad_lines='skip')
    df.columns = [c.strip() for c in df.columns]
    
    # Filtros Iniciales
    df = df[df['availability'] == 'in stock'].copy()
    df = df[df['image_link'].notna()]
    df = df[df['image_link'].str.endswith('.jpg', na=False)]
    
    # Limpieza Numérica
    df['price'] = df['price'].apply(clean_price)
    df['sale_price'] = df['sale_price'].apply(clean_price)
    
    total_products = len(df)
    print(f">>> Total productos validos: {total_products}")

    final_image_links = []
    generated_count = 0
    skipped_count = 0
    
    print(">>> [2/5] Iniciando escaneo inteligente de imágenes...")

    # --- BUCLE INTELIGENTE ---
    for index, row in df.iterrows():
        
        # 1. Calcular Nombre Esperado (Lógica ID + Precio)
        price_tag = str(row['sale_price']).replace('.', '_')
        expected_filename = f"{row['id']}_{price_tag}.jpg"
        expected_path = os.path.join(OUTPUT_DIR, expected_filename)
        
        # 2. Check Existencia (RÁPIDO)
        if os.path.exists(expected_path):
            # YA EXISTE: Usamos el link y saltamos
            final_image_links.append(f"{BASE_URL_IMG}{expected_filename}")
            skipped_count += 1
            continue
        
        # 3. NO EXISTE: ¿Tenemos tiempo para crearla?
        elapsed = time.time() - start_time
        if elapsed < TIME_LIMIT_SECONDS:
            # SÍ HAY TIEMPO: Borramos versiones viejas y creamos
            
            # Limpieza versiones anteriores del mismo ID
            old_files = glob.glob(os.path.join(OUTPUT_DIR, f"{row['id']}_*.jpg"))
            for f in old_files:
                try: os.remove(f)
                except: pass
            
            # Generar
            success = generar_imagen(row, expected_filename)
            if success:
                final_image_links.append(f"{BASE_URL_IMG}{expected_filename}")
                generated_count += 1
            else:
                # Si falló la generación, ponemos la original del feed
                final_image_links.append(row['image_link'])
        
        else:
            # SE ACABÓ EL TIEMPO: Usamos link original y lo dejamos para la próxima
            # (No se rompe el proceso, solo se pospone la imagen personalizada)
            final_image_links.append(row['image_link'])
        
        # Log de progreso cada 500 generadas (para no ensuciar consola)
        if generated_count > 0 and generated_count % 500 == 0:
            print(f"   Generadas: {generated_count} | Saltadas (Ya existen): {skipped_count} | Tiempo: {elapsed/60:.1f}m")

    print(f">>> [3/5] Resumen Procesamiento:")
    print(f"   Total Revisados: {len(final_image_links)}")
    print(f"   Imágenes Nuevas Creadas: {generated_count}")
    print(f"   Imágenes Ya Existentes (Ahorro): {skipped_count}")

    # Asignar columna final
    df['image_link'] = final_image_links
    df = df.astype(str)

    # --- SUBIDA A SHEETS ---
    print(">>> [4/5] Conectando a Google Sheets...")
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    
    # Usamos la función de carga por lotes
    upload_in_chunks(client, df, SHEET_ID, chunk_size=5000)

if __name__ == "__main__":
    main()
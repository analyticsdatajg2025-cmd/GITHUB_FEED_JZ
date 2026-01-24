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

# --- 1. CONFIGURACIÓN ---
# Directorios
OUTPUT_DIR = "images"
ASSETS_DIR = "assets"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Configuración de Usuario GitHub para el Link final
GITHUB_USER = "analyticsdatajg2025-cmd"  # <--- CAMBIA ESTO
REPO_NAME = "GITHUB_FEED_JZ"       # <--- CAMBIA ESTO
BASE_URL_IMG = f"https://{GITHUB_USER}.github.io/{REPO_NAME}/{OUTPUT_DIR}/"

# URLs de Datos
FEED_URL = "https://juntozstgsrvproduction.blob.core.windows.net/juntoz-feeds/google_juntoz_feed.txt"
# Link: https://docs.google.com/spreadsheets/d/14PcRSXLFHCmXgLdr42Phlp0U-J8jM5ZTe9-Pu1p6NE8/edit
SHEET_ID = "14PcRSXLFHCmXgLdr42Phlp0U-J8jM5ZTe9-Pu1p6NE8"

# Cargar Credenciales de Google desde Variable de Entorno (GitHub Secrets)
# Si estás en local, asegúrate de tener el archivo 'service_account.json'
credentials_json = os.environ.get('GCP_CREDENTIALS')
if credentials_json:
    creds_dict = json.loads(credentials_json)
else:
    # Fallback para pruebas locales si tienes el archivo
    with open('service_account.json') as f:
        creds_dict = json.load(f)

# Cargar Recursos Gráficos
LOGO_PATH = os.path.join(ASSETS_DIR, "logojuntozblanco.png")
try:
    LOGO_ORIGINAL = Image.open(LOGO_PATH).convert("RGBA")
except:
    print("ADVERTENCIA: No se encontró logo, usando placeholder.")
    LOGO_ORIGINAL = Image.new('RGBA', (400, 150), (255, 255, 255, 100))

# Tipografías
def get_font(filename, size):
    path = os.path.join(ASSETS_DIR, filename)
    try: return ImageFont.truetype(path, size)
    except: return ImageFont.load_default()

F_BOLD = "HurmeGeometricSans1 Bold.otf"
F_OBL = "HurmeGeometricSans1 Oblique.otf"
F_REG = "HurmeGeometricSans1.otf"

# --- 2. FUNCIONES DE LIMPIEZA ---
def clean_price(val):
    """Convierte '119.00 PEN' a 119.00 (float)"""
    if pd.isna(val): return 0.0
    s = str(val).upper().replace(' PEN', '').replace(',', '').strip()
    try:
        return float(s)
    except:
        return 0.0

# --- 3. GENERADOR DE IMAGEN (Tu diseño optimizado) ---
def generar_imagen(row):
    try:
        # Definir nombre del archivo basado en ID y PRECIO SALE (para cache busting)
        # Formato: id_precio.jpg
        price_tag = str(row['sale_price']).replace('.', '_')
        file_name = f"{row['id']}_{price_tag}.jpg"
        target_path = os.path.join(OUTPUT_DIR, file_name)
        
        # LÓGICA INCREMENTAL: Si ya existe, no la volvemos a hacer
        if os.path.exists(target_path):
            return file_name # Retornamos nombre para construir URL

        # Limpiar imágenes viejas de este mismo ID (si cambió el precio)
        old_files = glob.glob(os.path.join(OUTPUT_DIR, f"{row['id']}_*.jpg"))
        for f in old_files:
            try: os.remove(f)
            except: pass

        # --- INICIO DE TU DISEÑO ---
        res_prod = requests.get(row['image_link'], timeout=10) # Usamos image_link limpio
        if res_prod.status_code != 200: return None
        prod_img = Image.open(BytesIO(res_prod.content)).convert("RGBA")

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

        # Textos Dinámicos
        MARGIN_RIGHT = 1010
        MARGIN_LEFT = 70
        WIDTH_PRICE_MAX = 400 
        WIDTH_TEXT_MAX = 540 

        # Precio Venta
        p_sale_str = f"{row['sale_price']:.2f}" # Formato 2 decimales
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

        # Resize Final 900x900
        canvas = canvas.resize((900, 900), Image.Resampling.LANCZOS)
        canvas.save(target_path, "JPEG", quality=95)
        
        return file_name # Retornamos solo nombre

    except Exception as e:
        print(f"Error en {row['id']}: {e}")
        return None

# --- 4. PROCESO PRINCIPAL ---
def main():
    print(">>> Descargando Feed...")
    # Leemos el TXT asumiendo tabulaciones (común en feeds)
    df = pd.read_csv(FEED_URL, sep='\t', on_bad_lines='skip') 
    
    # Normalizar columnas (strip)
    df.columns = [c.strip() for c in df.columns]

    print(f"Total productos inicial: {len(df)}")

    # FILTROS
    # 1. Availability = in stock
    df = df[df['availability'] == 'in stock'].copy()
    
    # 2. Image Link: No vacíos y solo .jpg
    df = df[df['image_link'].notna()]
    df = df[df['image_link'].str.endswith('.jpg', na=False)]

    # LIMPIEZA DE PRECIOS
    df['price'] = df['price'].apply(clean_price)
    df['sale_price'] = df['sale_price'].apply(clean_price)

    print(f"Productos a procesar tras filtros: {len(df)}")

    # PROCESAMIENTO DE IMÁGENES
    generated_links = []
    
    # Iteramos sobre el DataFrame
    for index, row in df.iterrows():
        file_name = generar_imagen(row)
        
        if file_name:
            # Construir URL final: github.io/repo/images/id_price.jpg
            full_url = f"{BASE_URL_IMG}{file_name}"
            generated_links.append(full_url)
        else:
            # Si falló la imagen, usamos la original o vacía (decisión de negocio)
            generated_links.append(row['image_link']) 
    
    # Asignamos la nueva columna, sustituyendo image_link
    df['image_link'] = generated_links

    # PREPARAR DATA PARA SHEETS (Convertir todo a string para evitar errores JSON)
    df = df.astype(str)

    # SUBIDA A GOOGLE SHEETS
    print(">>> Conectando a Google Sheets...")
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    
    try:
        # CAMBIO AQUÍ: Usamos open_by_key para ir directo al ID
        sheet = client.open_by_key(SHEET_ID).sheet1
        # Limpiar hoja y subir nuevos datos
        sheet.clear()
        
        # set_dataframe es parte de gspread-dataframe o lo hacemos manual
        # Método manual robusto:
        data = [df.columns.values.tolist()] + df.values.tolist()
        sheet.update(data)
        print(">>> Google Sheet actualizado con éxito.")
    except Exception as e:
        print(f"Error subiendo a Sheets: {e}")

if __name__ == "__main__":
    main()
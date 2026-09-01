import os
from pathlib import Path
import pandas as pd
from langdetect import detect, LangDetectException
import re
from collections import Counter
from wordcloud import WordCloud
import nltk
from io import BytesIO
import base64
from nltk.util import ngrams
import unidecode

CSV_LANG_TO_CODE = {"português":"pt", "français":"fr",
    "castellano": "es", "spanish": "es", "es": "es", "español": "es", "español": "es",
    "ingles": "en", "english": "en", "en": "en", "inglés": "en",
    "frances": "fr", "french": "fr", "fr": "fr", "francés": "fr",
    "italiano": "it", "italian": "it", "it": "it",
    "portugues": "pt", "portuguese": "pt", "pt": "pt", "portugués": "pt",
    "catalan": "ca", "català": "ca", "ca": "ca", "catalán": "ca", "valenciano": "ca", "valencià": "ca",
    "euskera": "eu", "basque": "eu", "eu": "eu", "vasco": "eu"
}

# ==========================================
# 1. CONFIGURACIÓN NLTK Y STOPWORDS
# ==========================================
NLTK_DATA_PATH = os.path.join(os.getcwd(), "nltk_data")
os.makedirs(NLTK_DATA_PATH, exist_ok=True)
nltk.data.path.append(NLTK_DATA_PATH)

try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download("stopwords", download_dir=NLTK_DATA_PATH)

from nltk.corpus import stopwords

# Rutas a stopwords externas
ROOT_DIR = Path(__file__).resolve().parents[4]
CATALAN_STOPWORDS_DIR = ROOT_DIR / "stopwords" / "catalan"
BASQUE_STOPWORDS_DIR  = ROOT_DIR / "stopwords" / "basque"

def cargar_stopwords_externas(carpeta):
    stops = set()
    if not os.path.isdir(carpeta):
        return stops
    for fname in os.listdir(carpeta):
        if fname.endswith(".txt"):
            with open(os.path.join(carpeta, fname), "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip(): stops.add(line.strip().lower())
    return stops

# Diccionario maestro de Stopwords
STOPWORDS_DICT = {
    "es": set(stopwords.words("spanish")),
    "en": set(stopwords.words("english")),
    "fr": set(stopwords.words("french")),
    "it": set(stopwords.words("italian")),
    "pt": set(stopwords.words("portuguese")),
    "ca": cargar_stopwords_externas(CATALAN_STOPWORDS_DIR),
    "eu": cargar_stopwords_externas(BASQUE_STOPWORDS_DIR)
}

# Mapeo de lo que viene en el CSV -> Código interno


# ==========================================
# 2. FUNCIONES DE PROCESAMIENTO
# ==========================================
def limpiar_texto(texto):
    if not isinstance(texto, str): return ""
    texto = texto.lower()
    texto = re.sub(r"http\S+|www\S+", "", texto) # Quitar URLs
    # Mantener letras, tildes y ñ. Quitar el resto.
    texto = unidecode.unidecode(texto) 
    texto = re.sub(r"[^a-z\s]", "", texto) # Ahora solo quedan letras a-z
    return texto.strip()
    return texto.strip()

def obtener_codigo_idioma_csv(valor_celda):
    """
    Obtiene el código teórico según la columna del CSV.
    """
    if not valor_celda or pd.isna(valor_celda):
        return "es" # Default
    
    val_str = str(valor_celda).lower().replace("'", "").replace("[", "").replace("]", "")
    primer_idioma = val_str.split(",")[0].strip()
    
    return CSV_LANG_TO_CODE.get(primer_idioma, "es")


def obtener_stopwords_proyecto(df, lang_code):
    """
    Genera una lista de stopwords que incluye las del idioma
    MÁS las palabras que el usuario usó para buscar (keywords).
    """
    stops = set(STOPWORDS_DICT.get(lang_code, STOPWORDS_DICT["es"]))
    
    # 1. Añadir ruido común de redes sociales en español
    ruido_social = {
        "si", "no", "así", "hacer", "ver", "ir", "tan", "cada", "bien", 
        "aquí", "ahora", "solo", "ser", "esta", "esto", "este", "hace",
        "pueden", "puede", "donde", "comentario", "video", "youtube", 
        "twitter", "bluesky", "reddit", "hola", "gracias", "saludos",
        "bueno", "mismo", "toda", "todo", "pero", "para", "con", "por"
    }
    stops.update(ruido_social)

    # 2. EXTRAER KEYWORDS DEL PROYECTO
    # Si la columna KEYWORD existe, sacamos las palabras que la componen
    if "KEYWORD" in df.columns:
        kw_series = df["KEYWORD"].dropna().unique()
        for kw_item in kw_series:
            # Limpiamos la keyword (ej: "regularización de inmigrantes" -> ["regularizacion", "inmigrantes"])
            palabras_kw = limpiar_texto(str(kw_item)).split()
            stops.update(palabras_kw)
            
    return stops
def procesar_datos_para_nube(df_subset):
    word_counts = Counter()
    word_sentiments = {}

    # Pre-calculamos las stopwords del proyecto (usando el idioma principal del subset)
    # Para mayor precisión, podrías hacerlo por idioma, pero esto suele bastar.
    cache_stops = {}
    for _, row in df_subset.iterrows():
        contenido_raw = str(row.get("CONTENIDO", ""))
        if len(contenido_raw) < 10: continue 

        texto_limpio = limpiar_texto(contenido_raw)
        if not texto_limpio: continue
        
        score = pd.to_numeric(row.get("SENTIMIENTO", 0), errors='coerce')
        if pd.isna(score): score = 0

        idioma_ia_raw = row.get("IDIOMA_IA").lower().strip()

        # Buscamos el código (es, ca, en...) en tu diccionario
        lang_code = CSV_LANG_TO_CODE.get(idioma_ia_raw)
        # Obtenemos las stopwords específicas para ESE comentario
        if lang_code not in cache_stops:
            cache_stops[lang_code] = obtener_stopwords_proyecto(df_subset, lang_code)
        
        stops = cache_stops[lang_code]


        # Tokenizar y filtrar con las nuevas stopwords
        tokens = [t for t in texto_limpio.split() if len(t) > 3 and t not in stops]
        
        # Solo procesamos si quedan palabras interesantes
        if not tokens: continue

        for t in tokens:
            word_counts[t] += 1
            if t not in word_sentiments:
                word_sentiments[t] = []
            word_sentiments[t].append(score)

        # 2. Procesar Bigramas (Frases de 2 palabras) - PESO 4
        # Les damos peso 4 para que compitan con las palabras sueltas
        if len(tokens) >= 2:
            for ng in ngrams(tokens, 2):
                frase = " ".join(ng)
                word_counts[frase] += 4  # <--- EL BOOST
                
                if frase not in word_sentiments:
                    word_sentiments[frase] = []
                # Añadimos el score 4 veces para que el peso sea consistente con el conteo
                for _ in range(4):
                    word_sentiments[frase].append(score)

    # --- FILTRADO DE CALIDAD ---
    # Mínimo 3 apariciones para que una palabra/frase sea digna de la nube
    min_apariciones = 3 if len(df_subset) > 20 else 2
    final_counts = {k: v for k, v in word_counts.items() if v >= min_apariciones}
    
    if not final_counts: 
        final_counts = word_counts

    # Calcular sentimiento promedio final
    final_sentiments = {}
    for w, scores in word_sentiments.items():
        if w in final_counts:
            final_sentiments[w] = sum(scores) / len(scores)

    return final_counts, final_sentiments

# ==========================================
# 3. GENERACIÓN DE IMAGEN
# ==========================================
def generar_imagen_base64(counts, sentiments):
    if not counts:
        return None

    # Función de color basada en sentimiento
    def color_func(word, font_size, position, orientation, random_state=None, **kwargs):
        score = sentiments.get(word, 0)
        if score > 0.05:
            return "rgb(20, 160, 20)"   # Verde (Positivo)
        elif score < -0.05:
            return "rgb(220, 20, 20)"   # Rojo (Negativo)
        else:
            return "rgb(80, 80, 80)"    # Gris oscuro (Neutro)

    try:
        wc = WordCloud(
            width=1000,
            height=500,
            background_color="white",
            max_words=100,
            color_func=color_func,
            collocations=False # Ya calculamos n-gramas manualmente
        ).generate_from_frequencies(counts)

        buffer = BytesIO()
        wc.to_image().save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")
    except Exception as e:
        print(f"Error generando imagen WC: {e}")
        return None

# ==========================================
# 4. FUNCIÓN PRINCIPAL (ENTRY POINT)
# ==========================================
def generar_nubes_dashboard(csv_path, target_languages=None):
    """
    Genera un diccionario con todas las nubes necesarias en Base64.
    """
    resultados = {}
    allowed_codes = []
    if target_languages:
        allowed_codes = [CSV_LANG_TO_CODE.get(l.lower()) for l in target_languages if CSV_LANG_TO_CODE.get(l.lower())]
    
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
                sep = ';' if ';' in f.readline() else ','
        df = pd.read_csv(csv_path, sep=sep, encoding="utf-8", engine='python')
        
        # Normalizar columnas a mayúsculas
        df.columns = [c.upper() for c in df.columns] 
        
        if "CONTENIDO" not in df.columns:
            return {}
        
        if "SENTIMIENTO" in df.columns:
            df = df[df["SENTIMIENTO"].astype(str) != "2"]

        if "IDIOMA_IA" in df.columns and allowed_codes:
            # Mapeamos la columna IDIOMA_IA a códigos de 2 letras y filtramos
            df["LANG_CODE_TMP"] = df["IDIOMA_IA"].str.lower().str.strip().map(CSV_LANG_TO_CODE)
            df = df[df["LANG_CODE_TMP"].isin(allowed_codes)]    

        # 1. NUBE GLOBAL
        counts, sents = procesar_datos_para_nube(df)
        resultados["nube_global"] = generar_imagen_base64(counts, sents)

        # 2. POR RED SOCIAL
        if "FUENTE" in df.columns:
            for red in df["FUENTE"].dropna().unique():
                df_red = df[df["FUENTE"] == red]
                c, s = procesar_datos_para_nube(df_red)
                red_clean = str(red).lower().replace(" ", "")
                resultados[f"nube_{red_clean}"] = generar_imagen_base64(c, s)

        # 3. POR IDIOMA (Usando la columna del CSV para agrupar, pero detectando dentro)
        if "IDIOMA_IA" in df.columns and allowed_codes:
            # Mapeamos la columna IDIOMA_IA a códigos de 2 letras y filtramos
            df["LANG_CODE_TMP"] = df["IDIOMA_IA"].str.lower().map(CSV_LANG_TO_CODE)
            for code in df["LANG_CODE_TMP"].dropna().unique():
                df_lang = df[df["LANG_CODE_TMP"] == code]
                if not df_lang.empty:
                    c, s = procesar_datos_para_nube(df_lang)
                    # Guardamos con el código: nube_es, nube_ca, nube_en...
                    resultados[f"nube_{code}"] = generar_imagen_base64(c, s)

    except Exception as e:
        print(f"❌ Error en motor de nubes: {e}")
        import traceback
        traceback.print_exc()
    
    return resultados


if __name__ == "__main__":
    # Prueba rápida
    # vamos a recorer todas las carpetas de los directorios /home/rrss/proyecto_web/RRSS_version_stance/project_web/Web_Proyecto/datos/*/datos_sentimiento_filtrados.csv 
    for root, dirs, files in os.walk(r"/home/rrss/proyecto_web/RRSS_version_stance/project_web/Web_Proyecto/datos/"):
        for file in files:
            if file.endswith("datos_sentimiento_filtrados.csv"):
                csv_path = os.path.join(root, file)
                print(f"Procesando: {csv_path}")
                nubes = generar_nubes_dashboard(csv_path)
                # Guardar imágenes en disco (PNG)
                for nombre, b64_str in nubes.items():
                    if b64_str:
                        # guardarla en la misma carpeta del CSV con el mismo nombre pero extensión .png
                        # si ya existe, lo sobreescribe
                        with open(os.path.join(root, f"{nombre}.png"), "wb") as f:
                            f.write(base64.b64decode(b64_str))

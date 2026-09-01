import pandas as pd
import unidecode
import numpy as np
from pathlib import Path
#import clean_project.config.settings as config
import json
import hashlib
from datetime import datetime
from openpyxl.utils import get_column_letter

# ==============================================================================
# HELPER: PREPARAR TEXTO
# ==============================================================================
def preparar_texto_unificado(row, red):
    """
    Devuelve TITULO, CUERPO y CONTENIDO separados según la red.
    """
    # TITULO y CUERPO según la red
    if red == "reddit":
        titulo = str(row.get("post_title", "")).strip()
        cuerpo = str(row.get("post_selftext", "")).strip()
    elif red == "youtube":
        titulo = str(row.get("titulo_video", "")).strip()
        cuerpo = str(row.get("descripcion_video", "")).strip()
    elif red == "twitter":
        titulo = str(row.get("BeforeContenido", "")).strip()
        cuerpo = ""
    elif red == "telegram":
        titulo = str(row.get("canal", "")).strip()
        cuerpo = ""    
    else:  # TikTok, LinkedIn, BlueSky
        titulo = ""
        cuerpo = ""

    # Limpieza de strings "nan"
    if titulo.lower() == "nan": titulo = ""
    if cuerpo.lower() == "nan": cuerpo = ""

    contenido = str(row.get("contenido", "")).strip()
    if contenido.lower() == "nan": contenido = ""

    keyword = str(row.get("search_keyword", "")).strip()
    language = str(row.get("keyword_languages", "")).strip()

    return titulo, cuerpo, contenido, keyword, language

# ==============================================================================
# 1. FUNCIÓN DE ESTANDARIZACIÓN (Excel y JSON)
# ==============================================================================
def estandarizar_para_excel_simple(df, red):
    """
    Transforma el DF de cualquier red al formato estándar.
    CRUCIAL: Filtra automáticamente filas con sentimiento 2 (irrelevantes).
    """
    nuevo_df = pd.DataFrame()

    # --- 1. ID ANONIMIZADO ---
    col_user = 'usuario_comentario' if red == 'youtube' else 'usuario'
    if col_user in df.columns:
        nuevo_df['ID'] = df[col_user].astype(str).fillna('unknown').apply(
            lambda x: hashlib.sha256(x.encode()).hexdigest()[:16].upper()
        )
    else:
        nuevo_df['ID'] = 'UNKNOWN'

    # --- 2. FECHA y HRS ---
    col_date = 'fecha_comentario' if red == 'youtube' else 'fecha'
    fechas_list, horas_list = [], []
    
    if col_date in df.columns:
        raw_dates = df[col_date].astype(str)

        # Limpieza universal
        if raw_dates.dtype == "object":
            raw_dates = (
                raw_dates
                    .str.replace("·", "", regex=False)
                    .str.replace("UTC", "", regex=False)
                    .str.strip()
            )

        print("Ejemplos de fechas crudas:")
        print(raw_dates.head(10))
        sample = raw_dates.dropna().iloc[0]

        if "T" in sample and "-" in sample:
            fechas_dt = pd.to_datetime(raw_dates, format="ISO8601", errors="coerce", utc=True)
        elif "," in sample and "AM" in sample or "PM" in sample:
            raw_dates = raw_dates.str.replace(r"\s{2,}", " ", regex=True).str.strip()
            fechas_dt = pd.to_datetime(raw_dates, format="%b %d, %Y %I:%M %p", errors="coerce")
        else:
            fechas_dt = pd.to_datetime(raw_dates, errors="coerce")
        
        for val_raw, dt_obj in zip(raw_dates, fechas_dt):
            if pd.notna(dt_obj):
                fechas_list.append(dt_obj.strftime('%Y-%m-%d'))
                horas_list.append(dt_obj.strftime('%H:%M'))
            else:
                # Fallback manual si falla pandas
                parts = val_raw.split(' ')
                fechas_list.append(parts[0] if len(parts) > 0 else "")
                horas_list.append(parts[1] if len(parts) > 1 else "00:00")
    else:
        fechas_list = [""] * len(df)
        horas_list = ["00:00"] * len(df)

    nuevo_df['FECHA'] = fechas_list
    nuevo_df['HRS'] = horas_list

    # --- 3. TEXTO: TITULO, CUERPO, CONTENIDO ---
    # Usamos listas para mayor velocidad que .loc en bucle
    titulos, cuerpos, contenidos, keywords, languages = [], [], [], [], []
    n_likes, n_comments, n_shares, n_followers = [], [], [], []

    for _, row in df.iterrows():
        t, c, cont, k, l = preparar_texto_unificado(row, red)
        titulos.append(t)
        cuerpos.append(c)
        contenidos.append(cont)
        keywords.append(k)
        languages.append(l)


        likes, comms, shares, folls = preparar_metricas_unificado(row, red)
        n_likes.append(likes)
        n_comments.append(comms)
        n_shares.append(shares)
        n_followers.append(folls)

    nuevo_df['TITULO'] = titulos
    nuevo_df['CUERPO'] = cuerpos
    nuevo_df['CONTENIDO'] = contenidos
    nuevo_df['KEYWORD'] = keywords
    nuevo_df['LANGUAGE'] = languages

    # Asignar métricas al DF
    nuevo_df['LIKES'] = n_likes
    nuevo_df['COMMENTS'] = n_comments
    nuevo_df['SHARES'] = n_shares
    nuevo_df['FOLLOWERS'] = n_followers

    # --- 4. FUENTE / RED SOCIAL ---
    def normalizar_red(r):
        r = str(r).lower()
        if 'twitter' in r or 'x' in r: return 'X (Twitter)'
        if 'youtube' in r: return 'Youtube'
        if 'linkedin' in r: return 'Linkedin'
        if 'tiktok' in r: return 'TikTok'
        if 'reddit' in r: return 'Reddit'
        if 'bluesky' in r: return 'BlueSky'
        if 'telegram' in r: return 'Telegram'
        return r.capitalize()
    
    nuevo_df['FUENTE'] = normalizar_red(red)

    # --- 5. SENTIMIENTO (Lógica de filtrado) ---
    posibles_s = ['sentimiento_1', 'Sentimiento', 'sentimiento', 'SENTIMIENTO', 'score', 'sentiment']
    col_s = next((c for c in df.columns if c in posibles_s or c.lower() in posibles_s), None)
    
    if col_s:
        # Convertir a numérico, forzar errores a 2 (neutro/descartado)
        nuevo_df['SENTIMIENTO'] = pd.to_numeric(df[col_s], errors='coerce').fillna(2)
    else:
        nuevo_df['SENTIMIENTO'] = 2

    # --- 6. TOPIC ---
    posibles_t = ['topic', 'Topic', 'TOPIC', 'topics', 'Topics', 'TOPICS']

    col_t = next((c for c in df.columns if c in posibles_t or c.lower() in posibles_t), None)

    if col_t:
        nuevo_df['TOPIC'] = df[col_t].astype(str).fillna("").str.strip()
    else:
        nuevo_df['TOPIC'] = ""

    if "IDIOMA_IA" in df.columns:
        nuevo_df['IDIOMA_IA'] = df['IDIOMA_IA'].fillna("Desconocido")
    else:
        nuevo_df['IDIOMA_IA'] = "Desconocido"
    # 🚩 FILTRADO CRÍTICO: Eliminar filas con sentimiento 2
    # Esto asegura que ni el Excel, ni las gráficas, ni el buscador tengan basura.
    nuevo_df = nuevo_df[nuevo_df['SENTIMIENTO'] != 2].copy()

    return nuevo_df


# ==============================================================================
# 2. PREPARAR MÉTRICAS
# ==============================================================================
def preparar_metricas_unificado(row, red):
    """
    Extrae y unifica métricas: LIKES, COMMENTS, SHARES, VIEWS, FOLLOWERS.
    Convierte a entero (0 si falla).
    """
    def to_int(val):
        if val is None or val == "":
            return np.nan
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return np.nan

    likes = np.nan
    comments = np.nan
    shares = np.nan
    # views = np.nan
    followers = np.nan

    if red == "reddit":
        # Reddit: hearts/Likes vienen del score.
        # Priorizamos 'hearts' si existe, sino 'Likes', sino 'score'.
        # Nota: En el CSV ya debe venir el valor correcto (post o comentario) 
        likes = to_int(row.get("hearts")) #post.score, o comentario.score dependiendo si es post o comentario
        # comments = to_int(row.get("comments"))  # post.num_comments 
        
        
    elif red == "youtube":
        # Youtube: likes_comentario es la interacción directa.
        # numero_respuestas_al_comentario son los comments.
        # numero_visualizaciones_video son las views (contexto).
        likes = to_int(row.get("likes_comentario"))
        # comments = to_int(row.get("numero_respuestas_al_comentario"))
        #views = to_int(row.get("numero_visualizaciones_video"))
        # Opcional: Si quieres guardar likes del video en otra columna, podrías, 
        # pero para unificar usamos 'likes' para el elemento analizado (el comentario).

    elif red == "twitter":
        # Twitter: hearts, comments, retweets, plays (views), Followers
        likes = to_int(row.get("hearts"))
        comments = to_int(row.get("comments"))
        shares = to_int(row.get("retweets"))
        #views = to_int(row.get("plays"))
        followers = to_int(row.get("Followers"))

    elif red == "bluesky":
        # Bluesky: hearts, comments, retweets, quotes (sumamos quotes a shares o aparte)
        likes = to_int(row.get("hearts"))
        comments = to_int(row.get("comments"))
        shares = to_int(row.get("retweets")) # Reposts
        # Quotes podría sumarse a shares o ignorarse en la unificación simple
        followers = to_int(row.get("Followers"))

    elif red == "telegram":
        # Telegram: 'likes' siempre viene en 0 desde la API — usamos
        # 'reacciones_total' (suma de reacciones tipo 🔥😱) como proxy de
        # engagement directo. 'forwards' equivale a compartidos/reposts,
        # 'replies' ya viene corregido con el conteo real de respuestas
        # anidadas (ver telegram_scraper_with_filter.py), y 'seguidores'
        # es el número de suscriptores del canal.
        likes = to_int(row.get("reacciones_total"))
        comments = to_int(row.get("replies"))
        shares = to_int(row.get("reposts"))  # 'forwards' se escribe en la columna 'reposts' del CSV
        followers = to_int(row.get("seguidores"))    
    
    else:
        # Fallback genérico por si hay columnas con nombres estándar
        likes = to_int(row.get("hearts", row.get("Likes")))
        comments = to_int(row.get("comments"))
        shares = to_int(row.get("retweets"))
        #views = to_int(row.get("plays", row.get("views")))
        followers = to_int(row.get("Followers"))

    return likes, comments, shares, followers

# ==============================================================================
# 3. FUNCIÓN PRINCIPAL: GENERA EXCEL Y JSON (DASHBOARD)
# ==============================================================================
def generar_excel_sentimiento(all_rows, output_dir):
    """
    Recibe lista de tuplas (red, df).
    Genera reportes filtrados (sin sentimiento 2).
    """
    print("\n📊 [REPORTING] Iniciando generación de reportes...")
    
    lista_dfs = []
    
    # 1. Unificación y Limpieza
    for red, df in all_rows:
        try:
            df_std = estandarizar_para_excel_simple(df, red)
            if not df_std.empty:
                lista_dfs.append(df_std)
        except Exception as e:
            print(f"⚠️ Error procesando red {red}: {e}")

    if not lista_dfs:
        print("❌ No hay datos válidos (o todos eran irrelevantes) para generar reportes.")
        return None, None

    df_final = pd.concat(lista_dfs, ignore_index=True)
    
    # 2. Guardar EXCEL (Formato Solicitado)
    mapa_columnas = {
        'ID': 'ID', 'FECHA': 'Fecha', 'HRS': 'Hrs', 'TITULO': 'Título',
        'CUERPO': 'Cuerpo', 'CONTENIDO': 'Contenido', 'FUENTE': 'Fuente', 
        'KEYWORD': 'Keyword', 'LANGUAGE': 'Idioma', 'SENTIMIENTO': 'Sentimiento',
        'TOPIC': 'Topic',
        'LIKES': 'Likes/Hearts',
        'COMMENTS': 'Comentarios/Respuestas',
        'SHARES': 'Compartidos/Retweets',
        'FOLLOWERS': 'Seguidores'
    }
    # Aseguramos que existan las columnas antes de renombrar
    cols_existentes = [c for c in mapa_columnas.keys() if c in df_final.columns]
    df_excel = df_final[cols_existentes].rename(columns=mapa_columnas)
    
    excel_path = output_dir / "reporte_analisis.xlsx"
    df_excel.to_excel(excel_path, index=False)
    print(f"✅ Excel guardado: {excel_path.name}")

    # 3. Guardar CSV (Backup Filtrado)
    csv_path = output_dir / "datos_sentimiento_filtrados.csv"
    df_final.to_csv(csv_path, index=False, sep=';', encoding='utf-8')

    # ==========================================================================
    # 4. GENERACIÓN DE JSON PARA GRÁFICAS (DASHBOARD)
    # ==========================================================================
    print("📈 Generando datos para gráficas...")

    # A. Etiquetar Sentimiento
    def label_sentimiento(val):
        try:
            v = float(val)
            if v == 1: return "Positivo"
            if v == -1: return "Negativo"
            # El 2 ya está filtrado, pero por seguridad:
            if v == 2: return "Neutro" 
            return "Neutro" # 0 es Neutro
        except: return "Neutro"

    df_final['Sentimiento_Label'] = df_final['SENTIMIENTO'].apply(label_sentimiento)

    # B. Métricas para Gráficas
    menciones = df_final['FUENTE'].value_counts().to_dict()
    sent_por_cat = pd.crosstab(df_final['FUENTE'], df_final['Sentimiento_Label']).to_dict(orient='index')
    total_sent = df_final['Sentimiento_Label'].value_counts().to_dict()
    top_topics = (
    df_final['TOPIC']
    .value_counts()
    .head(15)
    .to_dict()
)
    # ============================================================
    # 5. PREPARAR DATOS CRUDOS PARA EL FRONTEND
    # ============================================================
    # ⚠️ CORRECCIÓN: Iteramos sobre df_final, NO sobre all_rows.
    # Así garantizamos que el buscador del frontend tenga los mismos datos limpios que las gráficas.
    
    raw_data_list = []
    
    # Convertimos a diccionario para iterar rápido
    records = df_final.to_dict(orient='records')
    
    for row in records:
        # Unimos todo el texto disponible para facilitar el Regex en JS
        texto_unificado = f"{row.get('TITULO', '')} {row.get('CUERPO', '')} {row.get('CONTENIDO', '')}"
        
        raw_data_list.append({
            "red": row.get("FUENTE", "Desconocido"),
            "sentimiento": row.get("Sentimiento_Label", "Neutro"),
            "topic": row.get("TOPIC", ""),
            "texto": texto_unificado.strip()
        })

    # Construir el JSON final
    dashboard_data = {
        "grafica_menciones": menciones,
        "grafica_barras_sentimiento": sent_por_cat,
        "grafica_gauge_total": total_sent,
        "total_menciones": len(df_final),
        "grafica_topics": top_topics,
        "raw_data": raw_data_list  # ✅ Datos limpios y filtrados
    }

    json_path = output_dir / "dashboard_data.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(dashboard_data, f, indent=2, ensure_ascii=False)
    
    print(f"✅ JSON Dashboard guardado: {json_path.name}")

    return df_final, dashboard_data

def cargar_datos_para_reporte(u_conf):
    """
    Carga todos los *_analizado.csv generados por llm_analysis
    """
    output_folder = Path(u_conf.general["output_folder"])
    archivos = list(output_folder.glob("*_analizado.csv"))

    if not archivos:
        print(f"❌ No se encontraron archivos *_analizado.csv en {output_folder}")
        return []

    all_rows = []
    for archivo in archivos:
        try:
            print(f"📂 Cargando: {archivo.name}")
            with open(archivo, 'r', encoding='utf-8', newline='') as f:
                sample = f.read(4096)
            sep = ';' if sample.count(';') >= sample.count(',') else ','
            df = pd.read_csv(archivo, sep=sep, encoding='utf-8',
                 engine='python', on_bad_lines='skip')

            red = archivo.name.split("_")[0].lower()
            all_rows.append((red, df))
        except Exception as e:
            print(f"⚠️ Error leyendo {archivo.name}: {e}")

    return all_rows


# if __name__ == "__main__":
#     from types import SimpleNamespace

#     u_conf = SimpleNamespace(
#         general={
#             "output_folder": "/home/romina/pruebas_telegram",
#         }
#     )

#     print("🧪 Probando cargar_datos_para_reporte + generar_excel_sentimiento\n")

#     all_rows = cargar_datos_para_reporte(u_conf)
#     print(f"\n📦 Datasets cargados: {[(red, len(df)) for red, df in all_rows]}")

#     if not all_rows:
#         print("⚠️ No hay datos para procesar. Verificá que exista *_analizado.csv en la carpeta.")
#     else:
#         output_folder_path = Path(u_conf.general["output_folder"])
#         df_final, dashboard_data = generar_excel_sentimiento(all_rows, output_folder_path)

#         if df_final is not None:
#             print(f"\n✅ df_final: {len(df_final)} filas tras filtrar sentimiento=2")
#             print(df_final[['FUENTE', 'SENTIMIENTO', 'TOPIC', 'LIKES', 'COMMENTS', 'SHARES', 'FOLLOWERS']].head(10))
#         else:
#             print("❌ generar_excel_sentimiento devolvió None (probablemente todo era sentimiento=2)")



'''-------------EJECUCIÓN DIRECTA DE PRUEBA-------------''' 
'''
def fun_aux():
    output_folder = Path("C:\\Users\\DATS004\\Dropbox\\14. DS4M - Social Media Research\\git\\project_web\\Web_Proyecto\\datos\\user\\martes17d (1)")
    archivos = list(output_folder.glob("*_analizado.csv"))

    if not archivos:
        print(f"❌ No se encontraron archivos *_analizado.csv en {output_folder}")
        return []

    all_rows = []
    for archivo in archivos:
        try:
            print(f"📂 Cargando: {archivo.name}")
            df = pd.read_csv(archivo)
            red = archivo.name.split("_")[0].lower()
            all_rows.append((red, df))
        except Exception as e:
            print(f"⚠️ Error leyendo {archivo.name}: {e}")

    if not all_rows:
        print("⚠️ No se pudieron cargar datos válidos.")
        return None

    # 🔹 Generar Excel y JSONs
    df_final, _ = generar_excel_sentimiento(all_rows, output_folder)

    return df_final



def combine():
    output_folder = Path("C:\\Users\\DATS004\\Dropbox\\14. DS4M - Social Media Research\\git\\project_web\\Web_Proyecto\\datos\\user\\martes17d (1)")
    path_sentimiento = output_folder / "datos_sentimiento_filtrados.csv"
    path_pilares = output_folder / "datos_con_pilares.csv"

    # --- 1. Leer CSV ---
    df_sent = pd.read_csv(path_sentimiento, sep=None, engine='python', encoding='utf-8-sig')
    df_pilares = pd.read_csv(path_pilares, sep=None, engine='python', encoding='utf-8-sig')

    # --- 2. Unificar columnas debug_* y sent_* en sent_* ---
    for col in df_pilares.columns:
        if col.startswith("debug_"):
            col_new = "sent_" + col.split("debug_")[1]  # Reemplaza debug_ por sent_
            # Si no existe la columna sent_* ya, crea y copia valores
            if col_new not in df_pilares.columns:
                df_pilares[col_new] = df_pilares[col]
    
    # Ahora solo nos quedamos con las columnas sent_* (unificadas)
    pilares_cols = [c for c in df_pilares.columns if c.startswith("sent_")]
    print("Columnas pilares unificadas:", pilares_cols)

    # --- 3. Merge por columnas clave ---
    merge_keys = ["ID", "FECHA", "SENTIMIENTO", "TOPIC"]
    if "HRS" in df_sent.columns and "HRS" in df_pilares.columns:
        merge_keys.append("HRS")

    df_combinado = df_sent.merge(
        df_pilares[merge_keys + pilares_cols],
        on=merge_keys,
        how="left"  # mantener todas las filas de df_sent
    )

    # --- 4. Guardar CSV final ---
    output_csv = output_folder / "datos_combinados.csv"
    df_combinado.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"✅ CSV combinado guardado en: {output_csv}")

    return df_combinado



if __name__ == "__main__":
    combine()
'''    
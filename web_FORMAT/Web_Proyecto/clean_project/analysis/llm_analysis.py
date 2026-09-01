import pandas as pd
import json
import re
from pathlib import Path
import ollama

# Imports de tu estructura de proyecto
from clean_project.config import settings as config
from clean_project.prompts.builder import (
    build_sentiment_prompt,
    build_acceptance_prompt
)

MODEL_NAME = "qwen2.5:1.5b" #"llama3:latest" # "gemma3:4b" # "qwen2.5:1.5b" # "qwen2.5:0.5b" # "gemma3:4b"

# Definimos las columnas fijas de los pilares
PILARES_COLS = [
    "Legitimación_sociopolítica",
    "Efectividad_percibida",
    "Justicia_y_equidad_percibida",
    "Confianza_y_legitimidad_institucional",
    "Marcos_discursivos_dominantes"
]

# -----------------------------
# Extraer JSON seguro
# -----------------------------
def extraer_json(texto: str):
    if not texto:
        return None
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", texto)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None

# -----------------------------
# Llamada al modelo
# -----------------------------
def call_llm(system_prompt, user_text, retries=3, validator=None):
    for i in range(1, retries + 1):
        try:
            response = ollama.chat(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text}
                ],
                format="json",
                options={
                    "temperature": 0.0, 
                    "num_ctx": 4096, 
                    "num_gpu": 1
                }  
            )
            raw = response.get("message", {}).get("content", "")
            data = extraer_json(raw)
            if data:
                # --- NUEVA LÓGICA DE VALIDACIÓN ---
                if validator:
                    if validator(data):
                        return data # ¡Formato correcto! Devolvemos.
                    else:
                        print(f"⚠️ Intento {i}/{retries}: JSON válido pero estructura incorrecta. Reintentando...")
                        continue # Forzamos siguiente intento del bucle
                else:
                    # Si no hay validador (ej. Pilares), devolvemos data tal cual
                    return data
                    
        except Exception as e:
            print(f"⚠️ Intento {i}/{retries} fallo técnico: {e}")
            
    return None # Si se acaban los intentos, devolvemos None

# -----------------------------
# Función de Validación de Estructura
# -----------------------------
def validar_formato_topics(data):
    """Devuelve True si data tiene la estructura correcta para Topics"""
    # 1. Debe ser un diccionario
    if not isinstance(data, dict): return False
    # 2. Debe tener la clave "Topics"
    if "Topics" not in data: return False
    # 3. "Topics" debe ser una lista
    if not isinstance(data["Topics"], list): return False
    # 4. Cada elemento de la lista debe ser un diccionario (NO un string)
    for item in data["Topics"]:
        if not isinstance(item, dict): return False
    
    return True
    
# -----------------------------
# Función Auxiliar: Prepara el texto
# -----------------------------
def preparar_texto(row):
    # 1. Obtener el contenido principal
    texto = row.get("contenido", "")
    if pd.isna(texto) or str(texto).strip() == "":
        return None
    
    # 2. INICIALIZAR LA VARIABLE (Corrección del error UnboundLocalError)
    bloque_contexto = ""
    
    # 3. Lógica para REDDIT
    if "post_title" in row:
        titulo = row.get("post_title", "")
        cuerpo = row.get("post_selftext", "")
        
        # Limpieza de nulos
        if pd.isna(titulo): titulo = ""
        if pd.isna(cuerpo): cuerpo = ""
        
        if titulo or cuerpo:
            bloque_contexto = (
                f"CONTEXTO (Hilo de Reddit):\n"
                f"TITULO DEL POST: {titulo}\n"
                f"CUERPO DEL POST: {cuerpo}\n"
            )

    # 4. Lógica para YOUTUBE
    elif "titulo_video" in row:
        titulo = row.get("titulo_video", "")
        descripcion = row.get("descripcion_video", "")
        
        # Limpieza de nulos
        if pd.isna(titulo): titulo = ""
        if pd.isna(descripcion): descripcion = ""
        
        if titulo or descripcion:
            bloque_contexto = (
                f"CONTEXTO (Video de YouTube):\n"
                f"TITULO DEL VIDEO: {titulo}\n"
                f"DESCRIPCIÓN DEL VIDEO: {descripcion}\n"
            )
    # 4.5. Lógica para TWITTER (respuesta / hilo)
    elif "BeforeContenido" in row:
        tweet_previo = row.get("BeforeContenido", "")

        # Limpieza de nulos
        if pd.isna(tweet_previo): tweet_previo = ""

        if tweet_previo.strip() != "":
            bloque_contexto = (
                f"CONTEXTO (Hilo de Twitter):\n"
                f"TWEET ANTERIOR:\n{tweet_previo}\n"
            )
        

    # 5. Retorno final (Corrección de 'texto_comentario' a 'texto')
    if bloque_contexto:
        return f"{bloque_contexto}\n-------------------\nCOMENTARIO A ANALIZAR:\n{texto}"
    else:
        return f"TEXTO A ANALIZAR:\n{texto}"

  
import csv
import random
# -----------------------------
# Programa principal
# -----------------------------
def llm_analysis(u_conf):
    print("\n=== INICIANDO ANÁLISIS LLM ===")
    data_folder = Path(u_conf.general["output_folder"])
    keywords_expandidas = u_conf.general["keywords"]

    print(f"📂 Data folder recibido: {data_folder}")
    print("📂 Existe?:", data_folder.exists())
    print("📄 Archivos CSV:", list(data_folder.glob("*.csv")))
    # if u_conf:
    #     keywords_expandidas = u_conf.general["keywords"]
    #     data_folder = Path(u_conf.general["output_folder"])
    # else:
    #     keywords_expandidas = config.general["keywords"]
    #     data_folder = Path(config.general["output_folder"])
    
    print(f"Keywords: {keywords_expandidas}")
    # sentiment_prompt_template = build_sentiment_prompt(keywords_expandidas)
    # acceptance_prompt_template = build_acceptance_prompt(keywords_expandidas)
    sentiment_prompt_template = u_conf.sentiment_prompt.get("sentiment_prompt") if u_conf else build_sentiment_prompt(keywords_expandidas)
    acceptance_prompt_template = u_conf.acceptace_prompt.get("acceptance_prompt") if u_conf else build_acceptance_prompt(keywords_expandidas)

    
    archivos_origen = list(data_folder.glob("*_global_dataset.csv"))
    print(f"Archivos encontrados para análisis LLM: {[f.name for f in archivos_origen]}")

    for archivo_input in archivos_origen:
        archivo_output = archivo_input.with_name(archivo_input.stem + "_analizado.csv")
        print(f"\n=== Procesando archivo: {archivo_input} ===")
        # ---------------------------------------------------------
        # CARGA DEL DATAFRAME
        # ---------------------------------------------------------
        df = None
        
        # 1. Intentar cargar archivo existente (Resume)
        if archivo_output.exists():
            print(f"\n📂 Reanudando archivo existente: {archivo_output.name}")
            try:
                with open(archivo_output, 'r', encoding='utf-8') as f:
                    sep = ';' if ';' in f.readline() else ','
                df = pd.read_csv(archivo_output, sep=sep, encoding="utf-8", engine='python')
            except Exception as e:
                print(f"Error leyendo existente: {e}. Se leerá el original.")
        
        # 2. Si no existe o falló, cargar original
        if df is None:
            print(f"\n🆕 Iniciando análisis desde cero: {archivo_input.name}")
            try:
                with open(archivo_input, 'r', encoding='utf-8') as f:
                    sep = ';' if ';' in f.readline() else ','
                df = pd.read_csv(archivo_input, sep=sep, encoding="utf-8", engine='python')
            except Exception as e:
                print(f"❌ Error fatal leyendo original: {e}")
                continue

            # Inicializar columnas base
            for p in PILARES_COLS:
                df[f"sent_{p}"] = ""
            df["Explicacion_pilares"] = ""
            df["Explicacion_topics"] = ""
            
            # Inicializamos al menos Topic 1 para arrancar
            df["Topic_1"] = ""
            df["Sentimiento_1"] = ""

        # ---------------------------------------------------------
        # CORRECCIÓN DE TIPOS (Evita errores de int vs float vs str)
        # ---------------------------------------------------------
        # Detectamos TODAS las columnas que parecen ser de Topics o Pilares y las forzamos a Object
        cols_dinamicas = [c for c in df.columns if "Topic_" in c or "Sentimiento_" in c or "sent_" in c or "Explicacion" in c]
        for col in cols_dinamicas:
            df[col] = df[col].astype("object")

        # Asegurar contenido
        if 'contenido' not in df.columns:
             print("⚠️ Columna 'contenido' no encontrada. Saltando.")
             continue
        df["contenido"] = df["contenido"].fillna("")

        # ==============================================================================
        # 👇👇👇 MODIFICACIÓN PARA ANALIZAR SOLO LA PRIMERA LÍNEA 👇👇👇
        # ==============================================================================
        print("\n🧪 MODO PRUEBA ACTIVADO: Recortando el dataset a solo 1 fila.")
        df = df.head(1)
        # ==============================================================================
        

        total_filas = len(df)
        print(f"Total filas: {total_filas}")

        # ---------------------------------------------------------
        # BUCLE FILA A FILA
        # ---------------------------------------------------------
        rows_modified = False 
        
        for idx, row in df.iterrows():
            
            texto_completo = preparar_texto(row)
            if not texto_completo:
                continue

            # --- VERIFICACIÓN DE ESTADO ---
            tiene_pilares = pd.notna(row.get("Explicacion_pilares", "")) and str(row.get("Explicacion_pilares", "")).strip() != ""
            
            # Verificamos si tiene Topic_1 relleno O Explicación.
            # (Si tiene Topic_1 vacío pero Topic_2 lleno, esto lo capturaría la iteración, pero asumimos orden)
            tiene_topics = (
                "Topic_1" in df.columns and 
                pd.notna(row.get("Topic_1", "")) and 
                str(row.get("Topic_1", "")).strip() != ""
            ) or (
                pd.notna(row.get("Explicacion_topics", "")) and 
                str(row.get("Explicacion_topics", "")).strip() != ""
            )

            # Si está completa, saltamos
            if tiene_pilares and tiene_topics:
                continue

            print(f"--> Procesando fila {idx + 1}/{total_filas}...")
            rows_modified = True

            # --------------------------------
            # TAREA 1: PILARES
            # --------------------------------
            if not tiene_pilares:
                prompt_final = acceptance_prompt_template.replace("{text}", texto_completo)
                data_pilares = call_llm(prompt_final, texto_completo)

                if data_pilares:
                    for p in PILARES_COLS:
                        val = data_pilares.get(p, 2)
                        df.at[idx, f"sent_{p}"] = val
                    df.at[idx, "Explicacion_pilares"] = data_pilares.get("Explicacion_pilares", "")
                else:
                    print(f"⚠️ Fallo Pilares fila {idx}")

            # --------------------------------
            # TAREA 2: TOPICS (Con expansión dinámica)
            # --------------------------------
            if not tiene_topics:
                prompt_final = sentiment_prompt_template.replace("{text}", texto_completo)
                data_topics = call_llm(prompt_final, texto_completo, retries=3, validator=validar_formato_topics)

                if data_topics:
                    lista_topics = data_topics.get("Topics", [])
                    explicacion = data_topics.get("Explicacion", "")
                    
                    df.at[idx, "Explicacion_topics"] = explicacion

                    # =========================================================
                    # GESTIÓN DINÁMICA DE COLUMNAS (Expansión al vuelo)
                    # =========================================================
                    # Esto reemplaza a 'expandir_topics' pero lo hace fila por fila
                    # asegurando que si sale un Topic_5, la columna se cree YA.
                    
                    for i, item in enumerate(lista_topics):
                        num = i + 1
                        col_topic = f"Topic_{num}"
                        col_sent = f"Sentimiento_{num}"

                        # 1. Si la columna NO existe en el DF, la creamos ahora mismo
                        if col_topic not in df.columns:
                            print(f"✨ Creando nueva columna dinámica: {col_topic}")
                            df[col_topic] = "" # Crear vacía
                            df[col_topic] = df[col_topic].astype("object") # Evitar FutureWarning
                        
                        if col_sent not in df.columns:
                            print(f"✨ Creando nueva columna dinámica: {col_sent}")
                            df[col_sent] = ""
                            df[col_sent] = df[col_sent].astype("object")

                        # 2. Escribimos el valor
                        df.at[idx, col_topic] = item.get("Topic", "No relacionado")
                        df.at[idx, col_sent] = item.get("Sentimiento", 2)
                    # =========================================================

                else:
                    print(f"⚠️ Fallo Topics fila {idx}")

            # --------------------------------
            # GUARDADO INCREMENTAL
            # --------------------------------
            # Guardamos tras cada modificación para no perder nada
            try:
                df.to_csv(archivo_output, index=False, encoding="utf-8",sep=sep)
            except Exception as e:
                print(f"Error guardando CSV en fila {idx}: {e}")

        if rows_modified:
            print(f"✅ Archivo completado y actualizado: {archivo_output}")
        else:
            print(f"✅ Archivo ya estaba completo: {archivo_output}")

if __name__ == "__main__":
    llm_analysis(u_conf=None)
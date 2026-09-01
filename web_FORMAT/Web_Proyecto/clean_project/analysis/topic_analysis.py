import pandas as pd
from pathlib import Path
import ollama
from typing import List
import time

# =====================================================
# CONFIGURACIÓN GENERAL
# =====================================================
MODEL_NAME = "qwen2.5:1.5b" #"llama3:latest" # "gemma3:4b" # "qwen2.5:1.5b"
BATCH_SIZE = 8           # subir a 16 si tu GPU aguanta
MAX_RETRIES = 3
NUM_CTX = 4096  # Límite de tokens del modelo

# TEMA = "Opinión pública sobre la movilidad de los adultos mayores"
# GEO_SCOPE = ["Provincia de Valencia"]


def preparar_texto_reddit_seguro(row, num_ctx=NUM_CTX):
    """
    Construye texto seguro para LLM para Reddit:
    - Siempre incluye comentario completo.
    - Añade título y cuerpo solo si no supera NUM_CTX.
    """
    def count_tokens(texto):
        if not texto or pd.isna(texto):
            return 0
        return len(str(texto)) // 4  # Aproximación: 1 token ≈ 4 caracteres

    comentario = str(row.get("contenido", ""))
    titulo = str(row.get("post_title", ""))
    cuerpo = str(row.get("post_selftext", ""))

    tokens_com = count_tokens(comentario)
    tokens_tit = count_tokens(titulo)
    tokens_cue = count_tokens(cuerpo)

    # Siempre incluimos comentario
    texto_final = f"[COMENTARIO]\n{comentario}"
    total_tokens = tokens_com

    # Añadimos título si cabe
    if total_tokens + tokens_tit <= num_ctx and titulo.strip():
        texto_final = f"[TÍTULO]\n{titulo}\n" + texto_final
        total_tokens += tokens_tit

    # Añadimos cuerpo si cabe
    if total_tokens + tokens_cue <= num_ctx and cuerpo.strip():
        texto_final = f"[CUERPO]\n{cuerpo}\n" + texto_final
        total_tokens += tokens_cue

    return texto_final

# =====================================================
# PROMPT
# =====================================================
# system → reglas permanentes, formato obligatorio, rol
# user → variables dinámicas
def build_prompts(tema, geo_scope):
    system = (
        "Eres un clasificador automático.\n"
        "NO expliques.\n"
        "NO escribas texto adicional.\n"
        "Responde SOLO un número."
    )

    user = f"""
Tema de análisis: {tema}

Ámbito geográfico válido:
{", ".join(geo_scope)}

Definiciones importantes:
- Solo considera relacionados los textos donde se expresa claramente una opinión, valoración o experiencia sobre {tema} en {geo_scope}.
- Textos informativos, noticias, estadísticas, anuncios o enlaces → NO relacionado (2).
- Si NO habla del tema → NO relacionado (2).
- Si ocurre fuera del ámbito → NO relacionado (2).

Texto a clasificar:
\"\"\"{{texto}}\"\"\"

Reglas de salida:
1  → positivo
-1 → negativo
0  → neutral
2  → no relacionado

Devuelve SOLO uno de estos valores:
1
-1
0
2
"""
    return system, user



# =====================================================
# DETECCIÓN DE RED
# =====================================================
def detectar_red_por_archivo(path: Path) -> str:
    name = path.name.lower()

    if "reddit" in name:
        return "reddit"
    if "youtube" in name:
        return "youtube"
    if "twitter" in name or "x_" in name:
        return "twitter"
    if "bluesky" in name:
        return "bluesky"

    return "generic"


# =====================================================
# PREPARAR TEXTO
# =====================================================
def preparar_texto(row, red):
    texto = row.get("contenido", "")
    if not texto or pd.isna(texto):
        return None

    partes = []

    if red == "reddit":
        titulo = row.get("post_title", "")
        cuerpo = row.get("post_selftext", "")
        if titulo or cuerpo:
            partes.append(f"[REDDIT]\nTítulo: {titulo}\nCuerpo: {cuerpo}")

    elif red == "youtube":
        titulo = row.get("titulo_video", "")
        desc = row.get("descripcion_video", "")
        if titulo or desc:
            partes.append(f"[YOUTUBE]\nTítulo: {titulo}\nDescripción: {desc}")

    elif red == "twitter":
        previo = row.get("BeforeContenido", "")
        if previo:
            partes.append(f"[TWITTER]\nTweet previo: {previo}")

    partes.append(f"[COMENTARIO]\n{texto}")
    return "\n\n".join(partes)

# =====================================================
# LLM BATCH (ESCALAR)
# =====================================================
def call_llm_batch(textos, system_prompt, user_template):
    resultados = []

    for texto in textos:
        val = 2  # fallback seguro

        for _ in range(MAX_RETRIES):
            try:
                response = ollama.chat(
                    model=MODEL_NAME,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_template.format(texto=texto)}
                    ],
                    options={
                        "temperature": 0.0,
                        "num_ctx": 2048
                    }
                )

                raw = response["message"]["content"].strip()
                parsed = int(raw)

                if parsed in {1, 0, -1, 2}:
                    val = parsed
                break

            except Exception as e:
                continue

        resultados.append(val)

    return resultados
# =====================================================
# PIPELINE PRINCIPAL
# =====================================================
def llm_analysis(u_conf):
    data_folder = Path(u_conf.general["output_folder"])
    TEMA = u_conf.tema
    GEO_SCOPE = u_conf.geo_scope
    print(f"📂 Carpeta de datos para LLM: {data_folder}")
    print(f"🧾 Tema: {TEMA}")
    print(f"🌍 Ámbito geográfico: {GEO_SCOPE}")
    print(f"Existe la carpeta? {data_folder.exists()}")

    SYSTEM_PROMPT, USER_TEMPLATE = build_prompts(TEMA, GEO_SCOPE)

    archivos = list(data_folder.glob("*_global_dataset.csv"))
    print(f"📂 Archivos detectados: {[f.name for f in archivos]}")

    for archivo in archivos:
        print(f"\n=== Procesando {archivo.name} ===")
        start_time = time.perf_counter()
        procesados = 0
        llamadas_llm = 0
        output = archivo.with_name(archivo.stem + "_analizado.csv")

        

        # Detectar separador automáticamente
        with open(archivo, 'r', encoding='utf-8') as f:
            primera_linea = f.readline()
            sep = ';' if ';' in primera_linea else ','

        # Leer CSV con separador correcto
        df = pd.read_csv(archivo, sep=sep, encoding='utf-8', engine='python')
        red = detectar_red_por_archivo(archivo)
        print(f"🔎 Red detectada: {red}")

        if "sentimiento" not in df.columns:
            df["sentimiento"] = ""

        pendientes = []
        indices = []

        for idx, row in df.iterrows():
            if str(row["sentimiento"]).strip():
                continue    
            if red == "reddit":
                texto = preparar_texto_reddit_seguro(row, NUM_CTX)
            
            else:
                texto = preparar_texto(row, red)
            if not texto:
                df.at[idx, "sentimiento"] = 2
                continue

            pendientes.append(texto)
            indices.append(idx)
            procesados += 1

            if len(pendientes) == BATCH_SIZE:
                resultados = call_llm_batch(pendientes, SYSTEM_PROMPT, USER_TEMPLATE)
                llamadas_llm += len(pendientes)
                for i, val in zip(indices, resultados):
                    df.at[i, "sentimiento"] = val
                pendientes, indices = [], []

        # últimos restos
        if pendientes:
            resultados = call_llm_batch(pendientes, SYSTEM_PROMPT, USER_TEMPLATE)
            llamadas_llm += len(pendientes)
            for i, val in zip(indices, resultados):
                df.at[i, "sentimiento"] = val
        elapsed = time.perf_counter() - start_time

        if procesados > 0:
            eps = procesados / elapsed
        else:
            eps = 0

        print("\n📊 MÉTRICAS DE RENDIMIENTO")
        print(f"Red social        : {red}")
        print(f"Ejemplos procesados: {procesados}")
        print(f"Llamadas LLM      : {llamadas_llm}")
        print(f"Tiempo total (s)  : {elapsed:.2f}")
        print(f"Tiempo total (min)  : {elapsed/60:.2f}")
        print(f"Ejemplos / segundo: {eps:.2f}")
        df.to_csv(output, index=False, encoding="utf-8", sep=sep)
        print(f"✅ Guardado: {output.name}")

# =====================================================
# MAIN
# =====================================================


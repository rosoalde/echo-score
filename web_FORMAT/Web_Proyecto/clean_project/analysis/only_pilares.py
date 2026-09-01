# analysis/only_pilares.py

import pandas as pd
import json
import ollama
from pathlib import Path
from tqdm import tqdm

from clean_project.prompts.pilares import get_prompt

MODEL_NAME = "qwen2.5:1.5b"#"gemma3:4b"
NUM_CTX = 4096

PILARES = [
    "Legitimación_sociopolítica",
    "Efectividad_percibida",
    "Justicia_y_equidad_percibida",
    "Confianza_y_legitimidad_institucional",
    "Marcos_discursivos_dominantes"
]

def safe_parse_json(text):

    # DEBUG: Mostrar respuesta cruda antes de parsear
    # print("\n--- RAW RESPONSE ---")
    # print(text)

    try:
        return json.loads(text)
    except:
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            return json.loads(text[start:end])
        except Exception as e:
            print("❌ Error parseando JSON:", e)
            return None

# ======================================================
# TEXTO SEGURO CON LÍMITE DE CONTEXTO
# ======================================================

def preparar_texto_seguro(row, base_prompt):

    def count_tokens(texto):
        if not texto or pd.isna(texto):
            return 0
        return len(str(texto)) // 4

    comentario = str(row.get("CONTENIDO", "")).strip()
    titulo = str(row.get("TITULO", "")).strip()
    cuerpo = str(row.get("CUERPO", "")).strip()

    tokens_prompt = count_tokens(base_prompt)
    estructura_fija = """
    === CONTEXTO (NO ANALIZAR, SOLO PARA ENTENDER) ===

    === COMENTARIO (ANALIZAR SOLO ESTO) ===
    """

    tokens_estructura = count_tokens(estructura_fija)

    presupuesto = NUM_CTX - tokens_prompt - tokens_estructura - 200


    print(f"Presupuesto disponible: {presupuesto}")

    # 1️⃣ El comentario SIEMPRE va completo o truncado
    tokens_com = count_tokens(comentario)

    if tokens_com > presupuesto:
        comentario = comentario[:presupuesto * 4]
        print("⚠ Comentario truncado")

    texto_final = "\n\n=== CONTEXTO (NO ANALIZAR, SOLO PARA ENTENDER) ===\n"

    usados = count_tokens(comentario)

    espacio_restante = presupuesto - usados

    # 2️⃣ Añadir contexto SOLO si queda espacio
    if espacio_restante > 100:

        contexto = ""

        if titulo:
            contexto += f"[TITULO]\n{titulo}\n\n"

        if cuerpo:
            max_chars = espacio_restante * 4
            contexto += f"[CUERPO]\n{cuerpo[:max_chars]}\n"

        texto_final += contexto

    texto_final += "\n\n=== COMENTARIO (ANALIZAR SOLO ESTO) ===\n"
    texto_final += comentario

    print("Tokens finales estimados:", count_tokens(texto_final))

    return texto_final
# ======================================================
# LLAMADA LLM
# ======================================================

def call_llm_batch(prompts):

    responses = []

    for prompt in prompts:


        # DEBUG: Mostrar prompt antes de llamar al modelo    
        # print("\n" + "="*100)
        # print("PROMPT ENVIADO:")
        # print(prompt)
        # print("="*100)

        try:
            response = ollama.chat(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": prompt}],
                options={
                    "temperature": 0.0,
                    "num_ctx": NUM_CTX
                }
            )

            content = response["message"]["content"]

        except Exception as e:
            print("❌ Error llamando modelo:", e)
            content = "{}"

        responses.append(content)

    return responses


def ejecutar_pilares_analysis(u_conf, batch_size=3):
    """
    Ejecuta análisis de pilares con guardado incremental real:
    - Solo recalcula filas que tienen algún pilar vacío
    - Mantiene intactas las filas completas
    - Guarda después de cada batch
    """
    output_folder = Path(u_conf.general["output_folder"])
    dataset_path = output_folder / "datos_sentimiento_filtrados.csv"
    output_path = output_folder / "datos_con_pilares.csv"

    # --- Determinar CSV base ---
    if output_path.exists():
        print(f"📂 datos_con_pilares.csv ya existe, recalculando solo filas incompletas...")
        with open(output_path, 'r', encoding='utf-8') as f:
            primera_linea = f.readline()
            sep = ';' if ';' in primera_linea else ','
        df = pd.read_csv(output_path, sep=sep, encoding='utf-8', engine='python', on_bad_lines='skip')
    else:
        print(f"📂 Creando datos_con_pilares.csv desde {dataset_path.name}...")
        with open(dataset_path, 'r', encoding='utf-8') as f:
            primera_linea = f.readline()
            sep = ';' if ';' in primera_linea else ','
        df = pd.read_csv(dataset_path, sep=sep, encoding='utf-8', engine='python', on_bad_lines='skip')

    if df.empty:
        raise Exception("Dataset vacío")

    # --- Inicializar columnas de pilares si faltan ---
    for p in PILARES:
        col_name = f"sent_{p}"
        if col_name not in df.columns:
            df[col_name] = None

    geo_scope_val = getattr(u_conf, "geo_scope", "Global")
    base_prompt = get_prompt(u_conf.tema, u_conf.languages, geo_scope_val)

    # --- Detectar filas incompletas ---
    pillar_cols = [f"sent_{p}" for p in PILARES]
    filas_incompletas = df[df[pillar_cols].isna().any(axis=1)]
    print(f"Filas totales: {len(df)} | Filas a procesar: {len(filas_incompletas)}")

    if filas_incompletas.empty:
        print("✅ Todas las filas ya tienen pilares completos. No hay nada que recalcular.")
        return

    indices = list(filas_incompletas.index)

    # --- Procesar por batches ---
    for i in range(0, len(indices), batch_size):
        batch_indices = indices[i:i+batch_size]
        prompts = []

        print(f"\n\n########## BATCH {i//batch_size + 1} ##########")

        for idx in batch_indices:
            texto = preparar_texto_seguro(df.loc[idx], base_prompt)
            prompt = f"{base_prompt}\n\nTEXTO A ANALIZAR:\n\"\"\"\n{texto}\n\"\"\""
            prompts.append(prompt)

        responses = call_llm_batch(prompts)

        for idx_df, response in zip(batch_indices, responses):
            print(f"\nProcesando respuesta fila {idx_df}")
            data = safe_parse_json(response)
            # DEBUG: Mostrar JSON parseado
            # print("\nJSON PARSEADO:")
            # print(data)
            if not data:
                continue

            for p in PILARES:
                valor = str(data.get(p, "MISSING"))
                df.at[idx_df, f"sent_{p}"] = valor
                print(f"✔ {p} → {valor}")

        # Guardar incremental: solo sobrescribe el CSV completo, pero las filas ya completas permanecen
        df.to_csv(output_path, index=False)
        print("\n💾 Guardado incremental.")

    print("\n\n✅ FINALIZADO. Resultado en:", output_path)
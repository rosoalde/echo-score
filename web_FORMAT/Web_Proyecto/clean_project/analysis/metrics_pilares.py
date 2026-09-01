# src/clean_project/analysis/metrics.py
import pandas as pd
import unidecode
import numpy as np
from pathlib import Path
import clean_project.config.settings as config
import json
import hashlib

# ---------------------------------------------------
# PILARES PARA MÉTRICA DE ACEPTACIÓN GLOBAL
# ---------------------------------------------------
PILARES = [
    "legitimacion",
    "efectividad",
    "justicia_equidad",
    "confianza_institucional",
    "marcos_discursivos"
]

# ---------------------------------------------------
# FUNCIONES AUXILIARES
# ---------------------------------------------------
def inferir_red(nombre_archivo):
    nombre = nombre_archivo.lower()
    if "bluesky" in nombre: return "bluesky"
    if "reddit" in nombre: return "reddit"
    if "twitter" in nombre or "x_" in nombre: return "twitter"
    if "youtube" in nombre: return "youtube"
    if "linkedin" in nombre: return "linkedin"
    if "telegram" in nombre: return "telegram"
    return nombre.replace("_global_dataset", "").replace(".csv", "")

def cargar_datos(data_path):
    archivos = list(data_path.glob("*_analizado.csv"))
    
    if not archivos:
        print(f"❌ No se encontraron archivos *_analizado.csv en {data_path}")
        return []

    all_rows = []
    for archivo in archivos:
        red = inferir_red(archivo.name)
        # IMPORTANTE: Usamos coma como separador estándar
        sep = "," 
        try:
            # on_bad_lines='skip' evita que falle si hay una línea mal formada
            df = pd.read_csv(archivo, sep=sep, on_bad_lines='skip')
            
            # Verificación básica de que no esté vacío
            if df.empty:
                print(f"⚠️ El archivo {archivo.name} está vacío. Saltando.")
                continue
                
            print(f"\n📥 Cargando archivo: {archivo.name} → Red detectada: {red} | Filas: {len(df)} | Columnas: {len(df.columns)}")
            all_rows.append((red, df))
        except pd.errors.EmptyDataError:
            print(f"⚠️ El archivo {archivo.name} está vacío o corrupto (EmptyDataError). Saltando.")
        except Exception as e:
            print(f"⚠️ Error al leer {archivo.name}: {e}")
            
    return all_rows

def mapear_columnas_pilares(df):
    mapeo = {}
    columnas_normalizadas = df.columns.str.lower().map(lambda x: unidecode.unidecode(str(x)))

    variantes = {
        "legitimacion": ["sent_legitimación_sociopolítica", "sent_Legitimación_sociopolítica"],
        "efectividad": ["sent_efectividad_percibida", "sent_Efectividad_percibida"],
        "justicia_equidad": ["sent_justicia_y_equidad_percibida", "sent_Justicia_y_equidad_percibida"],
        "confianza_institucional": ["sent_confianza_y_legitimidad_institucional", "sent_Confianza_y_legitimidad_institucional"]
    }

    for pilar, posibles in variantes.items():
        for col in posibles:
            col_normalizada = unidecode.unidecode(col).lower()
            if col_normalizada in columnas_normalizadas.tolist():
                indice = columnas_normalizadas.tolist().index(col_normalizada)
                mapeo[pilar] = df.columns[indice]
                break
    return mapeo

def generar_datasets_finales(all_rows, output_dir):
    """
    Genera datasets unificados, anonimizados y divididos por relevancia.
    Incluye explicaciones del LLM.
    """
    relevantes_list = []
    descartados_list = []

    print("\n🛡️  Generando Datasets Finales con Privacidad...")

    for red, df in all_rows:
        # 1. Estandarizar columnas básicas según la red
        if red == 'youtube':
            col_user = 'usuario_comentario'
            col_date = 'fecha_comentario'
        else:
            col_user = 'usuario'
            col_date = 'fecha'
        
        col_content = 'contenido'
        
        # Si no existe la columna de contenido, no podemos hacer nada
        if col_content not in df.columns:
            continue
        
        # 2. Crear DataFrame temporal estandarizado
        temp_df = pd.DataFrame()
        temp_df['fecha'] = df[col_date] if col_date in df.columns else None
        temp_df['red_social'] = red
        
        # 3. Anonimización (Hashing de usuario)
        if col_user in df.columns:
            # Convertimos a string, rellenamos nulos y aplicamos hash SHA256 recortado
            temp_df['usuario_id_anonimo'] = df[col_user].astype(str).fillna('unknown').apply(
                lambda x: hashlib.sha256(x.encode()).hexdigest()[:16]
            )
        else:
            temp_df['usuario_id_anonimo'] = 'unknown'

        temp_df['contenido'] = df[col_content]

        # 4. Métricas de Análisis (Sentimiento, Tópico y EXPLICACIONES)
        # Buscamos columnas de forma insensible a mayúsculas/minúsculas
        col_sent = next((c for c in df.columns if c.lower() == 'sentimiento_1'), None)
        col_topic = next((c for c in df.columns if c.lower() == 'topic_1'), None)
        col_exp_pilares = next((c for c in df.columns if c.lower() == 'explicacion_pilares'), None)
        col_exp_topics = next((c for c in df.columns if c.lower() == 'explicacion_topics'), None)
        
        temp_df['sentimiento_general'] = df[col_sent] if col_sent else None
        temp_df['topico_principal'] = df[col_topic] if col_topic else None
        
        # --- NUEVO: Agregamos las explicaciones ---
        temp_df['explicacion_pilares'] = df[col_exp_pilares] if col_exp_pilares else None
        temp_df['explicacion_topics'] = df[col_exp_topics] if col_exp_topics else None

        # 5. Pilares (Mapeo dinámico)
        mapeo = mapear_columnas_pilares(df)
        
        # Inicializar flags de relevancia (filas que tienen 1 o -1 en algún pilar)
        es_relevante_red = pd.Series([False] * len(df))

        for pilar in PILARES:
            col_original = mapeo.get(pilar)
            if col_original:
                # Copiamos el valor original
                temp_df[f'score_{pilar}'] = df[col_original]
                
                # Lógica de relevancia: Convertir a numérico y buscar 1 o -1
                vals = pd.to_numeric(df[col_original], errors='coerce').fillna(2)
                es_relevante_red = es_relevante_red | vals.isin([1, -1])
            else:
                temp_df[f'score_{pilar}'] = None

        # 6. Separación
        # Aseguramos que los índices coincidan para el filtrado
        temp_df.reset_index(drop=True, inplace=True)
        es_relevante_red.reset_index(drop=True, inplace=True)

        df_rel = temp_df[es_relevante_red].copy()
        df_desc = temp_df[~es_relevante_red].copy()

        relevantes_list.append(df_rel)
        descartados_list.append(df_desc)

    # 7. Concatenación y Guardado
    if relevantes_list:
        final_relevante = pd.concat(relevantes_list, ignore_index=True)
        path_rel = output_dir / "DATASET_FINAL_RELEVANTE_ANONIMIZADO.csv"
        final_relevante.to_csv(path_rel, index=False, encoding='utf-8')
        print(f"   ✅ Dataset Relevante guardado: {len(final_relevante)} filas -> {path_rel.name}")
    
    if descartados_list:
        final_descartado = pd.concat(descartados_list, ignore_index=True)
        path_desc = output_dir / "DATASET_FINAL_DESCARTADO_ANONIMIZADO.csv"
        final_descartado.to_csv(path_desc, index=False, encoding='utf-8')
        print(f"   🗑️  Dataset Descartado guardado: {len(final_descartado)} filas -> {path_desc.name}")


def aceptacion_global_promedio_pilares(all_rows, pilares):
    aceptacion_por_pilar = {}
    total_filas = 0
    detalles_por_red = {}

    for red, df in all_rows:
        mapeo = mapear_columnas_pilares(df)
        if not mapeo:
            print(f"⚠️ No se detectaron pilares en {red}")
            detalles_por_red[red] = {"error": "No se detectaron columnas de pilares"}
            continue

        print(f"\n🔹 Procesando red: {red}")
        columnas_disponibles = list(mapeo.values())
        
        df_pilares = df[columnas_disponibles].copy()
        df_pilares = df_pilares.apply(pd.to_numeric, errors='coerce').fillna(2)

        mask_relevantes = df_pilares.isin([1, -1]).any(axis=1)
        df_pilares = df_pilares[mask_relevantes]
        n_filas = len(df_pilares)
        print(f"   Filas relevantes para cálculo: {n_filas}")
        total_filas += n_filas
        
        stats_red = {
            "filas_relevantes": n_filas,
            "conteos": {}
        }
        
        for p in pilares:
            if p in mapeo:
                vals = df_pilares[mapeo[p]]
                vals = vals[vals != 2]
                pos = (vals == 1).sum()
                neg = (vals == -1).sum()
                neu = (vals == 0).sum()
                denom = pos + neg + neu
                
                aceptacion_por_pilar.setdefault(p, []).append(float((pos - neg) / denom) if denom > 0 else np.nan)
                print(f"      Pilar {p}: positivos {pos}, negativos {neg}, neutros {neu}")
                
                stats_red["conteos"][p] = {"pos": int(pos), "neg": int(neg), "neu": int(neu)}
            else:
                stats_red["conteos"][p] = {"pos": 0, "neg": 0, "neu": 0}

        detalles_por_red[red] = stats_red    

    promedio_pilares = {}
    for p, lista in aceptacion_por_pilar.items():
        valores_validos = [v for v in lista if not pd.isna(v)]
        promedio_pilares[p] = float(np.mean(valores_validos)) if valores_validos else np.nan

    valores_validos_global = [v for v in promedio_pilares.values() if not pd.isna(v)]
    aceptacion_global = float(np.mean(valores_validos_global)) if valores_validos_global else np.nan
    aceptacion_global_norm = (aceptacion_global + 1) / 2 * 100 if not pd.isna(aceptacion_global) else np.nan

    return {
        "aceptacion_por_pilar": promedio_pilares,
        "aceptacion_global": aceptacion_global,
        "aceptacion_global_norm": aceptacion_global_norm,
        "n_publicaciones_usadas": total_filas,
        "detalles_por_red": detalles_por_red
    }

def interpretar_aceptacion(valor_norm):
    if pd.isna(valor_norm): return "Sin datos"
    if valor_norm <= 20: return "Muy baja aceptación"
    elif valor_norm <= 40: return "Baja aceptación"
    elif valor_norm <= 60: return "Aceptación media"
    elif valor_norm <= 80: return "Alta aceptación"
    else: return "Muy alta aceptación"
    
def generar_informe(resultados, all_rows, pilares):
    n_descartados = sum(df.shape[0] - df[df.isin([1,-1]).any(axis=1)].shape[0] for _, df in all_rows)
    
    if resultados['aceptacion_por_pilar']:
        pilar_mas_influyente = max(resultados['aceptacion_por_pilar'], key=lambda k: abs(resultados['aceptacion_por_pilar'][k] if not pd.isna(resultados['aceptacion_por_pilar'][k]) else 0))
    else:
        pilar_mas_influyente = "Ninguno"
    
    informe = {
        "Aceptación Global [%]": resultados["aceptacion_global_norm"],
        "Interpretación": interpretar_aceptacion(resultados["aceptacion_global_norm"]),
        "Pilar más influyente": pilar_mas_influyente,
        "Cantidad de publicaciones usadas": resultados["n_publicaciones_usadas"],
        "Mensajes descartados": n_descartados,
        "Aceptación por pilar": resultados["aceptacion_por_pilar"],
        "Detalle por Red": resultados["detalles_por_red"]
    }
    return informe    

# ---------------------------------------------------
# FUNCIÓN PRINCIPAL
# ---------------------------------------------------
def metrics(config):
    data_path = Path(config.general["output_folder"])
    all_rows = cargar_datos(data_path)
    if not all_rows:
        return

    # 1. Calcular métricas
    resultados = aceptacion_global_promedio_pilares(all_rows, PILARES)

    print("\n📘 MÉTRICA DE ACEPTACIÓN GLOBAL (PROMEDIO DE PILARES)")
    for p, v in resultados["aceptacion_por_pilar"].items():
        print(f"   {p:<25}: {v:.4f}")
    print(f"\n   Aceptación Global [-1,1] : {resultados['aceptacion_global']:.4f}")
    print(f"   Aceptación Global [0-100]: {resultados['aceptacion_global_norm']:.2f}%")
    print(f"   Publicaciones usadas     : {resultados['n_publicaciones_usadas']}")
    
    # 2. Generar informe
    informe = generar_informe(resultados, all_rows, PILARES)

    # 3. Mostrar en consola (resumido)
    print("\n📘 INFORME DE ACEPTACIÓN GLOBAL")
    for k, v in informe.items():
        if k == "Detalle por Red": continue
        if isinstance(v, float):
            print(f"{k:<35}: {v:.2f}")
        elif isinstance(v, dict):
            print(f"{k}:")
            for p, val in v.items():
                if isinstance(val, (int, float)):
                    print(f"   {p:<25}: {val:.2f}")
        else:
            print(f"{k:<35}: {v}")

    # 4. Guardar JSON y CSV
    output_dir = data_path
    output_dir.mkdir(exist_ok=True)

    informe_simple = informe.copy()
    del informe_simple["Detalle por Red"]

    json_path = output_dir / "aceptacion_global.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(informe, f, indent=4, ensure_ascii=False)

    csv_path = output_dir / "aceptacion_global.csv"
    pd.DataFrame([informe_simple]).to_csv(csv_path, index=False)

    # 5. Guardar TXT con formato detallado
    txt_path = output_dir / "aceptacion_global.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("📘 INFORME DE ACEPTACIÓN GLOBAL\n")
        f.write("="*40 + "\n\n")
        
        for k, v in informe.items():
            if k == "Detalle por Red": continue
            
            if isinstance(v, float):
                f.write(f"{k:<35}: {v:.2f}\n")
            elif isinstance(v, dict):
                f.write(f"{k}:\n")
                for p, val in v.items():
                    f.write(f"   {p:<25}: {val:.2f}\n")
            else:
                f.write(f"{k:<35}: {v}\n")
        
        f.write("\n" + "="*40 + "\n")
        f.write("DETALLE POR RED SOCIAL\n")
        f.write("="*40 + "\n")
        
        detalles = informe.get("Detalle por Red", {})
        for red, stats in detalles.items():
            f.write(f"\n🔹 Red: {red.upper()}\n")
            if "error" in stats:
                f.write(f"   ⚠️ {stats['error']}\n")
            else:
                f.write(f"   Filas relevantes para cálculo: {stats['filas_relevantes']}\n")
                for pilar, counts in stats['conteos'].items():
                    f.write(f"      Pilar {pilar}: positivos {counts['pos']}, negativos {counts['neg']}, neutros {counts['neu']}\n")

    # 6. Generar Datasets Finales Anonimizados
    generar_datasets_finales(all_rows, output_dir)

    print(f"\n📁 Resultados guardados en:\n  - {txt_path}\n  - {json_path}\n  - {csv_path}")

if __name__ == "__main__":
    metrics()
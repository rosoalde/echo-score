import pandas as pd
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from pathlib import Path
import unicodedata
import re
import datetime

# ==============================
# 1️⃣ Cargar modelo UNA sola vez
# ==============================
model = SentenceTransformer("intfloat/multilingual-e5-large")


# ==============================
# 2️⃣ Normalización fuerte
# ==============================
def normalize_text(text):
    text = str(text).lower().strip()
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


# ==============================
# 3️⃣ Construir índice de embeddings (UNA VEZ por dataset)
# ==============================
def build_topic_embedding_index(df):

    topic_cols = [c for c in df.columns if c.startswith("Topic_")]

    all_topics = set()

    for col in topic_cols:
        all_topics.update(
            df[col]
            .dropna()
            .astype(str)
            .apply(normalize_text)
            .tolist()
        )

    # eliminar vacíos y no relacionado
    all_topics = [t for t in all_topics if t not in ["", "no relacionado"]]

    if not all_topics:
        return {}

    print(f"   ↳ Topics únicos detectados: {len(all_topics)}")

    topic_embeddings = model.encode(
        [f"passage: {t}" for t in all_topics],
        batch_size=64,
        show_progress_bar=False
    )

    return {
        topic: emb for topic, emb in zip(all_topics, topic_embeddings)
    }


# ==============================
# 4️⃣ Buscar topics semánticamente similares
# ==============================
def get_similar_topics(topic_index, user_topic, threshold):

    if not topic_index:
        return set()

    user_embedding = model.encode(
        [f"query: {normalize_text(user_topic)}"]
    )

    topics = list(topic_index.keys())
    embeddings = np.array(list(topic_index.values()))

    scores = cosine_similarity(user_embedding, embeddings)[0]

    similar_topics = {
        topics[i]
        for i, score in enumerate(scores)
        if score >= threshold
    }

    return similar_topics


# ==============================
# 5️⃣ Análisis de sentimiento optimizado
# ==============================
def sentiment_analysis_industrial(df, topic_index, user_topic, threshold):

    similar_topics = get_similar_topics(topic_index, user_topic, threshold)

    if not similar_topics:
        return {
            "topic_usuario": user_topic,
            "topics_detectados": [],
            "total_menciones": 0,
            "positivos": {"count": 0, "percent": 0},
            "neutros": {"count": 0, "percent": 0},
            "negativos": {"count": 0, "percent": 0},
            "irrelevantes": {"count": 0, "percent": 0},
            "score": None
        }

    topic_cols = [c for c in df.columns if c.startswith("Topic_")]

    sentiment_values = []

    for _, row in df.iterrows():

        for i in range(1, len(topic_cols) + 1):

            topic_val = row.get(f"Topic_{i}")
            sent_val = row.get(f"Sentimiento_{i}")

            if pd.isna(topic_val) or pd.isna(sent_val):
                continue

            topic_norm = normalize_text(topic_val)

            if topic_norm in similar_topics:

                try:
                    sent_val = int(sent_val)
                except:
                    continue

                if sent_val in [-1, 0, 1, 2]:
                    sentiment_values.append(sent_val)

    total = len(sentiment_values)

    positives = sentiment_values.count(1)
    neutrals = sentiment_values.count(0)
    negatives = sentiment_values.count(-1)
    irrelevants = sentiment_values.count(2)

    score = (positives - negatives) / total if total > 0 else None

    return {
        "topic_usuario": user_topic,
        "topics_detectados": sorted(similar_topics),
        "total_menciones": total,
        "positivos": {
            "count": positives,
            "percent": round(positives / total * 100, 1) if total > 0 else 0
        },
        "neutros": {
            "count": neutrals,
            "percent": round(neutrals / total * 100, 1) if total > 0 else 0
        },
        "negativos": {
            "count": negatives,
            "percent": round(negatives / total * 100, 1) if total > 0 else 0
        },
        "irrelevantes": {
            "count": irrelevants,
            "percent": round(irrelevants / total * 100, 1) if total > 0 else 0
        },
        "score": round(score, 3) if score is not None else None
    }


# ==============================
# 6️⃣ Generar informe global optimizado
# ==============================
def generar_informe_global(data_folder, user_topic, threshold):

    data_folder = Path(data_folder)
    archivos_origen = list(data_folder.glob("*_global_dataset_analizado.csv"))
    informe_global_path = data_folder / "informe_topics_global_redes.txt"

    resumen_global_counts = {'positivos':0, 'neutros':0, 'negativos':0, 'irrelevantes':0}
    resumen_global_total = 0

    with open(informe_global_path, "w", encoding="utf-8") as f_global:

        f_global.write("="*80 + "\n")
        f_global.write(f"INFORME DE SENTIMIENTO PARA EL TOPIC: {user_topic.upper()}\n")
        f_global.write("="*80 + "\n")

        for archivo_input in archivos_origen:

            print(f"\nProcesando: {archivo_input.name}")

            with open(archivo_input, 'r', encoding='utf-8') as f:
                sep = ';' if ';' in f.readline() else ','

            df = pd.read_csv(archivo_input, sep=sep, encoding="utf-8", engine="python")

            # 🔥 Construimos índice SOLO UNA VEZ por dataset
            topic_index = build_topic_embedding_index(df)

            resumen = sentiment_analysis_industrial(
                df,
                topic_index,
                user_topic,
                threshold
            )

            nombre_red = archivo_input.stem.replace("_global_dataset_analizado", "").capitalize()

            f_global.write("="*80 + "\n")
            f_global.write(f"RED SOCIAL / DATASET: {nombre_red}\n")
            f_global.write("="*80 + "\n\n")

            f_global.write(f"Topics detectados: {', '.join(resumen['topics_detectados']) if resumen['topics_detectados'] else 'Ninguno'}\n")
            f_global.write(f"Total de menciones analizadas: {resumen['total_menciones']}\n\n")

            f_global.write("-"*50 + "\n")
            f_global.write(f"{'Categoría':<15}{'Cantidad':<10}{'Porcentaje':<10}\n")
            f_global.write("-"*50 + "\n")

            for cat in ['positivos','neutros','negativos','irrelevantes']:
                data = resumen[cat]
                f_global.write(f"{cat.capitalize():<15}{data['count']:<10}{data['percent']:<10}%\n")
                resumen_global_counts[cat] += data['count']

            f_global.write("-"*50 + "\n")
            f_global.write(f"Score neto (-1 a 1): {resumen['score'] if resumen['score'] else 'N/A'}\n\n\n")

            resumen_global_total += resumen['total_menciones']

        # ===== RESUMEN GLOBAL =====
        f_global.write("="*80 + "\n")
        f_global.write("RESUMEN GLOBAL DE TODAS LAS REDES\n")
        f_global.write("="*80 + "\n\n")

        f_global.write(f"Total de menciones analizadas: {resumen_global_total}\n\n")

        for cat in ['positivos','neutros','negativos','irrelevantes']:
            count = resumen_global_counts[cat]
            percent = round(count/resumen_global_total*100,1) if resumen_global_total>0 else 0
            f_global.write(f"{cat.capitalize():<15}{count:<10}{percent:<10}%\n")

        score_global = (
            (resumen_global_counts['positivos'] - resumen_global_counts['negativos'])
            / resumen_global_total
            if resumen_global_total>0 else None
        )

        f_global.write("\n")
        f_global.write(f"Score neto global (-1 a 1): {round(score_global,3) if score_global else 'N/A'}\n")

    print(f"\n✅ Informe generado en: {informe_global_path}")


# a = datetime.datetime.now()

# generar_informe_global(
#     r"C:\Users\DATS004\Dropbox\PERSONAL\clean_project\DRONES_INFORME20250401_20250930",
#     "rusia",
#     0.82
# )

# b = datetime.datetime.now()
# print("Tiempo total:", b - a)
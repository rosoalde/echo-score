import clean_project.keyword_processing.language_detect as language_detect
import re

def detect_language(text: str) -> str:
    """
    Devuelve UN idioma fuente fiable para traducción.
    Fallback conservador: Spanish.
    """

    prediction = language_detect.predict_transformer(
        text,
        language_detect.model,
        language_detect.tokenizer
    )

    print(f"🧪 Predicción de idiomas cruda: {prediction}")

    matches = re.findall(r"([A-Za-z]+)\s*\((0\.\d+)\)", prediction)

    # 1️⃣ Alta confianza → usar ese idioma
    for lang, score_str in matches:
        score = float(score_str)
        if score >= 0.9:
            print(f"✅ Idioma fuente elegido (alta confianza): {lang}")
            return lang

    # 2️⃣ Confianza media → usar Spanish como idioma fuente
    for lang, score_str in matches:
        score = float(score_str)
        if score >= 0.25 and score < 0.9:
            print("⚠️ Confianza media → forzamos idioma fuente: Spanish")
            return "Spanish"

    # 3️⃣ Fallback total
    print("❌ No se detecta idioma fiable → fallback Spanish")
    return "Spanish"

from collections import defaultdict
from clean_project.keyword_processing.language_detection import detect_language
# from clean_project.keyword_processing.language_detection_fasttext import detect_language_fasttext
from clean_project.keyword_processing.translation import translate_keyword
from clean_project.keyword_processing.language_config import LANGUAGES



def generate_search_forms(
    keywords: list[str],
    target_languages: list[str]
) -> list[dict]:
    """
    Genera formas léxicas únicas para scraping multilingüe.
    """

    forms_map = defaultdict(lambda: {
        "search_form": None,
        "languages": set(),
        "original_keywords": set()
    })

    for keyword in keywords:
        source_lang = detect_language(keyword)
        print(
            f"🧪 Keyword original: '{keyword}' | "
            f"Idioma fuente detectado: {source_lang}"
        )

        print("🌐 Traducciones por idioma:")

        for lang in target_languages:
            if lang == source_lang:
                translated = keyword
                print(f"  - {lang}: '{translated}' (sin traducir)")
            else:
                translated = translate_keyword(keyword, source_lang, lang)
                print(f"  - {lang}: '{translated}'")

            normalized = translated.strip().lower()

            # 🛑 Si este idioma ya fue asignado a otra forma, no crear otra
            if lang in forms_map[normalized]["languages"]:
                continue

            forms_map[normalized]["search_form"] = translated
            forms_map[normalized]["languages"].add(lang)
            forms_map[normalized]["original_keywords"].add(keyword)

    # Convertir a lista limpia
    search_forms = []
    for data in forms_map.values():
        search_forms.append({
            "search_form": data["search_form"],
            "languages": list(data["languages"]),
            "original_keywords": list(data["original_keywords"])
        })

    return search_forms

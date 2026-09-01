from deep_translator import GoogleTranslator
print(f"instalar GoogleTranslator si no está instalado haciendo: pip install deep-translator")
LANG_NAME_TO_CODE = {
    "Castellano": "es",
    "Spanish": "es",
    "Ingles": "en",
    "English": "en",
    "Italiano": "it",
    "Frances": "fr",
    "Portugues": "pt",
    "Catalan": "ca",
    "Euskera": "eu"
}
def translate_keyword(keyword: str, source_language: str, target_language: str) -> str:
    try:
        source_code = LANG_NAME_TO_CODE[source_language]
        target_code = LANG_NAME_TO_CODE[target_language]

        return GoogleTranslator(
            source=source_code,
            target=target_code
        ).translate(keyword)

    except Exception as e:
        print(f"⚠️ Error traduciendo '{keyword}' → {target_language}: {e}")
        return keyword

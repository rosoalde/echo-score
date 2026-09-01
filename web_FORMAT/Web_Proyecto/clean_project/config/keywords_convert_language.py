import clean_project.keyword_processing.language_detect as language_detect
LANGUAGES = {
    "Spanish": "Castellano",
    "Catalan": "Catalán",
    "Basque": "Euskera",
    "English": "English",
    "Portuguese": "Português",
    "French": "Français",
    "Italian": "Italiano"
}
# "Galician": "Gallego" no tenemos detectión específica para gallego

languages_list = [
    "Arabic", "Basque", "Breton", "Catalan", "Chinese_China", "Chinese_Hongkong", 
    "Chinese_Taiwan", "Chuvash", "Czech", "Dhivehi", "Dutch", "English", 
    "Esperanto", "Estonian", "French", "Frisian", "Georgian", "German", "Greek", 
    "Hakha_Chin", "Indonesian", "Interlingua", "Italian", "Japanese", "Kabyle", 
    "Kinyarwanda", "Kyrgyz", "Latvian", "Maltese", "Mongolian", "Persian", "Polish", 
    "Portuguese", "Romanian", "Romansh_Sursilvan", "Russian", "Sakha", "Slovenian", 
    "Spanish", "Swedish", "Tamil", "Tatar", "Turkish", "Ukranian", "Welsh"
]

all_language_keywords=[]

def convert_keywords_language(keywords):
    for keyword in keywords:
        detected = language_detect.predict_transformer(keyword, language_detect.model, language_detect.tokenizer)
        lang_code = detected.split(' ')[0]  # Obtener el código del idioma detectado
    for lang_code in LANGUAGES.keys():
        all_language_keywords.append(f'"{keyword}" lang:{lang_code}')
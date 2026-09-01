import torch
import json
import ollama
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from langdetect import detect, DetectorFactory


from transformers import pipeline

# detector = pipeline(
#     "text-classification",
#     model="papluca/xlm-roberta-base-language-detection",
#     top_k=None
# )


# print(" ⏳ Ahora veremos los resultados de papluca/xlm-roberta-base-language-detection...")
# print(f"{detector("baliza v16")}")
# print("------------------------------------------------------------------------")
DetectorFactory.seed = 0

# ------------------------------------------------------------------------
# 1️⃣ MODELO TRANSFORMER (Mike0307/multilingual-e5-language-detection)
# ------------------------------------------------------------------------
print("⏳ Cargando modelo Transformer (esto puede tardar la primera vez)...")
tokenizer = AutoTokenizer.from_pretrained('Mike0307/multilingual-e5-language-detection')
model = AutoModelForSequenceClassification.from_pretrained('Mike0307/multilingual-e5-language-detection', num_labels=45)

languages_list = [
    "Arabic", "Basque", "Breton", "Catalan", "Chinese_China", "Chinese_Hongkong", 
    "Chinese_Taiwan", "Chuvash", "Czech", "Dhivehi", "Dutch", "English", 
    "Esperanto", "Estonian", "French", "Frisian", "Georgian", "German", "Greek", 
    "Hakha_Chin", "Indonesian", "Interlingua", "Italian", "Japanese", "Kabyle", 
    "Kinyarwanda", "Kyrgyz", "Latvian", "Maltese", "Mongolian", "Persian", "Polish", 
    "Portuguese", "Romanian", "Romansh_Sursilvan", "Russian", "Sakha", "Slovenian", 
    "Spanish", "Swedish", "Tamil", "Tatar", "Turkish", "Ukranian", "Welsh"
]

def predict_transformer(text, model, tokenizer):
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model.to(device)
    model.eval()
    tokenized = tokenizer(text, padding='max_length', truncation=True, max_length=128, return_tensors="pt")
    input_ids = tokenized['input_ids'].to(device)
    attention_mask = tokenized['attention_mask'].to(device)
    
    with torch.no_grad():
        outputs = model(input_ids=input_ids, attention_mask=attention_mask)
    
    logits = outputs.logits
    probabilities = torch.nn.functional.softmax(logits, dim=1)
    
    # Obtener el mejor
    topk_prob, topk_indices = torch.topk(probabilities, 2)
    # Convertimos a listas de Python
    probs = topk_prob.cpu().numpy()[0]      # Ej: [0.55, 0.40]
    indices = topk_indices.cpu().numpy()[0] # Indices de los idiomas
    
    # Candidato 1 (El ganador)
    lang1 = languages_list[indices[0]]
    score1 = probs[0]
    
    # Candidato 2 (El segundo mejor)
    lang2 = languages_list[indices[1]]
    score2 = probs[1]
    
    return f"{lang1} ({score1:.2f}) / {lang2} ({score2:.2f})"

# ------------------------------------------------------------------------
# 2️⃣ MODELO LLM (Ollama - Qwen2.5:0.5b)
# ------------------------------------------------------------------------
def predict_ollama(user_text):
    try:
        response = ollama.chat(
            model= "qwen2.5:1.5b", #"llama3:latest", # "qwen2.5:0.5b", 
            messages=[
                {
                    "role": "system", 
                    "content": "Detect language (ISO 639-1 code). Return JSON: {\"lang_code\": \"xx\"}."
                },
                {"role": "user", "content": user_text}
            ],
            format="json",
            options={"temperature": 0.0, "num_ctx": 1024} 
        )
        raw = response.get("message", {}).get("content", "")
        data = json.loads(raw)
        return data.get("lang_code", "unknown")
    except:
        return "error"

# ------------------------------------------------------------------------
# 3️⃣ MODELO ESTADÍSTICO (langdetect - Google)
# ------------------------------------------------------------------------
def predict_statistical(text):
    try:
        return detect(text)
    except:
        return "unknown"
    
'''
# ------------------------------------------------------------------------
# 🏁 EJECUCIÓN DE LA PRUEBA
# ------------------------------------------------------------------------
texts = [
    "acuerdo EU MERCOSUR",          # Español
    "EB-Mercosurreko akordioa",     # Euskera (Basque)
    "acordo UE Mercosur",           # Gallego 
    "EU Mercosur agreement",        # Inglés
    "accord EU MERCOSUR",           # Francés / Catalán
    "accordo UE MERCOSUR",          # Italiano
    "Nunca choveu que non escampara", # Gallego
    "acordo eu mercosul",            # Portugués
    "bon dia com va tot"         # Catalán
]

print(f"\n{'TEXTO':<35} | {'TRANSFORMER':<15} | {'OLLAMA':<10} | {'STATISTICAL':<10}")
print("-" * 80)

for text in texts:
    # 1. Transformer
    try:
        trans_res = predict_transformer(text, model, tokenizer)
        trans_res_detected = trans_res.split(' ')[0]  # Obtener el código del idioma detectado
        print(f"Código detectado por Transformer: {trans_res_detected}")
    except: trans_res = "Error"

    # 2. Ollama
    ollama_res = predict_ollama(text)

    # 3. Statistical
    stat_res = predict_statistical(text)

    print(f"{text:<35} | {trans_res:<15} | {ollama_res:<10} | {stat_res:<10}")
'''
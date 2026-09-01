from clean_project.utils.helpers import build_keywords_expandidas
from pathlib import Path
import json
from datetime import date

# ==============================
# LOCALIZAR RAÍZ DEL PROYECTO
# ==============================

BASE_DIR = Path(__file__).resolve()
while not (BASE_DIR / "config").exists():
    BASE_DIR = BASE_DIR.parent

CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"

DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

# ==============================
# KEYWORDS
# ==============================

keywords_base = ["acuerdo EU MERCOSUR"]#, "EB-Mercosurreko akordioa", "acordo  UE  Mercosur", "EU Mercosur agreement","accord EU MERCOSUR", "accordo UE MERCOSUR", "acordo eu mercosul"]

keywords_expandidas = build_keywords_expandidas(keywords_base)

# ==============================
# FECHAS Y CONFIG GENERAL
# ==============================
search_form_lang_map = {}
for keyword in keywords_expandidas:
    search_form_lang_map[keyword] = ["es"]#, "eu", "gl","en", "ca", "it", "pt"]

start_date = "2026-01-01"#"2025-04-01"#"2025-12-30"#"2026-01-06"#
end_date   = "2026-01-19"#"2025-04-30"#"2025-12-31"#"2026-01-09"#

general = {
    "start_date": start_date,
    "end_date": end_date,
    "keywords": keywords_expandidas,
    "search_form_lang_map": search_form_lang_map,
    "output_folder": f"prueba_language{start_date.replace('-', '')}_{end_date.replace('-', '')}" # CAMBIAR ESTO PARA CREAR UN DIRECTORIO NUEVO
}

# ==============================
# SCRAPING (🔥 ESTO ARREGLA TU ERROR)
# ==============================

scraping = {
    "reddit": {
        "enabled": True,
        "limit": None,
        "query": general["keywords"]
    },
    "bluesky": {
        "enabled": True,
        "limit": 100,
        "query": general["keywords"]
    },
    "twitter": {
        "enabled": True,
        "limit": 500,
        "query": general["keywords"]
    },
    "linkedin": {
        "enabled": True,
        "limit": 200,
        "query": general["keywords"]
    },
    "youtube": {
        "enabled": True,
        "limit": 200,
        "query": general["keywords"]
    },
    "tiktok": {
        "enabled": True,            
        "limit": 200,
        "query": general["keywords"]
}
}


# ==============================
# CREDENCIALES
# ==============================

CREDENTIALS_PATH = CONFIG_DIR / "credentials.json"

if not CREDENTIALS_PATH.exists():
    raise FileNotFoundError(f"credentials.json no encontrado en {CREDENTIALS_PATH}")

with open(CREDENTIALS_PATH, "r", encoding="utf-8") as f:
    CREDENTIALS = json.load(f)

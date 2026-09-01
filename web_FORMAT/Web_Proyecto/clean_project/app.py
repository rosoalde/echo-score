# Ubicación: src\clean_project\app.py

# =========================================================
# IMPORTS
# =========================================================
import streamlit as st
import zipfile
import io
import json
import re
import ollama
import copy
import uuid
from types import SimpleNamespace
from datetime import date, timedelta, datetime, time, timezone 
from pathlib import Path
import pandas as pd
import locale 

# --- Configuración y Prompts ---
import clean_project.config.settings as config
from clean_project.prompts.keywords import get_prompt_keywords 
from clean_project.prompts.pilares import get_prompt as get_prompt_pilares
from clean_project.prompts.topics import get_prompt as get_prompt_topics

# --- Scrapers ---
from clean_project.scrapers.bluesky_scraper import run_bluesky
from clean_project.scrapers.reddit_scraper import run_reddit
from clean_project.scrapers.linkedin_scraper import run_linkedin
from clean_project.scrapers.youtube_scraper import run_youtube
from clean_project.scrapers.twitter_scraper import run_twitter

# --- Análisis y Métricas ---
import clean_project.analysis.llm_analysis as llm_analysis_module
from clean_project.analysis.llm_analysis import llm_analysis
import clean_project.analysis.metrics as metrics_module
from clean_project.analysis.metrics import metrics

# Intentar poner fechas en español
try:
    locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
except:
    try:
        locale.setlocale(locale.LC_TIME, 'es_ES')
    except:
        pass

# =========================================================
# CONFIG Y HELPERS
# =========================================================
st.set_page_config(page_title="Análisis de Opinión en Redes Sociales", layout="wide")

# --- RUTAS ---
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent.parent
TESTS_DIR = PROJECT_ROOT / "tests"
CREDENTIALS_PATH = CURRENT_DIR / "config" / "credentials.json"

# --- GESTIÓN DE CONFIGURACIÓN DE USUARIO (AISLAMIENTO TOTAL) ---
def get_user_config():
    """
    Carga credenciales del JSON y prepara la configuración.
    ESTRATEGIA ROBUSTA: Pasa tanto variables sueltas como el diccionario original.
    """
    # 1. Cargar el JSON tal cual
    creds_data = {}
    if CREDENTIALS_PATH.exists():
        try:
            with open(CREDENTIALS_PATH, 'r', encoding='utf-8') as f:
                creds_data = json.load(f)
            print(f"✅ Credenciales cargadas desde: {CREDENTIALS_PATH}")
        except Exception as e:
            st.error(f"⚠️ Error leyendo credentials.json: {e}")
    else:
        st.warning(f"⚠️ No se encontró credentials.json en: {CREDENTIALS_PATH}")

    # 2. Extraer variables específicas con seguridad (.get para evitar errores si falta algo)
    # BLUESKY
    bs_data = creds_data.get("bluesky", {})
    bs_user = bs_data.get("USERNAME_bluesky", "")
    bs_pass = bs_data.get("PASSWORD_bluesky", "")

    # REDDIT
    rd_data = creds_data.get("reddit", {})
    rd_id = rd_data.get("reddit_client_id", "")
    rd_secret = rd_data.get("reddit_client_secret", "")

    # TWITTER (Puede estar como "twitter" o "red" según tu JSON)
    tw_data = creds_data.get("twitter", {})
    if not tw_data: tw_data = creds_data.get("red", {}) # Fallback
    
    tw_user = tw_data.get("USERNAME_red", tw_data.get("username", "")) # Intenta ambos nombres
    tw_pass = tw_data.get("PASSWORD_red", tw_data.get("password", ""))

    # LINKEDIN
    li_data = creds_data.get("linkedin", {})
    li_email = li_data.get("LINKEDIN_EMAIL", "")
    li_pass = li_data.get("LINKEDIN_PASSWORD", "")

    # YOUTUBE
    yt_data = creds_data.get("youtube", {})
    yt_key = yt_data.get("API_KEY_YOUTUBE", "")

    # 3. Construir el objeto de configuración
    # IMPORTANTE: CREDENTIALS lleva los datos crudos para que coincidan las claves
    return SimpleNamespace(
        general=copy.deepcopy(config.general),
        scraping=copy.deepcopy(config.scraping),
        keywords_base=copy.deepcopy(config.keywords_base),
        
        # --- AQUI ESTA LA SOLUCION DEL ERROR ---
        # Pasamos el diccionario 'creds_data' completo o reconstruido con TUS claves
        CREDENTIALS=creds_data, 

        # --- VARIABLES SUELTAS (GLOBALES) ---
        # Por si el scraper usa config.USERNAME_bluesky directamente
        USERNAME_bluesky=bs_user,
        PASSWORD_bluesky=bs_pass,
        
        # Por si el scraper usa config.reddit_client_id
        reddit_client_id=rd_id,
        REDDIT_CLIENT_ID=rd_id, # Alias por si acaso
        reddit_client_secret=rd_secret,
        REDDIT_CLIENT_SECRET=rd_secret, # Alias por si acaso
        
        # Twitter
        USERNAME_red=tw_user,
        PASSWORD_red=tw_pass,
        USERNAME_twitter=tw_user, # Alias
        
        # Linkedin
        LINKEDIN_EMAIL=li_email,
        LINKEDIN_PASSWORD=li_pass,
        
        # Youtube
        API_KEY_YOUTUBE=yt_key,

        # Prompts vacíos iniciales
        sentiment_prompt={},
        acceptace_prompt={} 
    )

# --- Helper: Convierte fechas ---
def convertir_a_iso_utc(fecha_inicio: date, fecha_fin: date):
    """
    Devuelve formato YYYY-MM-DD simple.
    Arregla el error 'unconverted data remains' de Reddit/Twitter.
    """
    iso_inicio = fecha_inicio.strftime("%Y-%m-%d")
    iso_fin = fecha_fin.strftime("%Y-%m-%d")
    return iso_inicio, iso_fin

def output_exists(cfg, red: str) -> bool:
    output_folder = Path(cfg.general["output_folder"])
    output_file = output_folder / f"{red}_global_dataset.csv"
    return output_file.exists()

def extraer_json(texto: str):
    if not texto: return None
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", texto)
        if match:
            try: return json.loads(match.group(0))
            except: return None
    return None

def generar_keywords_con_ia(tema: str):
    if not tema: return []
    prompt = get_prompt_keywords(tema)
    print(f"🤖 Prompt generado para IA:\n{prompt}")
    model_name = "qwen2.5:1.5b"#"gemma3:4b"#"qwen2.5:0.5b"#"qwen2.5:14b" 
    print(f"🤖 Consultando modelo Ollama: {model_name}")
    try:
        response = ollama.chat(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            # format="json",
            options={"temperature": 0.0, "num_ctx": 4096, "num_gpu": 1}  
        )
        print(f"🤖 Respuesta cruda Ollama:\n{response}")
        raw = response.get("message", {}).get("content", "")
        data = extraer_json(raw)
        if data and "keywords" in data:
            return data["keywords"]
    except Exception as e:
        st.error(f"Error Ollama (posible sobrecarga): {e}")
        return []
    return []

# =========================================================
# SESSION STATE INIT
# =========================================================
if "user_id" not in st.session_state:
    st.session_state.user_id = str(uuid.uuid4())[:8]

if "user_config" not in st.session_state:
    st.session_state.user_config = get_user_config()

if "pipeline_running" not in st.session_state: st.session_state.pipeline_running = False
if "pipeline_done" not in st.session_state: st.session_state.pipeline_done = False
if "output_path" not in st.session_state: st.session_state.output_path = None
if "keywords_content" not in st.session_state: st.session_state.keywords_content = "" 
if "temp_generated_kws" not in st.session_state: st.session_state.temp_generated_kws = []

u_conf = st.session_state.user_config
uid = st.session_state.user_id 

# =========================================================
# UI - TÍTULO
# =========================================================
st.title("📊 Análisis de Opinión en Redes Sociales")
st.caption(f"Sesión ID: {uid} | Procesos Aislados")

# =========================================================
# 1. ESTRATEGIA DE BÚSQUEDA
# =========================================================
st.markdown("### 1️⃣ Estrategia de Búsqueda")

col_ia_input, col_ia_btn = st.columns([4, 1])
with col_ia_input:
    tema_usuario = st.text_input("💡 Asistente IA (Opcional)", placeholder="Ej: Opinión pública sobre la crisis habitacional en España", key=f"tema_{uid}")

with col_ia_btn:
    st.write("") 
    st.write("") 
    if st.button("✨ Generar", key=f"btn_gen_{uid}"):
        if tema_usuario:
            print(f"🤖 [SESION {uid}] Generando keywords IA para tema: {tema_usuario}")
            with st.spinner("🤖 Consultando IA (Puede tardar si hay procesos activos)..."):
                kws = generar_keywords_con_ia(tema_usuario)
                print(f"🔑 [SESION {uid}] Keywords IA: {kws}")
                if kws:
                    st.session_state.temp_generated_kws = kws
                    st.success(f"¡{len(kws)} términos!")
                    st.rerun()
                else:
                    st.warning("No se pudo conectar con la IA.")

# Tabla IA
if st.session_state.temp_generated_kws:
    if "select_all_state" not in st.session_state: st.session_state.select_all_state = False
    with st.container(border=True):
        st.markdown("**🤖 Sugerencias de la IA**")
        c_btn_sel, _ = st.columns([1, 4])
        with c_btn_sel:
            if st.button("✅ Todas", key=f"btn_all_{uid}"):
                st.session_state.select_all_state = True
                if "editor_kws" in st.session_state: del st.session_state["editor_kws"]
                st.rerun()

        df_kws = pd.DataFrame({
            "Seleccionar": [st.session_state.select_all_state] * len(st.session_state.temp_generated_kws),
            "Palabra Clave": st.session_state.temp_generated_kws
        })

        edited_df = st.data_editor(
            df_kws,
            column_config={
                "Seleccionar": st.column_config.CheckboxColumn("Incluir", default=False, width="small"),
                "Palabra Clave": st.column_config.TextColumn("Término", width="large", disabled=True)
            },
            hide_index=True,
            use_container_width=True,
            key="editor_kws"
        )
        
        c_add, c_discard = st.columns([1, 1])
        with c_add:
            if st.button("⬇️ Incorporar", type="primary", key=f"btn_inc_{uid}"):
                kws_finales = edited_df[edited_df["Seleccionar"] == True]["Palabra Clave"].tolist()
                if kws_finales:
                    texto_actual = st.session_state.keywords_content.strip()
                    nuevas_kws = "\n".join(kws_finales)
                    st.session_state.keywords_content = f"{texto_actual}\n{nuevas_kws}" if texto_actual else nuevas_kws
                    st.session_state.temp_generated_kws = []
                    st.session_state.select_all_state = False 
                    if "editor_kws" in st.session_state: del st.session_state["editor_kws"]
                    st.rerun()
        with c_discard:
            if st.button("🗑️ Descartar", key=f"btn_del_{uid}"):
                st.session_state.temp_generated_kws = []
                st.rerun()

keywords_text = st.text_area(
    "📝 Lista Final de Palabras Clave",
    value=st.session_state.keywords_content,
    height=200,
    key=f"txt_kws_{uid}"
)
st.session_state.keywords_content = keywords_text 
keywords_list = [k.strip() for k in keywords_text.split("\n") if k.strip()]

st.divider()

# =========================================================
# 2. CONFIGURACIÓN TÉCNICA
# =========================================================
st.markdown("### 2️⃣ Configuración Técnica")

col_fechas, col_nombre = st.columns([1, 1])
with col_fechas:
    st.markdown("**Rango de Fechas**")
    c_f1, c_f2 = st.columns(2)
    today = date.today()
    yesterday = today - timedelta(days=1)
    # Formato visual DD/MM/YYYY
    with c_f1: start_date = st.date_input("Inicio", value=yesterday, format="DD/MM/YYYY", key=f"d_start_{uid}")
    with c_f2: end_date = st.date_input("Fin", value=today, format="DD/MM/YYYY", key=f"d_end_{uid}")

with col_nombre:
    st.markdown("**Organización**")
    default_name = tema_usuario.strip().replace(" ", "_").lower() if tema_usuario else ""
    user_folder_name = st.text_input("Nombre del proyecto", value=default_name, placeholder="ej: crisis_vivienda", key=f"fname_{uid}")

st.markdown("**Selección de Fuentes**")
redes = st.multiselect(
    "Redes sociales",
    ["bluesky", "reddit", "twitter", "youtube", "linkedin"],
    default=["bluesky", "reddit", "twitter", "youtube", "linkedin"],
    key=f"m_redes_{uid}"
)

# Prompts dinámicos
keywords_expandidas = config.build_keywords_expandidas(keywords_list)
with st.expander("⚙️ Configuración Avanzada de Prompts"):
    prompt_topics_val = get_prompt_topics(keywords_expandidas)
    prompt_pilares_val = get_prompt_pilares(keywords_expandidas)
    
    user_prompt_topics = st.text_area("Prompt Tópicos", value=prompt_topics_val, height=100, key=f"p_topic_{uid}")
    user_prompt_pilares = st.text_area("Prompt Pilares", value=prompt_pilares_val, height=100, key=f"p_pilar_{uid}")

st.divider()

# =========================================================
# EJECUCIÓN PIPELINE
# =========================================================
if st.button("🚀 INICIAR PIPELINE COMPLETO", type="primary", disabled=st.session_state.pipeline_running, key=f"btn_run_{uid}"):
    if not user_folder_name.strip():
        st.error("❗ Falta nombre del proyecto.")
    elif not keywords_list:
        st.error("❗ Faltan palabras clave.")
    else:
        st.session_state.pipeline_running = True
        st.session_state.pipeline_done = False
        st.rerun()

if st.session_state.pipeline_running and not st.session_state.pipeline_done:
    
    with st.spinner("⏳ Ejecutando pipeline..."):
        
        # 1. ACTUALIZAR CONFIGURACIÓN (Aislada en u_conf)
        u_conf.general["start_date"], u_conf.general["end_date"] = convertir_a_iso_utc(start_date, end_date)
        u_conf.keywords_base = keywords_list
        u_conf.general["keywords"] = keywords_expandidas
        u_conf.sentiment_prompt = {"sentiment_prompt": user_prompt_topics}
        u_conf.acceptace_prompt = {"acceptance_prompt": user_prompt_pilares}
        for r in u_conf.scraping: u_conf.scraping[r]["query"] = keywords_expandidas

        # 2. Rutas únicas
        folder_name = f"{user_folder_name}_{start_date.strftime('%Y%m%d')}_{uid}"
        final_output_path = TESTS_DIR / folder_name
        final_output_path.mkdir(exist_ok=True, parents=True)
        u_conf.general["output_folder"] = str(final_output_path)
        st.session_state.output_path = final_output_path
        
        print(f"📂 [SESION {uid}] Output: {final_output_path}")

        # 3. EJECUCIÓN DE SCRAPERS
        progress_bar = st.progress(0)
        step = 1.0 / (len(redes) + 2) 
        curr_p = 0.0

        for red in redes:
            if not output_exists(u_conf, red):
                st.write(f"📡 Scrapeando **{red.capitalize()}**...")
                try:
                    # Pasamos la config aislada
                    if red == "bluesky": run_bluesky(u_conf)
                    elif red == "reddit": run_reddit(u_conf)
                    elif red == "twitter": run_twitter(u_conf)
                    elif red == "youtube": run_youtube(u_conf)
                    elif red == "linkedin": run_linkedin(u_conf)
                except Exception as e: st.error(f"Error {red}: {e}")
            else:
                st.info(f"⏭️ {red} ya procesado.")
            curr_p += step
            progress_bar.progress(min(curr_p, 1.0))
        
        # 4. ANÁLISIS LLM
        st.write("🧠 Ejecutando análisis semántico...")
        try:
            llm_analysis_module.config = u_conf 
            try:
                llm_analysis(u_conf) 
            except TypeError:
                llm_analysis()
        except Exception as e: 
            st.error(f"Error Análisis: {e}")
            import traceback
            traceback.print_exc()
        
        curr_p += step
        progress_bar.progress(min(curr_p, 1.0))

        # 5. MÉTRICAS
        st.write("📊 Generando informes...")
        try:
            metrics_module.config = u_conf
            try:
                metrics(u_conf)
            except TypeError:
                metrics()
        except Exception as e: st.error(f"Error Métricas: {e}")
        
        progress_bar.progress(1.0)
        st.session_state.pipeline_done = True
        st.session_state.pipeline_running = False
        st.rerun()

# =========================================================
# RESULTADOS
# =========================================================
if st.session_state.pipeline_done:
    st.balloons()
    st.success(f"✅ Completado en: {st.session_state.output_path.name}")
    
    if st.session_state.output_path and st.session_state.output_path.exists():
        zip_buffer = io.BytesIO()
        count = 0
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path in st.session_state.output_path.glob("*"):
                if file_path.is_file():
                    zipf.write(file_path, arcname=file_path.name)
                    count += 1
        
        if count > 0:
            st.download_button(
                "⬇️ Descargar ZIP",
                data=zip_buffer.getvalue(),
                file_name=f"Informe_{st.session_state.output_path.name}.zip",
                mime="application/zip",
                key=f"dl_zip_{uid}"
            )
        else:
            st.error("⚠️ Carpeta vacía.")

    if st.button("🔄 Nueva Sesión", key=f"btn_reset_{uid}"):
        del st.session_state.user_config
        st.session_state.pipeline_done = False
        st.session_state.pipeline_running = False
        st.rerun()
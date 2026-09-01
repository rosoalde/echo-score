import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from pathlib import Path
import matplotlib

matplotlib.use('Agg')

# ==========================================
# CONFIGURACIÓN DE RUTAS Y PESOS
# ==========================================
RUTA_PROYECTO = Path("/home/rrss/proyecto_web/RRSS_version_stance/project_web/Web_Proyecto/datos/admin/carril_bus_vao")

W_REACTION = 0.05  # Likes / Hearts / Upvotes
W_SHARE = 0.20     # Retweets / Quotes
W_COMMENT = 0.75   # Comments / Replies

def unificar_columnas_y_limpiar(df, red):
    """
    Mapea las columnas específicas de cada red a nombres estándar:
    'likes_std', 'comments_std', 'shares_std'
    """
    # Convertir todo a minúsculas para evitar errores de Case
    df.columns = [c.lower() for c in df.columns]
    
    # Inicializar columnas estándar en 0
    df['likes_std'] = 0
    df['comments_std'] = 0
    df['shares_std'] = 0

    if red == 'reddit':
        # Reddit: Likes es 'likes', Comments es 'comments'
        df['likes_std'] = pd.to_numeric(df.get('Likes', 0), errors='coerce').fillna(0).abs()
        df['comments_std'] = pd.to_numeric(df.get('comments', 0), errors='coerce').fillna(0)
        # Reddit no tiene shares en tu dataset
        df['shares_std'] = 0

    elif red == 'bluesky':
        # Bluesky: Likes es 'likes' o 'hearts', Shares es 'retweets' + 'quotes'
        df['likes_std'] = pd.to_numeric(df.get('likes', 0), errors='coerce').fillna(0)
        df['comments_std'] = pd.to_numeric(df.get('comments', 0), errors='coerce').fillna(0)
        # Sumamos retweets y quotes como 'shares'
        rt = pd.to_numeric(df.get('retweets', 0), errors='coerce').fillna(0)
        qt = pd.to_numeric(df.get('quotes', 0), errors='coerce').fillna(0)
        df['shares_std'] = rt + qt

    elif red == 'youtube':
        # Youtube: Likes es 'likes_comentario', Comments es 'numero_respuestas_al_comentario'
        df['likes_std'] = pd.to_numeric(df.get('likes_comentario', 0), errors='coerce').fillna(0)
        df['comments_std'] = pd.to_numeric(df.get('numero_respuestas_al_comentario', 0), errors='coerce').fillna(0)
        df['shares_std'] = 0

    return df

def calcular_impacto_real(df):
    # Usamos las columnas estandarizadas
    df['impact_score'] = (
        (df['likes_std'] * W_REACTION) + 
        (df['shares_std'] * W_SHARE) + 
        (df['comments_std'] * W_COMMENT)
    )
    return df

# ==========================================
# CARGA DE DATOS
# ==========================================
print(f"📂 Analizando archivos en: {RUTA_PROYECTO}")
archivos = list(RUTA_PROYECTO.glob("*_analizado.csv"))

if not archivos:
    print("❌ No se encontraron archivos *_analizado.csv")
    exit()

lista_dfs = []
for arc in archivos:
    red_name = arc.name.split('_')[0].lower()
    print(f"   -> Procesando {red_name.upper()}...")
    
    try:
        # Leer con separador ;
        temp_df = pd.read_csv(arc, sep=';', encoding='utf-8', on_bad_lines='skip')
        if temp_df.shape[1] <= 1: # Reintento con coma
            temp_df = pd.read_csv(arc, sep=',', encoding='utf-8', on_bad_lines='skip')
        
        # Aplicar mapeo de columnas según la red
        temp_df = unificar_columnas_y_limpiar(temp_df, red_name)
        temp_df['fuente_original'] = red_name.capitalize()
        
        lista_dfs.append(temp_df)
    except Exception as e:
        print(f"      ⚠️ Error leyendo {arc.name}: {e}")

df = pd.concat(lista_dfs, ignore_index=True)

# Filtrar irrelevantes (Sentimiento 2)
df = df[df['sentimiento'].astype(str) != "2"].copy()
df['sentimiento'] = pd.to_numeric(df['sentimiento'], errors='coerce').fillna(0)

# Calcular impacto
df = calcular_impacto_real(df)

# ==========================================
# GENERACIÓN DE GRÁFICAS
# ==========================================
print("📈 Generando reporte visual...")
sns.set_theme(style="whitegrid")
fig, axes = plt.subplots(2, 2, figsize=(18, 14))
fig.suptitle(f'Análisis de Impacto Real: Carril Bus VAO', fontsize=22, fontweight='bold')

# A: Muro de Impacto
df_impact = df.groupby(['fuente_original', 'sentimiento'])['impact_score'].sum().unstack().fillna(0)
colores = {1.0: '#28a745', 0.0: '#6c757d', -1.0: '#dc3545'}
df_impact.plot(kind='bar', stacked=True, ax=axes[0,0], color=[colores.get(x, '#333') for x in df_impact.columns])
axes[0,0].set_title('1. Peso Real de la Opinión (Puntos de Impacto)', fontsize=15)

# B: Matriz de Controversia
sns.scatterplot(data=df, x='sentimiento', y='impact_score', size='impact_score', 
                hue='sentimiento', palette=colores, sizes=(50, 1000), ax=axes[0,1])
axes[0,1].set_title('2. Matriz de Controversia (Impacto vs Sentimiento)', fontsize=15)

# C: Agenda vs Reacción
if 'tipodetweet' in df.columns:
    df['categoria'] = df['tipodetweet'].apply(lambda x: 'Agenda (Post)' if str(x).lower() == 'post' else 'Reacción (Comms)')
    avg_sent = df.groupby('categoria')['sentimiento'].mean()
    sns.barplot(x=avg_sent.index, y=avg_sent.values, ax=axes[1,0], hue=avg_sent.index, palette='coolwarm', legend=False)
    axes[1,0].set_title('3. Sentimiento Promedio: Agenda vs Reacción', fontsize=15)
    axes[1,0].set_ylim(-1, 1)

# D: Top Tópicos
top_topics = df.groupby('topic')['impact_score'].sum().sort_values(ascending=False).head(10)
sns.barplot(x=top_topics.values, y=top_topics.index, ax=axes[1,1], hue=top_topics.index, palette='viridis', legend=False)
axes[1,1].set_title('4. Top 10 Argumentos con Mayor Impacto', fontsize=15)

plt.tight_layout(rect=[0, 0.03, 1, 0.95])
output_img = RUTA_PROYECTO / "reporte_impacto_final.png"
plt.savefig(output_img, dpi=300)
print(f"✅ Reporte guardado en: {output_img}")
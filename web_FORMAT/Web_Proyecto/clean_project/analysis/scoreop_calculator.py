"""
Calculadora de ScoreOP (Score de Posición Social).
Implementación adaptada a las columnas reales del proyecto.
Basado en da Silva (2021) + Oueslati (2023).

IMPORTANTE: Usa la columna 'sentimiento' (no pilares) como stance.
Filtra por sentimiento != 2 (solo analiza contenido relevante: 1, 0, -1)

NORMALIZACIÓN (v3):
  ScoreOP_raw   ∈ (-∞, +∞)   — valor bruto acumulado
  ScoreOP_sup   ∈ ( 0, +∞)   — máximo posible (denominador)
  ScoreOP_norm  ∈ [-1,  1]   — raw / sup
  ScoreOP_pct   ∈ [ 0,100]   — (norm + 1) / 2 × 100
    · 100 = toda la conversación es máximamente positiva
    ·   0 = toda la conversación es máximamente negativa
    ·  50 = perfecta polarización o contenido neutro

  El ScoreOP_pct de red se calcula como promedio simple de los
  ScoreOP_pct individuales de sus posts (opción A: cada red pesa igual).
  El ScoreOP_pct global es el promedio simple de los ScoreOP_pct de red.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List
import json


class ScoreOPCalculator:
    """
    Calcula Score de Posición Social ponderado por esfuerzo social.

    Fórmula por post:
      ScoreOP_raw(Post_i) = 0.4 × [Stance(Post_i) × I(Post_i) × F(Post_i)]
                           + 0.6 × Σ_k [Stance(Com_k) × I(Com_k)]

      ScoreOP_sup(Post_i) = 0.4 × I(Post_i) × F(Post_i)
                           + 0.6 × Σ_k I(Com_k)          ← máximo posible

      ScoreOP_norm(Post_i) = ScoreOP_raw / ScoreOP_sup    ∈ [-1, 1]
      ScoreOP_pct(Post_i)  = (ScoreOP_norm + 1) / 2 × 100 ∈ [0, 100]

    Donde:
      I(x) = 1+ (R × W_reac) + (S × W_comp) + (C × W_comm)
      W    = Pesos dinámicos: (TSE / M) / Total_Métrica
      F    = Factor de plataforma (solo posts)
      TSE  = Total Sample Engagement (contenido con sentimiento != 2)
    """

    def __init__(self, plataforma: str):
        self.plataforma = plataforma.lower()
        self.config = self._get_platform_config()

    def _get_platform_config(self) -> Dict:
        configs = {
            'reddit': {
                'M': 1,
                'col_id_post': 'id_raiz',
                'col_id_comentario': 'id_propio',
                'col_reacciones': None,
                'col_compartidos': None,
                'col_comentarios': 'comments',
                'identificar_post': lambda row: row.get('tipo', '').lower() == 'post',
                'identificar_comentario': lambda row: row.get('tipo', '').lower() in ['comentario', 'comment'],
                'get_post_id': lambda row: row.get('id_raiz'),
                'match_comentario_a_post': lambda com, post: com.get('id_raiz') == post.get('id_raiz'),
                'col_vistas': None, 'col_suscriptores': None, 'col_seguidores': None,
            },
            'youtube': {
                'M': 2,
                'col_id_post': 'id_video',
                'col_id_comentario': None,
                'col_reacciones': 'likes',
                'col_compartidos': None,
                'col_comentarios': 'comments',
                'identificar_post': lambda row: row.get('tipo', '').lower() in ['video', 'post'],
                'identificar_comentario': lambda row: row.get('tipo', '').lower() in ['comentario', 'comment'],
                'get_post_id': lambda row: row.get('id_video'),
                'match_comentario_a_post': lambda com, post: com.get('id_video') == post.get('id_video'),
                'col_vistas': 'vistas', 'col_suscriptores': 'suscriptores', 'col_seguidores': None,
            },
            'bluesky': {
                'M': 3,
                'col_id_post': 'uri',
                'col_id_comentario': 'uri',
                'col_reacciones': 'likes',
                'col_compartidos': 'reposts',
                'col_comentarios': 'replies',
                'identificar_post': lambda row: row.get('tipo', '').lower() == 'post',
                'identificar_comentario': lambda row: row.get('tipo', '').lower() in ['comentario', 'comment'],
                'get_post_id': lambda row: row.get('uri'),
                'match_comentario_a_post': lambda com, post: com.get('parent_uri') == post.get('uri'),
                'col_vistas': None, 'col_suscriptores': None, 'col_seguidores': 'seguidores',
            },

            'telegram': {
                # M=2: dos dimensiones de engagement (forwards + replies),
                # mismo criterio numérico que YouTube (likes + comments).
                'M': 2,
                'col_id_post': 'uri',
                'col_id_comentario': 'uri',
                # IMPORTANTE: 'reactions' se excluye deliberadamente, igual que
                # Reddit excluye su 'score' (votos netos). Las reacciones des
                # Telegram (🔥😱👍💩...) tienen valencia mixta — sumarlas todas
                # como si fueran aprobación pura mezclaría apoyo y rechazo en
                # un solo número, inconsistente con el resto del sistema.
                # 'likes' tampoco sirve: siempre viene en 0 desde la API.
                'col_reacciones': None,
                # 'forwards' es señal de aprobación inequívoca (difundir el
                # mensaje), equivalente a 'reposts' de Bluesky.
                'col_compartidos': 'reposts',
                'col_comentarios': 'replies',
                'identificar_post': lambda row: row.get('tipo', '').lower() == 'post',
                'identificar_comentario': lambda row: row.get('tipo', '').lower() in ['comentario', 'comment'],
                'get_post_id': lambda row: row.get('uri'),
                'match_comentario_a_post': lambda com, post: com.get('parent_uri') == post.get('uri'),
                # Telegram sí tiene vistas por mensaje Y suscriptores por
                # canal (como YouTube) — no tiene 'seguidores' individuales
                # por usuario como Bluesky.
                'col_vistas': 'vistas', 'col_suscriptores': 'seguidores', 'col_seguidores': None,
            },
        }
        return configs.get(self.plataforma, configs['reddit'])

    # ------------------------------------------------------------------ #
    #  Factor de plataforma F                                              #
    # ------------------------------------------------------------------ #

    def calcular_factor_plataforma(self, df_posts: pd.DataFrame) -> pd.Series:
        factores = pd.Series(1.0, index=df_posts.index)

        if self.plataforma == 'youtube':
            col_v = self.config['col_vistas']
            col_s = self.config['col_suscriptores']
            V = pd.to_numeric(df_posts[col_v], errors='coerce').fillna(0) if col_v and col_v in df_posts.columns else pd.Series(0, index=df_posts.index)
            S = pd.to_numeric(df_posts[col_s], errors='coerce').fillna(0) if col_s and col_s in df_posts.columns else pd.Series(0, index=df_posts.index)
            V_total, S_total = V.sum(), S.sum()
            f_v = (1 + np.log1p(V / V_total)) if V_total > 0 else pd.Series(1.0, index=df_posts.index)
            f_s = (1 + np.log1p(S / S_total)) if S_total > 0 else pd.Series(1.0, index=df_posts.index)
            factores = f_v * f_s

        elif self.plataforma == 'bluesky':
            col_f = self.config['col_seguidores']
            F = pd.to_numeric(df_posts[col_f], errors='coerce').fillna(0) if col_f and col_f in df_posts.columns else pd.Series(0, index=df_posts.index)
            F_total = F.sum()
            factores = (1 + np.log1p(F / F_total)) if F_total > 0 else pd.Series(1.0, index=df_posts.index)

        elif self.plataforma == 'telegram':
            # Igual que YouTube: combina alcance del mensaje (vistas) con
            # el tamaño del canal (suscriptores) — Telegram no tiene
            # seguidores por usuario individual, solo por canal.
            col_v = self.config['col_vistas']
            col_s = self.config['col_suscriptores']
            V = pd.to_numeric(df_posts[col_v], errors='coerce').fillna(0) if col_v and col_v in df_posts.columns else pd.Series(0, index=df_posts.index)
            S = pd.to_numeric(df_posts[col_s], errors='coerce').fillna(0) if col_s and col_s in df_posts.columns else pd.Series(0, index=df_posts.index)
            V_total, S_total = V.sum(), S.sum()
            f_v = (1 + np.log1p(V / V_total)) if V_total > 0 else pd.Series(1.0, index=df_posts.index)
            f_s = (1 + np.log1p(S / S_total)) if S_total > 0 else pd.Series(1.0, index=df_posts.index)
            factores = f_v * f_s    

        return factores

    # ------------------------------------------------------------------ #
    #  Filtrado de contenido relevante (excluye sentimiento == 2)          #
    # ------------------------------------------------------------------ #

    def filtrar_contenido_relevante(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Filtra SOLO contenido con sentimiento ∈ {-1, 0, 1}.
        Excluye sentimiento = 2 (no relacionado / spam).
        Aplica tanto a posts como a comentarios — ningún elemento con
        sentimiento = 2 debe contribuir al cálculo.
        """
        df = df.copy()
        df['sentimiento_num'] = pd.to_numeric(df['sentimiento'], errors='coerce')
        df_relevante = df[df['sentimiento_num'].isin([1, 0, -1])].copy()

        print(f"  📊 Contenido filtrado (sentimiento != 2):")
        print(f"     Total filas: {len(df)}")
        print(f"     Relevantes (sent ∈ {{1,0,-1}}): {len(df_relevante)}")
        print(f"     Excluidos  (sent = 2): {len(df) - len(df_relevante)}")

        return df_relevante

    # ------------------------------------------------------------------ #
    #  Pesos dinámicos TSE                                                 #
    # ------------------------------------------------------------------ #

    def calcular_tse_y_pesos(self, df: pd.DataFrame) -> Dict:
        M = self.config['M']
        R = S = C = 0.0

        if self.config['col_reacciones'] and self.config['col_reacciones'] in df.columns:
            R = df[self.config['col_reacciones']].fillna(0).astype(float).sum()
        if self.config['col_compartidos'] and self.config['col_compartidos'] in df.columns:
            S = df[self.config['col_compartidos']].fillna(0).astype(float).sum()
        if self.config['col_comentarios'] and self.config['col_comentarios'] in df.columns:
            C = df[self.config['col_comentarios']].fillna(0).astype(float).sum()

        TSE = R + S + C
        if TSE == 0:
            print("  ⚠️ TSE = 0, no hay engagement")
            return {'TSE': 0, 'R': 0, 'S': 0, 'C': 0,
                    'W_reac': 0, 'W_comp': 0, 'W_comm': 0, 'M': M}

        W_reac = (TSE / M) / R if R > 0 else 0.0
        W_comp = (TSE / M) / S if S > 0 else 0.0
        W_comm = (TSE / M) / C if C > 0 else 0.0

        return {'TSE': TSE, 'R': R, 'S': S, 'C': C,
                'W_reac': W_reac, 'W_comp': W_comp, 'W_comm': W_comm, 'M': M}

    # ------------------------------------------------------------------ #
    #  Impacto I(x)                                                        #
    # ------------------------------------------------------------------ #

    def calcular_impacto(self, row: pd.Series, pesos: Dict) -> float:
        impacto = 1.0
        for col_key, w_key in [('col_reacciones', 'W_reac'),
                                ('col_compartidos', 'W_comp'),
                                ('col_comentarios', 'W_comm')]:
            col = self.config[col_key]
            if col:
                val = row.get(col, 0)
                if pd.notna(val):
                    impacto += float(val) * pesos[w_key]
        return impacto

    def obtener_stance(self, row: pd.Series) -> int:
        sent = row.get('sentimiento_num', 0)
        return int(sent) if pd.notna(sent) and sent in [1, 0, -1] else 0

    # ------------------------------------------------------------------ #
    #  Cálculo principal                                                   #
    # ------------------------------------------------------------------ #

    def calcular_scoreop(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula ScoreOP_raw, ScoreOP_sup, ScoreOP_norm y ScoreOP_pct
        para cada post.

        ScoreOP_raw  ∈ (-∞, +∞)
        ScoreOP_sup  ∈ ( 0, +∞)   — denominador (máximo posible)
        ScoreOP_norm ∈ [-1,  1]   — raw / sup
        ScoreOP_pct  ∈ [ 0,100]   — (norm + 1) / 2 × 100
        """
        # 1. Filtrar sentimiento != 2 (posts Y comentarios)
        df_rel = self.filtrar_contenido_relevante(df)
        if df_rel.empty:
            print("  ⚠️ No hay contenido relevante")
            return pd.DataFrame()

        # 2. Pesos dinámicos (calculados sobre toda la red filtrada)
        pesos = self.calcular_tse_y_pesos(df_rel)
        print(f"\n  📊 Pesos dinámicos:")
        print(f"     TSE={pesos['TSE']:.0f}  M={pesos['M']}")
        print(f"     W_reac={pesos['W_reac']:.4f}  W_comp={pesos['W_comp']:.4f}  W_comm={pesos['W_comm']:.4f}")

        # 3. Identificar posts relevantes
        posts = df_rel[df_rel.apply(self.config['identificar_post'], axis=1)].copy()
        if posts.empty:
            print("  ⚠️ No hay posts relevantes")
            return pd.DataFrame()

        print(f"\n  🔍 Procesando {len(posts)} posts…")
        factores_serie = self.calcular_factor_plataforma(posts)

        resultados = []

        for idx, post_row in posts.iterrows():
            post_id    = self.config['get_post_id'](post_row)
            stance_p   = self.obtener_stance(post_row)
            impacto_p  = self.calcular_impacto(post_row, pesos)
            factor     = float(factores_serie.get(idx, 1.0))

            # Comentarios que pertenecen a este post Y tienen sentimiento != 2
            comentarios = df_rel[
                df_rel.apply(self.config['identificar_comentario'], axis=1) &
                df_rel.apply(
                    lambda row: self.config['match_comentario_a_post'](row, post_row),
                    axis=1
                )
            ]

            # Suma ponderada de comentarios: Σ [stance_k × I(com_k)]
            suma_com_raw = sum(
                self.obtener_stance(r) * self.calcular_impacto(r, pesos)
                for _, r in comentarios.iterrows()
            )
            # Suma de impactos (denominador comentarios)
            suma_com_sup = sum(
                self.calcular_impacto(r, pesos)
                for _, r in comentarios.iterrows()
            )

            # ── ScoreOP_raw ────────────────────────────────────────────
            scoreop_raw = (
                0.4 * (stance_p * impacto_p * factor)
                + 0.6 * suma_com_raw
            )

            # ── ScoreOP_sup (denominador = máximo posible si todos positivos) ──
            scoreop_sup = (
                0.4 * impacto_p * factor
                + 0.6 * suma_com_sup
            )

            # ── Normalización ──────────────────────────────────────────
            if scoreop_sup > 0:
                scoreop_norm = scoreop_raw / scoreop_sup          # ∈ [-1, 1]
            else:
                scoreop_norm = 0.0

            scoreop_pct = (scoreop_norm + 1.0) / 2.0 * 100.0     # ∈ [0, 100]

            fila_original  = post_row.to_dict()
            fila_calculada = {
                'post_id':                  post_id,
                'contenido_post':           str(post_row.get('contenido', '')),
                'stance_post':              stance_p,
                'impacto_post':             round(impacto_p, 4),
                'factor_post':              round(factor, 4),
                'num_comentarios':          len(comentarios),
                'suma_impacto_comentarios': round(suma_com_raw, 4),
                'factor_plataforma':        round(factor, 4),
                # ── Nuevas columnas normalizadas ──────────────────────
                'ScoreOP':                  round(scoreop_raw,  4),   # raw (retrocompat.)
                'ScoreOP_sup':              round(scoreop_sup,  4),   # denominador
                'ScoreOP_norm':             round(scoreop_norm, 4),   # ∈ [-1, 1]
                'ScoreOP_pct':              round(scoreop_pct,  2),   # ∈ [0, 100]
                # ─────────────────────────────────────────────────────
                'topic': post_row.get('topic', 'no relacionado'),
            }
            resultados.append({**fila_original, **fila_calculada})

        df_resultado = pd.DataFrame(resultados)

        # if not df_resultado.empty:
        #     sup_total = df_resultado['ScoreOP_sup'].sum()
        #     if sup_total > 0:
        #         df_resultado['ScoreOP_norm_red'] = (
        #             df_resultado['ScoreOP'] / sup_total
        #         ).clip(-1, 1)
        #         df_resultado['ScoreOP_pct'] = (
        #             df_resultado['ScoreOP_norm_red'] + 1.0
        #         ) / 2.0 * 100.0
        #     else:
        #         df_resultado['ScoreOP_pct'] = 50.0
        #     print(f"\n  ✅ ScoreOP calculado para {len(df_resultado)} posts")
        #     print(f"     ScoreOP_raw  — media: {df_resultado['ScoreOP'].mean():.2f}  "
        #           f"min: {df_resultado['ScoreOP'].min():.2f}  max: {df_resultado['ScoreOP'].max():.2f}")
        #     print(f"     ScoreOP_pct  — media: {df_resultado['ScoreOP_pct'].mean():.1f}%  "
        #           f"min: {df_resultado['ScoreOP_pct'].min():.1f}%  max: {df_resultado['ScoreOP_pct'].max():.1f}%")

        return df_resultado


# ======================================================================
# Funciones de orquestación (sin cambios de interfaz)
# ======================================================================

def calcular_scoreop_por_dataset(data_folder: str, plataforma: str) -> pd.DataFrame:
    print(f"\n{'='*60}\nCALCULANDO SCOREOP: {plataforma.upper()}\n{'='*60}")
    folder = Path(data_folder)

    archivos_posibles = [
        folder / f"{plataforma}_global_dataset_analizado.csv",
        folder / f"{plataforma}_dataset_analizado.csv",
        folder / f"{plataforma}_analizado.csv",
    ]
    archivo = next((f for f in archivos_posibles if f.exists()), None)
    if not archivo:
        print(f"❌ No se encontró archivo analizado para {plataforma}")
        return pd.DataFrame()

    print(f"📂 Archivo: {archivo.name}")
    try:
        with open(archivo, 'r', encoding='utf-8') as f:
            sep = ';' if ';' in f.readline() else ','
        df = pd.read_csv(archivo, sep=sep, encoding='utf-8', engine='python')
        print(f"  📊 Filas cargadas: {len(df)}")
    except Exception as e:
        print(f"❌ Error cargando {archivo}: {e}")
        return pd.DataFrame()

    if 'sentimiento' not in df.columns:
        print("❌ El archivo no tiene columna 'sentimiento'")
        return pd.DataFrame()

    calculator  = ScoreOPCalculator(plataforma)
    df_scoreop  = calculator.calcular_scoreop(df)
    if not df_scoreop.empty:
        df_scoreop['plataforma'] = plataforma
    return df_scoreop


def calcular_scoreop_completo(data_folder: str, plataformas: List[str] = None) -> Dict:
    if plataformas is None:
        plataformas = ['reddit', 'youtube', 'bluesky', 'telegram']

    print(f"\n{'='*70}\nCÁLCULO DE SCOREOP - ANÁLISIS COMPLETO\n{'='*70}")
    print(f"Carpeta: {data_folder} | Plataformas: {', '.join(plataformas)}")

    resultados      = {}
    dfs_consolidado = []

    for plataforma in plataformas:
        df_scoreop = calcular_scoreop_por_dataset(data_folder, plataforma)
        if not df_scoreop.empty:
            resultados[plataforma] = df_scoreop
            dfs_consolidado.append(df_scoreop)
            output_path = Path(data_folder) / f"{plataforma}_scoreop.csv"
            df_scoreop.to_csv(output_path, index=False, sep=';', encoding='utf-8')
            print(f"  💾 Guardado: {output_path.name}")

    if dfs_consolidado:
        df_consolidado = pd.concat(dfs_consolidado, ignore_index=True)
        resultados['consolidado'] = df_consolidado

        # ── Calcular ScoreOP_pct de red = promedio de ScoreOP_pct de posts ──
        if 'ScoreOP_pct' in df_consolidado.columns and 'ScoreOP_sup' in df_consolidado.columns:
            def _agg_pct_red(grp):
                s = grp['ScoreOP'].sum()       # ScoreOP_raw acumulado
                d = grp['ScoreOP_sup'].sum()   # denominador acumulado
                return round((s / d + 1.0) / 2.0 * 100.0, 2) if d > 0 else 50.0

            def _scoreop_pct(grp):
                s = grp['ScoreOP'].sum()
                d = grp['ScoreOP_sup'].sum()
                return round((s / d + 1.0) / 2.0 * 100.0, 2) if d > 0 else 50.0

            scoreop_pct_por_red = (
                df_consolidado.groupby('plataforma')
                .apply(_scoreop_pct)
                .to_dict()
            )

            # N_r = posts + comentarios por red
            col_com = 'num_comentarios' if 'num_comentarios' in df_consolidado.columns else None
            N_por_red = {}
            for red, grp in df_consolidado.groupby('plataforma'):
                n_posts = len(grp)
                n_com   = int(grp[col_com].fillna(0).sum()) if col_com else 0
                N_por_red[red] = n_posts + n_com

            total_N = sum(N_por_red.values()) or 1
            scoreop_pct_global = round(
                sum(scoreop_pct_por_red[r] * N_por_red.get(r, 0) for r in scoreop_pct_por_red)
                / total_N,
                2
            )
        else:
            scoreop_pct_por_red = {}
            scoreop_pct_global  = 50.0

        output_consolidado = Path(data_folder) / "scoreop_consolidado.csv"
        df_consolidado.to_csv(output_consolidado, index=False, sep=';', encoding='utf-8')

        print(f"\n{'='*70}\n✅ SCOREOP COMPLETADO\n{'='*70}")
        print(f"  📊 Total posts: {len(df_consolidado)}")
        print(f"  📈 ScoreOP_pct global: {scoreop_pct_global:.1f}%")
        for red, pct in scoreop_pct_por_red.items():
            print(f"     {red}: {pct:.1f}%")

        # Top 10 por ScoreOP_pct
        top10 = df_consolidado.nlargest(10, 'ScoreOP_pct')[
            ['plataforma', 'contenido_post', 'stance_post', 'num_comentarios',
             'ScoreOP', 'ScoreOP_pct']
        ]

        resumen = {
            'total_posts':            len(df_consolidado),
            'posts_por_plataforma':   df_consolidado.groupby('plataforma').size().to_dict(),
            'scoreop_pct_global':     scoreop_pct_global,
            'scoreop_pct_por_red':    scoreop_pct_por_red,
            'scoreop_raw_stats': {
                'media':   float(df_consolidado['ScoreOP'].mean()),
                'mediana': float(df_consolidado['ScoreOP'].median()),
                'min':     float(df_consolidado['ScoreOP'].min()),
                'max':     float(df_consolidado['ScoreOP'].max()),
                'std':     float(df_consolidado['ScoreOP'].std()),
            },
            'scoreop_pct_stats': {
                'media':   float(df_consolidado['ScoreOP_pct'].mean()),
                'mediana': float(df_consolidado['ScoreOP_pct'].median()),
                'min':     float(df_consolidado['ScoreOP_pct'].min()),
                'max':     float(df_consolidado['ScoreOP_pct'].max()),
                'std':     float(df_consolidado['ScoreOP_pct'].std()),
            } if 'ScoreOP_pct' in df_consolidado.columns else {},
            'top_10_posts': top10.to_dict('records'),
        }

        resumen_path = Path(data_folder) / "scoreop_resumen.json"
        with open(resumen_path, 'w', encoding='utf-8') as f:
            json.dump(resumen, f, ensure_ascii=False, indent=2)
        print(f"  📋 Resumen JSON: {resumen_path.name}")

    return resultados


def ejecutar_scoreop_desde_logica(u_conf):
    try:
        output_folder = u_conf.general["output_folder"]
        folder        = Path(output_folder)
        plataformas   = [
            p for p in ['reddit', 'youtube', 'bluesky', 'telegram']
            if list(folder.glob(f"{p}*_analizado.csv"))
        ]
        if not plataformas:
            print("⚠️ No se encontraron datasets analizados para calcular ScoreOP")
            return None
        return calcular_scoreop_completo(output_folder, plataformas)
    except Exception as e:
        print(f"❌ Error calculando ScoreOP: {e}")
        import traceback; traceback.print_exc()
        return None


# =====================================================
# TESTING
# =====================================================

# if __name__ == "__main__":
#     from types import SimpleNamespace
    
#     # Test con datos de prueba
#     test_config = SimpleNamespace(
#         general={
#             "output_folder": "/home/romina/pruebas_telegram" #"/home/rrss/proyecto_web/RRSS_version_stance/project_web/Web_Proyecto/datos/admin/regularización_inmigrantes"  # Cambia a tu ruta de prueba
#         }
#     )
    
#     # Crear datos de prueba
#     folder = Path(test_config.general["output_folder"])
#     folder.mkdir(exist_ok=True)
    
#     # Reddit de prueba
#     # df_reddit_test = pd.DataFrame({
#     #     'tipo': ['Post', 'Comentario', 'Comentario', 'Post'],
#     #     'id_raiz': ['post1', 'post1', 'post1', 'post2'],
#     #     'id_propio': ['post1', 'com1', 'com2', 'post2'],
#     #     'contenido': ['Post sobre transporte', 'Comentario positivo', 'Comentario negativo', 'Otro post'],
#     #     'sentimiento': [1, 1, -1, 0],
#     #     'topic': ['mejora servicio', 'eficiencia', 'coste alto', 'informativo'],
#     #     'likes': [10, 5, 3, 8],
#     #     'comments': [2, 0, 0, 1],
#     #     'usuario': ['user1', 'user2', 'user3', 'user4'],
#     #     'id_anonimo': ['hash1', 'hash2', 'hash3', 'hash4'],
#     #     'fecha': ['2026-04-01'] * 4
#     # })
    
#     # df_reddit_test.to_csv(folder / 'reddit_global_dataset_analizado.csv', index=False, sep=';')
    
#     # Ejecutar
#     print("🧪 EJECUTANDO TEST DE SCOREOP\n")
#     resultados = calcular_scoreop_completo(str(folder))
    
#     if 'telegram' in resultados:
#         print("\n📊 RESULTADOS REDDIT:")
#         print(resultados['telegram'])
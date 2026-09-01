"""
metrics.py  –  PillarOP: ScoreOP model applied to political-acceptance pillars.

Each pillar column (legitimacion, efectividad, justicia_equidad,
confianza_institucional) contains a stance value:
    1  → positive stance (supports / validates the pillar dimension)
    0  → neutral / ambiguous
   -1  → negative stance (rejects / criticises the pillar dimension)
    2  → no relation → EXCLUDED

Formula (mirrors ScoreOP v3 architecture):

    The unit of analysis is the POST THREAD (same as ScoreOP).
    Comments are absorbed internally via the 40/60 rule.

    For each post thread t, per pillar p:

        raw(t, p) =
            0.4 × [stance_p(post_t) × I_p(post_t) × F(post_t)]   if post stance ∈ {-1,0,1}
          + 0.6 × Σ_k [stance_p(com_k) × I_p(com_k)]             comments with stance ∈ {-1,0,1}

        sup(t, p) =
            0.4 × I_p(post_t) × F(post_t)
          + 0.6 × Σ_k I_p(com_k)

    KEY: I_p uses weights W computed from TSE_p, where TSE_p is the total
    engagement of rows with stance ≠ 2 on pillar p specifically.
    Each pillar has its own TSE and its own W weights.
    This mirrors ScoreOP's filtrar_contenido_relevante (sentimiento ≠ 2).

NORMALISATION (v3 — consistent with ScoreOP):
    PillarOP_norm(p, r) = Σ raw / Σ sup  → [-1, 1]
    PillarOP_pct(p, r)  = (norm + 1) / 2 × 100  → [0, 100]

═══════════════════════════════════════════════════════════════════
COUNTS  (two distinct things — read carefully)
═══════════════════════════════════════════════════════════════════

  menciones_<pilar>   [UI table]
      Number of ROOT POSTS with stance ≠ 2 on that pillar.
      Comments are NEVER counted here.

  total_menciones   [UI table, per-network row]
      Number of ROOT POSTS with ≥1 active pillar (each post counted
      once regardless of how many pillars it covers).
      Always ≤ total posts in that network.

  N_r   [internal weight for global aggregation ONLY]
      Mirrors ScoreOP's N_r = n_posts_activos + n_comentarios_activos,
      where "activos" means the row has at least one pillar with stance ≠ 2.
      This is NEVER shown in the UI; it is only used in the weighted mean:

          PillarOP_pct_global(p) =
              Σ_r [ pct(p, r) × N_r ] / Σ_r N_r

═══════════════════════════════════════════════════════════════════
INVARIANT
═══════════════════════════════════════════════════════════════════
    total_menciones(red) ≤ n_posts(red) ≤ kpis.total (29 in example)
    total_menciones GLOBAL ≤ kpis.total + kpis.total_comentarios (34 in example)
═══════════════════════════════════════════════════════════════════
"""

import pandas as pd
import numpy as np
from pathlib import Path

_POST_TIPOS    = {'post', 'video', 'tweet', 'publicación', 'publicacion'}
_COMMENT_TIPOS = {'comentario', 'comment', 'reply', 'respuesta'}
_ANCHOR_CANDIDATES = ['id_raiz', 'id_video', 'uri', 'parent_id', 'post_id']


def _tiene_pilar_activo(row, pilares) -> bool:
    """True if ANY pillar in the row has stance ∈ {-1, 0, 1}."""
    for p in pilares:
        v = row.get(p, 2)
        try:
            if int(float(v)) in (-1, 0, 1):
                return True
        except (ValueError, TypeError):
            pass
    return False


class Metrics:
    PILARES = [
        'legitimacion',
        'efectividad',
        'justicia_equidad',
        'confianza_institucional',
    ]

    _COL_REAC = ['likes']
    _COL_COMP = ['reposts', 'shares']
    _COL_COMM = ['comments', 'replies', 'num_comentarios']

    def __init__(self):
        pass

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _find_col(self, df, candidates):
        for c in candidates:
            if c in df.columns:
                return c
        return None

    def _find_anchor_col(self, df):
        for c in _ANCHOR_CANDIDATES:
            if c in df.columns and df[c].notna().any():
                return c
        return None

    def _calcular_pesos_dinamicos(self, df):
        """
        Compute dynamic weights from df.

        df must already be filtered to only the rows relevant for the current
        calculation (sentimiento ≠ 2 for ScoreOP, pilar ≠ 2 for PillarOP).

        The engagement values used are the declared platform metrics on each
        row: likes/reposts/comments as stored in the dataset.  For the
        'comments' column specifically, only the declared values of the
        filtered rows count — a row excluded by the filter does NOT
        contribute its 'comments' value to C, even if that value is > 0.
        """
        col_r = self._find_col(df, self._COL_REAC)
        col_s = self._find_col(df, self._COL_COMP)
        col_c = self._find_col(df, self._COL_COMM)

        R = pd.to_numeric(df[col_r], errors='coerce').fillna(0).sum() if col_r else 0.0
        S = pd.to_numeric(df[col_s], errors='coerce').fillna(0).sum() if col_s else 0.0
        C = pd.to_numeric(df[col_c], errors='coerce').fillna(0).sum() if col_c else 0.0

        TSE = R + S + C
        M   = sum(1 for x in [R, S, C] if x > 0)

        if M == 0 or TSE == 0:
            return 1.0, 1.0, 1.0, col_r, col_s, col_c

        w_r = (TSE / M) / R if R > 0 else 0.0
        w_s = (TSE / M) / S if S > 0 else 0.0
        w_c = (TSE / M) / C if C > 0 else 0.0

        return w_r, w_s, w_c, col_r, col_s, col_c

    def _calcular_impacto_serie(self, df, w_r, w_s, w_c, col_r, col_s, col_c):
        r = pd.to_numeric(df[col_r], errors='coerce').fillna(0) if col_r else pd.Series(0.0, index=df.index)
        s = pd.to_numeric(df[col_s], errors='coerce').fillna(0) if col_s else pd.Series(0.0, index=df.index)
        c = pd.to_numeric(df[col_c], errors='coerce').fillna(0) if col_c else pd.Series(0.0, index=df.index)
        return 1.0 + (r * w_r + s * w_s + c * w_c)

    def _calcular_factor_plataforma(self, df):
        factores = pd.Series(1.0, index=df.index)

        if 'tipo' in df.columns:
            es_post_mask = df['tipo'].fillna('').str.strip().str.lower().isin(_POST_TIPOS)
        else:
            es_post_mask = pd.Series(True, index=df.index)

        if 'plataforma' not in df.columns:
            return factores

        plat_lower = df['plataforma'].fillna('').str.lower()

        mask_yt = es_post_mask & plat_lower.str.contains('youtube', na=False)
        if mask_yt.any():
            df_yt = df[mask_yt]
            V = pd.to_numeric(df_yt['vistas'], errors='coerce').fillna(0) if 'vistas' in df.columns else pd.Series(0, index=df_yt.index)
            S = pd.to_numeric(df_yt['suscriptores'], errors='coerce').fillna(0) if 'suscriptores' in df.columns else pd.Series(0, index=df_yt.index)
            V_total, S_total = V.sum(), S.sum()
            f_v = (1 + np.log1p(V / V_total)) if V_total > 0 else pd.Series(1.0, index=df_yt.index)
            f_s = (1 + np.log1p(S / S_total)) if S_total > 0 else pd.Series(1.0, index=df_yt.index)
            factores[mask_yt] = (f_v * f_s).values

        mask_bs = es_post_mask & plat_lower.str.contains('bluesky', na=False)
        if mask_bs.any():
            df_bs = df[mask_bs]
            F_seg = pd.to_numeric(df_bs['seguidores'], errors='coerce').fillna(0) if 'seguidores' in df.columns else pd.Series(0, index=df_bs.index)
            F_total = F_seg.sum()
            if F_total > 0:
                factores[mask_bs] = (1 + np.log1p(F_seg / F_total)).values

        return factores

    # ------------------------------------------------------------------ #
    #  Per-network PillarOP                                               #
    # ------------------------------------------------------------------ #

    def _procesar_red(self, df_red: pd.DataFrame) -> dict:
        """
        Processes one network's data.

        TSE and weights are computed PER PILAR, using only rows where that
        specific pilar has stance ≠ 2.  This mirrors ScoreOP's behaviour
        where TSE is computed only on rows with sentimiento ≠ 2.

        Returns a dict with:
          - per-pilar results (raw, sup, norm, pct, n, pos, neu, neg)
          - '_n_posts_activos'    : posts with ≥1 active pillar  [UI: total_menciones]
          - '_N_r_ponderacion'    : posts_activos + comentarios_activos  [internal weight]
          - '_pesos'              : dict of per-pilar weight dicts
        """
        if df_red.empty:
            return self._empty_result()

        df_red = df_red.copy()

        # Factor de plataforma: computed once, does not depend on pillar.
        df_red['_F'] = self._calcular_factor_plataforma(df_red)

        # ── Type masks ──────────────────────────────────────────────────
        if 'tipo' in df_red.columns:
            tipo_lower = df_red['tipo'].fillna('').str.strip().str.lower()
            es_post    = tipo_lower.isin(_POST_TIPOS)
            es_comment = tipo_lower.isin(_COMMENT_TIPOS)
        else:
            es_post    = pd.Series(True,  index=df_red.index)
            es_comment = pd.Series(False, index=df_red.index)

        # Bluesky y Telegram usan uri (propio) / parent_uri (apunta al post);
        # Reddit/YouTube usan id_raiz/id_video compartido entre post y comentario.
        tiene_esquema_uri = (
            'parent_uri' in df_red.columns and 'uri' in df_red.columns and
            df_red['parent_uri'].notna().any() and df_red['uri'].notna().any()
        )
        if tiene_esquema_uri:
            df_red['_anchor'] = df_red['uri'].where(es_post, df_red['parent_uri'])
            anchor_col = '_anchor'
        else:
            anchor_col = self._find_anchor_col(df_red)

        # Track which posts/comments are active on ANY pillar (for N counts).
        posts_active_any    = pd.Series(False, index=df_red.index)
        comments_active_any = pd.Series(False, index=df_red.index)

        res          = {}
        pesos_record = {}   # per-pilar weights stored for transparency

        for pilar in self.PILARES:
            if pilar not in df_red.columns:
                res[pilar] = self._empty_pilar()
                continue

            scores = pd.to_numeric(df_red[pilar], errors='coerce').fillna(2)
            active = scores.isin([-1, 0, 1])   # rows where this pilar ≠ 2

            posts_active_pilar    = es_post    & active
            comments_active_pilar = es_comment & active

            # Accumulate union masks for N_r
            posts_active_any    |= posts_active_pilar
            comments_active_any |= comments_active_pilar

            if posts_active_pilar.sum() == 0:
                res[pilar] = self._empty_pilar()
                continue

            # ── Per-pilar TSE and weights ────────────────────────────────
            # Only rows where THIS pilar ≠ 2 feed into TSE.
            # This means the declared 'comments' value of a row with
            # pilar=2 is NOT included in C, even if that value > 0.
            df_pilar_activo = df_red[active]
            w_r, w_s, w_c, col_r, col_s, col_c = self._calcular_pesos_dinamicos(
                df_pilar_activo
            )
            pesos_record[pilar] = {
                'w_reac': round(w_r, 6),
                'w_comp': round(w_s, 6),
                'w_comm': round(w_c, 6),
            }

            # ── Per-pilar impacts on ALL rows ────────────────────────────
            # Weights come from the filtered TSE above; impacts are computed
            # on the full df_red so that _apply_40_60 can look up any row.
            # Rows with pilar=2 get an impact value but are never selected
            # by _apply_40_60, so they don't contribute to the score.
            df_red['_I']     = self._calcular_impacto_serie(
                df_red, w_r, w_s, w_c, col_r, col_s, col_c
            )
            df_red['_I_eff'] = df_red['_I'] * df_red['_F']

            # ── 40/60 aggregation ────────────────────────────────────────
            if anchor_col is None:
                valid_I_eff  = df_red.loc[active, '_I_eff']
                pillarop_raw = float((scores[active] * valid_I_eff).sum())
                pillarop_sup = float(valid_I_eff.sum())
            else:
                pillarop_raw, pillarop_sup = self._apply_40_60(
                    df_red, scores, active, es_post, es_comment, anchor_col
                )

            # ── Normalisation v3 ─────────────────────────────────────────
            if pillarop_sup > 0:
                pillarop_norm = pillarop_raw / pillarop_sup
            else:
                pillarop_norm = 0.0
            pillarop_pct = round((pillarop_norm + 1.0) / 2.0 * 100.0, 2)

            post_scores = scores[posts_active_pilar]
            res[pilar] = {
                'raw':  round(pillarop_raw,  4),
                'sup':  round(pillarop_sup,  4),
                'norm': round(pillarop_norm, 4),
                'pct':  pillarop_pct,
                'n':    int(posts_active_pilar.sum()),
                'pos':  int((post_scores ==  1).sum()),
                'neu':  int((post_scores ==  0).sum()),
                'neg':  int((post_scores == -1).sum()),
            }

        # ── Compute the two distinct N values ───────────────────────────
        n_posts_activos    = int((es_post    & posts_active_any).sum())
        n_comments_activos = int((es_comment & comments_active_any).sum())
        N_r_ponderacion    = n_posts_activos + n_comments_activos

        res['_n_posts_activos'] = n_posts_activos
        res['_N_r_ponderacion'] = N_r_ponderacion
        res['_pesos']           = pesos_record   # now a dict of per-pilar weight dicts

        df_red.drop(columns=['_F', '_I', '_I_eff', '_anchor'], inplace=True, errors='ignore')
        return res

    def _apply_40_60(self, df, scores, active, es_post, es_comment, anchor_col):
        """
        40/60 aggregation for one pillar.

        Uses '_I' and '_I_eff' columns already written into df for the
        current pilar iteration.

        raw += 0.4×(stance_post × I_eff_post) + 0.6×Σ(stance_com × I_com)
        sup += 0.4×I_eff_post                  + 0.6×Σ I_com

        Note: only rows with active=True (pilar ≠ 2) are used for stance
        calculations, ensuring pilar=2 rows never contribute to raw/sup.
        """
        pillarop_raw = 0.0
        pillarop_sup = 0.0

        posts_df = df[es_post & active]

        comments_df     = df[es_comment]
        comments_active = comments_df[scores[comments_df.index].isin([-1, 0, 1])]

        if anchor_col in comments_active.columns and not comments_active.empty:
            com_by_anchor = comments_active.groupby(anchor_col)
        else:
            com_by_anchor = None

        processed_comment_idxs = set()

        for idx, post_row in posts_df.iterrows():
            anchor_val = post_row.get(anchor_col)
            stance_p   = int(scores[idx])
            I_eff_p    = float(post_row['_I_eff'])

            sum_com_raw = 0.0
            sum_com_sup = 0.0
            if anchor_val is not None and com_by_anchor is not None:
                try:
                    coms = com_by_anchor.get_group(anchor_val)
                    # Use '_I' (not '_I_eff') for comments — platform factor F
                    # applies only to posts, consistent with ScoreOP.
                    sum_com_raw = float((scores[coms.index] * coms['_I']).sum())
                    sum_com_sup = float(coms['_I'].sum())
                    processed_comment_idxs.update(coms.index.tolist())
                except KeyError:
                    pass

            pillarop_raw += 0.4 * (stance_p * I_eff_p) + 0.6 * sum_com_raw
            pillarop_sup += 0.4 * I_eff_p               + 0.6 * sum_com_sup

        # Orphan active comments (no matching post for this pillar)
        orphan_mask = (
            es_comment & active &
            ~df.index.isin(processed_comment_idxs)
        )
        if orphan_mask.any():
            orphan_scores = scores[orphan_mask]
            orphan_I      = df.loc[orphan_mask, '_I']
            pillarop_raw += float((orphan_scores * orphan_I).sum())
            pillarop_sup += float(orphan_I.sum())

        # Rows of unknown type
        other_mask = (~es_post & ~es_comment) & active
        if other_mask.any():
            pillarop_raw += float((scores[other_mask] * df.loc[other_mask, '_I_eff']).sum())
            pillarop_sup += float(df.loc[other_mask, '_I_eff'].sum())

        return pillarop_raw, pillarop_sup

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _empty_pilar(self) -> dict:
        return {'raw': 0.0, 'sup': 0.0, 'norm': 0.0, 'pct': 50.0,
                'n': 0, 'pos': 0, 'neu': 0, 'neg': 0}

    def _empty_result(self) -> dict:
        res = {p: self._empty_pilar() for p in self.PILARES}
        res['_n_posts_activos'] = 0
        res['_N_r_ponderacion'] = 0
        res['_pesos']           = {p: {'w_reac': 0.0, 'w_comp': 0.0, 'w_comm': 0.0}
                                   for p in self.PILARES}
        return res

    def _flatten_red(self, res_red: dict) -> dict:
        """
        Converts the internal per-pilar dict to the flat dict sent to the frontend.
        """
        out = {}
        pct_values_con_datos = []

        for pilar in self.PILARES:
            d = res_red.get(pilar, self._empty_pilar())
            out[f'PillarOP_{pilar}']      = d['raw']
            out[f'PillarOP_norm_{pilar}'] = d['norm']
            out[f'PillarOP_pct_{pilar}']  = d['pct']
            out[f'menciones_{pilar}']     = d['n']
            out[f'pos_{pilar}']           = d['pos']
            out[f'neu_{pilar}']           = d['neu']
            out[f'neg_{pilar}']           = d['neg']
            if d['n'] > 0:
                pct_values_con_datos.append(d['pct'])

        out['PillarOP_pct_medio'] = (
            round(sum(pct_values_con_datos) / len(pct_values_con_datos), 2)
            if pct_values_con_datos else 50.0
        )
        out['total_menciones'] = res_red.get('_n_posts_activos', 0)
        return out

    # ------------------------------------------------------------------ #
    #  Core entry point                                                    #
    # ------------------------------------------------------------------ #

    def calcular_pillarop_desde_df(self, df_total: pd.DataFrame) -> dict:
        """
        Main entry point.

        Global aggregation is weighted by N_r_ponderacion (posts_activos +
        comentarios_activos per network), consistent with ScoreOP's N_r.
        """
        if df_total.empty:
            return {}

        resultados_por_red: dict = {}
        pesos_por_red:      dict = {}

        if 'plataforma' not in df_total.columns:
            res_red = self._procesar_red(df_total)
            pesos_por_red['dataset']      = res_red.pop('_pesos', {})
            resultados_por_red['dataset'] = res_red
        else:
            for red in df_total['plataforma'].dropna().unique():
                df_red  = df_total[df_total['plataforma'] == red].copy()
                res_red = self._procesar_red(df_red)
                pesos_por_red[str(red)]      = res_red.pop('_pesos', {})
                resultados_por_red[str(red)] = res_red

        # ── Global aggregation ────────────────────────────────────────────
        global_accum = {
            p: {
                'sum_pct_x_Nr': 0.0,
                'sum_Nr':       0.0,
                'count_nets':   0,
                'total_n':      0,
                'pos': 0, 'neu': 0, 'neg': 0,
            }
            for p in self.PILARES
        }

        total_menciones_global = 0

        for red, res_red in resultados_por_red.items():
            N_r       = res_red.get('_N_r_ponderacion', 0)
            n_posts_r = res_red.get('_n_posts_activos', 0)
            total_menciones_global += n_posts_r

            for pilar in self.PILARES:
                d = res_red.get(pilar, self._empty_pilar())
                if d['n'] > 0:
                    global_accum[pilar]['sum_pct_x_Nr'] += d['pct'] * N_r
                    global_accum[pilar]['sum_Nr']       += N_r
                    global_accum[pilar]['count_nets']   += 1
                    global_accum[pilar]['total_n']      += d['n']
                    global_accum[pilar]['pos']          += d['pos']
                    global_accum[pilar]['neu']          += d['neu']
                    global_accum[pilar]['neg']          += d['neg']

        global_flat:       dict = {}
        pct_values_global: list = []

        for pilar in self.PILARES:
            acc = global_accum[pilar]
            pct_g = (
                round(acc['sum_pct_x_Nr'] / acc['sum_Nr'], 2)
                if acc['sum_Nr'] > 0 else 50.0
            )
            global_flat[f'PillarOP_pct_{pilar}'] = pct_g
            global_flat[f'menciones_{pilar}']    = acc['total_n']
            global_flat[f'pos_{pilar}']          = acc['pos']
            global_flat[f'neu_{pilar}']          = acc['neu']
            global_flat[f'neg_{pilar}']          = acc['neg']
            if acc['count_nets'] > 0:
                pct_values_global.append(pct_g)

        global_flat['PillarOP_pct_medio'] = (
            round(sum(pct_values_global) / len(pct_values_global), 2)
            if pct_values_global else 50.0
        )
        global_flat['total_menciones'] = total_menciones_global

        return {
            "global":  global_flat,
            "por_red": {red: self._flatten_red(res) for red, res in resultados_por_red.items()},
            "pesos":   pesos_por_red,
        }

    # Backward-compat alias
    def calcular_aceptacion_desde_df(self, df_total: pd.DataFrame) -> dict:
        return self.calcular_pillarop_desde_df(df_total)

    # ------------------------------------------------------------------ #
    #  Load CSV files and run                                              #
    # ------------------------------------------------------------------ #

    def calcular_aceptacion_pilares(self, u_conf) -> dict:
        folder   = Path(u_conf.general["output_folder"])
        archivos = list(folder.glob("*_pilares.csv"))

        if not archivos:
            raise FileNotFoundError(
                f"No se encontraron archivos *_pilares.csv en {folder}"
            )

        dfs = []
        for arch in archivos:
            try:
                with open(arch, 'r', encoding='utf-8') as f:
                    sep = ';' if ';' in f.readline() else ','
                df_temp = pd.read_csv(arch, sep=sep, encoding='utf-8', on_bad_lines='skip')

                if 'plataforma' not in df_temp.columns:
                    nombre = arch.name.lower()
                    if   'youtube'  in nombre: df_temp['plataforma'] = 'youtube'
                    elif 'reddit'   in nombre: df_temp['plataforma'] = 'reddit'
                    elif 'bluesky'  in nombre: df_temp['plataforma'] = 'bluesky'
                    elif 'telegram' in nombre: df_temp['plataforma'] = 'telegram'
                    else:                      df_temp['plataforma'] = 'otros'

                dfs.append(df_temp)
                print(f"  📂 {arch.name}: {len(df_temp)} filas cargadas")

            except Exception as e:
                print(f"  ❌ Error leyendo {arch.name}: {e}")

        if not dfs:
            raise RuntimeError("No se pudo leer ningún archivo de pilares.")

        df_total = pd.concat(dfs, ignore_index=True)
        print(f"  📊 Total combinado: {len(df_total)} filas")
        return self.calcular_pillarop_desde_df(df_total)
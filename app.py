# app.py — Fantrax Pool Hockey (CLEAN)
# ✅ Logos propriétaires dans /data
# ✅ Tableau: clic équipe -> sync Alignement
# ✅ Alignement: Actifs + Mineur encadrés, Banc + IR en expanders
# ✅ Déplacement: popup intelligent (IR/Banc/Normal) + toast + history + undo + delete
# ✅ IR: salaire exclu des plafonds + IR Date enregistrée (America/Toronto)
# ✅ Import Fantrax robuste
# ✅ Joueurs (data/Hockey.Players.csv) filtres + comparaison

# =====================================================
# IMPORTS
# =====================================================
import os
import io
import re
import html
import base64
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import quote, unquote

import pandas as pd
import streamlit as st

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload


# =====================================================
# GOOGLE DRIVE CONFIG (global)
# =====================================================
GDRIVE_FOLDER_ID = str(st.secrets.get("gdrive_oauth", {}).get("folder_id", "")).strip()


# =====================================================
# CONFIG STREAMLIT
# =====================================================
st.set_page_config(page_title="PMS", layout="wide")

# (optionnel) réduire padding top
st.markdown(
    """
    <style>
        .block-container { padding-top: 0.5rem; }
    </style>
    """,
    unsafe_allow_html=True
)


import base64
import os
import streamlit as st

def _img_b64(path: str) -> str:
    if not path or not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

# --- paths (adapte si besoin)
LOGO_POOL_FILE = os.path.join("data", "Logo_Pool.png")
# logo d'équipe selon ta logique existante:
# logo_team = team_logo_path(get_selected_team())  # exemple
# selected_team = get_selected_team()

# =====================================================
# CSS: header sticky + banner flottant
# =====================================================
st.markdown(
    """
    <style>
      /* Réduit un peu le padding global */
      .block-container { padding-top: .5rem; }

      /* Header sticky */
      .pms-sticky {
        position: sticky;
        top: 0;
        z-index: 999;
        padding: 10px 0;
        backdrop-filter: blur(10px);
        background: rgba(10, 10, 14, 0.70);
        border-bottom: 1px solid rgba(255,255,255,0.08);
      }
      .pms-head {
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap: 14px;
      }
      .pms-left {
        display:flex;
        align-items:center;
        gap: 10px;
        font-weight: 1000;
        font-size: 28px;
      }
      .pms-right {
        display:flex;
        align-items:center;
        gap: 12px;
        font-weight: 900;
        font-size: 24px;
      }
      .pms-teamlogo {
        width: 42px;
        height: 42px;
        object-fit: contain;
        border-radius: 10px;
        background: rgba(255,255,255,0.06);
        padding: 4px;
      }

      /* Banner flottant */
      .pms-banner-wrap{
        /* ajuste ici la descente du banner */
        margin-top: 16px; /* <- mets 380px si tu veux ~10cm plus bas */
      }
      .pms-banner{
        width: 100%;
        border-radius: 18px;
        overflow: hidden;
        box-shadow: 0 18px 50px rgba(0,0,0,0.45);
        border: 1px solid rgba(255,255,255,0.08);
      }
      .pms-banner img{
        width:100%;
        height:auto;
        display:block;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


# =====================================================
# LOGOS (dans /data)
# =====================================================
LOGOS = {
    "Nordiques": "data/Nordiques_Logo.png",
    "Cracheurs": "data/Cracheurs_Logo.png",
    "Prédateurs": "data/Predateurs_logo.png",
    "Red Wings": "data/Red_Wings_Logo.png",
    "Whalers": "data/Whalers_Logo.png",
    "Canadiens": "data/montreal-canadiens-logo.png",
}


def team_logo_path(team: str) -> str:
    path = str(LOGOS.get(str(team or "").strip(), "")).strip()
    return path if path and os.path.exists(path) else ""


def find_logo_for_owner(owner: str) -> str:
    o = str(owner or "").strip().lower()
    for key, path in LOGOS.items():
        if key.lower() in o and os.path.exists(path):
            return path
    return ""


# =====================================================
# SESSION DEFAULTS
# =====================================================
if "uploader_nonce" not in st.session_state:
    st.session_state["uploader_nonce"] = 0
if "PLAFOND_GC" not in st.session_state:
    st.session_state["PLAFOND_GC"] = 95_500_000
if "PLAFOND_CE" not in st.session_state:
    st.session_state["PLAFOND_CE"] = 47_750_000

# ✅ équipe sélectionnée (source unique)
if "selected_team" not in st.session_state:
    st.session_state["selected_team"] = ""
if "align_owner" not in st.session_state:
    st.session_state["align_owner"] = ""

# popup déplacement
if "move_ctx" not in st.session_state:
    st.session_state["move_ctx"] = None
if "move_nonce" not in st.session_state:
    st.session_state["move_nonce"] = 0
if "move_source" not in st.session_state:
    st.session_state["move_source"] = ""


# =====================================================
# UTILS / HELPERS
# =====================================================
def do_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


def money(v) -> str:
    try:
        return f"{int(v):,}".replace(",", " ") + " $"
    except Exception:
        return "0 $"


def normalize_pos(pos: str) -> str:
    p = str(pos or "").upper()
    if "G" in p:
        return "G"
    if "D" in p:
        return "D"
    return "F"


# =====================================================
# 🧠 OWNER / IMPORT HELPERS
# =====================================================
def ensure_owner_column(df: pd.DataFrame, fallback_owner: str) -> pd.DataFrame:
    """
    Assure qu'on a une colonne 'Propriétaire' propre.
    - Si le CSV contient déjà une colonne Owner/Team/Propriétaire/etc, on la respecte.
    - Sinon, on met fallback_owner partout.
    """
    if df is None:
        return df

    out = df.copy()

    # Colonnes possibles dans des CSV externes
    candidates = [
        "Propriétaire", "Proprietaire",
        "Owner", "owner", "Owners", "owners",
        "Team", "team",
        "Équipe", "Equipe", "équipe", "equipe",
        "Franchise", "franchise",
        "Club", "club",
    ]

    existing = next((c for c in candidates if c in out.columns), None)

    # Si une colonne existe mais pas sous le nom exact "Propriétaire", on la mappe
    if existing and existing != "Propriétaire":
        out["Propriétaire"] = out[existing]

    # Si aucune colonne trouvée, on crée
    if "Propriétaire" not in out.columns:
        out["Propriétaire"] = str(fallback_owner or "").strip()

    # ✅ Nettoyage: ICI on travaille sur UNE SÉRIE (out["Propriétaire"]), jamais sur out
    s = out["Propriétaire"]
    s = s.astype(str).str.strip()
    s = s.replace({"nan": "", "None": ""})
    s = s.mask(s.eq(""), str(fallback_owner or "").strip())

    out["Propriétaire"] = s
    return out



def guess_owner_from_fantrax_upload(uploaded, fallback: str = "") -> str:
    """
    Tente de deviner l'équipe dans les lignes au-dessus du tableau Fantrax.
    """
    try:
        raw = uploaded.getvalue()
        text = raw.decode("utf-8", errors="ignore")
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        top = lines[:30]

        for ln in top:
            low = ln.lower()
            if low.startswith("id,") or ",player" in low:
                break
            if low not in {"skaters", "goalies", "players"} and "," not in ln and len(ln) <= 40:
                return ln.strip('"')
    except Exception:
        pass

    return str(fallback or "").strip()


from zoneinfo import ZoneInfo
TZ_MTL = ZoneInfo("America/Toronto")

def _fmt_ts_mtl(ts: str) -> str:
    s = str(ts or "").strip()
    if not s:
        return ""
    dt = pd.to_datetime(s, errors="coerce")
    if pd.isna(dt):
        return s
    try:
        if getattr(dt, "tzinfo", None) is None:
            dt = dt.to_pydatetime().replace(tzinfo=TZ_MTL)
        else:
            dt = dt.tz_convert(TZ_MTL).to_pydatetime()
    except Exception:
        try:
            dt = dt.to_pydatetime().replace(tzinfo=TZ_MTL)
        except Exception:
            return s
    return dt.strftime("%Y-%m-%d %H:%M")


from zoneinfo import ZoneInfo
TZ_MTL = ZoneInfo("America/Toronto")

def _fmt_ts_mtl(ts: str) -> str:
    s = str(ts or "").strip()
    if not s:
        return ""
    dt = pd.to_datetime(s, errors="coerce")
    if pd.isna(dt):
        return s
    try:
        if getattr(dt, "tzinfo", None) is None:
            dt = dt.to_pydatetime().replace(tzinfo=TZ_MTL)
        else:
            dt = dt.tz_convert(TZ_MTL).to_pydatetime()
    except Exception:
        try:
            dt = dt.to_pydatetime().replace(tzinfo=TZ_MTL)
        except Exception:
            return s
    return dt.strftime("%Y-%m-%d %H:%M")


# =====================================================
# TAB H — Historique
# =====================================================
with tabH:
    st.subheader("🕘 Historique des changements d’alignement")

    h = st.session_state.get("history")
    h = h.copy() if isinstance(h, pd.DataFrame) else pd.DataFrame()

    if h.empty:
        st.info("Aucune entrée d’historique pour cette saison.")
        st.stop()

    # Colonnes attendues (soft)
    expected_cols = [
        "id", "timestamp", "season",
        "proprietaire", "joueur", "pos", "equipe",
        "from_statut", "from_slot", "to_statut", "to_slot",
        "action",
    ]
    for c in expected_cols:
        if c not in h.columns:
            h[c] = ""

    # id numeric (robuste)
    h["__idnum"] = pd.to_numeric(h["id"], errors="coerce")

    # --- Dropdown propriétaire (Tous + liste)
    owners_list = sorted(h["proprietaire"].dropna().astype(str).str.strip().unique().tolist())
    owners = ["Tous"] + owners_list

    selected_team = str(get_selected_team() or "").strip()
    default_filter = selected_team if selected_team in owners_list else "Tous"

    if "hist_owner_filter" not in st.session_state:
        st.session_state["hist_owner_filter"] = default_filter
    else:
        # si sidebar change -> montrer son historique par défaut
        if selected_team and selected_team in owners_list:
            st.session_state["hist_owner_filter"] = selected_team
        if st.session_state["hist_owner_filter"] not in owners:
            st.session_state["hist_owner_filter"] = default_filter

    owner_filter = st.selectbox(
        "Voir les mouvements de :",
        owners,
        index=owners.index(st.session_state["hist_owner_filter"]),
        key="hist_owner_filter",
    )

    h_view = h.copy()
    if owner_filter != "Tous":
        h_view = h_view[h_view["proprietaire"].astype(str).str.strip().eq(str(owner_filter).strip())].copy()

    if h_view.empty:
        st.info("Aucune entrée pour ce propriétaire.")
        st.stop()

    # --- Tri plus récents en haut
    h_view["__dt"] = pd.to_datetime(h_view["timestamp"], errors="coerce")
    h_view = h_view.sort_values("__dt", ascending=False).drop(columns=["__dt"], errors="ignore")
    h_view = h_view.reset_index(drop=True)

    # --- Bulk selection state
    if "hist_bulk_selected" not in st.session_state:
        st.session_state["hist_bulk_selected"] = set()

    # Limite d'affichage
    max_rows = st.number_input(
        "Nombre max de lignes à afficher",
        min_value=50,
        max_value=5000,
        value=250,
        step=50,
        key="hist_max_rows",
    )
    h_view = h_view.head(int(max_rows)).reset_index(drop=True)

    # Barre bulk
    cA, cB, cC = st.columns([1.2, 1.2, 2.6])
    with cA:
        if st.button("☑️ Tout sélectionner (vue)", use_container_width=True, key="bulk_sel_all"):
            ids = h_view["__idnum"].dropna().astype(int).tolist()
            st.session_state["hist_bulk_selected"].update(ids)
            do_rerun()
    with cB:
        if st.button("⬜ Tout désélectionner", use_container_width=True, key="bulk_sel_none"):
            st.session_state["hist_bulk_selected"] = set()
            do_rerun()
    with cC:
        st.caption(f"Sélection: **{len(st.session_state['hist_bulk_selected'])}** entrée(s)")

    # Bulk delete
    n_sel = len(st.session_state["hist_bulk_selected"])
    if n_sel > 0:
        st.warning("🗑️ La suppression en bulk ne modifie PAS l’alignement, seulement l’historique.")
        if st.button("🗑️ Supprimer la sélection", type="primary", use_container_width=True, key="bulk_delete_btn"):
            ids_to_del = set(st.session_state["hist_bulk_selected"])

            h_all = st.session_state.get("history")
            h_all = h_all.copy() if isinstance(h_all, pd.DataFrame) else pd.DataFrame()

            if not h_all.empty and "id" in h_all.columns:
                h_all["__idnum"] = pd.to_numeric(h_all["id"], errors="coerce")
                h_all = h_all[~h_all["__idnum"].isin(list(ids_to_del))].drop(columns=["__idnum"], errors="ignore")

            st.session_state["history"] = h_all.reset_index(drop=True)

            # Save local
            save_history(st.session_state.get("HISTORY_FILE", HISTORY_FILE), st.session_state["history"])

            # Push drive history
            try:
                if "_drive_enabled" in globals() and _drive_enabled():
                    season_lbl = st.session_state.get("season", season)
                    gdrive_save_df(
                        st.session_state["history"],
                        f"history_{season_lbl}.csv",
                        GDRIVE_FOLDER_ID,
                    )
            except Exception:
                st.warning("⚠️ Sauvegarde Drive impossible (BULK DELETE) — local OK.")

            st.session_state["hist_bulk_selected"] = set()
            st.toast("🗑️ Suppression en bulk terminée", icon="🗑️")
            do_rerun()

    st.divider()
    st.caption("Fuseau horaire: Montréal. ↩️ = UNDO (modifie alignement + log). ❌ = supprime l’entrée.")

    # Header tableau
    head = st.columns([0.7, 1.7, 1.4, 2.2, 0.9, 1.4, 1.4, 2.4, 0.8, 0.8])
    head[0].markdown("**☑️**")
    head[1].markdown("**Date/Heure (MTL)**")
    head[2].markdown("**Proprio**")
    head[3].markdown("**Joueur**")
    head[4].markdown("**Pos**")
    head[5].markdown("**De**")
    head[6].markdown("**Vers**")
    head[7].markdown("**Action**")
    head[8].markdown("**↩️**")
    head[9].markdown("**❌**")

    def _safe_int(x):
        v = pd.to_numeric(x, errors="coerce")
        if pd.isna(v):
            return None
        try:
            return int(v)
        except Exception:
            return None

    def _uid(r: pd.Series, i: int) -> str:
        rid = _safe_int(r.get("__idnum", None))
        ts = str(r.get("timestamp", "")).strip()
        owner = str(r.get("proprietaire", "")).strip()
        joueur = str(r.get("joueur", "")).strip()
        action = str(r.get("action", "")).strip()
        return f"{rid if rid is not None else 'noid'}|{ts}|{owner}|{joueur}|{action}|{i}"

    for i, r in h_view.iterrows():
        uid = _uid(r, i)
        rid = _safe_int(r.get("__idnum", None))

        cols = st.columns([0.7, 1.7, 1.4, 2.2, 0.9, 1.4, 1.4, 2.4, 0.8, 0.8])

        # Bulk checkbox
        if rid is not None:
            checked = (rid in st.session_state["hist_bulk_selected"])
            new_checked = cols[0].checkbox("", value=checked, key=f"bulk_ck__{uid}")
            if new_checked and not checked:
                st.session_state["hist_bulk_selected"].add(rid)
            if (not new_checked) and checked:
                st.session_state["hist_bulk_selected"].discard(rid)
        else:
            cols[0].markdown("—")

        cols[1].markdown(_fmt_ts_mtl(r.get("timestamp", "")))
        cols[2].markdown(str(r.get("proprietaire", "")))
        cols[3].markdown(str(r.get("joueur", "")))
        cols[4].markdown(str(r.get("pos", "")))

        de = f"{r.get('from_statut', '')}" + (f" ({r.get('from_slot', '')})" if str(r.get("from_slot", "")).strip() else "")
        vers = f"{r.get('to_statut', '')}" + (f" ({r.get('to_slot', '')})" if str(r.get("to_slot", "")).strip() else "")
        cols[5].markdown(de)
        cols[6].markdown(vers)
        cols[7].markdown(str(r.get("action", "")))

        # =====================================================
        # UNDO (push local + Drive)  ✅ TON BLOC, adapté à cols[8]
        # =====================================================
        if cols[8].button("↩️", key=f"undo__{uid}", use_container_width=True):
            if st.session_state.get("LOCKED"):
                st.error("🔒 Saison verrouillée : annulation impossible.")
            else:
                owner = str(r.get("proprietaire", "")).strip()
                joueur = str(r.get("joueur", "")).strip()

                data_df = st.session_state.get("data")
                if data_df is None or not isinstance(data_df, pd.DataFrame) or data_df.empty:
                    st.error("Aucune donnée en mémoire.")
                else:
                    mask = (
                        data_df["Propriétaire"].astype(str).str.strip().eq(owner)
                        & data_df["Joueur"].astype(str).str.strip().eq(joueur)
                    )

                    if data_df.loc[mask].empty:
                        st.error("Impossible d'annuler : joueur introuvable.")
                    else:
                        before = data_df.loc[mask].iloc[0]
                        cur_statut = str(before.get("Statut", "")).strip()
                        cur_slot = str(before.get("Slot", "")).strip()
                        pos0 = str(before.get("Pos", "F")).strip()
                        equipe0 = str(before.get("Equipe", "")).strip()

                        from_statut = str(r.get("from_statut", "")).strip()
                        from_slot = str(r.get("from_slot", "")).strip()

                        # Applique retour arrière
                        st.session_state["data"].loc[mask, "Statut"] = from_statut
                        st.session_state["data"].loc[mask, "Slot"] = (from_slot if from_slot else "")

                        # Si on sort de IR -> reset IR Date
                        if cur_slot == "Blessé" and from_slot != "Blessé":
                            st.session_state["data"].loc[mask, "IR Date"] = ""

                        # Nettoyage + save local data
                        st.session_state["data"] = clean_data(st.session_state["data"])
                        data_file = st.session_state.get("DATA_FILE", "")
                        if data_file:
                            st.session_state["data"].to_csv(data_file, index=False)

                        # Log historique (local)
                        log_history_row(
                            owner, joueur, pos0, equipe0,
                            cur_statut, cur_slot,
                            from_statut,
                            (from_slot if from_slot else ""),
                            action=f"UNDO #{rid if rid is not None else 'NA'}",
                        )

                        # ✅ PUSH DRIVE (data + history) après UNDO
                        try:
                            if "_drive_enabled" in globals() and _drive_enabled():
                                season_lbl = st.session_state.get("season", season)

                                gdrive_save_df(
                                    st.session_state["data"],
                                    f"fantrax_{season_lbl}.csv",
                                    GDRIVE_FOLDER_ID,
                                )

                                h_now = st.session_state.get("history")
                                if isinstance(h_now, pd.DataFrame):
                                    gdrive_save_df(
                                        h_now,
                                        f"history_{season_lbl}.csv",
                                        GDRIVE_FOLDER_ID,
                                    )
                        except Exception:
                            st.warning("⚠️ Sauvegarde Drive impossible (UNDO) — local OK.")

                        st.toast("↩️ Changement annulé", icon="↩️")
                        do_rerun()

        # =====================================================
        # DELETE (push local + Drive) ✅ TON BLOC, adapté à cols[9]
        # =====================================================
        if cols[9].button("❌", key=f"del__{uid}", use_container_width=True):
            h2 = st.session_state.get("history")
            h2 = h2.copy() if isinstance(h2, pd.DataFrame) else pd.DataFrame()

            if not h2.empty:
                if rid is not None and "id" in h2.columns:
                    h2["__idnum"] = pd.to_numeric(h2["id"], errors="coerce")
                    h2 = h2[h2["__idnum"] != rid].drop(columns=["__idnum"], errors="ignore")
                else:
                    # fallback signature (si pas de id fiable)
                    sig_cols = [
                        "timestamp", "season", "proprietaire", "joueur",
                        "from_statut", "from_slot", "to_statut", "to_slot", "action"
                    ]
                    sig_cols = [c for c in sig_cols if c in h2.columns]
                    if sig_cols:
                        m = pd.Series([True] * len(h2))
                        for c in sig_cols:
                            m &= (h2[c].astype(str) == str(r.get(c, "")).astype(str))
                        h2 = h2[~m].copy()

            st.session_state["history"] = h2.reset_index(drop=True)

            # Save local
            save_history(st.session_state.get("HISTORY_FILE", HISTORY_FILE), st.session_state["history"])

            # ✅ PUSH DRIVE (history) après DELETE
            try:
                if "_drive_enabled" in globals() and _drive_enabled():
                    season_lbl = st.session_state.get("season", season)
                    gdrive_save_df(
                        st.session_state["history"],
                        f"history_{season_lbl}.csv",
                        GDRIVE_FOLDER_ID,
                    )
            except Exception:
                st.warning("⚠️ Sauvegarde Drive impossible (DELETE) — local OK.")

            st.toast("🗑️ Entrée supprimée", icon="🗑️")
            do_rerun()






# =====================================================
# 🔄 LOAD DATA — CAS B (état courant > initial)
# =====================================================
def load_current_or_bootstrap(season: str):
    """
    CAS B :
    1) Charge l'état courant (Drive -> local)
    2) Sinon bootstrap depuis CSV initial (UNE SEULE FOIS)
    """
    data_file = st.session_state["DATA_FILE"]
    folder_id = str(GDRIVE_FOLDER_ID or "").strip()

    # 1) Drive
    if folder_id and "_drive_enabled" in globals() and _drive_enabled():
        try:
            df_drive = gdrive_load_df(f"fantrax_{season}.csv", folder_id)
            if df_drive is not None and not df_drive.empty:
                return clean_data(df_drive), "drive_current"
        except Exception:
            pass

    # 2) Local
    if data_file and os.path.exists(data_file):
        try:
            df_local = pd.read_csv(data_file)
            if not df_local.empty:
                return clean_data(df_local), "local_current"
        except Exception:
            pass

    # 3) Bootstrap initial (1 fois)
    manifest = load_init_manifest()
    init_path = manifest.get("fantrax", {}).get("path", "")
    chosen_owner = manifest.get("fantrax", {}).get("chosen_owner", "")

    if init_path and os.path.exists(init_path):
        try:
            import io
            with open(init_path, "rb") as f:
                buf = io.BytesIO(f.read())
            buf.name = manifest.get("fantrax", {}).get(
                "uploaded_name", os.path.basename(init_path)
            )

            df_import = parse_fantrax(buf)
            if df_import is not None and not df_import.empty:
                df_import = ensure_owner_column(df_import, chosen_owner)
                df_boot = clean_data(df_import)

                # Sauvegarde état courant
                try:
                    df_boot.to_csv(data_file, index=False)
                except Exception:
                    pass

                try:
                    if folder_id and "_drive_enabled" in globals() and _drive_enabled():
                        gdrive_save_df(df_boot, f"fantrax_{season}.csv", folder_id)
                except Exception:
                    pass

                history_add(
                    action="BOOTSTRAP_INITIAL",
                    owner=chosen_owner,
                    details=f"Initial CSV appliqué automatiquement ({buf.name})",
                )

                return df_boot, "bootstrap_from_initial"
        except Exception:
            pass

    return pd.DataFrame(columns=REQUIRED_COLS), "empty"


# =====================================================
# AUTRES HELPERS UI
# =====================================================
def pos_sort_key(pos: str) -> int:
    return {"F": 0, "D": 1, "G": 2}.get(str(pos).upper(), 99)


def saison_auto():
    now = datetime.now()
    return f"{now.year}-{now.year+1}" if now.month >= 9 else f"{now.year-1}-{now.year}"


def saison_verrouillee(season: str) -> bool:
    return int(str(season)[:4]) < int(saison_auto()[:4])


def _count_badge(n: int, limit: int) -> str:
    if n > limit:
        return f"<span style='color:#ef4444;font-weight:1000'>{n}</span>/{limit} ⚠️"
    return f"<span style='color:#22c55e;font-weight:1000'>{n}</span>/{limit}"


def render_badge(text: str, bg: str, fg: str = "white") -> str:
    t = html.escape(str(text or ""))
    return (
        "<span style='display:inline-block;padding:2px 8px;border-radius:999px;"
        f"background:{bg};color:{fg};font-weight:900;font-size:12px'>"
        f"{t}</span>"
    )


def pos_badge_html(pos: str) -> str:
    p = normalize_pos(pos)
    if p == "F":
        return render_badge("F", "#16a34a")
    if p == "D":
        return render_badge("D", "#2563eb")
    return render_badge("G", "#7c3aed")


def cap_bar_html(used: int, cap: int, label: str) -> str:
    cap = int(cap or 0)
    used = int(used or 0)
    remain = cap - used
    pct = max(0, min((used / cap) if cap else 0, 1))
    color = "#16a34a" if remain >= 0 else "#dc2626"

    return f"""
    <div style="margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;font-size:12px;font-weight:900">
        <span>{html.escape(label)}</span>
        <span style="color:{color}">{money(remain)}</span>
      </div>
      <div style="background:#e5e7eb;height:10px;border-radius:6px;overflow:hidden">
        <div style="width:{int(pct*100)}%;background:{color};height:100%"></div>
      </div>
      <div style="font-size:11px;opacity:.75">
        Utilisé : {money(used)} / {money(cap)}
      </div>
    </div>
    """



# =====================================================
# PERSISTENCE — FICHIERS CSV INITIAUX
# =====================================================
import json
from datetime import datetime

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

INIT_MANIFEST = os.path.join(DATA_DIR, "initial_csv_manifest.json")

def load_init_manifest() -> dict:
    if os.path.exists(INIT_MANIFEST):
        try:
            with open(INIT_MANIFEST, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_init_manifest(m: dict) -> None:
    with open(INIT_MANIFEST, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)

def save_uploaded_csv(file, save_as_name: str) -> str:
    safe_name = os.path.basename(save_as_name).strip()
    if not safe_name.lower().endswith(".csv"):
        safe_name += ".csv"
    path = os.path.join(DATA_DIR, safe_name)

    with open(path, "wb") as out:
        out.write(file.getbuffer())

    return path


# =====================================================
# ADMIN GUARD
# =====================================================
def _is_admin_whalers() -> bool:
    return str(get_selected_team() or "").strip().lower() == "whalers"


# =====================================================
# GOOGLE DRIVE — OAUTH FINAL (clean + refresh silencieux)
# =====================================================

# ✅ Recommandé: scope minimal
OAUTH_SCOPES = ["https://www.googleapis.com/auth/drive"]

def _oauth_cfg() -> dict:
    return dict(st.secrets.get("gdrive_oauth", {}))

def _folder_id() -> str:
    return str(_oauth_cfg().get("folder_id", "")).strip()

def oauth_drive_enabled() -> bool:
    cfg = _oauth_cfg()
    return bool(str(cfg.get("client_id", "")).strip() and str(cfg.get("client_secret", "")).strip())

def oauth_drive_ready() -> bool:
    cfg = _oauth_cfg()
    return bool(_folder_id() and str(cfg.get("refresh_token", "")).strip())

def _build_oauth_flow() -> Flow:
    cfg = _oauth_cfg()
    client_config = {
        "web": {
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    return Flow.from_client_config(
        client_config=client_config,
        scopes=OAUTH_SCOPES,
        redirect_uri=cfg["redirect_uri"],
    )

def oauth_connect_ui():
    """
    UI à mettre dans l'onglet Admin:
    - bouton connecter si pas de refresh_token
    - si ?code=..., échange et affiche refresh_token à coller dans Secrets
    """
    if not oauth_drive_enabled():
        st.warning("OAuth Drive non configuré (client_id/client_secret/redirect_uri manquants dans Secrets).")
        return

    cfg = _oauth_cfg()
    qp = st.query_params
    code = qp.get("code", None)

    if code:
        try:
            flow = _build_oauth_flow()
            flow.fetch_token(code=code)
            creds = flow.credentials
            rt = getattr(creds, "refresh_token", None)

            st.success("✅ Connexion Google réussie.")
            if rt:
                st.warning("Copie ce refresh_token dans Streamlit Secrets → [gdrive_oauth].refresh_token")
                st.code(rt)
                st.caption("Ensuite enlève `?code=...` de l’URL (ou refresh) après avoir mis à jour Secrets.")
            else:
                st.error("⚠️ Aucun refresh_token reçu. Révoque l’accès (myaccount.google.com/permissions) puis reconnecte.")
        except Exception as e:
            st.error(f"❌ OAuth error: {type(e).__name__}: {e}")
        return

    if not str(cfg.get("refresh_token", "")).strip():
        flow = _build_oauth_flow()
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        st.link_button("🔐 Connecter Google Drive", auth_url, use_container_width=True)
        st.caption("Après l’autorisation, tu reviens ici avec `?code=...` et je te donne le refresh_token.")
    else:
        st.success("OAuth configuré (refresh_token présent).")

import ssl
import time
import socket
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request


def _get_oauth_creds() -> Credentials:
    """
    Construit Credentials + refresh silencieux si nécessaire.
    Raise si pas prêt.
    """
    cfg = _oauth_cfg()
    rt = str(cfg.get("refresh_token", "")).strip()
    if not rt:
        raise RuntimeError("OAuth Drive non prêt: refresh_token manquant (voir Admin).")

    creds = Credentials(
        token=None,
        refresh_token=rt,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=cfg["client_id"],
        client_secret=cfg["client_secret"],
        scopes=OAUTH_SCOPES,
    )

    # ✅ Refresh silencieux
    if not creds.valid:
        creds.refresh(Request())

    return creds


def _is_ssl_error(e: Exception) -> bool:
    msg = str(e).lower()
    return (
        isinstance(e, ssl.SSLError)
        or "ssl" in msg
        or "bad record mac" in msg
        or "decryption_failed_or_bad_record_mac" in msg
        or "wrong version number" in msg
        or "tlsv" in msg
    )


def _reset_drive_client_cache():
    # Reconstruit le client Drive si transport cassé
    try:
        st.cache_resource.clear()
    except Exception:
        pass


@st.cache_resource(show_spinner=False)
def _drive_client_cached():
    """
    Client Drive caché: accélère et évite rebuild à chaque rerun.
    Durci:
      - cache_discovery=False (évite soucis de cache)
      - timeouts (évite blocages longs)
    """
    creds = _get_oauth_creds()

    # ⚙️ Timeouts socket (global) — safe pour Streamlit
    # (Google API utilise httplib2 en-dessous; ça aide surtout contre connexions qui gèlent)
    try:
        socket.setdefaulttimeout(30)
    except Exception:
        pass

    # ✅ cache_discovery=False = recommandé en environnements serverless/streamlit
    return build(
        "drive",
        "v3",
        credentials=creds,
        cache_discovery=False,
    )


def gdrive_service():
    """
    Retourne un service Drive prêt.
    Si le client caché est corrompu suite à un incident SSL, on le reset au prochain retry
    (le retry est géré dans gdrive_save_df/gdrive_load_df).
    """
    return _drive_client_cached()


def _drive_enabled() -> bool:
    return oauth_drive_ready()


# -----------------------------
# Helpers Drive (liste / save / load) — ROBUST (SSL retry + reset)
# -----------------------------
import ssl
import time
import socket
from googleapiclient.errors import HttpError

def _is_ssl_error(e: Exception) -> bool:
    msg = str(e).lower()
    return (
        isinstance(e, ssl.SSLError)
        or "ssl" in msg
        or "bad record mac" in msg
        or "decryption_failed_or_bad_record_mac" in msg
        or "wrong version number" in msg
        or "tlsv" in msg
    )

def _reset_drive_client_cache():
    # Important: rebuild le service Drive après un incident TLS
    try:
        st.cache_resource.clear()
    except Exception:
        pass

def _call_with_retry(fn, *, retries: int = 3, base_sleep: float = 0.6):
    """
    Exécute fn() avec retry si erreur SSL/transient.
    - SSL => reset cache + retry
    - Socket timeout => retry
    - HttpError 429/5xx => retry
    """
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            # Petit timeout global (safe) — évite les transferts qui figent
            try:
                socket.setdefaulttimeout(30)
            except Exception:
                pass

            return fn()

        except Exception as e:
            last_err = e

            # Retry sur SSL/TLS cassé
            if _is_ssl_error(e):
                _reset_drive_client_cache()
                time.sleep(base_sleep * attempt)
                continue

            # Retry sur timeouts réseau
            if isinstance(e, (socket.timeout, TimeoutError)):
                _reset_drive_client_cache()
                time.sleep(base_sleep * attempt)
                continue

            # Retry sur erreurs API transientes
            if isinstance(e, HttpError):
                try:
                    status = int(getattr(e.resp, "status", 0) or 0)
                except Exception:
                    status = 0
                if status in {429, 500, 502, 503, 504}:
                    time.sleep(base_sleep * attempt)
                    continue

            # Sinon: on remonte l'erreur (non-transiente)
            raise

    # Si on sort de la boucle, on relance la dernière erreur
    raise last_err


def gdrive_get_file_id(service, filename: str, folder_id: str):
    safe_name = str(filename).replace("'", "")
    q = f"name='{safe_name}' and '{folder_id}' in parents and trashed=false"

    def _run():
        res = service.files().list(q=q, fields="files(id,name)").execute()
        files = res.get("files", [])
        return files[0]["id"] if files else None

    return _call_with_retry(_run, retries=3)


def gdrive_list_files(folder_id: str, limit: int = 20) -> list[str]:
    if not folder_id:
        return []
    def _run():
        s = gdrive_service()
        res = s.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            pageSize=int(limit),
            fields="files(name)",
        ).execute()
        return [f["name"] for f in res.get("files", [])]

    return _call_with_retry(_run, retries=3)


def gdrive_save_df(df: pd.DataFrame, filename: str, folder_id: str) -> bool:
    if not folder_id:
        return False

    def _run():
        s = gdrive_service()
        file_id = gdrive_get_file_id(s, filename, folder_id)

        csv_bytes = df.to_csv(index=False).encode("utf-8")
        media = MediaIoBaseUpload(io.BytesIO(csv_bytes), mimetype="text/csv", resumable=False)

        if file_id:
            s.files().update(fileId=file_id, media_body=media).execute()
        else:
            file_metadata = {"name": filename, "parents": [folder_id]}
            s.files().create(body=file_metadata, media_body=media).execute()

        return True

    return bool(_call_with_retry(_run, retries=3))


def gdrive_load_df(filename: str, folder_id: str) -> pd.DataFrame | None:
    if not folder_id:
        return None

    def _run():
        s = gdrive_service()
        file_id = gdrive_get_file_id(s, filename, folder_id)
        if not file_id:
            return None

        request = s.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)

        done = False
        while not done:
            _, done = downloader.next_chunk()

        fh.seek(0)
        return pd.read_csv(fh)

    return _call_with_retry(_run, retries=3)

# -----------------------------
# DRIVE — BATCH FLUSH (robuste SSL)
# -----------------------------
import time

# Init session si absent
if "drive_queue" not in st.session_state:
    st.session_state["drive_queue"] = {}  # filename -> df(copy)
if "drive_dirty_at" not in st.session_state:
    st.session_state["drive_dirty_at"] = 0.0
if "drive_last_flush" not in st.session_state:
    st.session_state["drive_last_flush"] = 0.0


def queue_drive_save_df(df: pd.DataFrame, filename: str):
    """
    Ajoute un DF à la queue Drive (batch write).
    Écriture réelle faite par flush_drive_queue().
    """
    if not _drive_enabled():
        return
    if df is None or not isinstance(df, pd.DataFrame):
        return

    st.session_state["drive_queue"][str(filename)] = df.copy()
    st.session_state["drive_dirty_at"] = time.time()


def flush_drive_queue(force: bool = False, max_age_sec: int = 8) -> tuple[int, list[str]]:
    """
    Vide la queue Drive avec sécurité réseau.
    - force=True : flush immédiat
    - max_age_sec : délai minimum avant flush auto
    Retourne: (nb_fichiers_écrits, [erreurs])
    """
    if not _drive_enabled():
        return (0, [])

    q = st.session_state.get("drive_queue", {})
    if not q:
        return (0, [])

    dirty_at = float(st.session_state.get("drive_dirty_at", 0.0) or 0.0)
    age = time.time() - dirty_at if dirty_at else 0.0

    if (not force) and (age < max_age_sec):
        return (0, [])

    folder_id = str(_folder_id() or "").strip()
    if not folder_id:
        return (0, ["folder_id manquant: écriture Drive impossible (queue conservée)."])

    written = 0
    errors: list[str] = []

    for filename, df in list(q.items()):
        try:
            gdrive_save_df(df, filename, folder_id)
            written += 1
            del st.session_state["drive_queue"][filename]

        except Exception as e:
            # 🔒 Si SSL/TLS cassé → reset client pour les prochains essais
            if "_is_ssl_error" in globals() and _is_ssl_error(e):
                try:
                    st.cache_resource.clear()
                except Exception:
                    pass

            errors.append(f"{filename}: {type(e).__name__}: {e}")

    st.session_state["drive_last_flush"] = time.time()

    if not st.session_state["drive_queue"]:
        st.session_state["drive_dirty_at"] = 0.0

    return (written, errors)


# -----------------------------
# Helpers Drive — Folder (auto-create)
# -----------------------------
def gdrive_find_folder_id_by_name(folder_name: str) -> str | None:
    """Cherche un dossier par nom (non supprimé). Retourne le premier id trouvé."""
    s = gdrive_service()
    safe = str(folder_name).replace("'", "")
    q = (
        "mimeType='application/vnd.google-apps.folder' "
        f"and name='{safe}' and trashed=false"
    )
    res = s.files().list(q=q, fields="files(id,name)", pageSize=10).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def gdrive_create_folder(folder_name: str) -> str:
    """Crée un dossier dans My Drive. Retourne folder_id."""
    s = gdrive_service()
    metadata = {"name": str(folder_name), "mimeType": "application/vnd.google-apps.folder"}
    created = s.files().create(body=metadata, fields="id").execute()
    return str(created.get("id", "")).strip()


def ensure_drive_folder_id(folder_name: str = "PoolHockeyData") -> str | None:
    """
    Si folder_id est déjà configuré et Drive prêt → retourne folder_id.
    Sinon, tente de trouver un dossier du même nom, sinon le crée.
    Retourne l'id (à copier dans Secrets).
    """
    if _drive_enabled():
        return _folder_id()

    # OAuth configuré mais refresh_token pas encore prêt
    if not oauth_drive_enabled():
        return None

    cfg = _oauth_cfg()
    if not str(cfg.get("refresh_token", "")).strip():
        return None

    found = gdrive_find_folder_id_by_name(folder_name)
    if found:
        return found

    return gdrive_create_folder(folder_name)

# =====================================================
# DRIVE — BATCH WRITE (queue + flush)
# =====================================================
import time

if "drive_queue" not in st.session_state:
    st.session_state["drive_queue"] = {}  # filename -> df(copy)
if "drive_dirty_at" not in st.session_state:
    st.session_state["drive_dirty_at"] = 0.0
if "drive_last_flush" not in st.session_state:
    st.session_state["drive_last_flush"] = 0.0


def queue_drive_save_df(df: pd.DataFrame, filename: str):
    if not _drive_enabled():
        return
    if df is None or not isinstance(df, pd.DataFrame):
        return

    st.session_state["drive_queue"][str(filename)] = df.copy()
    st.session_state["drive_dirty_at"] = time.time()


def flush_drive_queue(force: bool = False, max_age_sec: int = 8) -> tuple[int, list[str]]:
    if not _drive_enabled():
        return (0, [])

    q = st.session_state.get("drive_queue", {})
    if not q:
        return (0, [])

    dirty_at = float(st.session_state.get("drive_dirty_at", 0.0) or 0.0)
    age = time.time() - dirty_at if dirty_at else 0.0
    if (not force) and (age < max_age_sec):
        return (0, [])

    # ✅ folder_id obligatoire
    folder_id = str(_folder_id() or "").strip()
    if not folder_id:
        return (0, ["folder_id manquant: impossible d'écrire sur Drive (queue conservée)."])

    written = 0
    errors: list[str] = []

    for filename, df in list(q.items()):
        try:
            gdrive_save_df(df, filename, folder_id)
            written += 1
            del st.session_state["drive_queue"][filename]
        except Exception as e:
            errors.append(f"{filename}: {type(e).__name__}: {e}")

    st.session_state["drive_last_flush"] = time.time()
    if not st.session_state["drive_queue"]:
        st.session_state["drive_dirty_at"] = 0.0

    return (written, errors)


# =====================================================
# PERSIST — local immédiat + Drive en batch
# =====================================================
def persist_data(df_data: pd.DataFrame, season: str):
    # Local (immédiat)
    try:
        data_file = st.session_state.get("DATA_FILE", "")
        if data_file:
            df_data.to_csv(data_file, index=False)
    except Exception:
        pass

    # Drive (batch)
    if _drive_enabled():
        queue_drive_save_df(df_data, f"fantrax_{season}.csv")


def persist_history(h: pd.DataFrame, season: str):
    # Local (immédiat)
    try:
        hist_file = st.session_state.get("HISTORY_FILE", "")
        if hist_file:
            h.to_csv(hist_file, index=False)
    except Exception:
        pass

    # Drive (batch)
    if _drive_enabled():
        queue_drive_save_df(h, f"history_{season}.csv")


# =====================================================
# CLEAN DATA
# =====================================================
REQUIRED_COLS = ["Propriétaire", "Joueur", "Salaire", "Statut", "Slot", "Pos", "Equipe", "IR Date"]


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame(columns=REQUIRED_COLS)

    df = df.copy()

    for c in REQUIRED_COLS:
        if c not in df.columns:
            df[c] = ""

    for c in ["Propriétaire", "Joueur", "Statut", "Slot", "Pos", "Equipe", "IR Date"]:
        df[c] = df[c].astype(str).fillna("").map(lambda x: re.sub(r"\s+", " ", x).strip())

    def _to_int(x):
        s = str(x).strip().replace(",", "").replace(" ", "")
        s = re.sub(r"[^\d]", "", s)
        return int(s) if s.isdigit() else 0

    df["Salaire"] = df["Salaire"].apply(_to_int).astype(int)

    df["Statut"] = df["Statut"].replace(
        {
            "GC": "Grand Club",
            "CE": "Club École",
            "Club Ecole": "Club École",
            "GrandClub": "Grand Club",
        }
    )

    df["Slot"] = df["Slot"].replace(
        {
            "Active": "Actif",
            "Bench": "Banc",
            "IR": "Blessé",
            "Injured": "Blessé",
        }
    )

    df["Pos"] = df["Pos"].apply(normalize_pos)

    def _fix_row(r):
        statut = r["Statut"]
        slot = r["Slot"]
        if statut == "Club École":
            if slot not in {"", "Blessé"}:
                r["Slot"] = ""
        else:
            if slot not in {"Actif", "Banc", "Blessé"}:
                r["Slot"] = "Actif"
        return r

    df = df.apply(_fix_row, axis=1)
    df = df.drop_duplicates(subset=["Propriétaire", "Joueur"], keep="last").reset_index(drop=True)
    return df


# =====================================================
# HISTORY
# =====================================================
def load_history(history_file: str) -> pd.DataFrame:
    if os.path.exists(history_file):
        return pd.read_csv(history_file)
    return pd.DataFrame(
        columns=[
            "id", "timestamp", "season",
            "proprietaire", "joueur", "pos", "equipe",
            "from_statut", "from_slot", "to_statut", "to_slot",
            "action",
        ]
    )


def save_history(history_file: str, h: pd.DataFrame):
    h.to_csv(history_file, index=False)


def next_hist_id(h: pd.DataFrame) -> int:
    if h.empty or "id" not in h.columns:
        return 1
    return int(pd.to_numeric(h["id"], errors="coerce").fillna(0).max()) + 1


def log_history_row(proprietaire, joueur, pos, equipe,
                    from_statut, from_slot,
                    to_statut, to_slot,
                    action):
    h = st.session_state["history"].copy()
    row_hist = {
        "id": next_hist_id(h),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "season": st.session_state.get("season", ""),
        "proprietaire": proprietaire,
        "joueur": joueur,
        "pos": pos,
        "equipe": equipe,
        "from_statut": from_statut,
        "from_slot": from_slot,
        "to_statut": to_statut,
        "to_slot": to_slot,
        "action": action,
    }
    h = pd.concat([h, pd.DataFrame([row_hist])], ignore_index=True)
    st.session_state["history"] = h
    save_history(st.session_state["HISTORY_FILE"], h)

# =====================================================
# TEAM SELECTION — GLOBAL (UNIQUE SOURCE OF TRUTH)
# =====================================================
def pick_team(team: str):
    team = str(team or "").strip()
    st.session_state["selected_team"] = team
    st.session_state["align_owner"] = team
    do_rerun()


def get_selected_team() -> str:
    return str(st.session_state.get("selected_team", "")).strip()


# =====================================================
# HEADER STICKY (HTML)
# =====================================================
selected_team = str(st.session_state.get("selected_team", "")).strip()

team_html = ""
if selected_team:
    logo_path = LOGOS.get(selected_team, "")
    if logo_path and os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            logo_b64 = base64.b64encode(f.read()).decode()

        # ✅ Logo seulement (aucun texte visible) + accessibilité via alt
        safe_team = html.escape(selected_team)
        team_html = f"""
          <div class="pms-right">
            <img class="pms-teamlogo"
                 alt="{safe_team}"
                 src="data:image/png;base64,{logo_b64}" />
          </div>
        """



# =====================================================
# BANNER FLOTTANT (logo_pool)
# =====================================================
banner_b64 = _img_b64(LOGO_POOL_FILE)
if banner_b64:
    st.markdown(
        f"""
        <div class="pms-banner-wrap">
          <div class="pms-banner">
            <img src="data:image/png;base64,{banner_b64}" />
          </div>
        </div>
        """,
        unsafe_allow_html=True
    )

# =====================================================
# MOVE CONTEXT (popup)
# =====================================================
def set_move_ctx(owner: str, joueur: str, source_key: str):
    st.session_state["move_nonce"] = st.session_state.get("move_nonce", 0) + 1
    st.session_state["move_source"] = str(source_key or "").strip()
    st.session_state["move_ctx"] = {
        "owner": str(owner).strip(),
        "joueur": str(joueur).strip(),
        "nonce": st.session_state["move_nonce"],
    }


def clear_move_ctx():
    st.session_state["move_ctx"] = None
    st.session_state["move_source"] = ""


# =====================================================
# UI — roster cliquable compact
# =====================================================
def roster_click_list(df_src: pd.DataFrame, owner: str, source_key: str) -> str | None:
    """
    UI cliquable: 1 bouton par joueur + badges CSS.
    Colonnes: Pos | Team | Joueur | Salaire
    Tri: Pos (F,D,G) -> Salaire (desc) -> 1ère lettre -> Nom
    """
    if df_src is None or df_src.empty:
        st.info("Aucun joueur.")
        return None

    # CSS: boutons plus compacts + texte aligné gauche + salaire nowrap
    st.markdown(
        """
        <style>
          div[data-testid="stButton"] > button{
            padding: 0.18rem 0.45rem;
            font-weight: 900;
            text-align: left;
            justify-content: flex-start;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
          }
          .salaryCell{
            white-space: nowrap;
            text-align: right;
            font-weight: 900;
            display: block;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )

    t = df_src.copy()

    # Colonnes garanties
    for c, d in {"Joueur": "", "Pos": "F", "Equipe": "", "Salaire": 0}.items():
        if c not in t.columns:
            t[c] = d

    # Nettoyage minimal (évite "None" / "nan")
    t["Joueur"] = t["Joueur"].astype(str).fillna("").map(lambda x: re.sub(r"\s+", " ", x).strip())
    t["Equipe"] = t["Equipe"].astype(str).fillna("").map(lambda x: re.sub(r"\s+", " ", x).strip())
    t["Salaire"] = pd.to_numeric(t["Salaire"], errors="coerce").fillna(0).astype(int)

    # ✅ Retire les lignes parasites (None/nan/vide)
    bad = {"", "none", "nan", "null"}
    t = t[~t["Joueur"].str.lower().isin(bad)].copy()
    if t.empty:
        st.info("Aucun joueur.")
        return None

    # Tri: Pos -> Salaire desc -> initiale -> nom
    t["Pos"] = t["Pos"].apply(normalize_pos)
    t["_pos"] = t["Pos"].apply(pos_sort_key)
    t["_initial"] = t["Joueur"].str.upper().str[0].fillna("?")

    t = (
        t.sort_values(
            by=["_pos", "Salaire", "_initial", "Joueur"],
            ascending=[True, False, True, True],
            kind="mergesort",
        )
        .drop(columns=["_pos", "_initial"])
        .reset_index(drop=True)
    )

    # ✅ Colonnes: on réduit un peu "Joueur" et on élargit "Salaire"
    # (ça évite le wrap du salaire)
    h = st.columns([1.2, 1.6, 3.6, 2.4])
    h[0].markdown("**Pos**")
    h[1].markdown("**Team**")
    h[2].markdown("**Joueur**")
    h[3].markdown("**Salaire**")

    clicked = None
    for i, r in t.iterrows():
        joueur = str(r.get("Joueur", "")).strip()
        if not joueur:
            continue

        pos = r.get("Pos", "F")
        team = str(r.get("Equipe", "")).strip()
        salaire = int(r.get("Salaire", 0) or 0)

        c = st.columns([1.2, 1.6, 3.6, 2.4])
        c[0].markdown(pos_badge_html(pos), unsafe_allow_html=True)
        c[1].markdown(team if team and team.lower() not in bad else "—")

        if c[2].button(joueur, key=f"{source_key}_{owner}_{joueur}_{i}", use_container_width=True):
            clicked = joueur

        c[3].markdown(f"<span class='salaryCell'>{money(salaire)}</span>", unsafe_allow_html=True)

    return clicked




# =====================================================
# PLAYERS DB (data/Hockey.Players.csv)
# =====================================================

# ✅ Assure que PLAYERS_DB_FILE existe bien avant l'appel
if "PLAYERS_DB_FILE" not in globals():
    DATA_DIR = "data"
    os.makedirs(DATA_DIR, exist_ok=True)
    PLAYERS_DB_FILE = os.path.join(DATA_DIR, "Hockey.Players.csv")


def _norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip()).lower()


@st.cache_data(show_spinner=False)
def load_players_db(path: str) -> pd.DataFrame:
    if not path or not os.path.exists(path):
        return pd.DataFrame()

    dfp = pd.read_csv(path)

    name_col = None
    for c in dfp.columns:
        cl = c.strip().lower()
        if cl in {"player", "joueur", "name", "full name", "fullname"}:
            name_col = c
            break

    if name_col is not None:
        dfp["_name_key"] = dfp[name_col].astype(str).map(_norm_name)

    return dfp


players_db = load_players_db(PLAYERS_DB_FILE)

# Optionnel: debug doux (sidebar)
if players_db is None or players_db.empty:
    st.sidebar.warning(f"⚠️ Base joueurs introuvable ou vide: {PLAYERS_DB_FILE}")



# =====================================================
# APPLY MOVE (avec IR Date) + PERSIST (local + Drive)
# =====================================================
def apply_move_with_history(
    proprietaire: str,
    joueur: str,
    to_statut: str,
    to_slot: str,
    action_label: str,
) -> bool:
    st.session_state["last_move_error"] = ""

    if st.session_state.get("LOCKED"):
        st.session_state["last_move_error"] = "🔒 Saison verrouillée : modification impossible."
        return False

    df0 = st.session_state.get("data")
    if df0 is None or df0.empty:
        st.session_state["last_move_error"] = "Aucune donnée en mémoire."
        return False

    df0 = df0.copy()
    if "IR Date" not in df0.columns:
        df0["IR Date"] = ""

    proprietaire = str(proprietaire or "").strip()
    joueur = str(joueur or "").strip()
    to_statut = str(to_statut or "").strip()
    to_slot = str(to_slot or "").strip()

    mask = (
        df0["Propriétaire"].astype(str).str.strip().eq(proprietaire)
        & df0["Joueur"].astype(str).str.strip().eq(joueur)
    )
    if df0.loc[mask].empty:
        st.session_state["last_move_error"] = "Joueur introuvable."
        return False

    before = df0.loc[mask].iloc[0]
    from_statut = str(before.get("Statut", "")).strip()
    from_slot = str(before.get("Slot", "")).strip()
    pos0 = str(before.get("Pos", "F")).strip()
    equipe0 = str(before.get("Equipe", "")).strip()

    # IR — conserver le statut actuel
    if to_slot == "Blessé":
        to_statut = from_statut

    allowed_slots_gc = {"Actif", "Banc", "Blessé"}
    allowed_slots_ce = {"", "Blessé"}

    if to_statut == "Grand Club" and to_slot not in allowed_slots_gc:
        st.session_state["last_move_error"] = f"Slot invalide GC : {to_slot}"
        return False

    if to_statut == "Club École" and to_slot not in allowed_slots_ce:
        st.session_state["last_move_error"] = f"Slot invalide CE : {to_slot}"
        return False

    # Apply
    df0.loc[mask, "Statut"] = to_statut
    df0.loc[mask, "Slot"] = to_slot if to_slot else ""

    entering_ir = (to_slot == "Blessé") and (from_slot != "Blessé")
    leaving_ir = (from_slot == "Blessé") and (to_slot != "Blessé")

    if entering_ir:
        now_tor = datetime.now(ZoneInfo("America/Toronto"))
        df0.loc[mask, "IR Date"] = now_tor.strftime("%Y-%m-%d %H:%M")
    elif leaving_ir:
        df0.loc[mask, "IR Date"] = ""

    # Clean + store
    df0 = clean_data(df0)
    st.session_state["data"] = df0

    # History
    try:
        log_history_row(
            proprietaire=proprietaire,
            joueur=joueur,
            pos=pos0,
            equipe=equipe0,
            from_statut=from_statut,
            from_slot=from_slot,
            to_statut=to_statut,
            to_slot=to_slot,
            action=action_label,
        )
    except Exception:
        pass

    # Persist (local immédiat + Drive batch)
    season_lbl = str(st.session_state.get("season", "")).strip()
    try:
        persist_data(df0, season_lbl)
        h = st.session_state.get("history")
        if isinstance(h, pd.DataFrame):
            persist_history(h, season_lbl)
    except Exception as e:
        st.session_state["last_move_error"] = f"Erreur persistance: {type(e).__name__}: {e}"
        return False

    return True


    # -----------------------------
    # 1) SAVE LOCAL (data)
    # -----------------------------
    try:
        data_file = st.session_state.get("DATA_FILE")
        if data_file:
            df0.to_csv(data_file, index=False)
    except Exception as e:
        st.session_state["last_move_error"] = f"Erreur sauvegarde CSV local: {e}"
        return False

    # -----------------------------
    # 2) SAVE DRIVE (data) — optionnel
    # -----------------------------
    try:
        if "_drive_enabled" in globals() and _drive_enabled():
            season_lbl = st.session_state.get("season", "")
            gdrive_save_df(df0, f"fantrax_{season_lbl}.csv", GDRIVE_FOLDER_ID)
    except Exception as e:
        # On ne bloque pas l'app si Drive down
        st.sidebar.warning(f"⚠️ Drive indisponible (fallback local). ({e})")



    # -----------------------------
    # 3) HISTORY LOG + SAVE LOCAL (déjà fait dans log_history_row)
    # -----------------------------
    try:
        log_history_row(
            proprietaire=proprietaire,
            joueur=joueur,
            pos=pos0,
            equipe=equipe0,
            from_statut=from_statut,
            from_slot=from_slot,
            to_statut=to_statut,
            to_slot=to_slot,
            action=action_label,
        )
    except Exception:
        pass

    # -----------------------------
    # 4) SAVE DRIVE (history) — optionnel
    # -----------------------------
    try:
        if "_drive_enabled" in globals() and _drive_enabled():
            season_lbl = st.session_state.get("season", "")
            h = st.session_state.get("history")
            if h is not None and isinstance(h, pd.DataFrame):
                gdrive_save_df(h, f"history_{season_lbl}.csv", GDRIVE_FOLDER_ID)
    except Exception:
        st.warning("⚠️ Sauvegarde Drive (historique) impossible (local ok).")

    return True



# =====================================================
# FANTRAX PARSER
# =====================================================
def parse_fantrax(upload):
    raw_lines = upload.read().decode("utf-8", errors="ignore").splitlines()
    raw_lines = [re.sub(r"[\x00-\x1f\x7f]", "", l) for l in raw_lines]

    def detect_sep(lines):
        for l in lines:
            low = l.lower()
            if "player" in low and "salary" in low:
                for d in [",", ";", "\t", "|"]:
                    if d in l:
                        return d
        return ","

    sep = detect_sep(raw_lines)
    header_idxs = [i for i, l in enumerate(raw_lines) if ("player" in l.lower() and "salary" in l.lower() and sep in l)]
    if not header_idxs:
        raise ValueError("Colonnes Fantrax non détectées (Player/Salary).")

    def read_section(start, end):
        lines = [l for l in raw_lines[start:end] if l.strip() != ""]
        if len(lines) < 2:
            return None
        dfp = pd.read_csv(io.StringIO("\n".join(lines)), sep=sep, engine="python", on_bad_lines="skip")
        dfp.columns = [c.strip().replace('"', "") for c in dfp.columns]
        return dfp

    parts = []
    for i, h in enumerate(header_idxs):
        end = header_idxs[i + 1] if i + 1 < len(header_idxs) else len(raw_lines)
        dfp = read_section(h, end)
        if dfp is not None and not dfp.empty:
            parts.append(dfp)
    if not parts:
        raise ValueError("Sections Fantrax détectées mais aucune donnée exploitable.")

    df = pd.concat(parts, ignore_index=True)

    def find_col(possibles):
        for p in possibles:
            for c in df.columns:
                if p in c.lower():
                    return c
        return None

    player_col = find_col(["player"])
    salary_col = find_col(["salary"])
    team_col = find_col(["team"])
    pos_col = find_col(["pos"])
    status_col = find_col(["status"])

    if not player_col or not salary_col:
        raise ValueError(f"Colonnes Player/Salary introuvables. Colonnes trouvées: {list(df.columns)}")

    out = pd.DataFrame()
    out["Joueur"] = df[player_col].astype(str).str.strip()
    out["Equipe"] = df[team_col].astype(str).str.strip() if team_col else "N/A"
    out["Pos"] = df[pos_col].astype(str).str.strip() if pos_col else "F"
    out["Pos"] = out["Pos"].apply(normalize_pos)

    sal = (
        df[salary_col].astype(str)
        .str.replace(",", "", regex=False)
        .str.replace(" ", "", regex=False)
        .replace(["None", "nan", "NaN", ""], "0")
    )
    out["Salaire"] = pd.to_numeric(sal, errors="coerce").fillna(0).astype(int) * 1000

    if status_col:
        out["Statut"] = df[status_col].apply(lambda x: "Club École" if "min" in str(x).lower() else "Grand Club")
    else:
        out["Statut"] = "Grand Club"

    out["Slot"] = out["Statut"].apply(lambda s: "Actif" if s == "Grand Club" else "")
    out["IR Date"] = ""
    return clean_data(out)


# =====================================================
# POPUP MOVE DIALOG (ONE SINGLE VERSION)
# =====================================================
def open_move_dialog():
    """
    Pop-up déplacement (PROPRE + SAFE)
    - IR (slot Blessé ou move_source == "ir") : 3 boutons (Actifs/Banc/Mineur) + Annuler
    - Banc (slot Banc ou move_source == "banc") : 3 boutons (Actifs/Mineur/Blessé) + Annuler
    - Sinon : radio destination + Confirmer/Annuler
    """
    ctx = st.session_state.get("move_ctx")
    if not ctx:
        return

    if st.session_state.get("LOCKED"):
        st.warning("🔒 Saison verrouillée : aucun changement permis.")
        clear_move_ctx()
        return

    owner = str(ctx.get("owner", "")).strip()
    joueur = str(ctx.get("joueur", "")).strip()
    nonce = int(ctx.get("nonce", 0))

    df_all = st.session_state.get("data")
    if df_all is None or df_all.empty:
        st.error("Aucune donnée chargée.")
        clear_move_ctx()
        return

    mask = (
        df_all["Propriétaire"].astype(str).str.strip().eq(owner)
        & df_all["Joueur"].astype(str).str.strip().eq(joueur)
    )
    if df_all.loc[mask].empty:
        st.error("Joueur introuvable.")
        clear_move_ctx()
        return

    row = df_all.loc[mask].iloc[0]
    cur_statut = str(row.get("Statut", "")).strip()
    cur_slot = str(row.get("Slot", "")).strip()
    cur_pos = normalize_pos(row.get("Pos", "F"))
    cur_team = str(row.get("Equipe", "")).strip()
    cur_sal = int(row.get("Salaire", 0) or 0)

    def _close():
        clear_move_ctx()

    css = """
    <style>
      .dlg-title{font-weight:1000;font-size:16px;line-height:1.1}
      .dlg-sub{opacity:.75;font-weight:800;font-size:12px;margin-top:2px}
      .btnrow button{height:44px;font-weight:1000}
    </style>
    """

    @st.dialog(f"Déplacement — {joueur}", width="small")
    def _dlg():
        st.markdown(css, unsafe_allow_html=True)

        st.markdown(
            f"<div class='dlg-title'>{html.escape(owner)} • {html.escape(joueur)}</div>"
            f"<div class='dlg-sub'>{html.escape(cur_statut)}"
            f"{(' / ' + html.escape(cur_slot)) if cur_slot else ''}"
            f" • {html.escape(cur_pos)} • {html.escape(cur_team)} • {money(cur_sal)}</div>",
            unsafe_allow_html=True,
        )

        st.divider()

        source = str(st.session_state.get("move_source", "")).strip()
        is_ir = (source == "ir") or (cur_slot == "Blessé")
        is_banc = (source == "banc") or (cur_slot == "Banc")

        # IR -> 3 boutons: Actifs / Banc / Mineur
        if is_ir:
            st.caption("Déplacement IR (3 choix)")
            b1, b2, b3 = st.columns(3)

            if b1.button("🟢 Actifs", use_container_width=True, key=f"ir_to_actif_{owner}_{joueur}_{nonce}"):
                ok = apply_move_with_history(owner, joueur, "Grand Club", "Actif", "IR → Actif")
                if ok:
                    st.toast(f"🟢 {joueur} → Actifs", icon="🟢")
                    _close(); do_rerun()
                else:
                    st.error(st.session_state.get("last_move_error") or "Déplacement refusé.")

            if b2.button("🟡 Banc", use_container_width=True, key=f"ir_to_banc_{owner}_{joueur}_{nonce}"):
                ok = apply_move_with_history(owner, joueur, "Grand Club", "Banc", "IR → Banc")
                if ok:
                    st.toast(f"🟡 {joueur} → Banc", icon="🟡")
                    _close(); do_rerun()
                else:
                    st.error(st.session_state.get("last_move_error") or "Déplacement refusé.")

            if b3.button("🔵 Mineur", use_container_width=True, key=f"ir_to_min_{owner}_{joueur}_{nonce}"):
                ok = apply_move_with_history(owner, joueur, "Club École", "", "IR → Mineur")
                if ok:
                    st.toast(f"🔵 {joueur} → Mineur", icon="🔵")
                    _close(); do_rerun()
                else:
                    st.error(st.session_state.get("last_move_error") or "Déplacement refusé.")

            st.divider()
            if st.button("✖️ Annuler", use_container_width=True, key=f"cancel_ir_{owner}_{joueur}_{nonce}"):
                _close(); do_rerun()
            return

        # Banc -> 3 boutons: Actifs / Mineur / Blessé
        if is_banc:
            st.caption("Déplacement Banc (3 choix)")
            b1, b2, b3 = st.columns(3)

            if b1.button("🟢 Actifs", use_container_width=True, key=f"banc_to_actif_{owner}_{joueur}_{nonce}"):
                ok = apply_move_with_history(owner, joueur, "Grand Club", "Actif", "Banc → Actif")
                if ok:
                    st.toast(f"🟢 {joueur} → Actifs", icon="🟢")
                    _close(); do_rerun()
                else:
                    st.error(st.session_state.get("last_move_error") or "Déplacement refusé.")

            if b2.button("🔵 Mineur", use_container_width=True, key=f"banc_to_min_{owner}_{joueur}_{nonce}"):
                ok = apply_move_with_history(owner, joueur, "Club École", "", "Banc → Mineur")
                if ok:
                    st.toast(f"🔵 {joueur} → Mineur", icon="🔵")
                    _close(); do_rerun()
                else:
                    st.error(st.session_state.get("last_move_error") or "Déplacement refusé.")

            if b3.button("🩹 Blessé", use_container_width=True, key=f"banc_to_ir_{owner}_{joueur}_{nonce}"):
                ok = apply_move_with_history(owner, joueur, cur_statut, "Blessé", "Banc → IR")
                if ok:
                    st.toast(f"🩹 {joueur} placé sur IR", icon="🩹")
                    _close(); do_rerun()
                else:
                    st.error(st.session_state.get("last_move_error") or "Déplacement refusé.")

            st.divider()
            if st.button("✖️ Annuler", use_container_width=True, key=f"cancel_banc_{owner}_{joueur}_{nonce}"):
                _close(); do_rerun()
            return

        # Mode normal
        st.caption("Déplacement (mode normal)")
        destinations = [
            ("🟢 Actifs (GC)", ("Grand Club", "Actif")),
            ("🟡 Banc (GC)", ("Grand Club", "Banc")),
            ("🔵 Mineur (CE)", ("Club École", "")),
            ("🩹 Blessé (IR)", (cur_statut, "Blessé")),  # statut conservé automatiquement
        ]

        current = (cur_statut, cur_slot if cur_slot else "")
        destinations = [d for d in destinations if d[1] != current]

        labels = [d[0] for d in destinations]
        mapping = {d[0]: d[1] for d in destinations}

        choice = st.radio(
            "Destination",
            labels,
            index=0,
            label_visibility="collapsed",
            key=f"dest_{owner}_{joueur}_{nonce}",
        )
        to_statut, to_slot = mapping[choice]

        c1, c2 = st.columns(2)
        if c1.button("✅ Confirmer", type="primary", use_container_width=True, key=f"ok_{owner}_{joueur}_{nonce}"):
            ok = apply_move_with_history(
                owner,
                joueur,
                to_statut,
                to_slot,
                f"{cur_statut}/{cur_slot or '-'} → {to_statut}/{to_slot or '-'}",
            )
            if ok:
                st.toast("✅ Déplacement enregistré", icon="✅")
                _close(); do_rerun()
            else:
                st.error(st.session_state.get("last_move_error") or "Déplacement refusé.")

        if c2.button("✖️ Annuler", use_container_width=True, key=f"cancel_{owner}_{joueur}_{nonce}"):
            _close(); do_rerun()

    _dlg()


# =====================================================
# SIDEBAR — Saison + Équipe + Plafonds (SANS Import)
# =====================================================
st.sidebar.header("📅 Saison")

saisons = ["2024-2025", "2025-2026", "2026-2027"]
auto = saison_auto()
if auto not in saisons:
    saisons.append(auto)
    saisons.sort()

season = st.sidebar.selectbox(
    "Saison",
    saisons,
    index=saisons.index(auto),
    key="sb_season_select",
)
LOCKED = saison_verrouillee(season)

DATA_FILE = f"{DATA_DIR}/fantrax_{season}.csv"
HISTORY_FILE = f"{DATA_DIR}/history_{season}.csv"
st.session_state["DATA_FILE"] = DATA_FILE
st.session_state["HISTORY_FILE"] = HISTORY_FILE
st.session_state["LOCKED"] = LOCKED

# =====================================================
# LOAD DATA / HISTORY quand saison change (persist reboot)
#   ✅ Google Drive (principal si configuré)
#   ✅ fallback CSV local (secondaire)
#   ✅ crée un CSV vide si rien n'existe
#   ✅ Évite "dernier import" sur équipes non importées (filtrage LOGOS)
#   ✅ Migration historique ancien format -> nouveau
# =====================================================

def _safe_empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=REQUIRED_COLS)

def _history_expected_cols():
    return [
        "id", "timestamp", "season",
        "proprietaire", "joueur", "pos", "equipe",
        "from_statut", "from_slot", "to_statut", "to_slot",
        "action",
    ]

def _history_empty_df():
    return pd.DataFrame(columns=_history_expected_cols())

def _is_old_history_format(h: pd.DataFrame) -> bool:
    old_cols = {"Date", "Action", "Propriétaire", "Joueur"}
    return isinstance(h, pd.DataFrame) and len(old_cols.intersection(set(h.columns))) >= 3

def _migrate_old_history_to_new(h_old: pd.DataFrame) -> pd.DataFrame:
    h_old = h_old.copy()

    if "Propriétaire" in h_old.columns and "proprietaire" not in h_old.columns:
        h_old["proprietaire"] = h_old["Propriétaire"]
    if "Joueur" in h_old.columns and "joueur" not in h_old.columns:
        h_old["joueur"] = h_old["Joueur"]

    if "Date" in h_old.columns:
        h_old["timestamp"] = h_old["Date"].astype(str)
    else:
        h_old["timestamp"] = ""

    act = h_old["Action"].astype(str) if "Action" in h_old.columns else ""
    det = h_old["Détails"].astype(str) if "Détails" in h_old.columns else ""
    det = det.fillna("").astype(str)

    action_txt = act.fillna("").astype(str)
    action_txt = action_txt + det.map(lambda x: f" — {x}" if str(x).strip() else "")

    season_lbl = str(st.session_state.get("season", "") or "").strip()

    h_new = pd.DataFrame()
    h_new["id"] = range(1, len(h_old) + 1)
    h_new["timestamp"] = h_old["timestamp"].fillna("").astype(str)
    h_new["season"] = season_lbl
    h_new["proprietaire"] = h_old.get("proprietaire", "").fillna("").astype(str)
    h_new["joueur"] = h_old.get("joueur", "").fillna("").astype(str)
    h_new["pos"] = ""
    h_new["equipe"] = ""
    h_new["from_statut"] = ""
    h_new["from_slot"] = ""
    h_new["to_statut"] = ""
    h_new["to_slot"] = ""
    h_new["action"] = action_txt.fillna("").astype(str)

    # tri temporel si possible
    h_new["__dt"] = pd.to_datetime(h_new["timestamp"], errors="coerce")
    h_new = h_new.sort_values("__dt", ascending=True).drop(columns="__dt", errors="ignore").reset_index(drop=True)
    h_new["id"] = range(1, len(h_new) + 1)

    # assure toutes colonnes
    for c in _history_expected_cols():
        if c not in h_new.columns:
            h_new[c] = ""

    return h_new[_history_expected_cols()]

def _filter_to_known_teams(df_in: pd.DataFrame) -> pd.DataFrame:
    """
    Empêche que des équipes non importées 'héritent' d'anciens joueurs.
    On ne garde que les propriétaires présents dans LOGOS.
    """
    if df_in is None or not isinstance(df_in, pd.DataFrame) or df_in.empty:
        return df_in

    if "Propriétaire" not in df_in.columns:
        return df_in

    known = []
    try:
        known = [str(k).strip() for k in list(LOGOS.keys())]
    except Exception:
        known = []

    if not known:
        return df_in

    return df_in[df_in["Propriétaire"].astype(str).str.strip().isin(known)].copy()

# -----------------------------
# DATA — load on season change
# -----------------------------
if "season" not in st.session_state or st.session_state["season"] != season:
    df_loaded: pd.DataFrame | None = None
    drive_ok = False

    # 1) Drive (priorité)
    if "_drive_enabled" in globals() and _drive_enabled():
        try:
            df_loaded = gdrive_load_df(f"fantrax_{season}.csv", GDRIVE_FOLDER_ID)
            drive_ok = True
        except Exception as e:
            df_loaded = None
            drive_ok = False
            st.sidebar.warning(
                f"⚠️ Drive indisponible (fallback local data). ({type(e).__name__}: {e})"
            )

    # 2) Local fallback
    if df_loaded is None:
        if os.path.exists(DATA_FILE):
            try:
                df_loaded = pd.read_csv(DATA_FILE)
            except Exception:
                df_loaded = _safe_empty_df()
        else:
            df_loaded = _safe_empty_df()
            try:
                df_loaded.to_csv(DATA_FILE, index=False)
            except Exception:
                pass

    # 3) Clean + filtre équipes connues (évite héritage)
    df_loaded = clean_data(df_loaded)
    df_loaded = _filter_to_known_teams(df_loaded)

    st.session_state["data"] = df_loaded

    # 4) Save local cache
    try:
        st.session_state["data"].to_csv(DATA_FILE, index=False)
    except Exception:
        pass

    # 5) Save Drive (optionnel)
    if "_drive_enabled" in globals() and _drive_enabled() and drive_ok:
        try:
            gdrive_save_df(st.session_state["data"], f"fantrax_{season}.csv", GDRIVE_FOLDER_ID)
        except Exception as e:
            st.sidebar.warning(f"⚠️ Sauvegarde Drive impossible (data). ({type(e).__name__}: {e})")

    st.session_state["season"] = season

# -----------------------------
# HISTORY — load on season change
# -----------------------------
if "history_season" not in st.session_state or st.session_state["history_season"] != season:
    h_loaded: pd.DataFrame | None = None
    drive_ok = False

    # 1) Drive (priorité)
    if "_drive_enabled" in globals() and _drive_enabled():
        try:
            h_loaded = gdrive_load_df(f"history_{season}.csv", GDRIVE_FOLDER_ID)
            drive_ok = True
        except Exception as e:
            h_loaded = None
            drive_ok = False
            st.sidebar.warning(
                f"⚠️ Drive indisponible (fallback local history). ({type(e).__name__}: {e})"
            )

    # 2) Local fallback
    if h_loaded is None:
        if os.path.exists(HISTORY_FILE):
            try:
                h_loaded = pd.read_csv(HISTORY_FILE)
            except Exception:
                h_loaded = _history_empty_df()
        else:
            h_loaded = _history_empty_df()
            try:
                h_loaded.to_csv(HISTORY_FILE, index=False)
            except Exception:
                pass

    # 3) Migration ancien format
    if _is_old_history_format(h_loaded):
        try:
            h_loaded = _migrate_old_history_to_new(h_loaded)
        except Exception:
            h_loaded = _history_empty_df()

    # 4) Normalise colonnes attendues
    if h_loaded is None or not isinstance(h_loaded, pd.DataFrame):
        h_loaded = _history_empty_df()

    for c in _history_expected_cols():
        if c not in h_loaded.columns:
            h_loaded[c] = ""

    h_loaded = h_loaded[_history_expected_cols()].copy()
    st.session_state["history"] = h_loaded

    # 5) Persist local + Drive batch (si dispo)
    season_lbl = str(st.session_state.get("season", season) or season).strip()
    try:
        persist_history(st.session_state["history"], season_lbl)
    except Exception:
        try:
            st.session_state["history"].to_csv(HISTORY_FILE, index=False)
        except Exception:
            pass

    st.session_state["history_season"] = season




# -----------------------------
# Équipe (selectbox) + logo
# -----------------------------
st.sidebar.divider()
st.sidebar.markdown("### 🏒 Équipes")

teams = list(LOGOS.keys())
if not teams:
    st.sidebar.info("Aucune équipe configurée.")
    chosen = ""
else:
    cur = str(st.session_state.get("selected_team", "")).strip()
    if cur not in teams:
        cur = teams[0]
        st.session_state["selected_team"] = cur
        st.session_state["align_owner"] = cur

    chosen = st.sidebar.selectbox(
        "Choisir une équipe",
        teams,
        index=teams.index(cur),
        key="sb_team_select",
    )

    if chosen != cur:
        st.session_state["selected_team"] = chosen
        st.session_state["align_owner"] = chosen
        do_rerun()

    st.sidebar.markdown("---")
    logo_path = team_logo_path(chosen)
    c1, c2 = st.sidebar.columns([1, 2], vertical_alignment="center")
    with c1:
        if logo_path and os.path.exists(logo_path):
            st.image(logo_path, width=56)
    with c2:
        st.markdown(f"**{chosen}**")

# -----------------------------
# Plafonds (UI)
# -----------------------------
st.sidebar.divider()
st.sidebar.header("💰 Plafonds")

if st.sidebar.button("✏️ Modifier les plafonds"):
    st.session_state["edit_plafond"] = True

if st.session_state.get("edit_plafond"):
    st.session_state["PLAFOND_GC"] = st.sidebar.number_input(
        "Plafond Grand Club",
        value=int(st.session_state["PLAFOND_GC"]),
        step=500_000,
    )
    st.session_state["PLAFOND_CE"] = st.sidebar.number_input(
        "Plafond Club École",
        value=int(st.session_state["PLAFOND_CE"]),
        step=250_000,
    )

st.sidebar.metric("🏒 Plafond Grand Club", money(st.session_state["PLAFOND_GC"]))
st.sidebar.metric("🏫 Plafond Club École", money(st.session_state["PLAFOND_CE"]))


# =====================================================
# HEADER GLOBAL (TOP)
# =====================================================


selected_team = get_selected_team()
logo_team = team_logo_path(selected_team)

hL, hR = st.columns([3, 2], vertical_alignment="center")
with hL:
    st.markdown("## 🏒 PMS")
with hR:
    r1, r2 = st.columns([1, 4], vertical_alignment="center")
    with r1:
        if logo_team:
            st.image(logo_team, width=46)
    with r2:
        if selected_team:
            st.markdown(f"### {selected_team}")
        else:
            st.caption("Sélectionne une équipe dans le menu à gauche")


# =====================================================
# DATA (ne stop plus l'app si vide)
# =====================================================
df = st.session_state.get("data")
if df is None:
    df = pd.DataFrame(columns=REQUIRED_COLS)

df = clean_data(df)
st.session_state["data"] = df


# =====================================================
# PLAFONDS — toutes les équipes (LOGOS) même si df vide
#   ✅ IR exclu
#   ✅ 0$ si équipe vide
#   ✅ colonne "Importé" (utile pour Tableau)
# =====================================================
teams_all = sorted(list(LOGOS.keys())) if "LOGOS" in globals() else []

resume = []
for p in teams_all:
    team = str(p).strip()

    d = df[df["Propriétaire"].astype(str).str.strip().eq(team)].copy()

    # IR exclu
    if d.empty:
        total_gc = 0
        total_ce = 0
    else:
        total_gc = d[(d["Statut"] == "Grand Club") & (d["Slot"] != "Blessé")]["Salaire"].sum()
        total_ce = d[(d["Statut"] == "Club École") & (d["Slot"] != "Blessé")]["Salaire"].sum()

    resume.append(
        {
            "Importé": "✅" if (not d.empty) else "—",
            "Propriétaire": team,
            "Logo": team_logo_path(team),  # logo officiel de l’équipe
            "Total Grand Club": int(total_gc),
            "Montant Disponible GC": int(int(st.session_state["PLAFOND_GC"]) - int(total_gc)),
            "Total Club École": int(total_ce),
            "Montant Disponible CE": int(int(st.session_state["PLAFOND_CE"]) - int(total_ce)),
        }
    )

plafonds = pd.DataFrame(resume)




# =====================================================
# TABS (Admin seulement pour Whalers)
# =====================================================
is_admin = _is_admin_whalers()

if is_admin:
    tab1, tabA, tabJ, tabH, tab2, tabAdmin, tab3 = st.tabs(
        [
            "📊 Tableau",
            "🧾 Alignement",
            "👤 Joueurs",
            "🕘 Historique",
            "⚖️ Transactions",
            "🛠️ Gestion Admin",
            "🧠 Recommandations",
        ]
    )
else:
    tab1, tabA, tabJ, tabH, tab2, tab3 = st.tabs(
        [
            "📊 Tableau",
            "🧾 Alignement",
            "👤 Joueurs",
            "🕘 Historique",
            "⚖️ Transactions",
            "🧠 Recommandations",
        ]
    )
    tabAdmin = None  # 🔒 important pour éviter NameError


# =====================================================
# TAB Admin (Whalers only) — MULTI TEAM IMPORT SAFE
# =====================================================
if tabAdmin is not None:
    with tabAdmin:
        st.subheader("🛠️ Gestion Admin")

        # ... (tout ton code Admin ici: import multi-équipes, tests drive, export, backups, etc.)


        # =====================================================
        # 📥 IMPORT (TOP) — MULTI TEAM
        #   ✅ dropdown équipe en premier
        #   ✅ uploaders ensuite avec keys uniques
        # =====================================================
        st.markdown("### 📥 Import (multi-équipes)")
        manifest = load_init_manifest() or {}
        if "fantrax_by_team" not in manifest:
            manifest["fantrax_by_team"] = {}

        # --- Choix équipe (AU-DESSUS)
        teams = sorted(list(LOGOS.keys())) if "LOGOS" in globals() else ["Whalers"]
        if not teams:
            teams = ["Whalers"]

        # défaut = équipe sélectionnée dans sidebar si possible
        default_owner = str(get_selected_team() or "").strip()
        if default_owner not in teams:
            default_owner = teams[0]

        chosen_owner = st.selectbox(
            "Importer l'alignement dans quelle équipe ?",
            teams,
            index=(teams.index(default_owner) if default_owner in teams else 0),
            key="admin_import_team_pick",
        )

        clear_team_before = st.checkbox(
            f"Vider l’alignement de {chosen_owner} avant import",
            value=True,
            help="Recommandé si tu réimportes la même équipe pour éviter des restes/doublons.",
            key="admin_clear_team_before",
        )

        st.markdown("#### Fichiers")
        u_nonce = int(st.session_state.get("uploader_nonce", 0))

        c_init1, c_init2 = st.columns(2)
        with c_init1:
            init_align = st.file_uploader(
                "CSV — Alignement (Fantrax)",
                type=["csv", "txt"],
                help="Import dans UNE équipe. Les autres équipes restent intactes.",
                key=f"admin_import_align__{season}__{chosen_owner}__{u_nonce}",
            )

        with c_init2:
            init_hist = st.file_uploader(
                "CSV — Historique (optionnel)",
                type=["csv", "txt"],
                help="Optionnel: injecte un historique initial.",
                key=f"admin_import_hist__{season}__{chosen_owner}__{u_nonce}",
            )

        st.caption("Étapes: 1) Prévisualiser → 2) Confirmer l'import")

        c_btn1, c_btn2, c_btn3 = st.columns([1, 1, 2])

        # -----------------------------
        # 1) PRÉVISUALISER
        # -----------------------------
        with c_btn1:
            if st.button("👀 Prévisualiser", use_container_width=True, key="admin_preview_import"):
                if init_align is None:
                    st.warning("Choisis un fichier CSV alignement avant de prévisualiser.")
                else:
                    try:
                        buf = io.BytesIO(init_align.getbuffer())
                        buf.name = init_align.name

                        df_import = parse_fantrax(buf)
                        if df_import is None or df_import.empty:
                            st.error("❌ CSV Fantrax invalide : aucune donnée exploitable.")
                        else:
                            df_import = ensure_owner_column(df_import, fallback_owner=chosen_owner)
                            df_import["Propriétaire"] = str(chosen_owner).strip()
                            df_import = clean_data(df_import)

                            st.session_state["init_preview_df"] = df_import
                            st.session_state["init_preview_owner"] = str(chosen_owner).strip()
                            st.session_state["init_preview_filename"] = init_align.name

                            st.success(f"✅ Preview prête — {len(df_import)} joueur(s) pour **{chosen_owner}**.")
                    except Exception as e:
                        st.error(f"❌ Preview échouée : {type(e).__name__}: {e}")

        preview_df = st.session_state.get("init_preview_df")
        if isinstance(preview_df, pd.DataFrame) and not preview_df.empty:
            with st.expander("🔎 Aperçu (20 premières lignes)", expanded=True):
                st.dataframe(preview_df.head(20), use_container_width=True)

            st.info(
                f"Prêt: **{len(preview_df)}** joueur(s) → **{st.session_state.get('init_preview_owner','')}** "
                f"(fichier: {st.session_state.get('init_preview_filename','')})"
            )

        # -----------------------------
        # 2) CONFIRMER — REPLACE ONLY TEAM
        # -----------------------------
        with c_btn2:
            disabled_confirm = not (isinstance(preview_df, pd.DataFrame) and not preview_df.empty)

            if st.button(
                "✅ Confirmer l'import",
                use_container_width=True,
                disabled=disabled_confirm,
                key="admin_confirm_import",
            ):
                try:
                    df_team = st.session_state.get("init_preview_df")
                    owner_final = str(st.session_state.get("init_preview_owner", chosen_owner) or "").strip()
                    filename_final = st.session_state.get("init_preview_filename", "") or (init_align.name if init_align else "")

                    if df_team is None or df_team.empty:
                        st.error("Aucune preview valide.")
                    else:
                        # ---- Sauvegarde brute (par équipe) dans /data
                        saved_path = ""
                        try:
                            safe_team = owner_final.replace(" ", "_")
                            saved_path = save_uploaded_csv(init_align, f"initial_fantrax_{season}_{safe_team}.csv")
                        except Exception:
                            saved_path = ""

                        manifest["fantrax_by_team"][owner_final] = {
                            "path": saved_path,
                            "uploaded_name": filename_final,
                            "season": season,
                            "saved_at": datetime.now().isoformat(),
                            "team": owner_final,
                        }
                        save_init_manifest(manifest)

                        # ---- Merge: garde les autres équipes, remplace owner_final
                        df_cur = st.session_state.get("data")
                        if df_cur is None or not isinstance(df_cur, pd.DataFrame):
                            df_cur = pd.DataFrame(columns=REQUIRED_COLS)
                        df_cur = clean_data(df_cur)

                        df_team = df_team.copy()
                        df_team["Propriétaire"] = owner_final
                        df_team = clean_data(df_team)

                        if clear_team_before:
                            keep = df_cur[df_cur["Propriétaire"].astype(str).str.strip() != owner_final].copy()
                            df_new = pd.concat([keep, df_team], ignore_index=True)
                        else:
                            df_new = pd.concat([df_cur, df_team], ignore_index=True)

                        # Dédupe sécurité
                        if {"Propriétaire", "Joueur"}.issubset(df_new.columns):
                            df_new["Propriétaire"] = df_new["Propriétaire"].astype(str).str.strip()
                            df_new["Joueur"] = df_new["Joueur"].astype(str).str.strip()
                            df_new = df_new.drop_duplicates(subset=["Propriétaire", "Joueur"], keep="last")

                        df_new = clean_data(df_new)
                        st.session_state["data"] = df_new

                        # Persist (local + Drive batch)
                        season_lbl = str(st.session_state.get("season", season)).strip()
                        persist_data(df_new, season_lbl)

                        # Resync UI
                        st.session_state["selected_team"] = owner_final
                        st.session_state["align_owner"] = owner_final

                        # Clear move dialog state (évite popup sur joueur disparu)
                        clear_move_ctx()

                        # Trace
                        try:
                            history_add(
                                action="IMPORT_ALIGNEMENT_EQUIPE",
                                owner=owner_final,
                                details=f"{len(df_team)} joueurs importés (fichier: {filename_final})",
                            )
                        except Exception:
                            pass

                        # Historique initial (optionnel)
                        if init_hist is not None:
                            try:
                                hist_path = save_uploaded_csv(init_hist, f"initial_history_{season}.csv")
                                manifest["history"] = {
                                    "path": hist_path,
                                    "uploaded_name": init_hist.name,
                                    "season": season,
                                    "saved_at": datetime.now().isoformat(),
                                }
                                save_init_manifest(manifest)

                                h0 = pd.read_csv(hist_path)
                                st.session_state["history"] = h0
                                persist_history(h0, season_lbl)
                            except Exception as e:
                                st.warning(f"⚠️ Historique initial non chargé : {type(e).__name__}: {e}")

                        # Reset uploaders
                        st.session_state["uploader_nonce"] = st.session_state.get("uploader_nonce", 0) + 1
                        st.session_state.pop("init_preview_df", None)
                        st.session_state.pop("init_preview_owner", None)
                        st.session_state.pop("init_preview_filename", None)

                        st.success(f"✅ Import OK — seule l’équipe **{owner_final}** a été mise à jour.")
                        do_rerun()

                except Exception as e:
                    st.error(f"❌ Import échoué : {type(e).__name__}: {e}")

        # -----------------------------
        # 3) État imports (per team)
        # -----------------------------
        with c_btn3:
            st.markdown("#### 📌 Derniers imports par équipe")
            by_team = manifest.get("fantrax_by_team", {}) or {}
            if not by_team:
                st.caption("— Aucun import enregistré —")
            else:
                rows = []
                for team, info in by_team.items():
                    rows.append(
                        {
                            "Équipe": team,
                            "Fichier": info.get("uploaded_name", ""),
                            "Date": info.get("saved_at", ""),
                            "Path": os.path.basename(info.get("path", "") or ""),
                        }
                    )
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


            # =====================================================
            # 📤 EXPORT CSV (ADMIN ONLY)
            # =====================================================
            st.markdown("### 📤 Export CSV")

            data_file = st.session_state.get("DATA_FILE", "")
            hist_file = st.session_state.get("HISTORY_FILE", "")
            season_lbl = st.session_state.get("season", season)

            e1, e2 = st.columns(2)

            with e1:
                if data_file and os.path.exists(data_file):
                    with open(data_file, "rb") as f:
                        st.download_button(
                            "⬇️ Export Alignement (CSV)",
                            data=f.read(),
                            file_name=f"fantrax_{season_lbl}.csv",
                            mime="text/csv",
                            use_container_width=True,
                            key=f"dl_align_{season_lbl}_admin_local",
                        )
                else:
                    st.info("Aucun alignement à exporter.")

            with e2:
                if hist_file and os.path.exists(hist_file):
                    with open(hist_file, "rb") as f:
                        st.download_button(
                            "⬇️ Export Historique (CSV)",
                            data=f.read(),
                            file_name=f"history_{season_lbl}.csv",
                            mime="text/csv",
                            use_container_width=True,
                            key=f"dl_hist_{season_lbl}_admin_local",
                        )
                else:
                    st.info("Aucun historique à exporter.")

            # =====================================================
            # 🧨 SUPPRIMER ALIGNEMENT D'UNE ÉQUIPE (ADMIN ONLY) — SAFE + BACKUP
            # =====================================================
            st.divider()
            st.markdown("### 🧨 Supprimer l’alignement d’une équipe")

            df_cur = st.session_state.get("data")
            if df_cur is None or not isinstance(df_cur, pd.DataFrame):
                st.warning("Aucune donnée chargée.")
            else:
                if "Propriétaire" not in df_cur.columns:
                    st.error("Colonne 'Propriétaire' manquante dans les données.")
                else:
                    teams_in_data = sorted(df_cur["Propriétaire"].dropna().astype(str).unique().tolist())
                    if not teams_in_data:
                        st.info("Aucune équipe trouvée dans les données.")
                    else:
                        colS1, colS2 = st.columns([2, 1], vertical_alignment="center")
                        with colS1:
                            del_team = st.selectbox(
                                "Choisir l’équipe à supprimer (alignement)",
                                teams_in_data,
                                key="admin_del_team_pick_safe",
                            )
                        with colS2:
                            del_history_too = st.checkbox(
                                "Supprimer aussi son historique",
                                value=False,
                                key="admin_del_team_history_too_safe",
                            )

                        n_rows = int((df_cur["Propriétaire"].astype(str) == str(del_team)).sum())
                        st.caption(f"Joueurs dans l’équipe **{del_team}** : **{n_rows}**")

                        st.markdown("#### Confirmation")
                        typed = st.text_input(
                            f"Pour confirmer, retape exactement : {del_team}",
                            value="",
                            key="admin_del_team_type_name",
                        )
                        confirm_ok = (str(typed).strip() == str(del_team).strip())

                        if st.button(
                            "🗑️ SUPPRIMER DÉFINITIVEMENT l’alignement de cette équipe",
                            type="primary",
                            use_container_width=True,
                            disabled=(not confirm_ok),
                            key="admin_del_team_btn_safe",
                        ):
                            if st.session_state.get("LOCKED"):
                                st.error("🔒 Saison verrouillée : suppression impossible.")
                            else:
                                # 1) BACKUP
                                try:
                                    backup_dir = os.path.join(DATA_DIR, "backups")
                                    os.makedirs(backup_dir, exist_ok=True)

                                    season_lbl = str(st.session_state.get("season", "")).strip() or "season"
                                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

                                    df_team = df_cur[df_cur["Propriétaire"].astype(str) == str(del_team)].copy()
                                    backup_data_path = os.path.join(
                                        backup_dir,
                                        f"backup_align_{season_lbl}_{del_team}_{ts}.csv".replace(" ", "_"),
                                    )
                                    df_team.to_csv(backup_data_path, index=False)

                                    backup_hist_path = ""
                                    if del_history_too:
                                        h = st.session_state.get("history")
                                        if isinstance(h, pd.DataFrame) and not h.empty:
                                            # harmoniser colonne proprietaire
                                            if "proprietaire" not in h.columns and "Propriétaire" in h.columns:
                                                h = h.rename(columns={"Propriétaire": "proprietaire"})
                                            if "proprietaire" in h.columns:
                                                h_team = h[h["proprietaire"].astype(str) == str(del_team)].copy()
                                                backup_hist_path = os.path.join(
                                                    backup_dir,
                                                    f"backup_hist_{season_lbl}_{del_team}_{ts}.csv".replace(" ", "_"),
                                                )
                                                h_team.to_csv(backup_hist_path, index=False)

                                    st.success("✅ Backup créé avant suppression.")
                                    st.caption(f"Backup alignement : `{backup_data_path}`")
                                    if backup_hist_path:
                                        st.caption(f"Backup historique : `{backup_hist_path}`")

                                except Exception as e:
                                    st.warning(f"⚠️ Backup impossible (je continue quand même) : {type(e).__name__}: {e}")

                                # 2) SUPPRESSION DANS DATA
                                df_new = df_cur.copy()
                                df_new = df_new[df_new["Propriétaire"].astype(str) != str(del_team)].reset_index(drop=True)
                                df_new = clean_data(df_new)
                                st.session_state["data"] = df_new

                                # 3) SUPPRESSION DANS HISTORY (optionnel)
                                if del_history_too:
                                    h = st.session_state.get("history")
                                    if isinstance(h, pd.DataFrame) and not h.empty:
                                        if "proprietaire" not in h.columns and "Propriétaire" in h.columns:
                                            h = h.rename(columns={"Propriétaire": "proprietaire"})
                                        if "proprietaire" in h.columns:
                                            h2 = h[h["proprietaire"].astype(str) != str(del_team)].reset_index(drop=True)
                                            st.session_state["history"] = h2
                                            try:
                                                persist_history(h2, st.session_state.get("season", ""))
                                            except Exception:
                                                pass

                                # 4) PERSIST (local + Drive batch)
                                try:
                                    persist_data(df_new, st.session_state.get("season", ""))
                                except Exception as e:
                                    st.warning(f"⚠️ Suppression OK mais persistance data a échoué: {type(e).__name__}: {e}")

                                # 5) TRACE
                                try:
                                    history_add(
                                        action="DELETE_TEAM_ALIGNEMENT",
                                        owner=str(del_team),
                                        details=f"Alignement supprimé ({n_rows} lignes). Historique supprimé: {bool(del_history_too)}",
                                    )
                                except Exception:
                                    pass

                                st.toast(f"🗑️ Alignement supprimé : {del_team}", icon="🗑️")

                                # (optionnel) flush Drive immédiat
                                if "flush_drive_queue" in globals():
                                    n, errs = flush_drive_queue(force=True)
                                    if errs:
                                        st.warning("⚠️ Suppression OK, mais Drive flush a eu des erreurs:\n" + "\n".join(errs))
                                    else:
                                        st.success(f"✅ Drive flush OK — {n} fichier(s)")

                                do_rerun()

            # =====================================================
            # ♻️ RESTAURER UN BACKUP (ADMIN PRO) — auto-detect + preview + merge history
            # =====================================================
            st.divider()
            st.markdown("### ♻️ Restaurer un backup (PRO)")

            backup_dir = os.path.join(DATA_DIR, "backups")
            os.makedirs(backup_dir, exist_ok=True)

            def _list_csv_pro(dirpath: str) -> list[str]:
                try:
                    files = [f for f in os.listdir(dirpath) if f.lower().endswith(".csv")]
                    files.sort(reverse=True)
                    return files
                except Exception:
                    return []

            def _infer_team_from_backup_name_pro(fname: str) -> str:
                try:
                    base = os.path.basename(fname).replace(".csv", "")
                    parts = base.split("_")
                    if len(parts) >= 6 and parts[0] == "backup" and parts[1] == "align":
                        team = "_".join(parts[3:-1]).replace("_", " ").strip()
                        return team
                except Exception:
                    pass
                return ""

            align_backups = [f for f in _list_csv_pro(backup_dir) if f.lower().startswith("backup_align_")]
            hist_backups = [f for f in _list_csv_pro(backup_dir) if f.lower().startswith("backup_hist_")]

            if not align_backups:
                st.info("Aucun backup alignement trouvé dans /data/backups/.")
            else:
                pick_align = st.selectbox("Choisir un backup alignement", align_backups, key="admin_restore_align_pick_pro")

                inferred_team = _infer_team_from_backup_name_pro(pick_align)
                if inferred_team:
                    st.caption(f"Équipe détectée : **{inferred_team}**")
                else:
                    st.warning("Équipe non détectée automatiquement (nom atypique). Tu pourras la choisir manuellement.")

                df_preview = None
                preview_err = None
                try:
                    df_preview = pd.read_csv(os.path.join(backup_dir, pick_align))
                    df_preview = clean_data(df_preview)
                except Exception as e:
                    preview_err = f"{type(e).__name__}: {e}"

                if preview_err:
                    st.error(f"Impossible de lire le backup: {preview_err}")
                else:
                    df_cur = st.session_state.get("data")
                    cur_teams = []
                    if isinstance(df_cur, pd.DataFrame) and not df_cur.empty and "Propriétaire" in df_cur.columns:
                        cur_teams = sorted(df_cur["Propriétaire"].dropna().astype(str).unique().tolist())

                    default_team = inferred_team if inferred_team else (cur_teams[0] if cur_teams else "")
                    target_team = st.selectbox(
                        "Équipe cible (sera forcée dans les lignes du backup)",
                        options=(cur_teams if cur_teams else ([default_team] if default_team else [""])),
                        index=(cur_teams.index(default_team) if (default_team in cur_teams) else 0),
                        key="admin_restore_target_team_pro",
                    )
                    if not target_team:
                        target_team = default_team

                    mode = st.radio(
                        "Mode de restauration",
                        ["Remplacer l’équipe", "Ajouter (merge)"],
                        index=0,
                        horizontal=True,
                        key="admin_restore_mode_pro",
                    )

                    st.caption(f"Backup: **{pick_align}** • lignes: **{len(df_preview)}**")

                    with st.expander("🔎 Aperçu (20 premières lignes)", expanded=True):
                        st.dataframe(df_preview.head(20), use_container_width=True)

                    st.markdown("#### Historique (optionnel)")
                    restore_hist = st.checkbox("Restaurer un backup d’historique", value=False, key="admin_restore_hist_toggle_pro")

                    hist_mode = "Remplacer tout"
                    pick_hist = None
                    if restore_hist:
                        if not hist_backups:
                            st.warning("Aucun backup historique trouvé.")
                        else:
                            pick_hist = st.selectbox("Choisir un backup historique", hist_backups, key="admin_restore_hist_pick_pro")
                            hist_mode = st.radio(
                                "Mode historique",
                                ["Remplacer tout", "MERGE (ajouter + dédupliquer)"],
                                index=1,
                                horizontal=True,
                                key="admin_restore_hist_mode_pro",
                                help="MERGE garde l'historique existant et ajoute celui du backup, en dédupliquant si possible.",
                            )

                    st.markdown("#### Confirmation")
                    typed_restore = st.text_input(
                        f"Pour confirmer, tape exactement : RESTORE {target_team}",
                        value="",
                        key="admin_restore_type_pro",
                    )
                    confirm_restore = (typed_restore.strip() == f"RESTORE {target_team}")

                    if st.button(
                        "♻️ RESTAURER MAINTENANT",
                        type="primary",
                        use_container_width=True,
                        disabled=(not confirm_restore),
                        key="admin_restore_btn_pro",
                    ):
                        if st.session_state.get("LOCKED"):
                            st.error("🔒 Saison verrouillée : restauration impossible.")
                        else:
                            try:
                                df_b = df_preview.copy()
                                if "Propriétaire" not in df_b.columns:
                                    df_b["Propriétaire"] = str(target_team)
                                df_b["Propriétaire"] = str(target_team)
                                df_b = clean_data(df_b)

                                df_cur2 = st.session_state.get("data")
                                if df_cur2 is None or not isinstance(df_cur2, pd.DataFrame):
                                    df_cur2 = pd.DataFrame(columns=REQUIRED_COLS)
                                df_cur2 = clean_data(df_cur2)

                                if mode == "Remplacer l’équipe":
                                    df_keep = df_cur2[df_cur2["Propriétaire"].astype(str) != str(target_team)].copy()
                                    df_new = pd.concat([df_keep, df_b], ignore_index=True)
                                else:
                                    df_new = pd.concat([df_cur2, df_b], ignore_index=True)
                                    df_new = df_new.drop_duplicates(subset=["Propriétaire", "Joueur"], keep="last")

                                df_new = clean_data(df_new)
                                st.session_state["data"] = df_new
                                persist_data(df_new, st.session_state.get("season", ""))

                                if restore_hist and pick_hist:
                                    h_path = os.path.join(backup_dir, pick_hist)
                                    h_b = pd.read_csv(h_path)
                                    if "proprietaire" not in h_b.columns and "Propriétaire" in h_b.columns:
                                        h_b = h_b.rename(columns={"Propriétaire": "proprietaire"})

                                    h_cur = st.session_state.get("history")
                                    if (hist_mode == "MERGE (ajouter + dédupliquer)") and isinstance(h_cur, pd.DataFrame) and not h_cur.empty:
                                        h_merge = pd.concat([h_cur, h_b], ignore_index=True)
                                        if "id" in h_merge.columns:
                                            h_merge = h_merge.drop_duplicates(subset=["id"], keep="last")
                                        else:
                                            key_cols = [c for c in ["timestamp", "season", "proprietaire", "joueur", "from_statut", "from_slot", "to_statut", "to_slot", "action"] if c in h_merge.columns]
                                            if key_cols:
                                                h_merge = h_merge.drop_duplicates(subset=key_cols, keep="last")
                                        st.session_state["history"] = h_merge.reset_index(drop=True)
                                    else:
                                        st.session_state["history"] = h_b

                                    try:
                                        persist_history(st.session_state["history"], st.session_state.get("season", ""))
                                    except Exception:
                                        pass

                                try:
                                    history_add(
                                        action="RESTORE_BACKUP_ALIGNEMENT",
                                        owner=str(target_team),
                                        details=f"align={pick_align} | mode={mode} | hist={(pick_hist or 'no')} | hist_mode={hist_mode}",
                                    )
                                except Exception:
                                    pass

                                st.toast("♻️ Backup restauré", icon="♻️")

                                if "flush_drive_queue" in globals():
                                    n, errs = flush_drive_queue(force=True)
                                    if errs:
                                        st.warning("⚠️ Restore OK, mais Drive flush a eu des erreurs:\n" + "\n".join(errs))
                                    else:
                                        st.success(f"✅ Drive flush OK — {n} fichier(s)")

                                do_rerun()

                            except Exception as e:
                                st.error(f"❌ Restauration échouée : {type(e).__name__}: {e}")

            # =====================================================
            # 🗂️ GESTION DES BACKUPS (LISTE + RESTORE + DELETE + ROTATION)
            # =====================================================
            st.divider()
            st.markdown("### 🗂️ Gestion des backups")

            backup_dir = os.path.join(DATA_DIR, "backups")
            os.makedirs(backup_dir, exist_ok=True)

            def _parse_backup_filename_mgr(fname: str) -> dict:
                out = {"file": fname, "type": "", "season": "", "team": "", "ts": "", "path": os.path.join(backup_dir, fname)}
                base = os.path.basename(fname)
                if not base.lower().endswith(".csv"):
                    return out
                name = base[:-4]
                parts = name.split("_")
                if len(parts) < 5:
                    return out
                if parts[0] != "backup":
                    return out
                if parts[1] not in {"align", "hist"}:
                    return out
                out["type"] = "align" if parts[1] == "align" else "hist"
                out["season"] = parts[2]
                out["ts"] = parts[-1]
                out["team"] = "_".join(parts[3:-1]).replace("_", " ").strip()
                return out

            def _list_backups_mgr() -> list[dict]:
                try:
                    files = [f for f in os.listdir(backup_dir) if f.lower().endswith(".csv") and f.lower().startswith("backup_")]
                    rows = [_parse_backup_filename_mgr(f) for f in files]
                    rows.sort(key=lambda r: r.get("ts", ""), reverse=True)
                    return rows
                except Exception:
                    return []

            st.markdown("#### 🧹 Rotation auto des backups")
            keep_n = st.number_input(
                "Garder les N derniers backups par (type, saison, équipe)",
                min_value=1,
                max_value=200,
                value=30,
                step=5,
                key="bk_keep_n",
            )

            def _apply_rotation_mgr(keep_n: int) -> tuple[int, list[str]]:
                rows = _list_backups_mgr()
                groups = {}
                for r in rows:
                    k = (r.get("type", ""), r.get("season", ""), r.get("team", ""))
                    groups.setdefault(k, []).append(r)
                deleted = 0
                errs: list[str] = []
                for _, items in groups.items():
                    items.sort(key=lambda x: x.get("ts", ""), reverse=True)
                    for r in items[int(keep_n):]:
                        try:
                            os.remove(r["path"])
                            deleted += 1
                        except Exception as e:
                            errs.append(f"{r['file']}: {type(e).__name__}: {e}")
                return deleted, errs

            c_rot1, c_rot2 = st.columns([1, 2])
            with c_rot1:
                if st.button("🧹 Appliquer la rotation maintenant", use_container_width=True, key="bk_rotation_btn"):
                    n_del, errs = _apply_rotation_mgr(int(keep_n))
                    if errs:
                        st.warning("Rotation appliquée avec erreurs:\n" + "\n".join(errs))
                    st.success(f"✅ Rotation terminée — {n_del} fichier(s) supprimé(s).")
            with c_rot2:
                st.caption("Astuce: garde 30 ou 50. Les anciens sont supprimés automatiquement par groupe (align/hist, saison, équipe).")

            rows = _list_backups_mgr()
            if not rows:
                st.info("Aucun backup trouvé dans `data/backups/`.")
            else:
                st.markdown("#### 🔎 Liste des backups")

                all_types = ["Tous", "align", "hist"]
                all_seasons = ["Toutes"] + sorted(list({r["season"] for r in rows if r.get("season")}), reverse=True)
                all_teams = ["Toutes"] + sorted(list({r["team"] for r in rows if r.get("team") and r.get("team") != "ALL"}))

                f1, f2, f3 = st.columns(3)
                with f1:
                    t_filter = st.selectbox("Type", all_types, index=0, key="bk_type_filter")
                with f2:
                    s_filter = st.selectbox("Saison", all_seasons, index=0, key="bk_season_filter")
                with f3:
                    team_filter = st.selectbox("Équipe", all_teams, index=0, key="bk_team_filter")

                view = rows
                if t_filter != "Tous":
                    view = [r for r in view if r.get("type") == t_filter]
                if s_filter != "Toutes":
                    view = [r for r in view if r.get("season") == s_filter]
                if team_filter != "Toutes":
                    view = [r for r in view if r.get("team") == team_filter]

                if not view:
                    st.info("Aucun backup ne correspond aux filtres.")
                else:
                    head = st.columns([1.0, 1.2, 1.8, 1.6, 2.8, 1.1, 1.1])
                    head[0].markdown("**Type**")
                    head[1].markdown("**Saison**")
                    head[2].markdown("**Équipe**")
                    head[3].markdown("**Timestamp**")
                    head[4].markdown("**Fichier**")
                    head[5].markdown("**⬇️**")
                    head[6].markdown("**🗑️**")

                    for r in view[:200]:
                        cols = st.columns([1.0, 1.2, 1.8, 1.6, 2.8, 1.1, 1.1])
                        cols[0].markdown(r.get("type", ""))
                        cols[1].markdown(r.get("season", ""))
                        cols[2].markdown(r.get("team", ""))
                        cols[3].markdown(r.get("ts", ""))
                        cols[4].code(r.get("file", ""), language=None)

                        try:
                            with open(r["path"], "rb") as f:
                                cols[5].download_button(
                                    "⬇️",
                                    data=f.read(),
                                    file_name=r["file"],
                                    mime="text/csv",
                                    use_container_width=True,
                                    key=f"bk_dl_{r['file']}",
                                )
                        except Exception:
                            cols[5].write("—")

                        if cols[6].button("🗑️", use_container_width=True, key=f"bk_del_{r['file']}"):
                            try:
                                os.remove(r["path"])
                                st.toast("🗑️ Backup supprimé", icon="🗑️")
                                do_rerun()
                            except Exception as e:
                                st.error(f"Suppression impossible: {type(e).__name__}: {e}")




# =====================================================
# TAB 1 — Tableau
# =====================================================
with tab1:
    st.subheader("📊 Tableau — Masses salariales (toutes les équipes)")

    if plafonds is None or not isinstance(plafonds, pd.DataFrame) or plafonds.empty:
        st.info("Aucune équipe configurée.")
    else:
        view = plafonds.copy()

        # ✅ Guard colonnes attendues (évite KeyError)
        cols = [
            "Importé",
            "Propriétaire",
            "Total Grand Club",
            "Montant Disponible GC",
            "Total Club École",
            "Montant Disponible CE",
        ]
        for c in cols:
            if c not in view.columns:
                # num cols -> 0 ; text cols -> ""
                view[c] = 0 if ("Total" in c or "Montant" in c) else ""

        # ✅ Format $
        for c in ["Total Grand Club", "Montant Disponible GC", "Total Club École", "Montant Disponible CE"]:
            view[c] = view[c].apply(lambda x: money(int(x) if str(x).strip() != "" else 0))

        st.dataframe(
            view[cols],
            use_container_width=True,
            hide_index=True,
        )







# =====================================================
# TAB A — Alignement (SYNC SIDEBAR ONLY)
#   ✅ Aucun selectbox "Propriétaire" ici
#   ✅ Si équipe non importée -> alignement vide (ne montre pas le dernier import)
#   ✅ Fix: used_gc/used_ce toujours définis (évite NameError)
# =====================================================
with tabA:
    st.subheader("🧾 Alignement")

    # Source unique des données
    df = st.session_state.get("data")
    if df is None or not isinstance(df, pd.DataFrame):
        df = pd.DataFrame(columns=REQUIRED_COLS)

    df = clean_data(df)
    st.session_state["data"] = df

    # Équipe sélectionnée (sidebar)
    proprietaire = str(get_selected_team() or "").strip()

    if not proprietaire:
        st.info("Sélectionne une équipe dans le menu à gauche.")
        st.stop()

    # Filtre ROBUSTE (strip)
    dprop = df[df["Propriétaire"].astype(str).str.strip().eq(proprietaire)].copy()

    # ============================
    # ✅ Defaults (évite NameError si équipe vide)
    # ============================
    cap_gc = int(st.session_state.get("PLAFOND_GC", 0) or 0)
    cap_ce = int(st.session_state.get("PLAFOND_CE", 0) or 0)
    used_gc = 0
    used_ce = 0
    remain_gc = cap_gc
    remain_ce = cap_ce
    nb_F = nb_D = nb_G = 0

    # Si aucune donnée pour cette équipe -> affichage vide (IMPORTANT)
    if dprop.empty:
        st.warning(f"Aucun alignement importé pour **{proprietaire}**. Va dans 🛠️ Gestion Admin → Import.")

        # Barres de plafond (0/0)
        j1, j2 = st.columns(2)
        with j1:
            st.markdown(cap_bar_html(used_gc, cap_gc, f"📊 Plafond Grand Club (GC) — {proprietaire}"), unsafe_allow_html=True)
        with j2:
            st.markdown(cap_bar_html(used_ce, cap_ce, f"📊 Plafond Club École (CE) — {proprietaire}"), unsafe_allow_html=True)

        # Sections vides propres
        with st.container(border=True):
            st.markdown("### 🟢 Actifs")
            st.info("Aucun joueur.")
        with st.container(border=True):
            st.markdown("### 🔵 Mineur")
            st.info("Aucun joueur.")
        with st.expander("🟡 Banc", expanded=True):
            st.info("Aucun joueur.")
        with st.expander("🩹 Joueurs Blessés (IR)", expanded=True):
            st.info("Aucun joueur blessé.")

        # Ferme tout popup si jamais un ancien move_ctx traînait
        clear_move_ctx()
        st.stop()

    # ============================
    # Données équipe (non vide)
    # ============================
    injured_all = dprop[dprop.get("Slot", "") == "Blessé"].copy()
    dprop_ok = dprop[dprop.get("Slot", "") != "Blessé"].copy()

    gc_all = dprop_ok[dprop_ok["Statut"] == "Grand Club"].copy()
    ce_all = dprop_ok[dprop_ok["Statut"] == "Club École"].copy()

    gc_actif = gc_all[gc_all.get("Slot", "") == "Actif"].copy()
    gc_banc = gc_all[gc_all.get("Slot", "") == "Banc"].copy()

    # Compteurs positions (Actifs GC)
    tmp = gc_actif.copy()
    if "Pos" not in tmp.columns:
        tmp["Pos"] = "F"
    tmp["Pos"] = tmp["Pos"].apply(normalize_pos)
    nb_F = int((tmp["Pos"] == "F").sum())
    nb_D = int((tmp["Pos"] == "D").sum())
    nb_G = int((tmp["Pos"] == "G").sum())

    # Plafonds (IR exclu déjà car dprop_ok exclut Blessé)
    used_gc = int(gc_all["Salaire"].sum()) if "Salaire" in gc_all.columns else 0
    used_ce = int(ce_all["Salaire"].sum()) if "Salaire" in ce_all.columns else 0
    remain_gc = cap_gc - used_gc
    remain_ce = cap_ce - used_ce

    # Barres plafond
    j1, j2 = st.columns(2)
    with j1:
        st.markdown(cap_bar_html(used_gc, cap_gc, f"📊 Plafond Grand Club (GC) — {proprietaire}"), unsafe_allow_html=True)
    with j2:
        st.markdown(cap_bar_html(used_ce, cap_ce, f"📊 Plafond Club École (CE) — {proprietaire}"), unsafe_allow_html=True)

    # Métriques (pills)
    def gm_metric(label: str, value: str):
        st.markdown(
            f"""
            <div style="text-align:left">
                <div style="font-size:12px;opacity:.75;font-weight:700">{label}</div>
                <div style="font-size:20px;font-weight:1000">{value}</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    cols = st.columns(6)
    with cols[0]:
        gm_metric("Total GC", money(used_gc))
    with cols[1]:
        gm_metric("Reste GC", money(remain_gc))
    with cols[2]:
        gm_metric("Total CE", money(used_ce))
    with cols[3]:
        gm_metric("Reste CE", money(remain_ce))
    with cols[4]:
        gm_metric("Banc", str(len(gc_banc)))
    with cols[5]:
        gm_metric("IR", str(len(injured_all)))

    st.markdown(
        f"**Actifs** — F {_count_badge(nb_F, 12)} • D {_count_badge(nb_D, 6)} • G {_count_badge(nb_G, 2)}",
        unsafe_allow_html=True
    )

    st.divider()

    # Popup guard
    popup_open = st.session_state.get("move_ctx") is not None
    if popup_open:
        st.caption("🔒 Sélection désactivée: un déplacement est en cours.")

    colA, colB = st.columns(2, gap="small")

    with colA:
        with st.container(border=True):
            st.markdown("### 🟢 Actifs")
            if not popup_open:
                p = roster_click_list(gc_actif, proprietaire, "actifs")
                if p:
                    set_move_ctx(proprietaire, p, "actifs")
                    do_rerun()
            else:
                roster_click_list(gc_actif, proprietaire, "actifs_disabled")

    with colB:
        with st.container(border=True):
            st.markdown("### 🔵 Mineur")
            if not popup_open:
                p = roster_click_list(ce_all, proprietaire, "min")
                if p:
                    set_move_ctx(proprietaire, p, "min")
                    do_rerun()
            else:
                roster_click_list(ce_all, proprietaire, "min_disabled")

    st.divider()

    with st.expander("🟡 Banc", expanded=True):
        if gc_banc is None or gc_banc.empty:
            st.info("Aucun joueur.")
        else:
            if not popup_open:
                p = roster_click_list(gc_banc, proprietaire, "banc")
                if p:
                    set_move_ctx(proprietaire, p, "banc")
                    do_rerun()
            else:
                roster_click_list(gc_banc, proprietaire, "banc_disabled")

    with st.expander("🩹 Joueurs Blessés (IR)", expanded=True):
        if injured_all is None or injured_all.empty:
            st.info("Aucun joueur blessé.")
        else:
            if not popup_open:
                p_ir = roster_click_list(injured_all, proprietaire, "ir")
                if p_ir:
                    set_move_ctx(proprietaire, p_ir, "ir")
                    do_rerun()
            else:
                roster_click_list(injured_all, proprietaire, "ir_disabled")

    # Pop-up toujours à la fin du tab
    open_move_dialog()







# =====================================================
# TAB J — Joueurs (Autonomes)
# =====================================================
with tabJ:
    st.subheader("👤 Joueurs (Autonomes)")
    st.caption(
        "Aucun résultat tant qu’aucun filtre n’est rempli "
        "(Nom/Prénom, Équipe, Level/Contrat ou Cap Hit)."
    )

    # -------------------------------------------------
    # GUARDS (local au tab)
    # -------------------------------------------------
    if df is None or df.empty:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
        st.stop()

    if players_db is None or players_db.empty:
        st.error("Impossible de charger la base joueurs.")
        st.caption(f"Chemin attendu : {PLAYERS_DB_FILE}")
        st.stop()

    df_db = players_db.copy()

    # -------------------------------------------------
    # Normalisation colonne Player
    # -------------------------------------------------
    if "Player" not in df_db.columns:
        found = None
        for cand in ["Joueur", "Name", "Full Name", "fullname", "player"]:
            if cand in df_db.columns:
                found = cand
                break
        if found:
            df_db = df_db.rename(columns={found: "Player"})
        else:
            st.error(f"Colonne 'Player' introuvable. Colonnes: {list(df_db.columns)}")
            st.stop()

    # -------------------------------------------------
    # Helpers
    # -------------------------------------------------
    def _clean_intlike(x):
        s = str(x).strip()
        if s == "" or s.lower() in {"nan", "none"}:
            return ""
        if re.match(r"^\d+\.0$", s):
            return s.split(".")[0]
        return s

    def _cap_to_int(v) -> int:
        s = str(v if v is not None else "").strip()
        if s == "" or s.lower() in {"nan", "none"}:
            return 0
        s = s.replace("$", "").replace("€", "").replace("£", "")
        s = s.replace(",", "").replace(" ", "")
        s = re.sub(r"\.0+$", "", s)
        s = re.sub(r"[^\d]", "", s)
        return int(s) if s.isdigit() else 0

    def _money_space(v: int) -> str:
        try:
            return f"{int(v):,}".replace(",", " ") + " $"
        except Exception:
            return "0 $"

    def clear_j_name():
        st.session_state["j_name"] = ""

    # -------------------------------------------------
    # FILTRES PRINCIPAUX
    # -------------------------------------------------
    c1, c2, c3 = st.columns([2, 1, 1])

    # --- Nom / Prénom
    with c1:
        a, b = st.columns([12, 1])
        with a:
            q_name = st.text_input(
                "Nom / Prénom",
                placeholder="Ex: Jack Eichel",
                key="j_name",
            )
        with b:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            st.button(
                "❌",
                key="j_name_clear",
                help="Effacer Nom / Prénom",
                use_container_width=True,
                on_click=clear_j_name,
            )

    # --- Équipe (GUARD)
    with c2:
        if "Team" in df_db.columns:
            teams = sorted(df["Propriétaire"].dropna().astype(str).unique().tolist())
            options_team = ["Toutes"] + teams

            cur_team = st.session_state.get("j_team", "Toutes")
            if cur_team not in options_team:
                st.session_state["j_team"] = "Toutes"

            q_team = st.selectbox("Équipe", options_team, key="j_team")
        else:
            q_team = "Toutes"
            st.selectbox(
                "Équipe",
                ["Toutes"],
                disabled=True,
                key="j_team_disabled",
            )

    # --- Level / Contrat (GUARD IDENTIQUE)
    with c3:
        level_col = "Level" if "Level" in df_db.columns else None
        if level_col:
            levels = sorted(df_db[level_col].dropna().astype(str).unique().tolist())
            options_level = ["Tous"] + levels

            cur_level = st.session_state.get("j_level", "Tous")
            if cur_level not in options_level:
                st.session_state["j_level"] = "Tous"

            q_level = st.selectbox("Level (Contrat)", options_level, key="j_level")
        else:
            q_level = "Tous"
            st.selectbox(
                "Level (Contrat)",
                ["Tous"],
                disabled=True,
                key="j_level_disabled",
            )

    # -------------------------------------------------
    # CAP HIT
    # -------------------------------------------------
    st.divider()
    st.markdown("### 💰 Recherche par Salaire (Cap Hit)")

    cap_col = None
    for cand in ["Cap Hit", "CapHit", "AAV"]:
        if cand in df_db.columns:
            cap_col = cand
            break

    if not cap_col:
        st.warning("Aucune colonne Cap Hit/CapHit/AAV trouvée → filtre salaire désactivé.")
        cap_apply = False
        cap_min = cap_max = 0
    else:
        df_db["_cap_int"] = df_db[cap_col].apply(_cap_to_int)
        cap_apply = st.checkbox("Activer le filtre Cap Hit", value=False, key="cap_apply")
        cap_min, cap_max = st.slider(
            "Plage Cap Hit",
            min_value=0,
            max_value=30_000_000,
            value=(0, 30_000_000),
            step=250_000,
            disabled=(not cap_apply),
            key="cap_slider",
        )
        st.caption(f"Plage sélectionnée : **{_money_space(cap_min)} → {_money_space(cap_max)}**")

    # -------------------------------------------------
    # FILTRAGE
    # -------------------------------------------------
    has_filter = (
        bool(str(q_name).strip())
        or q_team != "Toutes"
        or q_level != "Tous"
        or cap_apply
    )

    if not has_filter:
        st.info("Entre au moins un filtre pour afficher les résultats.")
    else:
        dff = df_db.copy()

        if str(q_name).strip():
            dff = dff[dff["Player"].str.contains(q_name, case=False, na=False)]

        if q_team != "Toutes" and "Team" in dff.columns:
            dff = dff[dff["Team"].astype(str) == q_team]

        if q_level != "Tous" and level_col:
            dff = dff[dff[level_col].astype(str) == q_level]

        if cap_col and cap_apply:
            dff = dff[(dff["_cap_int"] >= cap_min) & (dff["_cap_int"] <= cap_max)]

        if dff.empty:
            st.warning("Aucun joueur trouvé avec ces critères.")
        else:
            dff = dff.head(250).reset_index(drop=True)
            st.markdown("### Résultats")

            show_cols = []
            for c in ["Player", "Team", "Position", cap_col, "Level"]:
                if c and c in dff.columns:
                    show_cols.append(c)

            df_show = dff[show_cols].copy()

            if cap_col in df_show.columns:
                df_show[cap_col] = df_show[cap_col].apply(
                    lambda x: _money_space(_cap_to_int(x))
                )
                df_show = df_show.rename(columns={cap_col: "Cap Hit"})

            for c in df_show.columns:
                df_show[c] = df_show[c].apply(_clean_intlike)

            st.dataframe(df_show, use_container_width=True, hide_index=True)



# =====================================================
# TAB H — Historique (Montréal + tri récent + filtre + bulk delete)
# =====================================================
with tabH:
    st.subheader("🕘 Historique des changements d’alignement")

    # ✅ Guard (NE PAS st.stop() sinon ça stoppe toute l'app)
    if df is None or not isinstance(df, pd.DataFrame) or plafonds is None:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
    else:
        h = st.session_state.get("history")
        h = h.copy() if isinstance(h, pd.DataFrame) else pd.DataFrame()

        if h.empty:
            st.info("Aucune entrée d’historique pour cette saison.")
        else:
            # -------------------------------------------------
            # Colonnes attendues (soft) pour éviter KeyError
            # -------------------------------------------------
            for c in [
                "id", "timestamp", "season",
                "proprietaire", "joueur", "pos", "equipe",
                "from_statut", "from_slot", "to_statut", "to_slot", "action"
            ]:
                if c not in h.columns:
                    h[c] = ""

            # -------------------------------------------------
            # 🔧 Timezone Montréal + tri récent
            # -------------------------------------------------
            from zoneinfo import ZoneInfo
            tz_mtl = ZoneInfo("America/Toronto")  # Montréal = America/Toronto

            # timestamp_dt robuste (accepte ISO ou "YYYY-mm-dd HH:MM:SS")
            ts = pd.to_datetime(h["timestamp"], errors="coerce", utc=False)

            # Si ts est naive -> on localize en Montréal; si tz-aware -> on convertit
            try:
                if getattr(ts.dt, "tz", None) is None:
                    ts = ts.dt.tz_localize(tz_mtl, nonexistent="shift_forward", ambiguous="NaT")
                else:
                    ts = ts.dt.tz_convert(tz_mtl)
            except Exception:
                # fallback: laisse naive
                pass

            h["timestamp_dt"] = ts
            h = h.sort_values("timestamp_dt", ascending=False)

            # -------------------------------------------------
            # 🎛️ Filtre propriétaire (Tous + default = sidebar team)
            # -------------------------------------------------
            owners = sorted(h["proprietaire"].dropna().astype(str).map(lambda x: x.strip()).unique().tolist())
            owners = [o for o in owners if o]  # remove empty
            options = ["Tous"] + owners

            # default = team sidebar (si présent)
            default_owner = str(get_selected_team() or "").strip()
            if default_owner in owners:
                default_index = options.index(default_owner)
            else:
                default_index = 0

            owner_filter = st.selectbox(
                "Filtrer par propriétaire",
                options,
                index=default_index,
                key="hist_owner_filter",
            )

            if owner_filter != "Tous":
                h = h[h["proprietaire"].astype(str).str.strip().eq(str(owner_filter).strip())]

            if h.empty:
                st.info("Aucune entrée pour ce propriétaire.")
            else:
                st.caption("↩️ = annuler ce changement. ❌ = supprimer l’entrée (sans modifier l’alignement).")
                st.caption("🗑️ Suppression bulk : coche plusieurs lignes puis supprime en une fois.")

                # -------------------------------------------------
                # Limite (perf)
                # -------------------------------------------------
                max_rows = st.number_input(
                    "Nombre max de lignes à afficher",
                    min_value=50,
                    max_value=5000,
                    value=250,
                    step=50,
                    key="hist_max_rows",
                )

                h_view = h.head(int(max_rows)).reset_index(drop=True)

                # -------------------------------------------------
                # Helpers
                # -------------------------------------------------
                def _safe_int(x):
                    v = pd.to_numeric(x, errors="coerce")
                    if pd.isna(v):
                        return None
                    try:
                        return int(v)
                    except Exception:
                        return None

                # 🔑 UID unique garanti (évite DuplicateElementKey même si id doublons)
                def _uid(r: pd.Series, i: int) -> str:
                    rid = _safe_int(r.get("id", None))
                    ts0 = str(r.get("timestamp", "")).strip()
                    owner0 = str(r.get("proprietaire", "")).strip()
                    joueur0 = str(r.get("joueur", "")).strip()
                    action0 = str(r.get("action", "")).strip()
                    return f"{rid if rid is not None else 'noid'}|{ts0}|{owner0}|{joueur0}|{action0}|{i}"

                def _fmt_ts(r: pd.Series) -> str:
                    t = r.get("timestamp_dt", None)
                    if pd.isna(t) or t is None:
                        return str(r.get("timestamp", ""))
                    try:
                        # format lisible Montréal
                        return t.strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        return str(r.get("timestamp", ""))

                # -------------------------------------------------
                # ✅ Bulk selection state
                # -------------------------------------------------
                if "hist_bulk_selected" not in st.session_state:
                    st.session_state["hist_bulk_selected"] = set()

                # -------------------------------------------------
                # Header
                # -------------------------------------------------
                head = st.columns([0.7, 1.6, 1.4, 2.4, 1.0, 1.6, 1.6, 2.0, 0.8, 0.7])
                head[0].markdown("**✔**")
                head[1].markdown("**Date/Heure (MTL)**")
                head[2].markdown("**Propriétaire**")
                head[3].markdown("**Joueur**")
                head[4].markdown("**Pos**")
                head[5].markdown("**De**")
                head[6].markdown("**Vers**")
                head[7].markdown("**Action**")
                head[8].markdown("**↩️**")
                head[9].markdown("**❌**")

                # -------------------------------------------------
                # Rows
                # -------------------------------------------------
                for i, r in h_view.iterrows():
                    uid = _uid(r, i)
                    rid = _safe_int(r.get("id", None))

                    cols = st.columns([0.7, 1.6, 1.4, 2.4, 1.0, 1.6, 1.6, 2.0, 0.8, 0.7])

                    # ✅ checkbox bulk (store UID)
                    checked = cols[0].checkbox(
                        "",
                        value=(uid in st.session_state["hist_bulk_selected"]),
                        key=f"chk__{uid}",
                    )
                    if checked:
                        st.session_state["hist_bulk_selected"].add(uid)
                    else:
                        st.session_state["hist_bulk_selected"].discard(uid)

                    cols[1].markdown(_fmt_ts(r))
                    cols[2].markdown(str(r.get("proprietaire", "")))
                    cols[3].markdown(str(r.get("joueur", "")))
                    cols[4].markdown(str(r.get("pos", "")))

                    de = f"{r.get('from_statut', '')}" + (
                        f" ({r.get('from_slot', '')})" if str(r.get("from_slot", "")).strip() else ""
                    )
                    vers = f"{r.get('to_statut', '')}" + (
                        f" ({r.get('to_slot', '')})" if str(r.get("to_slot", "")).strip() else ""
                    )
                    cols[5].markdown(de)
                    cols[6].markdown(vers)
                    cols[7].markdown(str(r.get("action", "")))

                    # =====================================================
                    # UNDO (push local + Drive)
                    # =====================================================
                    if cols[8].button("↩️", key=f"undo__{uid}", use_container_width=True):
                        if st.session_state.get("LOCKED"):
                            st.error("🔒 Saison verrouillée : annulation impossible.")
                        else:
                            owner = str(r.get("proprietaire", "")).strip()
                            joueur = str(r.get("joueur", "")).strip()

                            data_df = st.session_state.get("data")
                            if data_df is None or not isinstance(data_df, pd.DataFrame) or data_df.empty:
                                st.error("Aucune donnée en mémoire.")
                            else:
                                mask = (
                                    data_df["Propriétaire"].astype(str).str.strip().eq(owner)
                                    & data_df["Joueur"].astype(str).str.strip().eq(joueur)
                                )

                                if data_df.loc[mask].empty:
                                    st.error("Impossible d'annuler : joueur introuvable.")
                                else:
                                    before = data_df.loc[mask].iloc[0]
                                    cur_statut = str(before.get("Statut", "")).strip()
                                    cur_slot = str(before.get("Slot", "")).strip()
                                    pos0 = str(before.get("Pos", "F")).strip()
                                    equipe0 = str(before.get("Equipe", "")).strip()

                                    from_statut = str(r.get("from_statut", "")).strip()
                                    from_slot = str(r.get("from_slot", "")).strip()

                                    # Applique retour arrière
                                    st.session_state["data"].loc[mask, "Statut"] = from_statut
                                    st.session_state["data"].loc[mask, "Slot"] = (from_slot if from_slot else "")

                                    # Si on sort de IR -> reset IR Date
                                    if cur_slot == "Blessé" and from_slot != "Blessé":
                                        st.session_state["data"].loc[mask, "IR Date"] = ""

                                    # Nettoyage + save local data
                                    st.session_state["data"] = clean_data(st.session_state["data"])
                                    data_file = st.session_state.get("DATA_FILE", "")
                                    if data_file:
                                        st.session_state["data"].to_csv(data_file, index=False)

                                    # Log historique (local)
                                    log_history_row(
                                        owner, joueur, pos0, equipe0,
                                        cur_statut, cur_slot,
                                        from_statut,
                                        (from_slot if from_slot else ""),
                                        action=f"UNDO #{rid if rid is not None else 'NA'}",
                                    )

                                    # ✅ PUSH DRIVE (data + history) après UNDO
                                    try:
                                        if "_drive_enabled" in globals() and _drive_enabled():
                                            season_lbl = st.session_state.get("season", season)

                                            gdrive_save_df(
                                                st.session_state["data"],
                                                f"fantrax_{season_lbl}.csv",
                                                GDRIVE_FOLDER_ID,
                                            )

                                            h_now = st.session_state.get("history")
                                            if isinstance(h_now, pd.DataFrame):
                                                gdrive_save_df(
                                                    h_now,
                                                    f"history_{season_lbl}.csv",
                                                    GDRIVE_FOLDER_ID,
                                                )
                                    except Exception:
                                        st.warning("⚠️ Sauvegarde Drive impossible (UNDO) — local OK.")

                                    st.toast("↩️ Changement annulé", icon="↩️")
                                    do_rerun()

                    # =====================================================
                    # DELETE (push local + Drive)
                    # =====================================================
                    if cols[9].button("❌", key=f"del__{uid}", use_container_width=True):
                        h2 = st.session_state.get("history")
                        h2 = h2.copy() if isinstance(h2, pd.DataFrame) else pd.DataFrame()

                        if not h2.empty:
                            if rid is not None and "id" in h2.columns:
                                h2["__idnum"] = pd.to_numeric(h2["id"], errors="coerce")
                                h2 = h2[h2["__idnum"] != rid].drop(columns=["__idnum"], errors="ignore")
                            else:
                                # fallback signature (si pas de id fiable)
                                sig_cols = [
                                    "timestamp", "season", "proprietaire", "joueur",
                                    "from_statut", "from_slot", "to_statut", "to_slot", "action"
                                ]
                                sig_cols = [c for c in sig_cols if c in h2.columns]
                                if sig_cols:
                                    m = pd.Series([True] * len(h2))
                                    for c in sig_cols:
                                        m &= (h2[c].astype(str) == str(r.get(c, "")))
                                    h2 = h2[~m].copy()

                        st.session_state["history"] = h2.reset_index(drop=True)

                        # Save local
                        save_history(st.session_state.get("HISTORY_FILE", HISTORY_FILE), st.session_state["history"])

                        # ✅ PUSH DRIVE (history) après DELETE
                        try:
                            if "_drive_enabled" in globals() and _drive_enabled():
                                season_lbl = st.session_state.get("season", season)
                                gdrive_save_df(
                                    st.session_state["history"],
                                    f"history_{season_lbl}.csv",
                                    GDRIVE_FOLDER_ID,
                                )
                        except Exception:
                            st.warning("⚠️ Sauvegarde Drive impossible (DELETE) — local OK.")

                        st.toast("🗑️ Entrée supprimée", icon="🗑️")
                        do_rerun()

                # -------------------------------------------------
                # 🗑️ BULK DELETE BAR
                # -------------------------------------------------
                sel = list(st.session_state.get("hist_bulk_selected", set()))
                if sel:
                    st.divider()
                    c1, c2, c3 = st.columns([2, 1, 2])
                    c1.info(f"{len(sel)} ligne(s) sélectionnée(s).")

                    if c2.button("🗑️ Supprimer sélection", use_container_width=True, key="bulk_del_btn"):
                        h2 = st.session_state.get("history")
                        h2 = h2.copy() if isinstance(h2, pd.DataFrame) else pd.DataFrame()

                        if not h2.empty:
                            # Recompute a UID for each row in the FULL history (important)
                            # We'll rebuild UID using same logic but with row index enumeration.
                            # (stable enough + avoids needing to store ids list only)
                            tmp = h2.copy()
                            for c in ["id","timestamp","proprietaire","joueur","action"]:
                                if c not in tmp.columns:
                                    tmp[c] = ""
                            tmp["__uid"] = [
                                f"{_safe_int(rr.get('id', None)) if _safe_int(rr.get('id', None)) is not None else 'noid'}"
                                f"|{str(rr.get('timestamp','')).strip()}"
                                f"|{str(rr.get('proprietaire','')).strip()}"
                                f"|{str(rr.get('joueur','')).strip()}"
                                f"|{str(rr.get('action','')).strip()}"
                                f"|{ii}"
                                for ii, rr in tmp.reset_index(drop=True).iterrows()
                            ]

                            h2 = tmp[~tmp["__uid"].isin(set(sel))].drop(columns=["__uid"], errors="ignore")

                        st.session_state["history"] = h2.reset_index(drop=True)
                        st.session_state["hist_bulk_selected"] = set()

                        # Save local
                        save_history(st.session_state.get("HISTORY_FILE", HISTORY_FILE), st.session_state["history"])

                        # Push Drive
                        try:
                            if "_drive_enabled" in globals() and _drive_enabled():
                                season_lbl = st.session_state.get("season", season)
                                gdrive_save_df(
                                    st.session_state["history"],
                                    f"history_{season_lbl}.csv",
                                    GDRIVE_FOLDER_ID,
                                )
                        except Exception:
                            st.warning("⚠️ Sauvegarde Drive impossible (BULK DELETE) — local OK.")

                        st.toast("🗑️ Suppression en lot effectuée", icon="🗑️")
                        do_rerun()

                    if c3.button("✖️ Désélectionner tout", use_container_width=True, key="bulk_clear_btn"):
                        st.session_state["hist_bulk_selected"] = set()
                        do_rerun()





# =====================================================
# TAB 2 — Transactions (plafonds safe)
# =====================================================
with tab2:
    st.subheader("⚖️ Transactions")
    st.caption("Vérifie si une transaction respecte le plafond GC / CE.")

    # ✅ Guard DANS le tab (ne stop pas toute l'app)
    if df is None or df.empty or plafonds is None or plafonds.empty:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
        st.stop()

    # Liste propriétaires safe
    owners = sorted(plafonds["Propriétaire"].dropna().astype(str).unique().tolist())
    if not owners:
        st.info("Aucun propriétaire trouvé. Va dans 🛠️ Gestion Admin → Import.")
        st.stop()

    p = st.selectbox("Propriétaire", owners, key="tx_owner")

    salaire = st.number_input(
        "Salaire du joueur",
        min_value=0,
        step=100_000,
        value=0,
        key="tx_salary",
    )

    statut = st.radio(
        "Statut",
        ["Grand Club", "Club École"],
        key="tx_statut",
        horizontal=True,
    )

    # Sélection de la ligne propriétaire (safe)
    ligne_df = plafonds[plafonds["Propriétaire"].astype(str) == str(p)]
    if ligne_df.empty:
        st.error("Propriétaire introuvable dans les plafonds.")
        st.stop()

    ligne = ligne_df.iloc[0]
    reste = int(ligne["Montant Disponible GC"]) if statut == "Grand Club" else int(ligne["Montant Disponible CE"])

    st.metric("Montant disponible", money(reste))

    if int(salaire) > int(reste):
        st.error("🚨 Dépassement du plafond")
    else:
        st.success("✅ Transaction valide")


# =====================================================
# TAB 3 — Recommandations (plafonds safe)
# =====================================================
with tab3:
    st.subheader("🧠 Recommandations")
    st.caption("Recommandations automatiques basées sur les montants disponibles.")

    # ✅ Guard DANS le tab (ne stop pas toute l'app)
    if df is None or df.empty or plafonds is None or plafonds.empty:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
        st.stop()

    # Recos
    for _, r in plafonds.iterrows():
        dispo_gc = int(r.get("Montant Disponible GC", 0) or 0)
        dispo_ce = int(r.get("Montant Disponible CE", 0) or 0)
        owner = str(r.get("Propriétaire", "")).strip()

        if dispo_gc < 2_000_000:
            st.warning(f"{owner} : rétrogradation recommandée")
        if dispo_ce > 10_000_000:
            st.info(f"{owner} : rappel possible")

# Flush Drive automatique (batch)
if "flush_drive_queue" in globals():
    n, errs = flush_drive_queue(force=False, max_age_sec=8)
    # (DEBUG temporaire)
    # if n: st.toast(f"Drive flush: {n} fichier(s)", icon="☁️")


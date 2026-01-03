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
st.set_page_config("Fantrax Pool Hockey", layout="wide")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

PLAYERS_DB_FILE = "data/Hockey.Players.csv"   # ✅ confirmé
LOGO_POOL_FILE = os.path.join(DATA_DIR, "Logo_Pool.png")


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


def pos_sort_key(pos: str) -> int:
    return {"F": 0, "D": 1, "G": 2}.get(str(pos).upper(), 99)


def saison_auto():
    now = datetime.now()
    return f"{now.year}-{now.year+1}" if now.month >= 9 else f"{now.year-1}-{now.year}"


def saison_verrouillee(season: str) -> bool:
    return int(str(season)[:4]) < int(saison_auto()[:4])


def _count_badge(n: int, limit: int) -> str:
    if n > limit:
        color = "#ef4444"  # rouge
        icon = " ⚠️"
    else:
        color = "#22c55e"  # vert
        icon = ""
    return f"<span style='color:{color};font-weight:1000'>{n}</span>/{limit}{icon}"


def render_badge(text: str, bg: str, fg: str = "white") -> str:
    t = html.escape(str(text or ""))
    return (
        "<span style='display:inline-block;padding:2px 8px;border-radius:999px;"
        f"background:{bg};color:{fg};font-weight:900;font-size:12px;line-height:18px'>"
        f"{t}</span>"
    )


def pos_badge_html(pos: str) -> str:
    p = normalize_pos(pos)
    if p == "F":
        return render_badge("F", "#16a34a")        # vert
    if p == "D":
        return render_badge("D", "#2563eb")        # bleu
    return render_badge("G", "#7c3aed")            # violet


def cap_bar_html(used: int, cap: int, label: str) -> str:
    cap = int(cap or 0)
    used = int(used or 0)
    remain = cap - used

    pct_used = (used / cap) if cap else 0.0
    pct_used = max(0.0, min(pct_used, 1.0))

    color = "#16a34a" if remain >= 0 else "#dc2626"

    return f"""
    <div style="margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;font-size:12px;font-weight:900">
        <span>{html.escape(label)}</span>
        <span style="color:{color}">{money(remain)}</span>
      </div>
      <div style="background:#e5e7eb;height:10px;border-radius:6px;overflow:hidden">
        <div style="width:{int(pct_used*100)}%;background:{color};height:100%"></div>
      </div>
      <div style="font-size:11px;opacity:.75">
        Utilisé : {money(used)} / {money(cap)}
      </div>
    </div>
    """

# =====================================================
# GOOGLE DRIVE — OAUTH FINAL (clean + refresh silencieux)
# =====================================================

# ✅ Recommandé: scope minimal
OAUTH_SCOPES = ["https://www.googleapis.com/auth/drive.file"]

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

@st.cache_resource(show_spinner=False)
def _drive_client_cached() :
    """
    Client Drive caché: accélère et évite rebuild à chaque rerun.
    Le refresh du token se fera via _get_oauth_creds() au moment du build.
    """
    creds = _get_oauth_creds()
    return build("drive", "v3", credentials=creds)

def gdrive_service():
    return _drive_client_cached()

def _drive_enabled() -> bool:
    return oauth_drive_ready()

# -----------------------------
# Helpers Drive (liste / save / load)
# -----------------------------
def gdrive_get_file_id(service, filename: str, folder_id: str):
    safe_name = str(filename).replace("'", "")
    q = f"name='{safe_name}' and '{folder_id}' in parents and trashed=false"
    res = service.files().list(q=q, fields="files(id,name)").execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None

def gdrive_list_files(folder_id: str, limit: int = 20) -> list[str]:
    s = gdrive_service()
    res = s.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        pageSize=int(limit),
        fields="files(name)",
    ).execute()
    return [f["name"] for f in res.get("files", [])]

def gdrive_save_df(df: pd.DataFrame, filename: str, folder_id: str) -> bool:
    if not folder_id:
        return False
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

def gdrive_load_df(filename: str, folder_id: str) -> pd.DataFrame | None:
    if not folder_id:
        return None
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
def _norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip()).lower()


@st.cache_data(show_spinner=False)
def load_players_db(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
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
# =====================================================

def _safe_empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=REQUIRED_COLS)


def _drive_enabled() -> bool:
    return oauth_drive_ready()


# -----------------------------
# DATA — load on season change
# -----------------------------
if "season" not in st.session_state or st.session_state["season"] != season:
    df_loaded: pd.DataFrame | None = None
    drive_ok = False

    # 1) Google Drive (priorité)
    if _drive_enabled():
        try:
            df_loaded = gdrive_load_df(f"fantrax_{season}.csv", GDRIVE_FOLDER_ID)
            drive_ok = True
        except Exception as e:
            df_loaded = None
            drive_ok = False
            st.sidebar.warning(
                f"⚠️ Drive indisponible (fallback local data). ({type(e).__name__}: {e})"
            )

    # 2) Fallback local (DATA_FILE)
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

    # Clean + store session
    df_loaded = clean_data(df_loaded)
    st.session_state["data"] = df_loaded

    # Save local (cache)
    try:
        st.session_state["data"].to_csv(DATA_FILE, index=False)
    except Exception:
        pass

    # Save Drive (assure l'existence / à jour) — seulement si Drive accessible
    if _drive_enabled() and drive_ok:
        try:
            gdrive_save_df(st.session_state["data"], f"fantrax_{season}.csv", GDRIVE_FOLDER_ID)
        except Exception as e:
            st.sidebar.warning(f"⚠️ Sauvegarde Drive impossible (data). ({type(e).__name__}: {e})")

    st.session_state["season"] = season



# -----------------------------
# HISTORY — load on season change (Drive + fallback local)
# -----------------------------
if "history_season" not in st.session_state or st.session_state["history_season"] != season:
    h_loaded: pd.DataFrame | None = None
    drive_ok = False

    # 1) Drive (priorité)
    if _drive_enabled():
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
        h_loaded = load_history(HISTORY_FILE)

    # Normalise (au cas où)
    if h_loaded is None or not isinstance(h_loaded, pd.DataFrame):
        h_loaded = pd.DataFrame(
            columns=[
                "id", "timestamp", "season",
                "proprietaire", "joueur", "pos", "equipe",
                "from_statut", "from_slot", "to_statut", "to_slot",
                "action",
            ]
        )

    st.session_state["history"] = h_loaded

    # Save local cache
    try:
        st.session_state["history"].to_csv(HISTORY_FILE, index=False)
    except Exception:
        pass

    # Save Drive (assure l'existence / à jour) — seulement si Drive accessible
    if _drive_enabled() and drive_ok:
        try:
            gdrive_save_df(st.session_state["history"], f"history_{season}.csv", GDRIVE_FOLDER_ID)
        except Exception as e:
            st.sidebar.warning(
                f"⚠️ Sauvegarde Drive impossible (history). ({type(e).__name__}: {e})"
            )

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
if os.path.exists(LOGO_POOL_FILE):
    st.image(LOGO_POOL_FILE, use_container_width=True)

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
# PLAFONDS (safe si df vide)
# =====================================================
if df.empty:
    plafonds = pd.DataFrame(
        columns=[
            "Propriétaire", "Logo",
            "Total Grand Club", "Montant Disponible GC",
            "Total Club École", "Montant Disponible CE",
        ]
    )
else:
    resume = []
    for p in df["Propriétaire"].dropna().astype(str).unique():
        d = df[df["Propriétaire"].astype(str) == str(p)]

        total_gc = d[(d["Statut"] == "Grand Club") & (d["Slot"] != "Blessé")]["Salaire"].sum()
        total_ce = d[(d["Statut"] == "Club École") & (d["Slot"] != "Blessé")]["Salaire"].sum()

        resume.append(
            {
                "Propriétaire": str(p),
                "Logo": find_logo_for_owner(p),
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
        ["📊 Tableau", "🧾 Alignement", "👤 Joueurs", "🕘 Historique", "⚖️ Transactions", "🛠️ Gestion Admin", "🧠 Recommandations"]
    )
else:
    tab1, tabA, tabJ, tabH, tab2, tab3 = st.tabs(
        ["📊 Tableau", "🧾 Alignement", "👤 Joueurs", "🕘 Historique", "⚖️ Transactions", "🧠 Recommandations"]
    )
    tabAdmin = None

# =====================================================
# TAB Admin (Whalers only)
# =====================================================
if tabAdmin is not None:
    with tabAdmin:
        st.subheader("🛠️ Gestion Admin")

        # --- OAuth connect UI
        st.markdown("### 🔐 Connexion Google Drive (OAuth)")
        if not oauth_drive_enabled():
            st.warning(
                "OAuth Drive non configuré. Ajoute [gdrive_oauth].client_id / "
                "client_secret / redirect_uri dans Secrets."
            )
        else:
            oauth_connect_ui()

        st.divider()

        folder_id = _folder_id()
        drive_ready = _drive_enabled()

        # --- Statut + batch tools
        if not folder_id:
            st.warning("⚠️ folder_id manquant dans [gdrive_oauth] (Secrets).")
            st.caption("Astuce: tu peux créer/trouver 'PoolHockeyData' et copier le folder_id dans Secrets.")
        elif not drive_ready:
            st.info("OAuth pas encore prêt (refresh_token manquant).")
        else:
            st.success("✅ OAuth prêt — Drive activé.")
            st.caption(f"📁 Folder ID: {folder_id}")

            st.markdown("### 🚀 Drive batch")
            q = st.session_state.get("drive_queue", {})
            st.caption(f"En attente : **{len(q)}** fichier(s)")

            c1, c2 = st.columns(2)
            with c1:
                if st.button("🚀 Flush Drive", key="admin_flush_drive", use_container_width=True):
                    if "flush_drive_queue" in globals():
                        n, errs = flush_drive_queue(force=True)
                        if errs:
                            st.error("\n".join(errs))
                        else:
                            st.success(f"{n} fichier(s) écrits")
                    else:
                        st.error("flush_drive_queue() introuvable (bloc batch non chargé).")

            with c2:
                if st.button("♻️ Reset cache Drive", key="admin_reset_drive_cache", use_container_width=True):
                    try:
                        st.cache_resource.clear()
                    except Exception:
                        pass

                    st.session_state["drive_queue"] = {}
                    st.session_state["drive_dirty_at"] = 0.0
                    st.session_state["drive_last_flush"] = 0.0
                    st.success("Cache reset")

            st.divider()

            # --- Tests Drive
            st.markdown("### 🧪 Tests Drive")

            t1, t2 = st.columns(2)
            with t1:
                if st.button("Test lecture", key="admin_test_read", use_container_width=True):
                    try:
                        names = gdrive_list_files(folder_id, limit=10)
                        st.success(f"{len(names)} fichier(s)")
                        if names:
                            st.write(names)
                    except Exception as e:
                        st.error(f"❌ Lecture KO — {type(e).__name__}: {e}")

            with t2:
                if st.button("Test écriture", key="admin_test_write", use_container_width=True):
                    try:
                        df_test = pd.DataFrame([{"ok": 1, "ts": datetime.now().isoformat()}])
                        gdrive_save_df(df_test, "drive_test.csv", folder_id)
                        st.success("✅ Écriture OK")
                    except Exception as e:
                        st.error(f"❌ Écriture KO — {type(e).__name__}: {e}")

        st.divider()


                # =====================================================
                # 🚀 DRIVE BATCH (Flush + statut)
                # =====================================================
                if drive_ready:
                    st.markdown("### 🚀 Drive batch (réduction des écritures)")

                    q = st.session_state.get("drive_queue", {})
                    st.caption(f"En attente d'écriture Drive : **{len(q)}** fichier(s).")

                    cF1, cF2 = st.columns(2)

                    with cF1:
                        if st.button("🚀 Flush Drive maintenant", use_container_width=True, key="admin_flush_drive_now"):
                            if "flush_drive_queue" in globals():
                                n, errs = flush_drive_queue(force=True)
                                if errs:
                                    st.error("❌ Erreurs:\n" + "\n".join(errs))
                                else:
                                    st.success(f"✅ Flush OK — {n} fichier(s) écrit(s) sur Drive.")
                            else:
                                st.error("flush_drive_queue() introuvable (bloc batch non chargé).")

                    with cF2:
                        if st.button("♻️ Reset Drive cache", use_container_width=True, key="admin_reset_drive"):
                            try:
                                st.cache_resource.clear()
                            except Exception:
                                pass

                            st.session_state["drive_queue"] = {}
                            st.session_state["drive_dirty_at"] = 0.0
                            st.session_state["drive_last_flush"] = 0.0

                            st.success("✅ Cache Drive + queue reset.")


                with cF2:
                    if st.button("♻️ Reset Drive cache", use_container_width=True):
                        # reset caches + queue batch
                        try:
                            st.cache_resource.clear()
                        except Exception:
                            pass

                        st.session_state["drive_queue"] = {}
                        st.session_state["drive_dirty_at"] = 0.0
                        st.session_state["drive_last_flush"] = 0.0

                        st.success("✅ Cache Drive + queue batch reset. Le client Drive sera reconstruit.")

                st.divider()

                # =====================================================
                # 🧪 TESTS DRIVE (Whalers only + silencieux)
                # =====================================================
                st.markdown("### 🧪 Tests Drive (Whalers only)")

                colT1, colT2 = st.columns(2)

                with colT1:
                    if st.button("🧪 Test LECTURE (liste 10 fichiers)", use_container_width=True):
                        try:
                            names = gdrive_list_files(folder_id, limit=10)
                            st.success(f"✅ Lecture OK — {len(names)} fichier(s).")
                            if names:
                                st.write(names)
                        except Exception as e:
                            st.error(f"❌ Lecture KO — {type(e).__name__}: {e}")

                with colT2:
                    if st.button("🧪 Test ÉCRITURE (écraser fichier test)", use_container_width=True):
                        try:
                            df_test = pd.DataFrame([{"ok": 1, "ts": datetime.now().isoformat()}])
                            gdrive_save_df(df_test, "drive_write_test.csv", folder_id)
                            st.success("✅ Écriture OK — drive_write_test.csv créé/mis à jour.")
                        except Exception as e:
                            st.error(f"❌ Écriture KO — {type(e).__name__}: {e}")

            else:
                st.info(
                    "ℹ️ OAuth pas encore prêt : clique sur **Connecter Google Drive** "
                    "pour obtenir le refresh_token, puis colle-le dans Secrets."
                )
                st.caption(f"📁 Folder ID: {folder_id}")

            st.divider()




            # =====================================================
            # 🧪 TEST GOOGLE DRIVE (OAuth)
            # =====================================================
            st.markdown("### 🧪 Test Google Drive (OAuth)")

            cfg = _oauth_cfg()
            folder_id = str(cfg.get("folder_id", "")).strip()

            if not folder_id:
                st.warning("folder_id manquant dans [gdrive_oauth] (Secrets).")
            elif not oauth_drive_ready():
                st.info("OAuth pas encore prêt: connecte-toi ci-dessus pour obtenir un refresh_token, puis colle-le dans Secrets.")
            else:
                if st.button("🧪 Tester Google Drive (liste)", use_container_width=True):
                    try:
                        s = gdrive_service()
                        res = s.files().list(
                            q=f"'{folder_id}' in parents and trashed=false",
                            pageSize=10,
                            fields="files(id,name)"
                        ).execute()
                        files = res.get("files", [])
                        st.success(f"✅ Drive OK — {len(files)} fichier(s) visibles dans le dossier.")
                        if files:
                            st.write([f["name"] for f in files])
                    except Exception as e:
                        st.error(f"❌ Drive KO — {type(e).__name__}: {e}")

                if st.button("✍️ Tester ÉCRITURE Drive (créer un fichier)", use_container_width=True):
                    try:
                        df_test = pd.DataFrame([{"ok": 1, "ts": datetime.now().isoformat()}])
                        gdrive_save_df(df_test, "drive_write_test.csv", folder_id)
                        st.success("✅ Écriture OK — 'drive_write_test.csv' créé/mis à jour.")

                        s = gdrive_service()
                        res = s.files().list(
                            q=f"'{folder_id}' in parents and trashed=false",
                            pageSize=10,
                            fields="files(id,name)"
                        ).execute()
                        files = res.get("files", [])
                        st.info(f"📁 Fichiers visibles maintenant : {len(files)}")
                        if files:
                            st.write([f["name"] for f in files])
                    except Exception as e:
                        st.error(f"❌ Écriture KO — {type(e).__name__}: {e}")

            st.divider()

            # =====================================================
            # 🧪 TESTS UNITAIRES DRIVE (silencieux)
            # =====================================================
            st.markdown("### 🧪 Tests Drive (silencieux)")

            # 1) Auto-création / découverte du dossier si folder_id manquant
            if oauth_drive_enabled() and not _folder_id():
                st.info("Aucun folder_id dans Secrets. Tu peux créer/trouver automatiquement le dossier.")
                if st.button("📁 Créer / Trouver 'PoolHockeyData' et afficher folder_id", use_container_width=True):
                    try:
                        fid = ensure_drive_folder_id("PoolHockeyData")
                        if fid:
                            st.success("✅ Dossier Drive OK.")
                            st.warning("Copie ce folder_id dans Streamlit Secrets → [gdrive_oauth].folder_id")
                            st.code(fid)
                            st.caption("Ensuite: Save Secrets puis recharge l’app.")
                        else:
                            st.error("❌ Impossible (OAuth pas prêt ou config manquante).")
                    except Exception as e:
                        st.error(f"❌ Folder error: {type(e).__name__}: {e}")

            # 2) Tests lecture / écriture (silencieux)
            folder_id = _folder_id()
            if not folder_id:
                st.caption("ℹ️ Ajoute un folder_id dans Secrets pour activer les tests lecture/écriture.")
            elif not _drive_enabled():
                st.caption("ℹ️ OAuth pas prêt (refresh_token manquant).")
            else:
                colT1, colT2 = st.columns(2)

                with colT1:
                    if st.button("🧪 Test LECTURE (liste 10 fichiers)", use_container_width=True):
                        try:
                            names = gdrive_list_files(folder_id, limit=10)
                            st.success(f"✅ Lecture OK — {len(names)} fichier(s).")
                            if names:
                                st.write(names)
                        except Exception as e:
                            st.error(f"❌ Lecture KO — {type(e).__name__}: {e}")

                with colT2:
                    if st.button("🧪 Test ÉCRITURE (écraser fichier test)", use_container_width=True):
                        try:
                            df_test = pd.DataFrame([{"ok": 1, "ts": datetime.now().isoformat()}])
                            gdrive_save_df(df_test, "drive_write_test.csv", folder_id)
                            st.success("✅ Écriture OK — drive_write_test.csv créé/mis à jour.")
                        except Exception as e:
                            st.error(f"❌ Écriture KO — {type(e).__name__}: {e}")

            st.divider()


            # =====================================================
            # 📥 IMPORT FANTRAX
            # =====================================================
            st.markdown("### 📥 Import")

            uploaded = st.file_uploader(
                "Fichier CSV Fantrax",
                type=["csv", "txt"],
                help="Le fichier peut contenir Skaters et Goalies séparés par une ligne vide.",
                key=f"fantrax_uploader_{st.session_state.get('uploader_nonce', 0)}_admin",
            )

            if uploaded is not None:
                if st.session_state.get("LOCKED"):
                    st.warning("🔒 Saison verrouillée : import désactivé.")
                else:
                    try:
                        df_import = parse_fantrax(uploaded)

                        if df_import is None or df_import.empty:
                            st.error("❌ Import invalide : aucune donnée exploitable.")
                        else:
                            owner = os.path.splitext(uploaded.name)[0]
                            df_import["Propriétaire"] = owner

                            cur_data = st.session_state.get("data")
                            if cur_data is None:
                                cur_data = pd.DataFrame(columns=REQUIRED_COLS)

                            st.session_state["data"] = pd.concat([cur_data, df_import], ignore_index=True)
                            st.session_state["data"] = clean_data(st.session_state["data"])

                            # ✅ Save local (fallback/cache)
                            try:
                                st.session_state["data"].to_csv(
                                    st.session_state["DATA_FILE"], index=False
                                )
                            except Exception:
                                pass

                            # ✅ Save Drive (persist reboot) si configuré
                            try:
                                if _drive_enabled():
                                    gdrive_save_df(
                                        st.session_state["data"],
                                        f"fantrax_{season}.csv",
                                        GDRIVE_FOLDER_ID,
                                    )
                            except Exception as e:
                                st.warning(
                                    f"⚠️ Sauvegarde Drive impossible (local ok). "
                                    f"({type(e).__name__}: {e})"
                                )

                            st.success("✅ Import réussi")
                            st.session_state["uploader_nonce"] = (
                                st.session_state.get("uploader_nonce", 0) + 1
                            )
                            do_rerun()

                    except Exception as e:
                        st.error(f"❌ Import échoué : {e}")

            st.divider()



            # -----------------------------
            # 📤 Export CSV
            # -----------------------------
            st.markdown("### 📤 Export CSV")

            data_file = st.session_state.get("DATA_FILE", "")
            hist_file = st.session_state.get("HISTORY_FILE", "")
            season_lbl = st.session_state.get("season", season)

            c1, c2 = st.columns(2)

            # ---- Export Alignement
            with c1:
                exported = False

                # 1) Drive prioritaire si dispo
                try:
                    if "_drive_enabled" in globals() and _drive_enabled():
                        df_drive = gdrive_load_df(f"fantrax_{season_lbl}.csv", GDRIVE_FOLDER_ID)
                        if df_drive is not None:
                            st.download_button(
                                "⬇️ Export Alignement (CSV)",
                                data=df_drive.to_csv(index=False).encode("utf-8"),
                                file_name=f"fantrax_{season_lbl}.csv",
                                mime="text/csv",
                                use_container_width=True,
                                key=f"dl_align_{season_lbl}_admin_drive",
                            )
                            exported = True
                except Exception:
                    exported = False

                # 2) Fallback local
                if not exported:
                    if data_file and os.path.exists(data_file):
                        with open(data_file, "rb") as f:
                            st.download_button(
                                "⬇️ Export Alignement (CSV)",
                                data=f.read(),
                                file_name=os.path.basename(data_file),
                                mime="text/csv",
                                use_container_width=True,
                                key=f"dl_align_{season_lbl}_admin_local",
                            )
                    else:
                        st.info("Aucun fichier d'alignement à exporter (importe d’abord).")

            # ---- Export Historique
            with c2:
                exported = False

                # 1) Drive prioritaire si dispo
                try:
                    if "_drive_enabled" in globals() and _drive_enabled():
                        h_drive = gdrive_load_df(f"history_{season_lbl}.csv", GDRIVE_FOLDER_ID)
                        if h_drive is not None:
                            st.download_button(
                                "⬇️ Export Historique (CSV)",
                                data=h_drive.to_csv(index=False).encode("utf-8"),
                                file_name=f"history_{season_lbl}.csv",
                                mime="text/csv",
                                use_container_width=True,
                                key=f"dl_hist_{season_lbl}_admin_drive",
                            )
                            exported = True
                except Exception:
                    exported = False

                # 2) Fallback local
                if not exported:
                    if hist_file and os.path.exists(hist_file):
                        with open(hist_file, "rb") as f:
                            st.download_button(
                                "⬇️ Export Historique (CSV)",
                                data=f.read(),
                                file_name=os.path.basename(hist_file),
                                mime="text/csv",
                                use_container_width=True,
                                key=f"dl_hist_{season_lbl}_admin_local",
                            )
                    else:
                        st.info("Aucun fichier d'historique à exporter.")




# =====================================================
# TAB 1 — Tableau
# =====================================================
with tab1:
    st.subheader("📊 Tableau")

    if df is None or df.empty:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
        st.stop()

    # ... ton code Tableau ici ...



# (les autres tabs: tabA/tabJ/tabH/tab2/tab3 suivent ensuite, chacun avec son guard interne)




# =====================================================
# TAB A — Alignement
# =====================================================
with tabA:
    st.subheader("🧾 Alignement")

    # ✅ Data safe (source unique) DANS le tab
    df = st.session_state.get("data")
    if df is None:
        df = pd.DataFrame(columns=REQUIRED_COLS)

    df = clean_data(df)
    st.session_state["data"] = df

    # ✅ Guard : NE PAS st.stop() (sinon ça stoppe toute l'app)
    if df.empty:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
    else:
        all_owners = sorted(df["Propriétaire"].dropna().astype(str).unique().tolist())
        selected_team = get_selected_team()

        # Sync sélection d’équipe -> align_owner si possible
        if selected_team and selected_team in all_owners:
            st.session_state["align_owner"] = selected_team

        proprietaire = st.selectbox(
            "Propriétaire",
            all_owners,
            key="align_owner",
        )

        dprop = df[df["Propriétaire"] == proprietaire].copy()

        injured_all = dprop[dprop.get("Slot", "") == "Blessé"].copy()
        dprop_ok = dprop[dprop.get("Slot", "") != "Blessé"].copy()

        gc_all = dprop_ok[dprop_ok["Statut"] == "Grand Club"].copy()
        ce_all = dprop_ok[dprop_ok["Statut"] == "Club École"].copy()

        gc_actif = gc_all[gc_all.get("Slot", "") == "Actif"].copy()
        gc_banc = gc_all[gc_all.get("Slot", "") == "Banc"].copy()

        tmp = gc_actif.copy()
        if "Pos" not in tmp.columns:
            tmp["Pos"] = "F"
        tmp["Pos"] = tmp["Pos"].apply(normalize_pos)
        nb_F = int((tmp["Pos"] == "F").sum())
        nb_D = int((tmp["Pos"] == "D").sum())
        nb_G = int((tmp["Pos"] == "G").sum())

        cap_gc = int(st.session_state["PLAFOND_GC"])
        cap_ce = int(st.session_state["PLAFOND_CE"])
        used_gc = int(gc_all["Salaire"].sum()) if "Salaire" in gc_all.columns else 0
        used_ce = int(ce_all["Salaire"].sum()) if "Salaire" in ce_all.columns else 0
        remain_gc = cap_gc - used_gc
        remain_ce = cap_ce - used_ce

        j1, j2 = st.columns(2)
        with j1:
            st.markdown(cap_bar_html(used_gc, cap_gc, "📊 Plafond Grand Club (GC)"), unsafe_allow_html=True)
        with j2:
            st.markdown(cap_bar_html(used_ce, cap_ce, "📊 Plafond Club École (CE)"), unsafe_allow_html=True)

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
            f"**Actifs** — F {_count_badge(nb_F,12)} • D {_count_badge(nb_D,6)} • G {_count_badge(nb_G,2)}",
            unsafe_allow_html=True
        )

        st.divider()

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
    st.caption("Aucun résultat tant qu’aucun filtre n’est rempli (Nom/Prénom, Équipe, Level/Contrat ou Cap Hit).")

    # ✅ Guard DANS le tab (ne stop pas toute l'app)
    if df is None or df.empty:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
        st.stop()

    if players_db is None or players_db.empty:
        st.error("Impossible de charger la base joueurs.")
        st.caption(f"Chemin attendu : {PLAYERS_DB_FILE}")
        st.stop()

    df_db = players_db.copy()


    if "Player" not in df_db.columns:
        possible = None
        for cand in ["Joueur", "Name", "Full Name", "fullname", "player"]:
            if cand in df_db.columns:
                possible = cand
                break
        if possible:
            df_db = df_db.rename(columns={possible: "Player"})
        else:
            st.error(f"Colonne 'Player' introuvable. Colonnes: {list(df_db.columns)}")
            st.stop()

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
        s2 = re.sub(r"[^\d]", "", s)
        return int(s2) if s2.isdigit() else 0

    def _money_space(v: int) -> str:
        try:
            return f"{int(v):,}".replace(",", " ") + " $"
        except Exception:
            return "0 $"

    def clear_j_name():
        st.session_state["j_name"] = ""

    c1, c2, c3 = st.columns([2, 1, 1])

    with c1:
        name_col1, name_col2 = st.columns([12, 1])
        with name_col1:
            q_name = st.text_input("Nom / Prénom", placeholder="Ex: Jack Eichel", key="j_name")
        with name_col2:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            st.button("❌", key="j_name_clear", help="Effacer Nom / Prénom", use_container_width=True, on_click=clear_j_name)

    with c2:
        if "Team" in df_db.columns:
            teams = sorted(df_db["Team"].dropna().astype(str).unique())
            q_team = st.selectbox("Équipe", ["Toutes"] + teams, key="j_team")
        else:
            q_team = "Toutes"
            st.selectbox("Équipe", ["Toutes"], disabled=True, key="j_team_disabled")

    with c3:
        level_col = "Level" if "Level" in df_db.columns else None
        if level_col:
            levels = sorted(df_db[level_col].dropna().astype(str).unique())
            q_level = st.selectbox("Level (Contrat)", ["Tous"] + levels, key="j_level")
        else:
            q_level = "Tous"
            st.selectbox("Level (Contrat)", ["Tous"], disabled=True, key="j_level_disabled")

    st.divider()
    st.markdown("### 💰 Recherche par Salaire (Cap Hit)")

    cap_col = None
    for cand in ["Cap Hit", "CapHit", "AAV"]:
        if cand in df_db.columns:
            cap_col = cand
            break

    if not cap_col:
        st.warning("Aucune colonne Cap Hit/CapHit/AAV trouvée → filtre salaire désactivé.")
        cap_enabled = False
        cap_apply = False
        cap_min = 0
        cap_max = 0
    else:
        cap_enabled = True
        df_db["_cap_int"] = df_db[cap_col].apply(_cap_to_int)
        cap_apply = st.checkbox("Activer le filtre Cap Hit", value=False, key="cap_apply")
        cap_min, cap_max = st.slider(
            "Plage Cap Hit",
            min_value=0,
            max_value=30_000_000,
            value=(0, 30_000_000),
            step=250_000,
            format="%d",
            disabled=(not cap_apply),
            key="cap_slider",
        )
        st.caption(f"Plage sélectionnée : **{_money_space(cap_min)} → {_money_space(cap_max)}**")

    has_any_filter = bool(str(q_name).strip()) or (q_team != "Toutes") or (q_level != "Tous") or bool(cap_apply)

    if not has_any_filter:
        st.info("Entre au moins un filtre pour afficher les résultats.")
    else:
        dff = df_db.copy()
        if str(q_name).strip():
            dff = dff[dff["Player"].astype(str).str.contains(str(q_name), case=False, na=False)]
        if q_team != "Toutes" and "Team" in dff.columns:
            dff = dff[dff["Team"].astype(str) == str(q_team)]
        if q_level != "Tous" and level_col and level_col in dff.columns:
            dff = dff[dff[level_col].astype(str) == str(q_level)]
        if cap_enabled and cap_apply:
            if "_cap_int" not in dff.columns:
                dff["_cap_int"] = dff[cap_col].apply(_cap_to_int)
            dff = dff[(dff["_cap_int"] >= int(cap_min)) & (dff["_cap_int"] <= int(cap_max))]

        if dff.empty:
            st.warning("Aucun joueur trouvé avec ces critères.")
        else:
            dff = dff.head(250).reset_index(drop=True)
            st.markdown("### Résultats")

            nhl_gp_col = "NHL GP" if "NHL GP" in dff.columns else None

            show_cols = []
            for c in ["Player", "Team", "Position", cap_col, "Level"]:
                if c and c in dff.columns and c not in show_cols:
                    show_cols.append(c)

            df_show = dff[show_cols].copy()

            if nhl_gp_col:
                insert_at = 3 if ("Position" in df_show.columns) else 1
                df_show.insert(insert_at, "GP", dff[nhl_gp_col])

            if cap_col and cap_col in df_show.columns:
                df_show[cap_col] = dff[cap_col].apply(lambda x: _money_space(_cap_to_int(x)))
                df_show = df_show.rename(columns={cap_col: "Cap Hit"})

            for c in df_show.columns:
                df_show[c] = df_show[c].apply(_clean_intlike)

            st.dataframe(df_show, use_container_width=True, hide_index=True)

    # Comparaison 2 joueurs
    st.divider()
    st.markdown("### 📊 Comparer 2 joueurs")

    players_list = sorted(df_db["Player"].dropna().astype(str).unique().tolist())

    def _filter_names(q: str, names: list[str], limit: int = 40) -> list[str]:
        q = str(q or "").strip().lower()
        if not q:
            return names[:limit]
        out = [n for n in names if q in n.lower()]
        return out[:limit]

    for k, v in {
        "cmp_q1": "",
        "cmp_q2": "",
        "compare_p1": None,
        "compare_p2": None,
        "cmp_sel_1": "—",
        "cmp_sel_2": "—",
    }.items():
        if k not in st.session_state:
            st.session_state[k] = v

    def clear_cmp_a():
        st.session_state["compare_p1"] = None
        st.session_state["cmp_q1"] = ""
        st.session_state["cmp_sel_1"] = "—"

    def clear_cmp_b():
        st.session_state["compare_p2"] = None
        st.session_state["cmp_q2"] = ""
        st.session_state["cmp_sel_2"] = "—"

    def add_cmp_a():
        sel = st.session_state.get("cmp_sel_1", "—")
        st.session_state["compare_p1"] = None if sel == "—" else sel

    def add_cmp_b():
        sel = st.session_state.get("cmp_sel_2", "—")
        st.session_state["compare_p2"] = None if sel == "—" else sel

    cA, cB = st.columns(2)
    with cA:
        st.markdown("**Joueur A**")
        q1 = st.text_input("Rechercher A", placeholder="Tape un nom…", key="cmp_q1")
        opt1 = ["—"] + _filter_names(q1, players_list, limit=40)
        st.selectbox("Sélection A", opt1, key="cmp_sel_1")
        b1, b2 = st.columns(2)
        b1.button("➕ Ajouter A", use_container_width=True, key="cmp_add_a", on_click=add_cmp_a)
        b2.button("🧹 Effacer A", use_container_width=True, key="cmp_clear_a", on_click=clear_cmp_a)

    with cB:
        st.markdown("**Joueur B**")
        q2 = st.text_input("Rechercher B", placeholder="Tape un nom…", key="cmp_q2")
        opt2 = ["—"] + _filter_names(q2, players_list, limit=40)
        st.selectbox("Sélection B", opt2, key="cmp_sel_2")
        b3, b4 = st.columns(2)
        b3.button("➕ Ajouter B", use_container_width=True, key="cmp_add_b", on_click=add_cmp_b)
        b4.button("🧹 Effacer B", use_container_width=True, key="cmp_clear_b", on_click=clear_cmp_b)

    p1 = st.session_state.get("compare_p1")
    p2 = st.session_state.get("compare_p2")

    if not p1 or not p2:
        st.info("Choisis 2 joueurs (A et B) pour afficher la comparaison.")
    elif p1 == p2:
        st.warning("Choisis 2 joueurs différents.")
    else:
        r1 = df_db[df_db["Player"].astype(str) == str(p1)].head(1)
        r2 = df_db[df_db["Player"].astype(str) == str(p2)].head(1)
        if r1.empty or r2.empty:
            st.error("Impossible de trouver un des joueurs dans la base.")
        else:
            df_cmp = pd.concat([r1, r2], ignore_index=True)
            nhl_gp_col = "NHL GP" if "NHL GP" in df_cmp.columns else None

            cmp_show_cols = []
            for c in ["Player", "Team", "Position", cap_col, "Level"]:
                if c and c in df_cmp.columns and c not in cmp_show_cols:
                    cmp_show_cols.append(c)

            df_cmp_show = df_cmp[cmp_show_cols].copy()
            if nhl_gp_col:
                insert_at = 3 if ("Position" in df_cmp_show.columns) else 1
                df_cmp_show.insert(insert_at, "GP", df_cmp[nhl_gp_col])

            if cap_col and cap_col in df_cmp_show.columns:
                df_cmp_show[cap_col] = df_cmp[cap_col].apply(lambda x: _money_space(_cap_to_int(x)))
                df_cmp_show = df_cmp_show.rename(columns={cap_col: "Cap Hit"})

            for c in df_cmp_show.columns:
                df_cmp_show[c] = df_cmp_show[c].apply(_clean_intlike)

            st.dataframe(df_cmp_show, use_container_width=True, hide_index=True)


# =====================================================
# TAB H — Historique
# =====================================================
with tabH:
    st.subheader("🕘 Historique des changements d’alignement")

    # ✅ Guard (espaces seulement)
    if df is None or df.empty or plafonds is None or plafonds.empty:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
        st.stop()

    h = st.session_state.get("history", pd.DataFrame()).copy()
    if h.empty:
        st.info("Aucune entrée d’historique pour cette saison.")
        st.stop()

    owners = ["Tous"] + sorted(h["proprietaire"].dropna().astype(str).unique().tolist())
    owner_filter = st.selectbox("Filtrer par propriétaire", owners, key="hist_owner_filter")

    if owner_filter != "Tous":
        h = h[h["proprietaire"].astype(str) == str(owner_filter)]

    if h.empty:
        st.info("Aucune entrée pour ce propriétaire.")
        st.stop()

    h["timestamp_dt"] = pd.to_datetime(h["timestamp"], errors="coerce")
    h = h.sort_values("timestamp_dt", ascending=False).drop(columns=["timestamp_dt"])

    st.caption("↩️ = annuler ce changement. ❌ = supprimer l’entrée (sans modifier l’alignement).")

    head = st.columns([1.5, 1.4, 2.4, 1.0, 1.6, 1.6, 2.0, 0.8, 0.7])
    head[0].markdown("**Date/Heure**")
    head[1].markdown("**Propriétaire**")
    head[2].markdown("**Joueur**")
    head[3].markdown("**Pos**")
    head[4].markdown("**De**")
    head[5].markdown("**Vers**")
    head[6].markdown("**Action**")
    head[7].markdown("**↩️**")
    head[8].markdown("**❌**")

    for _, r in h.iterrows():
        rid = int(pd.to_numeric(r.get("id", 0), errors="coerce") or 0)

        cols = st.columns([1.5, 1.4, 2.4, 1.0, 1.6, 1.6, 2.0, 0.8, 0.7])

        cols[0].markdown(str(r.get("timestamp", "")))
        cols[1].markdown(str(r.get("proprietaire", "")))
        cols[2].markdown(str(r.get("joueur", "")))
        cols[3].markdown(str(r.get("pos", "")))

        de = f"{r.get('from_statut', '')}" + (f" ({r.get('from_slot', '')})" if str(r.get("from_slot", "")).strip() else "")
        vers = f"{r.get('to_statut', '')}" + (f" ({r.get('to_slot', '')})" if str(r.get("to_slot", "")).strip() else "")
        cols[4].markdown(de)
        cols[5].markdown(vers)
        cols[6].markdown(str(r.get("action", "")))

        # =====================================================
        # UNDO (push local + Drive)
        # =====================================================
        if cols[7].button("↩️", key=f"undo_{rid}"):
            if LOCKED:
                st.error("🔒 Saison verrouillée : annulation impossible.")
            else:
                owner = str(r.get("proprietaire", "")).strip()
                joueur = str(r.get("joueur", "")).strip()

                data_df = st.session_state.get("data")
                if data_df is None or data_df.empty:
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
                        st.session_state["data"].loc[mask, "Slot"] = from_slot if from_slot else ""

                        # Si on sort de IR -> reset IR Date
                        if cur_slot == "Blessé" and from_slot != "Blessé":
                            st.session_state["data"].loc[mask, "IR Date"] = ""

                        # Nettoyage + save local
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
                            action=f"UNDO #{rid}",
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
        if cols[8].button("❌", key=f"del_{rid}"):
            h2 = st.session_state.get("history", pd.DataFrame()).copy()
            if not h2.empty and "id" in h2.columns:
                h2 = h2[h2["id"] != rid]

            st.session_state["history"] = h2

            # Save local
            save_history(st.session_state.get("HISTORY_FILE", HISTORY_FILE), h2)

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



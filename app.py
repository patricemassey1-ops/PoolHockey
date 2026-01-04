Skip to content
Chat history


You said:
Hello, can you help me built the best NHL Pool fantasy app?
ChatGPT said:
Absolutely — and since you’re already working in Streamlit + pandas + (optionally) Google Drive OAuth, you’re in a great spot to build something really strong.
Here’s a blueprint for a “best-in-class” NHL pool fantasy app, plus a concrete, buildable starting plan.

What “best” looks like (features that actually win)
Core (must-have)
Roster management: Active / Bench / Minors / IR / NA, with rules & limits
Salary cap + contract logic (GC / CE like you have), live totals, warnings, and “what changed” history
Transactions: add/drop, move between slots, trade tool, approvals if needed
Scoring engine: configurable categories/points, per-week and season totals
Standings: overall + per-category, with tie-break rules
Player database: search, filters (team/pos/status), and a clean player card (stats, injuries, schedule)
Audit trail: history of every action (who/what/when), with undo where possible
“Elite” (what makes it feel premium)
Fantrax sync (or CSV import + reconciliation) + “diff view” of what changed
Live NHL data ingestion (stats, injuries, line combos, goalie starts, schedule strength)
Projections + “Start/Sit helper”: weekly matchups, schedule density, opponent strength
Trade analyzer: rest-of-season value, cap impact, roster legality check
Notifications: injury alerts, goalie confirmed starts, cap violations, deadline reminders
Mobile-first UI (Streamlit can do it, but we’ll design for it)
Architecture that won’t collapse later
Data model (tables you’ll want)
players (id, name, pos, team, NHL status, injury, etc.)
stats_daily or stats_game (player_id, date/game_id, categories)
projections (player_id, week/date range, projected categories)
teams (pool teams/owners, logos, settings)
rosters (team_id, player_id, slot, start_date, end_date)
transactions (id, timestamp, user, action, payload)
settings (league scoring, roster rules, cap rules)
Storage options
Best overall: Postgres (Supabase/Neon) + SQLAlchemy
Simpler: SQLite locally + backup to Drive
Your current approach (CSV + Drive) works, but once you add stats + history + projections, you’ll feel pain. We can migrate gradually.
App structure (Streamlit)
/pages for: Standings, Teams, Players, Transactions, Admin
services/ for data loading, rules engine, scoring engine, sync engine
ui/ components: roster table, player card, filters, toasts, modals
rules/ for roster/cap validation
The fastest path to a great v1 (2–3 phases)
Phase 1 — “Playable League” (your current direction, but hardened)
Clean roster UI + moves (GC/CE/bench/minors/IR)
Salary caps + warnings
Transactions history + undo-last
Import/sync from Fantrax CSV
Authentication (simple: password in secrets; better: OAuth)
Phase 2 — “Smart League”
Auto-update player statuses (IR/DTD/Out) from data feed
You said:
here's my code
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


# =====================================================
# 📜 HISTORIQUE
# =====================================================
def history_add(action: str, details: str = "", owner: str = "", player: str = ""):
    ts = datetime.now().isoformat(timespec="seconds")

    row = {
        "Date": ts,
        "Action": action,
        "Propriétaire": owner,
        "Joueur": player,
        "Détails": details,
    }

    h = st.session_state.get("history")
    if h is None or not isinstance(h, pd.DataFrame):
        h = pd.DataFrame(columns=row.keys())

    for c in row:
        if c not in h.columns:
            h[c] = ""

    h = pd.concat([h, pd.DataFrame([row])], ignore_index=True)
    st.session_state["history"] = h

    # Local
    try:
        hist_file = st.session_state.get("HISTORY_FILE")
        if hist_file:
            h.to_csv(hist_file, index=False)
    except Exception:
        pass

    # Drive (optionnel)
    try:
        if "_drive_enabled" in globals() and _drive_enabled():
            season_lbl = st.session_state.get("season")
            if season_lbl:
                gdrive_save_df(h, f"history_{season_lbl}.csv", GDRIVE_FOLDER_ID)
    except Exception:
        pass


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
                st.caption("Ensuite enlève ?code=... de l’URL (ou refresh) après avoir mis à jour Secrets.")
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
        st.caption("Après l’autorisation, tu reviens ici avec ?code=... et je te donne le refresh_token.")
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
# =====================================================

def _safe_empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=REQUIRED_COLS)



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
    tabAdmin = None  # important pour éviter NameError ailleurs


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

        # --- Statut OAuth / Drive
        folder_id = str(_folder_id() or "").strip()
        drive_ready = bool(_drive_enabled())

        if not folder_id:
            st.warning("⚠️ folder_id manquant dans [gdrive_oauth] (Secrets).")

            # Optionnel: bouton auto-création/trouver dossier
            if "ensure_drive_folder_id" in globals() and oauth_drive_enabled():
                st.caption("Option: créer/trouver automatiquement le dossier Drive 'PoolHockeyData'.")
                if st.button(
                    "📁 Créer / Trouver 'PoolHockeyData' (afficher folder_id)",
                    use_container_width=True,
                    key="admin_create_folder",
                ):
                    try:
                        fid = ensure_drive_folder_id("PoolHockeyData")
                        if fid:
                            st.success("✅ Dossier Drive OK.")
                            st.warning("Copie ce folder_id dans Streamlit Secrets → [gdrive_oauth].folder_id")
                            st.code(fid)
                        else:
                            st.error("❌ Impossible (OAuth pas prêt ou config manquante).")
                    except Exception as e:
                        st.error(f"❌ Folder error: {type(e).__name__}: {e}")

        elif not drive_ready:
            st.info("OAuth pas encore prêt (refresh_token manquant ou invalide).")
            st.caption(f"📁 Folder ID: {folder_id}")

        else:
            st.success("✅ OAuth prêt — Drive activé.")
            st.caption(f"📁 Folder ID: {folder_id}")

            # =====================================================
            # 🚀 DRIVE BATCH (Flush + Reset)
            # =====================================================
            st.markdown("### 🚀 Drive batch (réduction des écritures)")

            q = st.session_state.get("drive_queue", {})
            st.caption(f"En attente d'écriture Drive : **{len(q)}** fichier(s).")

            c1, c2 = st.columns(2)
            with c1:
                if st.button(
                    "🚀 Flush Drive maintenant",
                    key="admin_flush_drive_now",
                    use_container_width=True,
                ):
                    if "flush_drive_queue" in globals():
                        n, errs = flush_drive_queue(force=True)
                        if errs:
                            st.error("❌ Erreurs:\n" + "\n".join(errs))
                        else:
                            st.success(f"✅ Flush OK — {n} fichier(s) écrit(s) sur Drive.")
                    else:
                        st.error("flush_drive_queue() introuvable (bloc batch non chargé).")

            with c2:
                if st.button(
                    "♻️ Reset cache Drive",
                    key="admin_reset_drive_cache",
                    use_container_width=True,
                ):
                    try:
                        st.cache_resource.clear()
                    except Exception:
                        pass

                    st.session_state["drive_queue"] = {}
                    st.session_state["drive_dirty_at"] = 0.0
                    st.session_state["drive_last_flush"] = 0.0
                    st.success("✅ Cache Drive + queue reset. Le client Drive sera reconstruit.")

            st.divider()

            # =====================================================
            # 🧪 TESTS DRIVE (lecture / écriture)
            # =====================================================
            st.markdown("### 🧪 Tests Drive")

            t1, t2 = st.columns(2)

            with t1:
                if st.button(
                    "🧪 Test lecture (liste 10 fichiers)",
                    key="admin_test_read",
                    use_container_width=True,
                ):
                    try:
                        names = gdrive_list_files(folder_id, limit=10)
                        st.success(f"✅ Lecture OK — {len(names)} fichier(s).")
                        if names:
                            st.write(names)
                    except Exception as e:
                        st.error(f"❌ Lecture KO — {type(e).__name__}: {e}")

            with t2:
                if st.button(
                    "🧪 Test écriture (écraser fichier test)",
                    key="admin_test_write",
                    use_container_width=True,
                ):
                    try:
                        df_test = pd.DataFrame([{"ok": 1, "ts": datetime.now().isoformat()}])
                        gdrive_save_df(df_test, "drive_test.csv", folder_id)
                        st.success("✅ Écriture OK — drive_test.csv créé/mis à jour.")
                    except Exception as e:
                        st.error(f"❌ Écriture KO — {type(e).__name__}: {e}")

            st.divider()

            # =====================================================
            # 📥 IMPORT (ADMIN ONLY) — CSV INITIAUX (1 fois)
            #   ✅ Choix équipe + Preview + Confirmation obligatoire
            #   ✅ Trace dans historique
            #   ✅ PAS de bouton Recharger
            # =====================================================
            st.markdown("### 📥 Import")
            manifest = load_init_manifest()

            st.markdown("#### 🧾 CSV initiaux (1 seule fois)")

            c_init1, c_init2 = st.columns(2)
            with c_init1:
                init_align = st.file_uploader(
                    "CSV initial — Alignement (Fantrax)",
                    type=["csv", "txt"],
                    help="Import initial (1 fois). Ensuite, l'état courant est celui sauvegardé (local/Drive).",
                    key=f"init_align_upl_{st.session_state.get('uploader_nonce', 0)}_admin",
                )

            with c_init2:
                init_hist = st.file_uploader(
                    "CSV initial — Historique",
                    type=["csv", "txt"],
                    help="Optionnel: injecte un historique initial.",
                    key=f"init_hist_upl_{st.session_state.get('uploader_nonce', 0)}_admin",
                )

            # --- Choix équipe (obligatoire pour alignement)
            teams = sorted(list(LOGOS.keys())) if "LOGOS" in globals() else []
            if not teams:
                teams = ["Whalers"]

            chosen_owner = st.selectbox(
                "Importer l'alignement initial dans quelle équipe ?",
                teams,
                index=0,
                key="init_align_owner_pick_admin",
            )

            st.caption("Étapes: 1) Prévisualiser → 2) Confirmer l'import (obligatoire)")

            c_btn1, c_btn2, c_btn3 = st.columns([1, 1, 2])

            # -----------------------------
            # 1) PRÉVISUALISER
            # -----------------------------
            with c_btn1:
                if st.button("👀 Prévisualiser", use_container_width=True, key="preview_init_csvs_admin"):
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
                                df_import["Propriétaire"] = chosen_owner
                                df_import = clean_data(df_import)

                                st.session_state["init_preview_df"] = df_import
                                st.session_state["init_preview_owner"] = chosen_owner
                                st.session_state["init_preview_filename"] = init_align.name

                                st.success(f"✅ Prévisualisation prête — {len(df_import)} joueur(s) pour **{chosen_owner}**.")
                        except Exception as e:
                            st.error(f"❌ Prévisualisation échouée : {type(e).__name__}: {e}")

            # Aperçu si présent
            preview_df = st.session_state.get("init_preview_df")
            if isinstance(preview_df, pd.DataFrame) and not preview_df.empty:
                with st.expander("🔎 Aperçu (20 premières lignes)", expanded=True):
                    st.dataframe(preview_df.head(20), use_container_width=True)

                st.info(
                    f"Prêt à importer: **{len(preview_df)}** joueur(s) "
                    f"dans **{st.session_state.get('init_preview_owner','')}** "
                    f"(fichier: {st.session_state.get('init_preview_filename','')})"
                )

            # -----------------------------
            # 2) CONFIRMER (OBLIGATOIRE)
            # -----------------------------
            with c_btn2:
                disabled_confirm = not (isinstance(preview_df, pd.DataFrame) and not preview_df.empty)

                if st.button(
                    "✅ Confirmer l'import",
                    use_container_width=True,
                    key="confirm_init_csvs_admin",
                    disabled=disabled_confirm,
                ):
                    try:
                        df_final = st.session_state.get("init_preview_df")
                        owner_final = st.session_state.get("init_preview_owner", chosen_owner)
                        filename_final = st.session_state.get("init_preview_filename", "")

                        if df_final is None or df_final.empty:
                            st.error("Aucune prévisualisation valide à confirmer.")
                        else:
                            # 1) Sauvegarde CSV brut initial
                            try:
                                path = save_uploaded_csv(init_align, f"initial_fantrax_{season}.csv")
                            except Exception:
                                path = manifest.get("fantrax", {}).get("path", "")

                            manifest["fantrax"] = {
                                "path": path,
                                "uploaded_name": filename_final or (init_align.name if init_align else ""),
                                "season": season,
                                "saved_at": datetime.now().isoformat(),
                                "chosen_owner": owner_final,
                            }

                            # 2) Charge état courant
                            st.session_state["data"] = df_final

                            # 3) Save local état courant
                            try:
                                st.session_state["data"].to_csv(st.session_state["DATA_FILE"], index=False)
                            except Exception:
                                pass

                            # 4) Save Drive état courant (optionnel)
                            try:
                                if "_drive_enabled" in globals() and _drive_enabled():
                                    gdrive_save_df(
                                        st.session_state["data"],
                                        f"fantrax_{season}.csv",
                                        GDRIVE_FOLDER_ID,
                                    )
                            except Exception:
                                pass

                            # 5) Trace historique
                            try:
                                history_add(
                                    action="IMPORT_INITIAL_ALIGNEMENT",
                                    owner=owner_final,
                                    details=f"{len(df_final)} joueurs importés (fichier: {manifest['fantrax'].get('uploaded_name','')})",
                                )
                            except Exception:
                                pass

                            # 6) CSV historique initial (optionnel)
                            if init_hist is not None:
                                try:
                                    hist_path = save_uploaded_csv(init_hist, f"initial_history_{season}.csv")
                                    manifest["history"] = {
                                        "path": hist_path,
                                        "uploaded_name": init_hist.name,
                                        "season": season,
                                        "saved_at": datetime.now().isoformat(),
                                    }

                                    h0 = pd.read_csv(hist_path)
                                    st.session_state["history"] = h0

                                    try:
                                        st.session_state["history"].to_csv(st.session_state["HISTORY_FILE"], index=False)
                                    except Exception:
                                        pass

                                    try:
                                        history_add(
                                            action="IMPORT_INITIAL_HISTORIQUE",
                                            owner="",
                                            details=f"Historique initial importé (fichier: {init_hist.name})",
                                        )
                                    except Exception:
                                        pass
                                except Exception as e:
                                    st.warning(f"⚠️ Historique initial non chargé : {type(e).__name__}: {e}")

                            # 7) Sauve manifest
                            save_init_manifest(manifest)

                            # 8) Nettoyage preview
                            st.session_state.pop("init_preview_df", None)
                            st.session_state.pop("init_preview_owner", None)
                            st.session_state.pop("init_preview_filename", None)

                            st.success("✅ Import initial confirmé et sauvegardé.")
                            st.session_state["uploader_nonce"] = st.session_state.get("uploader_nonce", 0) + 1
                            do_rerun()

                    except Exception as e:
                        st.error(f"❌ Confirmation échouée : {type(e).__name__}: {e}")

            # -----------------------------
            # État du manifest (info)
            # -----------------------------
            with c_btn3:
                fantrax_info = manifest.get("fantrax", {})
                hist_info = manifest.get("history", {})

                def _fmt(info: dict) -> str:
                    if not info:
                        return "—"
                    p = info.get("path", "")
                    name = info.get("uploaded_name", "")
                    ts = info.get("saved_at", "")
                    owner = info.get("chosen_owner", "")
                    ok = "✅" if (p and os.path.exists(p)) else "⚠️"
                    extra = f" | équipe: {owner}" if owner else ""
                    return f"{ok} {name} | {os.path.basename(p) if p else ''} | {ts}{extra}"

                st.caption("**État CSV initiaux (manifest local)**")
                st.caption(f"Alignement : {_fmt(fantrax_info)}")
                st.caption(f"Historique : {_fmt(hist_info)}")

            st.divider()

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
                                    st.caption(f"Backup alignement : {backup_data_path}")
                                    if backup_hist_path:
                                        st.caption(f"Backup historique : {backup_hist_path}")

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
                st.info("Aucun backup trouvé dans data/backups/.")
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
    st.subheader("📊 Tableau")

    if df is None or df.empty:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
        st.stop()

    # ... ton code Tableau ici ...





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
        if not all_owners:
            all_owners = ["—"]

        selected_team = get_selected_team()

        # Sync sélection d’équipe -> align_owner si possible
        if selected_team and selected_team in all_owners:
            st.session_state["align_owner"] = selected_team

        # ✅ Guard béton: si la valeur en session_state n'est plus dans options, reset
        cur_owner = st.session_state.get("align_owner")
        if cur_owner not in all_owners:
            st.session_state["align_owner"] = all_owners[0]

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
            f"**Actifs** — F {_count_badge(nb_F, 12)} • D {_count_badge(nb_D, 6)} • G {_count_badge(nb_G, 2)}",
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
# TAB H — Historique
# =====================================================
with tabH:
    st.subheader("🕘 Historique des changements d’alignement")

    # ✅ Guard (NE PAS st.stop() sinon ça stoppe toute l'app)
    if df is None or df.empty or plafonds is None or plafonds.empty:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
    else:
        h = st.session_state.get("history")
        h = h.copy() if isinstance(h, pd.DataFrame) else pd.DataFrame()

        if h.empty:
            st.info("Aucune entrée d’historique pour cette saison.")
        else:
            # Colonnes attendues (soft) pour éviter KeyError
            for c in [
                "id", "timestamp", "proprietaire", "joueur", "pos",
                "from_statut", "from_slot", "to_statut", "to_slot", "action"
            ]:
                if c not in h.columns:
                    h[c] = ""

            owners = ["Tous"] + sorted(h["proprietaire"].dropna().astype(str).unique().tolist())
            owner_filter = st.selectbox("Filtrer par propriétaire", owners, key="hist_owner_filter")

            if owner_filter != "Tous":
                h = h[h["proprietaire"].astype(str) == str(owner_filter)]

            if h.empty:
                st.info("Aucune entrée pour ce propriétaire.")
            else:
                h["timestamp_dt"] = pd.to_datetime(h["timestamp"], errors="coerce")
                h = h.sort_values("timestamp_dt", ascending=False).drop(columns=["timestamp_dt"], errors="ignore")

                st.caption("↩️ = annuler ce changement. ❌ = supprimer l’entrée (sans modifier l’alignement).")

                # Limite (perf)
                max_rows = st.number_input(
                    "Nombre max de lignes à afficher",
                    min_value=50,
                    max_value=5000,
                    value=250,
                    step=50,
                    key="hist_max_rows",
                )
                h_view = h.head(int(max_rows)).reset_index(drop=True)

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

                def _safe_int(x):
                    v = pd.to_numeric(x, errors="coerce")
                    if pd.isna(v):
                        return None
                    try:
                        return int(v)
                    except Exception:
                        return None

                # 🔑 UID unique garanti (évite DuplicateElementKey même si id=0 ou doublons)
                def _uid(r: pd.Series, i: int) -> str:
                    rid = _safe_int(r.get("id", None))
                    ts = str(r.get("timestamp", "")).strip()
                    owner = str(r.get("proprietaire", "")).strip()
                    joueur = str(r.get("joueur", "")).strip()
                    action = str(r.get("action", "")).strip()
                    return f"{rid if rid is not None else 'noid'}|{ts}|{owner}|{joueur}|{action}|{i}"

                for i, r in h_view.iterrows():
                    uid = _uid(r, i)
                    rid = _safe_int(r.get("id", None))  # peut être None

                    cols = st.columns([1.5, 1.4, 2.4, 1.0, 1.6, 1.6, 2.0, 0.8, 0.7])

                    cols[0].markdown(str(r.get("timestamp", "")))
                    cols[1].markdown(str(r.get("proprietaire", "")))
                    cols[2].markdown(str(r.get("joueur", "")))
                    cols[3].markdown(str(r.get("pos", "")))

                    de = f"{r.get('from_statut', '')}" + (
                        f" ({r.get('from_slot', '')})" if str(r.get("from_slot", "")).strip() else ""
                    )
                    vers = f"{r.get('to_statut', '')}" + (
                        f" ({r.get('to_slot', '')})" if str(r.get("to_slot", "")).strip() else ""
                    )
                    cols[4].markdown(de)
                    cols[5].markdown(vers)
                    cols[6].markdown(str(r.get("action", "")))

                    # =====================================================
                    # UNDO (push local + Drive)
                    # =====================================================
                    if cols[7].button("↩️", key=f"undo__{uid}", use_container_width=True):
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
                    if cols[8].button("❌", key=f"del__{uid}", use_container_width=True):
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

ChatGPT said:
Yep — this is already a really solid v1. You’ve got the hard parts working: roster state, move dialog UX, history/undo, Drive persistence + SSL retry, and a player DB view.
If you want to turn this into a “best NHL pool fantasy app”, the next step isn’t adding more tabs — it’s making the codebase scalable (so you can add scoring, matchups, projections, trades, alerts without it turning into a 5,000-line app.py).

Below are the highest-impact fixes + refactors based on your pasted code (I’m being very concrete).

1) Fix a major bug: dead code after return True
In apply_move_with_history() you return True, and then you still have a big block that will never execute (old save logic / history logic).
That dead block increases confusion and can hide real bugs.

✅ Keep only one persistence path (you already have persist_data() + persist_history() with Drive queue).

What to do

Delete everything after the first return True inside apply_move_with_history().
That’s it.
2) You defined Drive batch code twice (and _is_ssl_error twice)
Right now you have:
_is_ssl_error, _reset_drive_client_cache, queue_drive_save_df, flush_drive_queue duplicated (I see two full copies).
This can cause “why is it not using my new version?” confusion because reruns + caching can make it feel inconsistent.
✅ Keep one canonical version of each.
Rule of thumb

Keep _call_with_retry, gdrive_save_df, gdrive_load_df, queue/flush exactly once.
Put them in a drive.py module later, but for now: remove duplicates.
3) Normalize history: right now you have TWO history systems
You have:
history_add() writing a DataFrame with columns Date/Action/Propriétaire/Joueur/Détails
AND log_history_row() writing another schema id/timestamp/proprietaire/...
That’s going to bite you later (filters, exports, undo, admin logs etc).
✅ Pick one schema.

Recommendation
Keep the detailed one (the log_history_row schema) and expand it to also cover admin actions (import/restore/delete).

So replace usages of history_add() with log_history_row(...) style events, e.g.:

action = "ADMIN_IMPORT_INITIAL"
from/to can be blank
4) Create a “rules engine” for roster legality (you already started)
Right now you compute counts (F/D/G) and show badges, but you don’t enforce roster rules during moves.
✅ Add a function that validates a move before writing it:

Max Actifs: F 12, D 6, G 2 (you already display this)
Max Banc size (if applicable)
IR unlimited? (your code treats salary excluded, good)
CE limits? (if applicable)
Pattern
def validate_move(df, owner, joueur, to_statut, to_slot) -> tuple[bool, str]:
    # compute resulting roster if applied
    # return (True, "") or (False, "Reason")
Then in apply_move_with_history():
run validate_move(...) first
if invalid: set last_move_error and return False
This single addition will make the app feel “league-grade”.
5) Performance: your roster UI is O(n) Streamlit buttons (fine) but needs stability
roster_click_list() creates many st.button keys using player names. Names can repeat across seasons/imports and can include weird characters.
✅ Use a deterministic internal id per row.
You already have Propriétaire + Joueur uniqueness; use a safe hash:

import hashlib
def _k(*parts):
    s = "|".join(str(p or "") for p in parts)
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:12]
Then:
key=f"{source_key}_{_k(owner, joueur, i)}"
This kills “DuplicateElementKey” forever.
6) Make Drive writes consistent: stop mixing direct save + queued save
You sometimes do:
persist_data() (queued)
but in Undo/Delete you also do direct gdrive_save_df().
✅ Choose one model:
Always queue updates (queue_drive_save_df)
Flush on:
Admin tab “Flush now”
App footer auto flush (you already do this)
After destructive operations (delete/restore) call flush_drive_queue(force=True)
So in Undo/Delete, replace direct saves with:
persist_data(st.session_state["data"], season_lbl)
persist_history(st.session_state["history"], season_lbl)
flush_drive_queue(force=True)
7) Split the file (this is the real “level up”)
Your app.py has at least 6 subsystems:
Drive OAuth + retry
Persistence + bootstrap
Data cleaning + parsing Fantrax
History + undo/delete
UI components (roster list, badges, bars)
Tabs
✅ Minimum split (no architecture overkill):
drive.py → oauth + gdrive_* + queue/flush
data_model.py → REQUIRED_COLS, clean_data, parse_fantrax
history.py → load/save/log/undo helpers
ui_components.py → roster_click_list, badges, bars, header/banner
app.py becomes mostly “wiring + tabs”
This makes it possible to add:
scoring engine
matchup page
projections
without fear.
8) Feature roadmap that fits YOUR app (next 3 big wins)
Given what you have, the next “wow” features are:
A) Scoring + Standings (weekly + season)
Add a settings_scoring.json (or a Streamlit UI to define categories/points)
Import stats (CSV first, then live API later)
Compute:
weekly totals by owner
standings table
B) Schedule density & start/sit helper
For each player: games next 7 days, back-to-backs
Team schedule strength
“Recommend bench/minor” based on games played and cap relief
C) Trade tool (cap + legality checker)
Select “Team A gives X, receives Y”
Show:
cap impact GC/CE
roster legality post-trade
depth chart impact (F/D/G)
If you want, I can do the next step directly on your code
Without asking you to rewrite everything, the single best “surgical” improvement I can apply first is:
✅ Clean the duplicates + remove dead code + unify history + unify Drive writes

That alone will cut complexity by a lot and make future additions painless.

If you tell me which direction you want next:

(1) Scoring/standings
(2) Trade analyzer
(3) Better players page (add to roster, compare, waiver suggestions)
…I’ll give you the exact blocks/files to paste (Streamlit-ready), matching your current structure and naming.
You said:
let's try 1 and 3
ChatGPT said:

Thought for 14s
Cool — we’ll add (1) scoring/standings and (3) a smarter Players page (add + compare + waiver suggestions) in a way that fits your current Streamlit + CSV + Drive setup.
Below is the cleanest path that doesn’t force a rewrite.

0) What we’ll store (minimal new files)
Add these files in /data:
data/scoring_settings.json
Example (points system — edit freely):
{
  "mode": "points",
  "points": {
    "G": 3,
    "A": 2,
    "PPP": 1,
    "SOG": 0.2,
    "HIT": 0.2,
    "BLK": 0.2,
    "W": 3,
    "SV": 0.1,
    "GA": -1,
    "SO": 2
  }
}
data/stats_game_log.csv (or weekly — your choice)
Simplest to start: weekly totals per player:
Columns:
season, week, player, team, pos, G, A, PPP, SOG, HIT, BLK, W, SV, GA, SO
(You can export this from wherever you track stats. Later we can auto-fetch.)
1) Drop-in scoring engine (copy/paste block)
Put this block once (ideally near your other helpers). It works with local CSV and can also be queued to Drive later.
import json

SCORING_FILE = os.path.join("data", "scoring_settings.json")
STATS_WEEKLY_FILE = os.path.join("data", "stats_weekly.csv")  # or rename to your file

@st.cache_data(show_spinner=False)
def load_scoring_settings(path: str) -> dict:
    if not os.path.exists(path):
        # safe default
        return {"mode": "points", "points": {"G": 3, "A": 2}}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

@st.cache_data(show_spinner=False)
def load_stats_weekly(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path)
    # normalize
    for c in ["season", "week", "player"]:
        if c not in df.columns:
            df[c] = ""
    df["season"] = df["season"].astype(str).str.strip()
    df["week"] = pd.to_numeric(df["week"], errors="coerce").fillna(0).astype(int)
    df["player"] = df["player"].astype(str).str.strip()
    return df

def compute_player_points(stats_row: pd.Series, scoring: dict) -> float:
    pts = 0.0
    weights = scoring.get("points", {}) if scoring.get("mode") == "points" else {}
    for stat, w in weights.items():
        if stat in stats_row.index:
            v = pd.to_numeric(stats_row.get(stat, 0), errors="coerce")
            v = 0 if pd.isna(v) else float(v)
            pts += v * float(w)
    return float(pts)

def compute_owner_points(df_rosters: pd.DataFrame, stats_weekly: pd.DataFrame, scoring: dict,
                         season: str, week: int | None = None) -> pd.DataFrame:
    """
    Returns owner totals for the given season (and optionally week).
    Uses your roster df: columns Propriétaire, Joueur, Statut, Slot, etc.
    """
    if df_rosters is None or df_rosters.empty:
        return pd.DataFrame(columns=["Propriétaire", "Points"])

    if stats_weekly is None or stats_weekly.empty:
        # no stats yet → return zeros
        owners = sorted(df_rosters["Propriétaire"].dropna().astype(str).unique().tolist())
        return pd.DataFrame({"Propriétaire": owners, "Points": [0.0]*len(owners)})

    # filter stats
    s = stats_weekly.copy()
    s = s[s["season"].astype(str) == str(season)]
    if week is not None:
        s = s[s["week"] == int(week)]

    if s.empty:
        owners = sorted(df_rosters["Propriétaire"].dropna().astype(str).unique().tolist())
        return pd.DataFrame({"Propriétaire": owners, "Points": [0.0]*len(owners)})

    # precompute player points
    s["_pts"] = s.apply(lambda r: compute_player_points(r, scoring), axis=1)
    pts_by_player = s.groupby("player", as_index=False)["_pts"].sum()

    # roster join by name (good enough for v1; later we add ids)
    r = df_rosters.copy()
    r["Joueur"] = r["Joueur"].astype(str).str.strip()

    merged = r.merge(pts_by_player, how="left", left_on="Joueur", right_on="player")
    merged["_pts"] = merged["_pts"].fillna(0.0)

    # Optional: count only Actifs (common pool rule)
    # If you want ALL roster to count, remove this filter.
    merged = merged[merged["Slot"].astype(str).isin(["Actif"])]

    out = merged.groupby("Propriétaire", as_index=False)["_pts"].sum()
    out = out.rename(columns={"_pts": "Points"}).sort_values("Points", ascending=False).reset_index(drop=True)
    out["Rang"] = range(1, len(out)+1)
    return out[["Rang", "Propriétaire", "Points"]]
2) Add a new tab: Standings (Scoring)
Add a tab label (for both admin & non-admin):
Admin tabs: insert "🏆 Classement" somewhere
Non-admin tabs: same
Then add this block:
# =====================================================
# TAB Standings — Classement
# =====================================================
with tabStand:
    st.subheader("🏆 Classement")

    scoring = load_scoring_settings(SCORING_FILE)
    stats_w = load_stats_weekly(STATS_WEEKLY_FILE)

    season_lbl = st.session_state.get("season", "")
    if not season_lbl:
        st.info("Choisis une saison.")
        st.stop()

    # Week selector (auto from file)
    weeks = sorted(stats_w[stats_w["season"].astype(str)==str(season_lbl)]["week"].unique().tolist()) if not stats_w.empty else []
    c1, c2 = st.columns([1, 2])
    with c1:
        mode = st.radio("Période", ["Saison", "Semaine"], horizontal=True, key="stand_mode")
    with c2:
        wk = None
        if mode == "Semaine":
            wk = st.selectbox("Semaine", weeks if weeks else [1], key="stand_week")

    df_rosters = st.session_state.get("data")
    df_rosters = clean_data(df_rosters) if isinstance(df_rosters, pd.DataFrame) else pd.DataFrame(columns=REQUIRED_COLS)

    table = compute_owner_points(df_rosters, stats_w, scoring, season_lbl, week=None if mode=="Saison" else int(wk))
    if table.empty:
        st.info("Aucun classement à afficher (stats manquantes ou roster vide).")
    else:
        st.dataframe(table, use_container_width=True, hide_index=True)

    with st.expander("⚙️ Scoring settings (debug)", expanded=False):
        st.json(scoring)
        st.caption(f"Stats file: {STATS_WEEKLY_FILE} ({'OK' if os.path.exists(STATS_WEEKLY_FILE) else 'missing'})")
Important: you need to actually create tabStand from st.tabs(...).
3) Players page: Add + Compare + Waiver Suggestions
Right now your “Joueurs” tab is a search-only viewer. We’ll add three things:
A) “Add to roster” (Free Agent → Team)
This requires your main roster df to accept a new row.
Add this function once:

def add_player_to_team(owner: str, player_name: str, team: str, pos: str, salary: int,
                       statut: str, slot: str) -> bool:
    if st.session_state.get("LOCKED"):
        st.session_state["last_move_error"] = "🔒 Saison verrouillée : ajout impossible."
        return False

    df0 = st.session_state.get("data")
    df0 = clean_data(df0) if isinstance(df0, pd.DataFrame) else pd.DataFrame(columns=REQUIRED_COLS)

    owner = str(owner).strip()
    player_name = str(player_name).strip()

    # avoid duplicates in same owner
    exists = (
        (df0["Propriétaire"].astype(str).str.strip() == owner)
        & (df0["Joueur"].astype(str).str.strip() == player_name)
    ).any()
    if exists:
        st.session_state["last_move_error"] = "Ce joueur est déjà dans cette équipe."
        return False

    new_row = {
        "Propriétaire": owner,
        "Joueur": player_name,
        "Salaire": int(salary or 0),
        "Statut": str(statut),
        "Slot": str(slot),
        "Pos": normalize_pos(pos),
        "Equipe": str(team or "").strip(),
        "IR Date": "",
    }

    df0 = pd.concat([df0, pd.DataFrame([new_row])], ignore_index=True)
    df0 = clean_data(df0)
    st.session_state["data"] = df0

    # history (use your detailed logger)
    try:
        log_history_row(
            proprietaire=owner, joueur=player_name, pos=new_row["Pos"], equipe=new_row["Equipe"],
            from_statut="", from_slot="", to_statut=new_row["Statut"], to_slot=new_row["Slot"],
            action="ADD_PLAYER"
        )
    except Exception:
        pass

    # persist
    season_lbl = str(st.session_state.get("season", "")).strip()
    persist_data(df0, season_lbl)
    h = st.session_state.get("history")
    if isinstance(h, pd.DataFrame):
        persist_history(h, season_lbl)

    return True
B) Compare (side-by-side)
No data model changes needed.
C) Waiver suggestions
For v1 we’ll suggest “best available” by:
cap hit range
position filter
(optional) last-week points if your stats_weekly exists
4) Minimal patch inside your tabJ
Inside with tabJ: after you compute dff results, add:
“Available players” definition
# Owned players list (by name)
roster_df = st.session_state.get("data")
roster_df = clean_data(roster_df) if isinstance(roster_df, pd.DataFrame) else pd.DataFrame(columns=REQUIRED_COLS)
owned = set(roster_df["Joueur"].astype(str).str.strip().tolist())

# dff currently = filtered results from players_db
# We'll tag which are available
dff["_available"] = ~dff["Player"].astype(str).str.strip().isin(owned)
Add + Compare UI
st.divider()
st.markdown("## ➕ Ajouter / 🔍 Comparer")

# pick from current filtered results
choices = dff["Player"].astype(str).tolist()
if not choices:
    st.info("Aucun joueur à sélectionner.")
else:
    cA, cB = st.columns(2)

    with cA:
        pick_add = st.selectbox("Ajouter un joueur", choices, key="pick_add_player")
        row_add = dff[dff["Player"].astype(str) == str(pick_add)].iloc[0]
        is_avail = bool(row_add.get("_available", True))

        owner_opts = sorted(roster_df["Propriétaire"].dropna().astype(str).unique().tolist())
        owner_to = st.selectbox("Vers quelle équipe ?", owner_opts if owner_opts else ["—"], key="add_owner_to")

        # basic fields
        pos_val = row_add.get("Position", row_add.get("Pos", "F"))
        team_val = row_add.get("Team", row_add.get("Equipe", ""))

        salary = st.number_input("Salaire (cap hit)", min_value=0, step=250_000, value=0, key="add_salary")
        statut = st.radio("Statut", ["Grand Club", "Club École"], horizontal=True, key="add_statut")
        slot = st.radio("Slot", ["Actif", "Banc", "Blessé"] if statut=="Grand Club" else ["" , "Blessé"],
                        horizontal=True, key="add_slot")

        if st.button("✅ Ajouter à l'équipe", use_container_width=True, disabled=(not is_avail)):
            ok = add_player_to_team(owner_to, pick_add, team_val, pos_val, int(salary), statut, slot)
            if ok:
                st.toast(f"✅ {pick_add} ajouté à {owner_to}", icon="✅")
                do_rerun()
            else:
                st.error(st.session_state.get("last_move_error") or "Ajout refusé.")

        if not is_avail:
            st.warning("Ce joueur est déjà détenu (pas disponible).")

    with cB:
        st.markdown("### 🔍 Comparaison")
        p1 = st.selectbox("Joueur A", choices, key="cmp_a")
        p2 = st.selectbox("Joueur B", choices, index=min(1, len(choices)-1), key="cmp_b")

        r1 = dff[dff["Player"].astype(str)==str(p1)].head(1)
        r2 = dff[dff["Player"].astype(str)==str(p2)].head(1)

        cols_show = [c for c in ["Player","Team","Position","Level"] if c in dff.columns]
        # cap column naming from earlier
        if "Cap Hit" in dff.columns: cols_show.append("Cap Hit")

        c1, c2 = st.columns(2)
        c1.dataframe(r1[cols_show], use_container_width=True, hide_index=True)
        c2.dataframe(r2[cols_show], use_container_width=True, hide_index=True)
Waiver suggestions (simple but useful)
st.divider()
st.markdown("## 🧠 Waiver suggestions (disponibles)")

avail = dff[dff["_available"] == True].copy()
if avail.empty:
    st.info("Aucun joueur disponible dans tes filtres actuels.")
else:
    # Optional: add “last week points” if stats file exists
    scoring = load_scoring_settings(SCORING_FILE)
    stats_w = load_stats_weekly(STATS_WEEKLY_FILE)
    season_lbl = st.session_state.get("season","")

    show = avail.copy()

    if not stats_w.empty and season_lbl:
        # last available week for that season
        season_stats = stats_w[stats_w["season"].astype(str)==str(season_lbl)]
        if not season_stats.empty:
            last_week = int(season_stats["week"].max())
            w = season_stats[season_stats["week"] == last_week].copy()
            w["_pts"] = w.apply(lambda r: compute_player_points(r, scoring), axis=1)
            pts = w.groupby("player", as_index=False)["_pts"].sum()
            show = show.merge(pts, how="left", left_on="Player", right_on="player")
            show["_pts"] = show["_pts"].fillna(0.0)
            show = show.sort_values("_pts", ascending=False)

            st.caption(f"Trié par points semaine {last_week} (si dispo).")

    cols = [c for c in ["Player","Team","Position","Level"] if c in show.columns]
    if "_pts" in show.columns:
        cols.append("_pts")
        show = show.rename(columns={"_pts":"Points (dernière semaine)"})

    st.dataframe(show[cols].head(50), use_container_width=True, hide_index=True)
What you’ll get after this
✅ A working Classement tab
✅ Players page can now:
search
add a free agent to a team
compare 2 players
show waiver suggestions (and it gets smarter automatically once you provide weekly stats)
Next “smart” upgrade (when you’re ready)
To avoid name-matching issues (“Alex DeBrincat” vs “DeBrincat, Alex”), we’ll add a stable player_id:
store player_id in your roster df
store same player_id in stats file
join on id, not name
No rush — but that’s the step that makes projections & automation painless.
If you paste me:

a sample of your data/stats_weekly.csv (first ~20 lines)
what your league scoring categories are (Fantrax settings screenshot or list)
…I’ll tailor the scoring mapping and make sure your standings match your exact rules (Actifs only vs all, goalie scoring, etc.).
You said:
how are you gonna calculate scoring points?
ChatGPT said:
Great question — this is the core of the app, so let’s be very clear and very deterministic.
I’ll explain exactly how points are calculated, step by step, and how it fits your current data model. No hand-waving.

1️⃣ Scoring philosophy (what I’m assuming)
We use a Fantrax-style points system:
Each stat has a weight
A player earns points = stat_value × stat_weight
Team (owner) points = sum of points of eligible players
Eligibility rules decide which players count (Actifs only, IR excluded, etc.)
This matches Fantrax Points Leagues, and it’s the most flexible system.
2️⃣ Inputs required (very important)
A) Scoring rules (once per league)
Stored in a JSON file (or DB later):
{
  "mode": "points",
  "points": {
    "G": 3,
    "A": 2,
    "PPP": 1,
    "SOG": 0.2,
    "HIT": 0.2,
    "BLK": 0.2,
    "W": 3,
    "SV": 0.1,
    "GA": -1,
    "SO": 2
  }
}
Meaning:
Goal = 3 pts
Assist = 2 pts
Shot = 0.2 pts
Save = 0.1 pts
Goal Against = −1 pt
👉 exactly how Fantrax calculates it
B) Player stats (per game or per week)
For v1, we keep it simple and robust:
Weekly totals per player
Example stats_weekly.csv:
season	week	player	G	A	SOG	HIT	BLK	W	SV	GA	SO
2025-2026	1	Jack Eichel	2	3	15	4	2	0	0	0	0
2025-2026	1	Connor Hellebuyck	0	1	0	0	0	2	68	4	0
Later we can go per-game, but weekly is faster, lighter, and matches fantasy scoring.
3️⃣ Player points calculation (atomic rule)
For each player, for a given week (or season):
PlayerPoints =
  (G × 3)
+ (A × 2)
+ (PPP × 1)
+ (SOG × 0.2)
+ (HIT × 0.2)
+ (BLK × 0.2)
+ (W × 3)
+ (SV × 0.1)
+ (GA × -1)
+ (SO × 2)
Example skater
Jack Eichel (Week 1):
2 G → 2 × 3 = 6
3 A → 3 × 2 = 6
15 SOG → 15 × 0.2 = 3
4 HIT → 4 × 0.2 = 0.8
2 BLK → 2 × 0.2 = 0.4
✅ Total = 16.2 points
Example goalie
Connor Hellebuyck (Week 1):
2 W → 2 × 3 = 6
68 SV → 68 × 0.1 = 6.8
4 GA → 4 × -1 = -4
✅ Total = 8.8 points
4️⃣ Roster eligibility rules (THIS is where leagues differ)
This is where your app becomes league-grade.
Default rule (recommended)
Only count:
Statut == "Grand Club"
Slot == "Actif"
Excluded:
Banc
Club École
IR
In code (you already saw this):
merged = merged[merged["Slot"] == "Actif"]
Optional variations (easy to toggle later)
Rule	Change
Count Banc too	remove Slot filter
IR still counts	allow Slot == "Blessé"
Minors score	allow Statut == "Club École"
Max games per position	enforce before summing
We can store this in scoring_settings.json later:
"eligibility": {
  "count_slots": ["Actif"],
  "count_statuts": ["Grand Club"]
}
5️⃣ Team (owner) scoring
Once player points are computed:
TeamPoints = Σ PlayerPoints
Grouped by Propriétaire.
Weekly standings
Filter stats to week = X
Compute points
Rank by total
Season standings
Sum all weeks
Rank by total
6️⃣ Why this approach is the right one
✅ Matches Fantrax logic
✅ Transparent (you can show the formula to GMs)
✅ Easy to audit (history + CSV)
✅ Easy to extend:
Head-to-head matchups
Category leagues
Projections
“Start / Sit” optimizer
7️⃣ What I need from you to finalize it perfectly
Answer these and I’ll lock the scoring engine exactly to your league:
1️⃣ Does your league score only Actifs?
2️⃣ Do goalies and skaters share the same pool?
3️⃣ Any caps like “max 4 goalie games/week”?
4️⃣ Do you already export weekly stats from Fantrax or another site?

Once I have that, I can:

add per-week matchup scoring
add live standings
add “this move gives you +2.4 pts/week” predictions
You’re already 70% of the way to a full Fantrax replacement — now we’re just formalizing the math.
You said:
pour nous les points sont en fonction de 
Buts/Goal = 1 points
Passes/Assists = 1 points
Victoire/Wins for goalies = 2 points
Defaites en prolongation/Loss in overtime = 1 points
ChatGPT said:
Parfait — c’est simple, clair et très propre 👍
Je te montre exactement comment les points seront calculés dans ton app, sans ambiguïté, et comment ça se traduit en code.
🧮 Règles de scoring de TON pool (confirmées)
🏒 Joueurs (skaters)
Stat	Points
But (G)	+1
Passe (A)	+1
➡️ Total skater = G + A
🥅 Gardiens
Stat	Points
Victoire (W)	+2
Défaite en prolongation (OTL)	+1
➡️ Total goalie = (W × 2) + (OTL × 1)
❌ Aucun point pour :

Arrêts (SV)
Buts alloués (GA)
Blanchissages (SO)
📊 Formule mathématique (officielle)
Skater
Points = Buts + Passes
Goalie
Points = (Victoires × 2) + (Défaites en prolongation × 1)
📁 Format des stats attendu (simple & robuste)
data/stats_weekly.csv
(hebdomadaire — recommandé)
season	week	player	pos	G	A	W	OTL
2025-2026	1	Jack Eichel	F	2	1	0	0
2025-2026	1	Connor Hellebuyck	G	0	0	2	1
🧠 Calcul EXACT dans l’app (player → team)
Étape 1 — Calcul points joueur
def compute_player_points(row: pd.Series) -> int:
    pos = str(row.get("pos", "")).upper()

    if pos == "G":
        w = int(row.get("W", 0) or 0)
        otl = int(row.get("OTL", 0) or 0)
        return (w * 2) + otl

    # Skaters
    g = int(row.get("G", 0) or 0)
    a = int(row.get("A", 0) or 0)
    return g + a
Étape 2 — Éligibilité roster (TRÈS IMPORTANT)
👉 Seuls ces joueurs comptent :
Statut == "Grand Club"
Slot == "Actif"
❌ Exclus :
Banc
IR
Club École
eligible = roster_df[
    (roster_df["Statut"] == "Grand Club") &
    (roster_df["Slot"] == "Actif")
]
Étape 3 — Total équipe (Propriétaire)
TeamPoints = somme(points_joueur)
🏆 Classement
Hebdomadaire
Filtrer week = X
Calculer les points
Trier décroissant
Saison
Additionner toutes les semaines
Trier décroissant
✅ Exemple réel
Équipe Whalers — Semaine 1
Joueur	Pos	Stats	Points
Jack Eichel	F	2 G, 1 A	3
Cole Caufield	F	1 G, 1 A	2
Connor Hellebuyck	G	2 W, 1 OTL	5
➡️ Total équipe = 10 points
🧩 Pourquoi ce système est parfait pour ton app
✅ Ultra simple à vérifier
✅ Aucun calcul flou
✅ Parfait pour classements hebdos
✅ Facile à expliquer aux GMs
✅ Hyper rapide à calculer (même avec 10 ans de données)
🔜 Prochaines étapes (logiques)
Maintenant qu’on a le scoring figé, je peux :
1️⃣ Ajouter le tab Classement exact (hebdo + saison)
2️⃣ Ajouter le breakdown par joueur (clic → détail points)
3️⃣ Ajouter un simulateur de move :

« Si tu montes ce joueur, tu gagnes +1.3 pt / semaine »
👉 Dis-moi juste :
Confirme : seuls les Actifs GC comptent ?
Combien de gardiens Actifs max par semaine ? (ex: 2)
Et je t’intègre ça directement dans ton code actuel, sans casser quoi que ce soit.
You said:
j'ai oublie qu'un Blanchissages/shutout pour un gardien est de = 2 points
ChatGPT said:
Parfait — on ajoute simplement SO (blanchissage) = +2 pour les gardiens.
Règles finales (d’après ce que tu viens de dire)
🏒 Skaters
G (Buts) = 1
A (Passes) = 1
➡️ Points = G + A
🥅 Gardiens
W (Victoires) = 2
OTL (Défaites en prolongation) = 1
SO (Blanchissages) = 2
➡️ Points = (W×2) + (OTL×1) + (SO×2)
Code exact du calcul (drop-in)
Remplace ton calcul de points par ceci (ou utilise-le dans ton moteur de scoring):
def compute_player_points(row: pd.Series) -> int:
    pos = str(row.get("pos", row.get("Pos", ""))).upper().strip()
    if pos == "G":
        w = int(pd.to_numeric(row.get("W", 0), errors="coerce") or 0)
        otl = int(pd.to_numeric(row.get("OTL", 0), errors="coerce") or 0)
        so = int(pd.to_numeric(row.get("SO", 0), errors="coerce") or 0)
        return (w * 2) + (otl * 1) + (so * 2)

    g = int(pd.to_numeric(row.get("G", 0), errors="coerce") or 0)
    a = int(pd.to_numeric(row.get("A", 0), errors="coerce") or 0)
    return g + a
Format stats à avoir (hebdo recommandé)
Dans data/stats_weekly.csv, assure-toi d’avoir au minimum ces colonnes:
season, week, player, pos, G, A, W, OTL, SO
Même si une ligne skater a W/OTL/SO = 0, c’est OK.
Petit détail important (pour éviter un bug plus tard)
Dans ton roster, ta colonne Pos est déjà normalisée (F/D/G).
Dans ton fichier de stats, assure-toi que pos ou Pos pour les goalies vaut bien "G".
Si tu me dis juste comment s’appelle la colonne shutout dans ta source (souvent SO, parfois Shutouts), je te fais le mapping automatique pour accepter les 2 sans effort.
You said:
Confirme : seuls les Actifs GC comptent ?
ChatGPT said:
✅ Confirmé.
👉 Seuls les joueurs :

Statut = Grand Club
Slot = Actif
comptent dans le calcul des points.
❌ Ne comptent PAS
Banc
Club École (mineur)
IR / Blessé
🔎 Règle appliquée dans le calcul
Concrètement, avant de sommer les points, on filtre toujours ainsi :
eligible = roster_df[
    (roster_df["Statut"] == "Grand Club") &
    (roster_df["Slot"] == "Actif")
]
Tout le reste est automatiquement ignoré pour le classement hebdo et saison.
🧠 Pourquoi c’est une bonne règle
Conforme à la majorité des pools Fantrax
Évite les abus (banc/minor qui score)
Rend les décisions Actif ↔ Banc ↔ Mineur ↔ IR vraiment stratégiques
Simplifie énormément les audits et les contestations
Prochaine étape logique (je te la fais ensuite)
Maintenant que le scoring ET l’éligibilité sont figés, je peux te livrer :
1️⃣ Le tab Classement final prêt à coller (hebdo + saison)
2️⃣ Le détail par équipe (points par joueur Actif)
3️⃣ Un simulateur de move

“Si tu montes ce joueur Actif cette semaine → +X points attendus”
👉 Dis-moi juste :
Combien de gardiens Actifs max par semaine ? (ex: 2)
You said:
lorsqu'un changement est effectuer ,Un joueur Actif  remplacé car blessure IR, pour qu'un joueur des mineurs rejoigne le grand club prends 3 jours donc on fait le changement aujourd'hui, il sera de l'alignement le 7 janvier 

Lorsqu'un changement est effectué a cause d'un joueur Actif blessé, si c'est un joueur du banc qui rejoint le Grand Club, c'est une journée donc le changement devient effectif le 5 janvier.

Le moment qu'un joueur blessé est de retour, le remplacent retourne ou il était.

Le changement qui est effectuer doit respecter le plafond salariale du Grand Club
ChatGPT said:

Thought for a couple of seconds
Parfait — tu viens de décrire un vrai moteur de transactions avec délais + remplacement temporaire + plafond. On peut l’implémenter proprement dans ton app actuelle en ajoutant une couche “Transaction en attente” au lieu de déplacer immédiatement les joueurs.
Voici comment je le ferais (clair, testable, et compatible avec ton code).

1) Règles que j’implémente (selon ton message)
A) Quand un Actif devient IR (blessé)
Tu choisis un remplaçant qui va devenir Actif GC, mais avec délai selon sa provenance :
Remplaçant vient des Mineurs (CE → GC Actif)
✅ délai 3 jours → effectif à today + 3 jours
Ex: changement fait le 4 janv → effectif le 7 janv
Remplaçant vient du Banc (GC Banc → GC Actif)
✅ délai 1 jour → effectif à today + 1 jour
Ex: changement fait le 4 janv → effectif le 5 janv
Important : l’IR du joueur blessé peut être immédiat (ou aussi planifié, mais généralement IR c’est immédiat). La partie “remplacement” est ce qui est delayed.
B) Quand le joueur blessé revient
✅ le remplaçant retourne automatiquement où il était (Banc ou Mineur), et le joueur original redevient Actif (souvent immédiat, ou tu peux aussi ajouter un délai si tu veux).
C) Plafond salarial GC
✅ À la date effective, l’alignement doit respecter le plafond GC (en excluant IR comme tu fais déjà).
2) Comment on le modélise dans l’app (simple)
Au lieu de faire apply_move_with_history() qui modifie tout de suite Statut/Slot, on crée des “transactions en attente”.
Nouveau state
st.session_state["pending_moves"] : DataFrame ou liste de dicts
Chaque transaction contient :
id
created_at
effective_at (date/heure)
owner
player
from_statut/from_slot
to_statut/to_slot
reason (ex: IR_REPLACEMENT)
link_id (pour lier blessé + remplaçant)
revert_to_statut/revert_to_slot (où retourner quand le blessé revient)
3) Le comportement UX que je recommande (intuitif)
Quand tu cliques un joueur Actif → “🩹 Blessé”
Tu le mets IR (immédiat) ✅
Un 2e écran te demande : “Choisir un remplaçant”
liste Banc + Mineurs
Tu sélectionnes un joueur :
si Banc → effective demain
si Mineur → effective +3 jours
Tu vois un message :
“Remplacement planifié : effectif le 7 janvier”
Le roster affiche le remplaçant en statut “⏳ En attente” jusqu’à la date.
4) Ce qu’il faut ajouter dans TON code (blocs prêts)
A) Utilitaire dates + délai
Ajoute ça une fois :
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Toronto")

def now_tor():
    return datetime.now(TZ)

def add_days_effective(days: int) -> datetime:
    # effectif à 00:00 du jour cible (ou même heure que maintenant — à toi)
    dt = now_tor() + timedelta(days=days)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)
B) Queue pending moves (stockage)
Ajoute :
def pending_init():
    if "pending_moves" not in st.session_state:
        st.session_state["pending_moves"] = pd.DataFrame(columns=[
            "id","created_at","effective_at","owner","player",
            "from_statut","from_slot","to_statut","to_slot",
            "reason","link_id","revert_to_statut","revert_to_slot","status"
        ])

def pending_next_id(p: pd.DataFrame) -> int:
    if p is None or p.empty: 
        return 1
    return int(pd.to_numeric(p["id"], errors="coerce").fillna(0).max()) + 1

def pending_add(row: dict):
    pending_init()
    p = st.session_state["pending_moves"].copy()
    row["id"] = pending_next_id(p)
    p = pd.concat([p, pd.DataFrame([row])], ignore_index=True)
    st.session_state["pending_moves"] = p
C) Vérification plafond “à la date effective”
On simule l’alignement futur en appliquant le move puis on calcule :
def gc_cap_ok_after_move(df: pd.DataFrame, owner: str, apply_changes: list[dict]) -> tuple[bool, str]:
    """
    apply_changes = [{player, to_statut, to_slot}, ...]
    Simule et vérifie plafond GC (IR exclu comme dans ton code).
    """
    df2 = clean_data(df.copy())
    owner = str(owner).strip()

    for ch in apply_changes:
        player = str(ch["player"]).strip()
        mask = (df2["Propriétaire"].astype(str).str.strip()==owner) & (df2["Joueur"].astype(str).str.strip()==player)
        if df2.loc[mask].empty:
            continue
        df2.loc[mask, "Statut"] = str(ch["to_statut"])
        df2.loc[mask, "Slot"] = str(ch["to_slot"])

    d = df2[df2["Propriétaire"].astype(str)==owner].copy()
    used_gc = int(d[(d["Statut"]=="Grand Club") & (d["Slot"]!="Blessé")]["Salaire"].sum())
    cap_gc = int(st.session_state.get("PLAFOND_GC", 0) or 0)
    if used_gc > cap_gc:
        return (False, f"🚨 Plafond GC dépassé: {money(used_gc)} / {money(cap_gc)}")
    return (True, "")
D) Process automatique : appliquer les transactions arrivées à échéance
À la fin de ton app (là où tu flush Drive), ajoute :
def process_pending_moves():
    pending_init()
    p = st.session_state["pending_moves"]
    if p.empty:
        return

    df = st.session_state.get("data")
    df = clean_data(df) if isinstance(df, pd.DataFrame) else pd.DataFrame(columns=REQUIRED_COLS)

    now = now_tor()
    changed = False

    # moves prêts à appliquer
    ready = p[(p["status"]!="APPLIED") & (pd.to_datetime(p["effective_at"], errors="coerce") <= now)].copy()
    if ready.empty:
        return

    for _, mv in ready.iterrows():
        owner = str(mv["owner"]).strip()
        player = str(mv["player"]).strip()
        to_statut = str(mv["to_statut"]).strip()
        to_slot = str(mv["to_slot"]).strip()

        # Vérif plafond au moment d'appliquer (sécuritaire)
        ok, msg = gc_cap_ok_after_move(df, owner, [{"player": player, "to_statut": to_statut, "to_slot": to_slot}])
        if not ok:
            # on marque refused (tu peux aussi laisser pending)
            p.loc[p["id"]==mv["id"], "status"] = "REFUSED_CAP"
            p.loc[p["id"]==mv["id"], "reason"] = str(mv.get("reason","")) + " | " + msg
            continue

        # appliquer vraiment
        mask = (df["Propriétaire"].astype(str).str.strip()==owner) & (df["Joueur"].astype(str).str.strip()==player)
        if not df.loc[mask].empty:
            df.loc[mask, "Statut"] = to_statut
            df.loc[mask, "Slot"] = to_slot
            changed = True

        p.loc[p["id"]==mv["id"], "status"] = "APPLIED"

        # log history
        try:
            before = st.session_state["data"].loc[mask].iloc[0] if not st.session_state["data"].loc[mask].empty else {}
            log_history_row(owner, player, str(before.get("Pos","")), str(before.get("Equipe","")),
                            str(mv["from_statut"]), str(mv["from_slot"]),
                            to_statut, to_slot,
                            action=f"PENDING_APPLIED #{int(mv['id'])}")
        except Exception:
            pass

    if changed:
        df = clean_data(df)
        st.session_state["data"] = df
        season_lbl = str(st.session_state.get("season","")).strip()
        persist_data(df, season_lbl)
        h = st.session_state.get("history")
        if isinstance(h, pd.DataFrame):
            persist_history(h, season_lbl)

    st.session_state["pending_moves"] = p
Puis tu appelles :
process_pending_moves()
juste avant ton flush_drive_queue(...).
5) Comment gérer le “remplaçant retourne où il était”
Quand tu crées un remplacement suite à IR, tu sauvegardes où était le remplaçant:
revert_to_statut
revert_to_slot
link_id commun avec le joueur blessé
Ensuite, quand tu “retournes” le blessé Actif (sortie IR), tu crées aussi un pending (ou immédiat) pour renvoyer le remplaçant à son ancienne place.
➡️ Ça se fait avec un couple de transactions liées :

link_id = "IRCASE-<timestamp>-<owner>"
6) Où brancher ça dans ton flux existant (le plus simple)
Tu n’as pas besoin de tout refaire.
Option minimaliste (rapide)
Tu gardes ton dialog actuel
Quand tu fais un move “Mineur → Actif”, au lieu d’appeler apply_move_with_history():
tu crées un pending avec effective_at = now + 3j
Quand “Banc → Actif”:
pending = now + 1j
Les autres moves (Actif ↔ Banc, IR, etc.) peuvent rester immédiats si tu veux.
7) Il me manque 1 détail (mais je fais une hypothèse si tu veux)
Tu dis : “quand un joueur blessé est de retour”.
Est-ce que tu veux :
A) Un bouton “✅ De retour” sur un joueur IR (qui déclenche retour + revert du remplaçant)
ou
B) Tu importes une liste “injury status” et on auto-détecte?

👉 Je te recommande A (simple, contrôle total).

8) Ce que je te propose maintenant (prochaine réponse)
Je peux te donner le bloc exact à coller dans ton open_move_dialog() pour gérer le cas IR comme tu veux :
Quand tu places quelqu’un sur IR → pop “Choisir remplaçant”
Calcul automatique de la date effective (1j banc / 3j mineur)
Vérif plafond au moment de planifier et au moment d’appliquer
Enregistrement dans un nouveau onglet ⏳ Transactions en attente (super utile)
Si tu veux que je te le livre en mode “copier-coller”, dis-moi juste :
Les délais sont-ils exactement 3 jours / 1 jour (jours calendaires) ?
L’heure effective : à minuit du jour effectif, ou même heure + délai ?
(Si tu ne réponds pas, je pars sur minuit America/Toronto, c’est le plus clair pour une ligue.)
You said:
2) ce n'est pas une transaction mais bien un remplacement d'un joueur blessé
ChatGPT said:
Parfait — ce n’est pas une transaction, c’est un REMPLACEMENT TEMPORAIRE (IR Replacement).
Donc on va le modéliser comme un cas de remplacement (avec délai), pas comme un échange/transaction.
Voici la version “propre” des règles + comment je l’implémente dans ton app.

✅ Concept: “Cas de remplacement IR”
Quand un joueur Actif GC tombe IR :
Le blessé passe IR tout de suite (Slot = Blessé)
Tu choisis un remplaçant
Le remplaçant devient Actif GC, mais effectif avec délai :
vient du Banc → +1 jour
vient des Mineurs (CE) → +3 jours
Quand le blessé revient, le remplaçant retourne automatiquement à sa place d’origine (Banc ou Mineurs), et le blessé redevient Actif.
À la date effective, le plafond GC doit être respecté (IR exclu, comme tu fais déjà).
👉 Ça ressemble à une “transaction”, mais c’est mécaniquement un remplacement lié, temporaire, avec auto-retour.
🧠 Comment je le stocke (sans parler de “transactions”)
On ajoute un objet replacement_cases en session (et optionnellement en CSV/Drive), contenant :
case_id
owner
injured_player
replacement_player
replacement_from = "BANC" ou "MINEUR"
created_at
effective_at
status = PENDING / ACTIVE / CLOSED
replacement_revert_to_statut/slot (où il doit retourner)
(optionnel) note, closed_at
Ce n’est pas un historique : c’est l’état “cas en cours”.
🔧 Fonctionnement concret dans ton app (simple)
A) Quand tu mets un Actif sur IR
Ton open_move_dialog() fait :
apply_move_with_history(owner, joueur, "Grand Club", "Blessé", "...") immédiat
ensuite ouvre un petit panneau “Choisir remplaçant”
quand tu choisis :
on ne bouge pas le remplaçant tout de suite
on crée un replacement_case avec effective_at calculé
B) À chaque rerun (en bas du app.py)
On appelle un “processor” :
si effective_at <= now et status PENDING → on applique le move du remplaçant vers GC Actif (si plafond OK) et status devient ACTIVE
quand tu cliques “✅ De retour” sur le blessé (dans IR), ça “ferme” le cas :
blessé → Actif (immédiat)
remplaçant → retourne à son ancien slot/statut (immédiat)
status CLOSED
💰 Plafond GC
Important : le plafond doit être respecté au moment où le remplacement devient effectif.
Donc on vérifie :

total GC (hors IR) après activation du remplaçant
si dépassement :
soit on bloque l’activation (REFUSED_CAP)
soit on met une alerte et on laisse “PENDING” (mais perso je préfère bloquer proprement)
✨ UX recommandé (clair pour toi)
Dans l’expander 🩹 Joueurs Blessés (IR) :
chaque blessé affiche :
s’il a un remplacement PENDING : “⏳ Remplacement effectif le 7 jan”
s’il a un remplacement ACTIVE : “✅ Remplacé par X”
bouton ✅ De retour (qui auto-réverse le remplaçant)
Ce que je te propose maintenant (livrable copier-coller)
Je te donne :
Le bloc replacement_cases (init + save/load optionnel)
create_replacement_case()
process_replacements() (applique automatiquement quand la date arrive)
Un mini UI dans l’expander IR pour ✅ De retour + statut du remplacement
La vérif plafond GC au moment de l’activation
Je pars sur ton exemple : changement fait 4 janvier → mineur effectif 7 janvier (donc délai = 3 jours calendaires). Et en America/Toronto.
Dis-moi juste une chose (et je tranche sans te re-questionner après) :

l’activation est à minuit du jour effectif (00:00), ou à l’heure exacte du changement + délai?
Si tu ne veux pas répondre : je mets minuit (le plus clair en pool).
You said:
si tu es capable de garder le logo_pool et le sidebar tel quel avec un look and feel mais avec les nouvelles fonctionnalité... Go
ChatGPT said:

Thought for 20s
Go. Je garde logo_pool + ton sidebar + ton look & feel intacts ✅
Je rajoute uniquement ce qu’il faut pour gérer le remplacement IR avec délais + retour automatique + plafond GC.
Je pars sur cette règle (sans te re-questionner) :

Banc → Actif : effectif +1 jour (à minuit America/Toronto)
Mineur → Actif : effectif +3 jours (à minuit America/Toronto)
✅ Ce que ça ajoute (sans casser ton UI)
Dans 🧾 Alignement → 🩹 Joueurs Blessés (IR) :
Pour chaque blessé, on affiche :
⏳ Remplacement planifié (date effective)
✅ Remplacement actif
❌ Remplacement refusé (plafond dépassé)
Bouton ✅ De retour :
remet le blessé Actif
remet le remplaçant exactement où il était (Banc ou Mineur)
ferme le cas
Et côté action :
Quand tu mets un Actif sur IR, l’app ouvre un popup “Choisir remplaçant”
tu choisis un joueur du Banc ou des Mineurs
l’app crée un case de remplacement (pas une transaction)
le remplaçant devient Actif quand la date arrive (auto)
1) COLLE CE BLOC (nouveau) après tes helpers (ex: après persist_history)
Bloc complet “REMPLACEMENTS IR” à ajouter tel quel.
# =====================================================
# 🩹 REMPLACEMENTS IR (avec délai + retour auto + plafond GC)
# =====================================================
from datetime import timedelta

TZ = ZoneInfo("America/Toronto")

def now_tor() -> datetime:
    return datetime.now(TZ)

def effective_midnight_in(days: int) -> str:
    dt = now_tor() + timedelta(days=int(days))
    dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return dt.isoformat(timespec="seconds")

def _repl_file(season: str) -> str:
    return os.path.join(DATA_DIR, f"replacements_{season}.csv")

def replacements_init(season: str):
    if "replacements_season" not in st.session_state or st.session_state["replacements_season"] != season:
        path = _repl_file(season)
        st.session_state["REPLACEMENTS_FILE"] = path

        cols = [
            "case_id", "season", "owner",
            "injured_player", "injured_pos", "injured_team",
            "replacement_player", "replacement_from",
            "created_at", "effective_at",
            "status",  # PENDING / ACTIVE / CLOSED / REFUSED_CAP / CANCELLED
            "repl_revert_statut", "repl_revert_slot",
            "note", "closed_at"
        ]

        df_cases = pd.DataFrame(columns=cols)

        # Load local
        if os.path.exists(path):
            try:
                df_cases = pd.read_csv(path)
            except Exception:
                df_cases = pd.DataFrame(columns=cols)

        # Normalize columns
        for c in cols:
            if c not in df_cases.columns:
                df_cases[c] = ""

        st.session_state["replacements"] = df_cases
        st.session_state["replacements_season"] = season

def replacements_save(season: str):
    df_cases = st.session_state.get("replacements")
    if not isinstance(df_cases, pd.DataFrame):
        return

    path = st.session_state.get("REPLACEMENTS_FILE", _repl_file(season))
    try:
        df_cases.to_csv(path, index=False)
    except Exception:
        pass

    # Drive batch (optionnel)
    if "_drive_enabled" in globals() and _drive_enabled():
        try:
            queue_drive_save_df(df_cases, f"replacements_{season}.csv")
        except Exception:
            pass

def replacements_next_id(df_cases: pd.DataFrame) -> int:
    if df_cases is None or df_cases.empty or "case_id" not in df_cases.columns:
        return 1
    return int(pd.to_numeric(df_cases["case_id"], errors="coerce").fillna(0).max()) + 1

def gc_used(owner: str, df: pd.DataFrame) -> int:
    owner = str(owner).strip()
    d = df[df["Propriétaire"].astype(str).str.strip().eq(owner)].copy()
    return int(d[(d["Statut"] == "Grand Club") & (d["Slot"] != "Blessé")]["Salaire"].sum())

def cap_ok_for_owner(owner: str, df_after: pd.DataFrame) -> tuple[bool, str]:
    used = gc_used(owner, df_after)
    cap = int(st.session_state.get("PLAFOND_GC", 0) or 0)
    if used > cap:
        return False, f"🚨 Plafond GC dépassé: {money(used)} / {money(cap)}"
    return True, ""

def find_active_case(df_cases: pd.DataFrame, owner: str, injured_player: str) -> pd.Series | None:
    if df_cases is None or df_cases.empty:
        return None
    owner = str(owner).strip()
    injured_player = str(injured_player).strip()
    sub = df_cases[
        (df_cases["owner"].astype(str).str.strip() == owner) &
        (df_cases["injured_player"].astype(str).str.strip() == injured_player) &
        (df_cases["status"].astype(str).isin(["PENDING", "ACTIVE", "REFUSED_CAP"]))
    ]
    if sub.empty:
        return None
    # dernier case
    return sub.tail(1).iloc[0]

def create_replacement_case(owner: str, injured_player: str, replacement_player: str, replacement_from: str):
    season = str(st.session_state.get("season", "")).strip()
    replacements_init(season)

    df = st.session_state.get("data")
    df = clean_data(df) if isinstance(df, pd.DataFrame) else pd.DataFrame(columns=REQUIRED_COLS)

    owner = str(owner).strip()
    injured_player = str(injured_player).strip()
    replacement_player = str(replacement_player).strip()
    replacement_from = str(replacement_from).strip().upper()  # BANC / MINEUR

    # Lookup injured + replacement rows
    m_inj = (df["Propriétaire"].astype(str).str.strip().eq(owner)) & (df["Joueur"].astype(str).str.strip().eq(injured_player))
    m_rep = (df["Propriétaire"].astype(str).str.strip().eq(owner)) & (df["Joueur"].astype(str).str.strip().eq(replacement_player))

    if df.loc[m_inj].empty or df.loc[m_rep].empty:
        st.session_state["last_replace_error"] = "Joueur introuvable (blessé ou remplaçant)."
        return False

    inj = df.loc[m_inj].iloc[0]
    rep = df.loc[m_rep].iloc[0]

    # Injured must be IR
    if str(inj.get("Slot", "")).strip() != "Blessé":
        st.session_state["last_replace_error"] = "Le joueur blessé n'est pas sur IR."
        return False

    # Replacement origin determines delay
    delay_days = 1 if replacement_from == "BANC" else 3
    eff_at = effective_midnight_in(delay_days)

    # Where replacement must return later
    revert_statut = str(rep.get("Statut", "")).strip()
    revert_slot = str(rep.get("Slot", "")).strip()

    # Build case
    cases = st.session_state["replacements"].copy()
    case_id = replacements_next_id(cases)

    row = {
        "case_id": int(case_id),
        "season": season,
        "owner": owner,
        "injured_player": injured_player,
        "injured_pos": str(inj.get("Pos", "")),
        "injured_team": str(inj.get("Equipe", "")),
        "replacement_player": replacement_player,
        "replacement_from": replacement_from,  # BANC / MINEUR
        "created_at": now_tor().isoformat(timespec="seconds"),
        "effective_at": eff_at,
        "status": "PENDING",
        "repl_revert_statut": revert_statut,
        "repl_revert_slot": revert_slot,
        "note": "",
        "closed_at": "",
    }

    cases = pd.concat([cases, pd.DataFrame([row])], ignore_index=True)
    st.session_state["replacements"] = cases
    replacements_save(season)

    # History trace
    try:
        history_add(
            action="IR_REPLACEMENT_PLANNED",
            owner=owner,
            player=injured_player,
            details=f"Remplaçant: {replacement_player} ({replacement_from}) | effectif: {eff_at}",
        )
    except Exception:
        pass

    return True

def process_replacements():
    season = str(st.session_state.get("season", "")).strip()
    replacements_init(season)

    cases = st.session_state.get("replacements")
    if not isinstance(cases, pd.DataFrame) or cases.empty:
        return

    df = st.session_state.get("data")
    df = clean_data(df) if isinstance(df, pd.DataFrame) else pd.DataFrame(columns=REQUIRED_COLS)

    now = now_tor()
    changed = False

    # pending ready
    eff_dt = pd.to_datetime(cases["effective_at"], errors="coerce")
    ready = cases[
        (cases["status"].astype(str) == "PENDING") &
        (eff_dt.notna()) &
        (eff_dt <= now)
    ].copy()

    if ready.empty:
        return

    for _, r in ready.iterrows():
        owner = str(r["owner"]).strip()
        injured = str(r["injured_player"]).strip()
        repl = str(r["replacement_player"]).strip()

        # If injured not IR anymore -> cancel
        m_inj = (df["Propriétaire"].astype(str).str.strip().eq(owner)) & (df["Joueur"].astype(str).str.strip().eq(injured))
        if df.loc[m_inj].empty or str(df.loc[m_inj].iloc[0].get("Slot","")).strip() != "Blessé":
            cases.loc[cases["case_id"] == r["case_id"], "status"] = "CANCELLED"
            continue

        # Apply replacement -> GC Actif
        m_rep = (df["Propriétaire"].astype(str).str.strip().eq(owner)) & (df["Joueur"].astype(str).str.strip().eq(repl))
        if df.loc[m_rep].empty:
            cases.loc[cases["case_id"] == r["case_id"], "status"] = "CANCELLED"
            continue

        df2 = df.copy()
        df2.loc[m_rep, "Statut"] = "Grand Club"
        df2.loc[m_rep, "Slot"] = "Actif"
        df2 = clean_data(df2)

        ok, msg = cap_ok_for_owner(owner, df2)
        if not ok:
            cases.loc[cases["case_id"] == r["case_id"], "status"] = "REFUSED_CAP"
            cases.loc[cases["case_id"] == r["case_id"], "note"] = msg
            continue

        df = df2
        changed = True
        cases.loc[cases["case_id"] == r["case_id"], "status"] = "ACTIVE"

        try:
            history_add(
                action="IR_REPLACEMENT_ACTIVE",
                owner=owner,
                player=repl,
                details=f"Remplacement actif (case #{int(r['case_id'])}) pour {injured}",
            )
        except Exception:
            pass

    if changed:
        st.session_state["data"] = df
        persist_data(df, season)

    st.session_state["replacements"] = cases
    replacements_save(season)

def close_replacement_case(case_id: int, note: str = ""):
    season = str(st.session_state.get("season", "")).strip()
    replacements_init(season)

    cases = st.session_state.get("replacements")
    if not isinstance(cases, pd.DataFrame) or cases.empty:
        return

    m = cases["case_id"].astype(str) == str(case_id)
    if not m.any():
        return

    cases.loc[m, "status"] = "CLOSED"
    cases.loc[m, "closed_at"] = now_tor().isoformat(timespec="seconds")
    if note:
        cases.loc[m, "note"] = str(note)

    st.session_state["replacements"] = cases
    replacements_save(season)
2) AJOUTE UN CTX POUR LE POPUP “CHOISIR REMPLAÇANT”
Ajoute dans tes SESSION DEFAULTS (avec tes autres move_ctx):
# replacement dialog ctx
if "replace_ctx" not in st.session_state:
    st.session_state["replace_ctx"] = None
if "replace_nonce" not in st.session_state:
    st.session_state["replace_nonce"] = 0
if "last_replace_error" not in st.session_state:
    st.session_state["last_replace_error"] = ""
Ajoute aussi ces helpers (n’importe où avec tes helpers):
def set_replace_ctx(owner: str, injured_player: str):
    st.session_state["replace_nonce"] = st.session_state.get("replace_nonce", 0) + 1
    st.session_state["replace_ctx"] = {
        "owner": str(owner).strip(),
        "injured_player": str(injured_player).strip(),
        "nonce": st.session_state["replace_nonce"],
    }

def clear_replace_ctx():
    st.session_state["replace_ctx"] = None
3) AJOUTE LE POPUP “CHOISIR REMPLAÇANT”
Colle ce bloc après open_move_dialog() (même section):
def open_replacement_dialog():
    ctx = st.session_state.get("replace_ctx")
    if not ctx:
        return

    owner = str(ctx.get("owner","")).strip()
    injured = str(ctx.get("injured_player","")).strip()
    nonce = int(ctx.get("nonce", 0))

    df = st.session_state.get("data")
    df = clean_data(df) if isinstance(df, pd.DataFrame) else pd.DataFrame(columns=REQUIRED_COLS)

    dprop = df[df["Propriétaire"].astype(str).str.strip().eq(owner)].copy()
    if dprop.empty:
        clear_replace_ctx()
        return

    # candidates: banc + mineur (exclude IR)
    banc = dprop[(dprop["Statut"]=="Grand Club") & (dprop["Slot"]=="Banc")].copy()
    mineur = dprop[(dprop["Statut"]=="Club École") & (dprop["Slot"]!="Blessé")].copy()

    banc = banc[banc["Joueur"].astype(str).str.strip().ne(injured)]
    mineur = mineur[mineur["Joueur"].astype(str).str.strip().ne(injured)]

    @st.dialog(f"Remplacement IR — {injured}", width="large")
    def _dlg():
        st.caption("Choisis un remplaçant. Le délai dépend de la provenance : Banc=+1 jour, Mineur=+3 jours (effectif à minuit).")

        if st.session_state.get("last_replace_error"):
            st.error(st.session_state["last_replace_error"])

        c1, c2 = st.columns(2)

        with c1:
            st.markdown("### 🟡 Candidats — Banc (effectif +1 jour)")
            if banc.empty:
                st.info("Aucun candidat sur le banc.")
            else:
                # UI simple (selectbox) pour éviter trop de boutons
                options = banc["Joueur"].astype(str).tolist()
                pick = st.selectbox("Joueur (Banc)", ["—"] + options, key=f"repl_pick_banc_{owner}_{nonce}")
                if st.button("✅ Planifier depuis Banc", type="primary", use_container_width=True, key=f"repl_ok_banc_{owner}_{nonce}", disabled=(pick=="—")):
                    st.session_state["last_replace_error"] = ""
                    ok = create_replacement_case(owner, injured, pick, "BANC")
                    if ok:
                        st.toast(f"⏳ Remplacement planifié (Banc) — effectif demain", icon="⏳")
                        clear_replace_ctx(); do_rerun()
                    else:
                        st.error(st.session_state.get("last_replace_error") or "Impossible de planifier.")

        with c2:
            st.markdown("### 🔵 Candidats — Mineur (effectif +3 jours)")
            if mineur.empty:
                st.info("Aucun candidat dans les mineurs.")
            else:
                options = mineur["Joueur"].astype(str).tolist()
                pick = st.selectbox("Joueur (Mineur)", ["—"] + options, key=f"repl_pick_min_{owner}_{nonce}")
                if st.button("✅ Planifier depuis Mineur", type="primary", use_container_width=True, key=f"repl_ok_min_{owner}_{nonce}", disabled=(pick=="—")):
                    st.session_state["last_replace_error"] = ""
                    ok = create_replacement_case(owner, injured, pick, "MINEUR")
                    if ok:
                        st.toast(f"⏳ Remplacement planifié (Mineur) — effectif dans 3 jours", icon="⏳")
                        clear_replace_ctx(); do_rerun()
                    else:
                        st.error(st.session_state.get("last_replace_error") or "Impossible de planifier.")

        st.divider()
        if st.button("✖️ Annuler", use_container_width=True, key=f"repl_cancel_{owner}_{nonce}"):
            clear_replace_ctx(); do_rerun()

    _dlg()
4) MODIFIE open_move_dialog() pour déclencher le remplacement quand on met un Actif sur IR
Dans ton bloc Mode normal (où tu as le choix “🩹 Blessé (IR)”), on change uniquement l’action Confirmer :
Trouve ce bloc :

if c1.button("✅ Confirmer", type="primary", use_container_width=True, key=f"ok_{owner}_{joueur}_{nonce}"):
    ok = apply_move_with_history(...)
    ...
Remplace-le par ceci :
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

        # ✅ Si on vient de mettre un ACTIF GC sur IR -> ouvrir le popup remplacement
        if (cur_statut == "Grand Club") and (cur_slot == "Actif") and (to_slot == "Blessé"):
            # on ouvre le popup choix remplaçant
            set_replace_ctx(owner, joueur)

        _close(); do_rerun()
    else:
        st.error(st.session_state.get("last_move_error") or "Déplacement refusé.")
✅ Résultat : quand tu places un Actif sur IR, ça enchaîne automatiquement sur “Choisir remplaçant”.
5) AJOUTE l’affichage + bouton “✅ De retour” dans l’expander IR (dans TAB Alignement)
Dans ton with st.expander("🩹 Joueurs Blessés (IR)", expanded=True):
Ajoute juste avant roster_click_list(...) ce bloc :
# --- Statut remplacement IR (par blessé)
season_lbl = str(st.session_state.get("season","")).strip()
replacements_init(season_lbl)
cases = st.session_state.get("replacements")
cases = cases.copy() if isinstance(cases, pd.DataFrame) else pd.DataFrame()

# small helper
def _case_line(owner: str, injured_player: str):
    if cases is None or cases.empty:
        return None
    r = find_active_case(cases, owner, injured_player)
    return r

# Liste IR avec info remplacement + bouton retour
for j in injured_all["Joueur"].astype(str).tolist():
    rcase = _case_line(proprietaire, j)
    if rcase is None:
        continue

    status = str(rcase.get("status","")).strip()
    eff = str(rcase.get("effective_at","")).strip()
    repl = str(rcase.get("replacement_player","")).strip()
    note = str(rcase.get("note","")).strip()
    cid = int(pd.to_numeric(rcase.get("case_id", 0), errors="coerce") or 0)

    if status == "PENDING":
        st.caption(f"⏳ Remplacement planifié : **{repl}** — effectif **{eff}**")
    elif status == "ACTIVE":
        st.caption(f"✅ Remplacement actif : **{repl}** (case #{cid})")
    elif status == "REFUSED_CAP":
        st.caption(f"❌ Remplacement refusé (plafond) : **{repl}** — {note}")

    # Bouton De retour (ferme le cas + revert remplaçant)
    if st.button(f"✅ De retour — {j}", use_container_width=True, key=f"inj_return_{proprietaire}_{j}_{cid}"):
        if st.session_state.get("LOCKED"):
            st.error("🔒 Saison verrouillée : changement impossible.")
        else:
            df_all = st.session_state.get("data")
            df_all = clean_data(df_all) if isinstance(df_all, pd.DataFrame) else pd.DataFrame(columns=REQUIRED_COLS)

            # 1) blessé -> Actif GC
            apply_move_with_history(proprietaire, j, "Grand Club", "Actif", "IR → Actif (Retour)")

            # 2) revert remplaçant seulement si ACTIVE (si PENDING, on annule)
            if status == "ACTIVE":
                rev_statut = str(rcase.get("repl_revert_statut","")).strip()
                rev_slot = str(rcase.get("repl_revert_slot","")).strip()
                # si remplaçant venait des mineurs, rev_slot = "" (par exemple)
                apply_move_with_history(proprietaire, repl, rev_statut, rev_slot, f"REVERT → {rev_statut}/{rev_slot or '-'}")

            # 3) fermer case
            close_replacement_case(cid, note="Injured returned")

            st.toast("✅ Retour effectué (blessé + revert remplaçant)", icon="✅")
            do_rerun()
👉 Ça n’altère pas ton UI : ça ajoute juste une ligne d’info + un bouton.
6) APPEL AUTO du “processor” (activation automatique à la date)
Tout en bas de ton app (juste avant ton flush Drive), ajoute :
# ✅ Active automatiquement les remplacements arrivés à échéance
process_replacements()
Et tu peux garder ton flush_drive_queue(...) tel quel.
Ce que tu obtiens immédiatement
Remplacement IR planifié (banc +1 jour / mineur +3 jours)
Activation automatique à la date
Si plafond GC dépassé à l’activation → refusé (et affiché)
Quand le blessé revient → auto-revert du remplaçant à son spot d’origine
Si tu veux, prochaine étape (sans toucher au look) :
afficher dans 📊 Tableau les points “actuels” vs “effectifs au 7 janvier” (projection)
ajouter une petite pastille “⏳” sur le remplaçant dans les listes (Actifs/Mineur) tant qu’il est PENDING
Dis-moi juste : tu veux qu’un remplaçant PENDING apparaisse déjà dans les Actifs (avec badge ⏳), ou seulement quand il devient effectif?
You said:
je met le bloc remplacement après le bloc Alignement?
ChatGPT said:
Oui — mais précisément voici la règle à suivre pour éviter toute erreur 👇
👉 NON, pas après le bloc Alignement (UI).
👉 OUI, avant les tabs / UI.
✅ Emplacement CORRECT (important)
Le bloc Remplacements IR doit être placé :
📍 APRÈS
tous tes helpers / persistence
persist_data
persist_history
clean_data
apply_move_with_history
📍 AVANT
st.tabs(...)
TAB Alignement
open_move_dialog()
toute logique UI
🔧 Concrètement dans ton app.py
Cherche ce commentaire (chez toi il existe) :
# =====================================================
# APPLY MOVE (avec IR Date) + PERSIST (local + Drive)
# =====================================================
def apply_move_with_history(...):
    ...
⬇️ JUSTE APRÈS la fin de cette fonction, colle :
# =====================================================
# 🩹 REMPLACEMENTS IR (avec délai + retour auto + plafond GC)
# =====================================================
# ⬅️ COLLER ICI
Puis plus bas, après ta fonction open_move_dialog() (toujours AVANT les tabs) tu ajoutes :
open_replacement_dialog()
❌ Où il ne faut PAS le mettre
Ne mets PAS :
après with tabA: (Alignement)
dans un with tab...
après st.tabs(...)
Sinon :
le popup ne s’ouvrira pas
les remplacements ne s’activeront pas automatiquement
tu risques des NameError ou des reruns infinis
🧠 Pourquoi c’est critique
Les remplacements sont de la logique métier
L’Alignement est seulement une vue
Streamlit ré-exécute le script de haut en bas → les fonctions doivent exister avant d’être appelées
✅ Checklist rapide
Tu es bon si :
 Bloc Remplacements IR est avant st.tabs(...)
 process_replacements() est appelé tout en bas
 open_replacement_dialog() est appelé après open_move_dialog()
 Aucun st.stop() n’est déclenché avant ces appels
Si tu veux, envoie-moi juste la portion de ton fichier autour de
apply_move_with_history() et je te dis exactement où coller, ligne par ligne 👍
You said:
est ce correct?
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

# =====================================================
# 🩹 REMPLACEMENTS IR (avec délai + retour auto + plafond GC)
# =====================================================
from datetime import timedelta

TZ = ZoneInfo("America/Toronto")

def now_tor() -> datetime:
    return datetime.now(TZ)

def effective_midnight_in(days: int) -> str:
    dt = now_tor() + timedelta(days=int(days))
    dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return dt.isoformat(timespec="seconds")

def _repl_file(season: str) -> str:
    return os.path.join(DATA_DIR, f"replacements_{season}.csv")

def replacements_init(season: str):
    if "replacements_season" not in st.session_state or st.session_state["replacements_season"] != season:
        path = _repl_file(season)
        st.session_state["REPLACEMENTS_FILE"] = path

        cols = [
            "case_id", "season", "owner",
            "injured_player", "injured_pos", "injured_team",
            "replacement_player", "replacement_from",
            "created_at", "effective_at",
            "status",  # PENDING / ACTIVE / CLOSED / REFUSED_CAP / CANCELLED
            "repl_revert_statut", "repl_revert_slot",
            "note", "closed_at"
        ]

        df_cases = pd.DataFrame(columns=cols)

        # Load local
        if os.path.exists(path):
            try:
                df_cases = pd.read_csv(path)
            except Exception:
                df_cases = pd.DataFrame(columns=cols)

        # Normalize columns
        for c in cols:
            if c not in df_cases.columns:
                df_cases[c] = ""

        st.session_state["replacements"] = df_cases
        st.session_state["replacements_season"] = season

def replacements_save(season: str):
    df_cases = st.session_state.get("replacements")
    if not isinstance(df_cases, pd.DataFrame):
        return

    path = st.session_state.get("REPLACEMENTS_FILE", _repl_file(season))
    try:
        df_cases.to_csv(path, index=False)
    except Exception:
        pass

    # Drive batch (optionnel)
    if "_drive_enabled" in globals() and _drive_enabled():
        try:
            queue_drive_save_df(df_cases, f"replacements_{season}.csv")
        except Exception:
            pass

def replacements_next_id(df_cases: pd.DataFrame) -> int:
    if df_cases is None or df_cases.empty or "case_id" not in df_cases.columns:
        return 1
    return int(pd.to_numeric(df_cases["case_id"], errors="coerce").fillna(0).max()) + 1

def gc_used(owner: str, df: pd.DataFrame) -> int:
    owner = str(owner).strip()
    d = df[df["Propriétaire"].astype(str).str.strip().eq(owner)].copy()
    return int(d[(d["Statut"] == "Grand Club") & (d["Slot"] != "Blessé")]["Salaire"].sum())

def cap_ok_for_owner(owner: str, df_after: pd.DataFrame) -> tuple[bool, str]:
    used = gc_used(owner, df_after)
    cap = int(st.session_state.get("PLAFOND_GC", 0) or 0)
    if used > cap:
        return False, f"🚨 Plafond GC dépassé: {money(used)} / {money(cap)}"
    return True, ""

def find_active_case(df_cases: pd.DataFrame, owner: str, injured_player: str) -> pd.Series | None:
    if df_cases is None or df_cases.empty:
        return None
    owner = str(owner).strip()
    injured_player = str(injured_player).strip()
    sub = df_cases[
        (df_cases["owner"].astype(str).str.strip() == owner) &
        (df_cases["injured_player"].astype(str).str.strip() == injured_player) &
        (df_cases["status"].astype(str).isin(["PENDING", "ACTIVE", "REFUSED_CAP"]))
    ]
    if sub.empty:
        return None
    # dernier case
    return sub.tail(1).iloc[0]

def create_replacement_case(owner: str, injured_player: str, replacement_player: str, replacement_from: str):
    season = str(st.session_state.get("season", "")).strip()
    replacements_init(season)

    df = st.session_state.get("data")
    df = clean_data(df) if isinstance(df, pd.DataFrame) else pd.DataFrame(columns=REQUIRED_COLS)

    owner = str(owner).strip()
    injured_player = str(injured_player).strip()
    replacement_player = str(replacement_player).strip()
    replacement_from = str(replacement_from).strip().upper()  # BANC / MINEUR

    # Lookup injured + replacement rows
    m_inj = (df["Propriétaire"].astype(str).str.strip().eq(owner)) & (df["Joueur"].astype(str).str.strip().eq(injured_player))
    m_rep = (df["Propriétaire"].astype(str).str.strip().eq(owner)) & (df["Joueur"].astype(str).str.strip().eq(replacement_player))

    if df.loc[m_inj].empty or df.loc[m_rep].empty:
        st.session_state["last_replace_error"] = "Joueur introuvable (blessé ou remplaçant)."
        return False

    inj = df.loc[m_inj].iloc[0]
    rep = df.loc[m_rep].iloc[0]

    # Injured must be IR
    if str(inj.get("Slot", "")).strip() != "Blessé":
        st.session_state["last_replace_error"] = "Le joueur blessé n'est pas sur IR."
        return False

    # Replacement origin determines delay
    delay_days = 1 if replacement_from == "BANC" else 3
    eff_at = effective_midnight_in(delay_days)

    # Where replacement must return later
    revert_statut = str(rep.get("Statut", "")).strip()
    revert_slot = str(rep.get("Slot", "")).strip()

    # Build case
    cases = st.session_state["replacements"].copy()
    case_id = replacements_next_id(cases)

    row = {
        "case_id": int(case_id),
        "season": season,
        "owner": owner,
        "injured_player": injured_player,
        "injured_pos": str(inj.get("Pos", "")),
        "injured_team": str(inj.get("Equipe", "")),
        "replacement_player": replacement_player,
        "replacement_from": replacement_from,  # BANC / MINEUR
        "created_at": now_tor().isoformat(timespec="seconds"),
        "effective_at": eff_at,
        "status": "PENDING",
        "repl_revert_statut": revert_statut,
        "repl_revert_slot": revert_slot,
        "note": "",
        "closed_at": "",
    }

    cases = pd.concat([cases, pd.DataFrame([row])], ignore_index=True)
    st.session_state["replacements"] = cases
    replacements_save(season)

    # History trace
    try:
        history_add(
            action="IR_REPLACEMENT_PLANNED",
            owner=owner,
            player=injured_player,
            details=f"Remplaçant: {replacement_player} ({replacement_from}) | effectif: {eff_at}",
        )
    except Exception:
        pass

    return True

def process_replacements():
    season = str(st.session_state.get("season", "")).strip()
    replacements_init(season)

    cases = st.session_state.get("replacements")
    if not isinstance(cases, pd.DataFrame) or cases.empty:
        return

    df = st.session_state.get("data")
    df = clean_data(df) if isinstance(df, pd.DataFrame) else pd.DataFrame(columns=REQUIRED_COLS)

    now = now_tor()
    changed = False

    # pending ready
    eff_dt = pd.to_datetime(cases["effective_at"], errors="coerce")
    ready = cases[
        (cases["status"].astype(str) == "PENDING") &
        (eff_dt.notna()) &
        (eff_dt <= now)
    ].copy()

    if ready.empty:
        return

    for _, r in ready.iterrows():
        owner = str(r["owner"]).strip()
        injured = str(r["injured_player"]).strip()
        repl = str(r["replacement_player"]).strip()

        # If injured not IR anymore -> cancel
        m_inj = (df["Propriétaire"].astype(str).str.strip().eq(owner)) & (df["Joueur"].astype(str).str.strip().eq(injured))
        if df.loc[m_inj].empty or str(df.loc[m_inj].iloc[0].get("Slot","")).strip() != "Blessé":
            cases.loc[cases["case_id"] == r["case_id"], "status"] = "CANCELLED"
            continue

        # Apply replacement -> GC Actif
        m_rep = (df["Propriétaire"].astype(str).str.strip().eq(owner)) & (df["Joueur"].astype(str).str.strip().eq(repl))
        if df.loc[m_rep].empty:
            cases.loc[cases["case_id"] == r["case_id"], "status"] = "CANCELLED"
            continue

        df2 = df.copy()
        df2.loc[m_rep, "Statut"] = "Grand Club"
        df2.loc[m_rep, "Slot"] = "Actif"
        df2 = clean_data(df2)

        ok, msg = cap_ok_for_owner(owner, df2)
        if not ok:
            cases.loc[cases["case_id"] == r["case_id"], "status"] = "REFUSED_CAP"
            cases.loc[cases["case_id"] == r["case_id"], "note"] = msg
            continue

        df = df2
        changed = True
        cases.loc[cases["case_id"] == r["case_id"], "status"] = "ACTIVE"

        try:
            history_add(
                action="IR_REPLACEMENT_ACTIVE",
                owner=owner,
                player=repl,
                details=f"Remplacement actif (case #{int(r['case_id'])}) pour {injured}",
            )
        except Exception:
            pass

    if changed:
        st.session_state["data"] = df
        persist_data(df, season)

    st.session_state["replacements"] = cases
    replacements_save(season)

def close_replacement_case(case_id: int, note: str = ""):
    season = str(st.session_state.get("season", "")).strip()
    replacements_init(season)

    cases = st.session_state.get("replacements")
    if not isinstance(cases, pd.DataFrame) or cases.empty:
        return

    m = cases["case_id"].astype(str) == str(case_id)
    if not m.any():
        return

    cases.loc[m, "status"] = "CLOSED"
    cases.loc[m, "closed_at"] = now_tor().isoformat(timespec="seconds")
    if note:
        cases.loc[m, "note"] = str(note)

    st.session_state["replacements"] = cases
    replacements_save(season)


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
ChatGPT said:
Presque ✅ — l’emplacement est bon (juste après apply_move_with_history()), mais ton bloc n’est PAS correct tel quel pour 2 raisons critiques (qui vont te causer des bugs / erreurs) :
❌ Problème #1 (MAJEUR) : tu as recollé du “vieux code” dans close_replacement_case()
À la fin de ton extrait, à partir de :
    # -----------------------------
    # 1) SAVE LOCAL (data)
    # -----------------------------
…tout ça n’a rien à faire dans close_replacement_case().
👉 Tu utilises dedans des variables qui n’existent pas dans cette fonction :

df0
proprietaire
joueur
pos0, equipe0, from_statut, action_label, etc.
✅ Résultat : tu vas avoir un NameError dès que close_replacement_case() est appelée.
➡️ Solution : supprime complètement ce bloc à partir de # ----------------------------- jusqu’au return True.

❌ Problème #2 : process_replacements() ne gère pas encore le “retour automatique” du remplaçant
Tu as bien :
planification PENDING
activation ACTIVE à la date effective
refus si plafond dépassé
Mais il manque la logique :
✅ “Quand le joueur blessé revient, le remplaçant retourne où il était.”
Ça, pour le moment, ton process_replacements() ne le fait pas.

✅ Bloc corrigé (à remplacer)
Remplace ENTIÈREMENT ta fonction close_replacement_case() par ceci :
def close_replacement_case(case_id: int, note: str = ""):
    season = str(st.session_state.get("season", "")).strip()
    replacements_init(season)

    cases = st.session_state.get("replacements")
    if not isinstance(cases, pd.DataFrame) or cases.empty:
        return

    m = cases["case_id"].astype(str) == str(case_id)
    if not m.any():
        return

    cases.loc[m, "status"] = "CLOSED"
    cases.loc[m, "closed_at"] = now_tor().isoformat(timespec="seconds")
    if note:
        cases.loc[m, "note"] = str(note)

    st.session_state["replacements"] = cases
    replacements_save(season)
✅ Ça enlève le code parasite et évite tous les NameError.
✅ Bonus rapide (petite amélioration utile)
Dans replacements_init(), tu fais :
df_cases = pd.DataFrame(columns=cols)
if os.path.exists(path):
    df_cases = pd.read_csv(path)
➡️ ajoute juste après le read :
df_cases["case_id"] = pd.to_numeric(df_cases["case_id"], errors="coerce").fillna(0).astype(int)
Ça stabilise tes case_id (sinon parfois c’est lu comme string).
En résumé
✅ Oui l’endroit est correct (après apply_move_with_history)
❌ Non ton bloc n’est pas correct tel quel parce que tu as du code “move/history” collé au mauvais endroit.
Si tu veux, je te donne la version complète de process_replacements() qui inclut :

retour auto du remplaçant quand le blessé revient
fermeture automatique du case
toast + history propres
sans toucher ton sidebar / logo_pool / look & feel.
You said:
est ce correct?
 cols = [
            "case_id", "season", "owner",
            "injured_player", "injured_pos", "injured_team",
            "replacement_player", "replacement_from",
            "created_at", "effective_at",
            "status",  # PENDING / ACTIVE / CLOSED / REFUSED_CAP / CANCELLED
            "repl_revert_statut", "repl_revert_slot",
            "note", "closed_at"
        ]

        df_cases = pd.DataFrame(columns=cols)
        df_cases["case_id"] = pd.to_numeric(df_cases["case_id"], errors="coerce").fillna(0).astype(int)


        # Load local
        if os.path.exists(path):
            try:
                df_cases = pd.read_csv(path)
            except Exception:
                df_cases = pd.DataFrame(columns=cols)
ChatGPT said:
Presque 👍 — l’intention est bonne, mais l’ordre n’est pas correct.
Tel que tu l’as écrit, la normalisation de case_id ne s’applique PAS aux données chargées depuis le CSV.
❌ Problème
Tu fais :
créer un DataFrame vide
convertir case_id en int
puis charger le CSV → écrase df_cases
➡️ Résultat : si le CSV contient des case_id en string, ils restent en string.
✅ Version CORRECTE (à copier-coller)
Voici le bon bloc, dans le bon ordre :
cols = [
    "case_id", "season", "owner",
    "injured_player", "injured_pos", "injured_team",
    "replacement_player", "replacement_from",
    "created_at", "effective_at",
    "status",  # PENDING / ACTIVE / CLOSED / REFUSED_CAP / CANCELLED
    "repl_revert_statut", "repl_revert_slot",
    "note", "closed_at"
]

# Load local
if os.path.exists(path):
    try:
        df_cases = pd.read_csv(path)
    except Exception:
        df_cases = pd.DataFrame(columns=cols)
else:
    df_cases = pd.DataFrame(columns=cols)

# Normalize columns
for c in cols:
    if c not in df_cases.columns:
        df_cases[c] = ""

# Normalize types
df_cases["case_id"] = (
    pd.to_numeric(df_cases["case_id"], errors="coerce")
      .fillna(0)
      .astype(int)
)
✅ Pourquoi c’est la bonne version
charge les données avant la normalisation
garantit que toutes les colonnes existent
assure que case_id est toujours un int
évite les bugs subtils dans :
replacements_next_id()
find_active_case()
close_replacement_case()
✔️ Verdict
❌ Tel quel : non
✅ Avec l’ordre corrigé ci-dessus : oui, parfait
Tu es rendu exactement au point où un détail d’ordre peut faire planter une saison complète — donc très bon réflexe de demander 👍

You said:
correct maintenant ?
cols = [
            "case_id", "season", "owner",
            "injured_player", "injured_pos", "injured_team",
            "replacement_player", "replacement_from",
            "created_at", "effective_at",
            "status",  # PENDING / ACTIVE / CLOSED / REFUSED_CAP / CANCELLED
            "repl_revert_statut", "repl_revert_slot",
            "note", "closed_at"
        ]

        # Load local
        if os.path.exists(path):
            try:
                df_cases = pd.read_csv(path)
            except Exception:
                df_cases = pd.DataFrame(columns=cols)
        else:
            df_cases = pd.DataFrame(columns=cols)

        # Normalize columns
        for c in cols:
            if c not in df_cases.columns:
                df_cases[c] = ""

        # Normalize types
        df_cases["case_id"] = (
            pd.to_numeric(df_cases["case_id"], errors="coerce")
              .fillna(0)
              .astype(int)
ChatGPT said:
Oui ✅ — c’est correct maintenant (ordre + normalisation 👍).
Il te manque juste la parenthèse de fermeture à la toute fin de ton snippet (probablement juste coupée dans ton message). Ça doit finir comme ça :

df_cases["case_id"] = (
    pd.to_numeric(df_cases["case_id"], errors="coerce")
      .fillna(0)
      .astype(int)
)
Mini-check utile
Ajoute aussi (optionnel mais safe) juste après, pour éviter des espaces invisibles :
df_cases["owner"] = df_cases["owner"].astype(str).str.strip()
df_cases["status"] = df_cases["status"].astype(str).str.strip()
Mais sinon, ta version est bonne ✅
You said:
def replacements_init(season: str):
    if "replacements_season" not in st.session_state or st.session_state["replacements_season"] != season:
        path = _repl_file(season)
        st.session_state["REPLACEMENTS_FILE"] = path

        cols = [
            "case_id", "season", "owner",
            "injured_player", "injured_pos", "injured_team",
            "replacement_player", "replacement_from",
            "created_at", "effective_at",
            "status",  # PENDING / ACTIVE / CLOSED / REFUSED_CAP / CANCELLED
            "repl_revert_statut", "repl_revert_slot",
            "note", "closed_at"
        ]

        # Load local
        if os.path.exists(path):
            try:
                df_cases = pd.read_csv(path)
            except Exception:
                df_cases = pd.DataFrame(columns=cols)
        else:
            df_cases = pd.DataFrame(columns=cols)

        # Normalize columns
        for c in cols:
            if c not in df_cases.columns:
                df_cases[c] = ""

        # Normalize types
        df_cases["case_id"] = (
            pd.to_numeric(df_cases["case_id"], errors="coerce")
              .fillna(0)
              .astype(int)
        )

        df_cases["owner"] = df_cases["owner"].astype(str).str.strip()
        df_cases["status"] = df_cases["status"].astype(str).str.strip()
ChatGPT said:
Oui ✅ — cette fonction est maintenant correcte et propre.
Tu as exactement le bon ordre et les bonnes normalisations. 👍
Il ne te reste qu’une toute petite chose à ajouter pour que replacements_init() soit complète et fonctionne vraiment en session.

🔧 Ce qui manque (obligatoire)
À la fin de la fonction, tu dois stocker le DataFrame dans st.session_state et mémoriser la saison :
➕ Ajoute ces 2 lignes à la fin de la fonction
        st.session_state["replacements"] = df_cases
        st.session_state["replacements_season"] = season
✅ Version finale (complète et correcte)
Voici ta fonction finale, telle qu’elle devrait être :
def replacements_init(season: str):
    if "replacements_season" not in st.session_state or st.session_state["replacements_season"] != season:
        path = _repl_file(season)
        st.session_state["REPLACEMENTS_FILE"] = path

        cols = [
            "case_id", "season", "owner",
            "injured_player", "injured_pos", "injured_team",
            "replacement_player", "replacement_from",
            "created_at", "effective_at",
            "status",  # PENDING / ACTIVE / CLOSED / REFUSED_CAP / CANCELLED
            "repl_revert_statut", "repl_revert_slot",
            "note", "closed_at"
        ]

        # Load local
        if os.path.exists(path):
            try:
                df_cases = pd.read_csv(path)
            except Exception:
                df_cases = pd.DataFrame(columns=cols)
        else:
            df_cases = pd.DataFrame(columns=cols)

        # Normalize columns
        for c in cols:
            if c not in df_cases.columns:
                df_cases[c] = ""

        # Normalize types
        df_cases["case_id"] = (
            pd.to_numeric(df_cases["case_id"], errors="coerce")
              .fillna(0)
              .astype(int)
        )

        df_cases["owner"] = df_cases["owner"].astype(str).str.strip()
        df_cases["status"] = df_cases["status"].astype(str).str.strip()

        # 🔑 Store in session
        st.session_state["replacements"] = df_cases
        st.session_state["replacements_season"] = season
✅ Verdict final
✔️ Ordre de chargement : OK
✔️ Normalisation colonnes : OK
✔️ Types (case_id) : OK
✔️ Session state : OK maintenant
Tu es rendu exactement au niveau “code robuste de saison complète”.
Prochaine étape logique (si tu veux) :
➡️ afficher un badge ⏳ / ✅ directement sur le remplaçant dans l’alignement sans changer ton look.

You said:
ok
ChatGPT said:
Parfait 👍
Tu es 100 % correct maintenant et bien structuré.
👉 Prochaines bonnes pratiques (optionnelles, mais utiles) quand tu auras un moment :

🔁 Appeler process_replacements() une seule fois par run (tout en bas du app.py)
📌 Ajouter un petit indicateur visuel :
⏳ remplaçant planifié
✅ remplaçant actif
(sans toucher au sidebar ni au logo_pool)
🧪 Tester un scénario complet :
Actif → IR
Remplaçant Banc (+1 jour)
Forcer la date (ou changer l’horloge)
Vérifier activation + plafond
Bouton De retour
Quand tu voudras, je peux :
t’aider à écrire 1 test manuel pas à pas (checklist)
ajouter un onglet “⏳ Remplacements en attente” pour admin seulement
brancher le calcul de points avec date effective (projection au 7 janvier)
Dis-moi simplement ce que tu veux faire ensuite.
You said:
Alignement de chaque équipe ne change pas lorsque je change l'équipe
ChatGPT said:

Thought for 30s
Ça arrive souvent avec Streamlit quand :
tu changes la valeur dans le sidebar, mais
l’Alignement utilise une autre variable / un autre widget state (ou les noms ne matchent pas exactement).
Dans ton code, tu fais des st.session_state["selected_team"] = chosen + st.session_state["align_owner"] = chosen, mais tu bypasses ta fonction pick_team() et tu relies ça à des widgets qui ont déjà leur propre state (key="align_owner"). Ça peut “coller” sur l’ancienne valeur selon l’ordre des runs.
✅ Fix simple et robuste (recommandé)
1) Sidebar : utilise on_change + pick_team()
Remplace ton bloc sidebar “Choisir une équipe” par ça :
def _on_team_change():
    pick_team(st.session_state["sb_team_select"])

cur = str(st.session_state.get("selected_team", "")).strip()
if cur not in teams:
    cur = teams[0]
    st.session_state["selected_team"] = cur

chosen = st.sidebar.selectbox(
    "Choisir une équipe",
    teams,
    index=teams.index(cur),
    key="sb_team_select",
    on_change=_on_team_change,
)
✅ Résultat : dès que tu changes l’équipe, pick_team() synchronise selected_team et align_owner proprement.
Important : dans cette version, enlève ton bloc :
if chosen != cur:
    st.session_state["selected_team"] = chosen
    st.session_state["align_owner"] = chosen
    do_rerun()
Sinon tu vas doubler la logique.
✅ Fix #2 (souvent la vraie cause) : tes “owners” dans le CSV ne matchent pas les noms du sidebar
Dans ton tabA, tu fais :
all_owners = sorted(df["Propriétaire"].unique())
selected_team = get_selected_team()
if selected_team and selected_team in all_owners:
    st.session_state["align_owner"] = selected_team
Si dans ton CSV, Propriétaire contient autre chose que LOGOS.keys() (ex: “Patrice”, “Nordiques (PMS)”, espace à la fin, accent différent), alors ça ne match jamais, donc ça ne change pas.
Debug ultra rapide (à mettre temporairement dans tabA)
Juste après all_owners = ..., ajoute :
st.caption(f"DEBUG selected_team='{selected_team}' | match={selected_team in all_owners}")
Si tu vois match=False, c’est ça.
✅ Solution : normaliser les deux côtés (minuscule + strip) :

owners_norm = {str(o).strip().lower(): o for o in all_owners}
sel_norm = selected_team.strip().lower()

if sel_norm in owners_norm:
    st.session_state["align_owner"] = owners_norm[sel_norm]
✅ Petit ajustement Streamlit (évite les “états collés”)
Pour être encore plus safe, je te conseille de ne pas donner au selectbox la même key que ta variable logique.
Dans tabA, change :

proprietaire = st.selectbox("Propriétaire", all_owners, key="align_owner")
➡️ en :
proprietaire = st.selectbox(
    "Propriétaire",
    all_owners,
    index=all_owners.index(st.session_state["align_owner"]),
    key="align_owner_select",
)
st.session_state["align_owner"] = proprietaire
Ça évite que Streamlit “verrouille” la valeur du widget.
Ce que je te conseille de faire maintenant
Applique le fix sidebar avec on_change + pick_team() (c’est le plus important).
Si ça ne marche pas encore : active le debug match → si match=False, applique la normalisation.
Si tu me colles les 10 premières valeurs uniques de df["Propriétaire"].unique() (juste un print), je te dis exactement si c’est un problème de matching de noms ou de state Streamlit.
You said:
est ce correct?
ChatGPT said:
Je peux te dire “oui/non”, mais là tu ne m’as pas collé le code 😅
Colle-moi le bloc que tu as ajouté/modifié (le selectbox du sidebar + le selectbox dans tabA) et je te confirme.
En attendant, voici la version correcte (copie-colle) — si c’est ça que tu as, tu es bon ✅

✅ Sidebar (choix équipe) — version stable
def _on_team_change():
    pick_team(st.session_state["sb_team_select"])

teams = list(LOGOS.keys())
cur = str(st.session_state.get("selected_team", "")).strip()
if cur not in teams and teams:
    cur = teams[0]
    st.session_state["selected_team"] = cur

st.sidebar.selectbox(
    "Choisir une équipe",
    teams,
    index=teams.index(cur) if cur in teams else 0,
    key="sb_team_select",
    on_change=_on_team_change,
)
✅ Tab Alignement — sync avec matching robuste
all_owners = sorted(df["Propriétaire"].dropna().astype(str).unique().tolist())
selected_team = get_selected_team()

owners_norm = {str(o).strip().lower(): o for o in all_owners}
sel_norm = str(selected_team).strip().lower()

if sel_norm in owners_norm:
    st.session_state["align_owner"] = owners_norm[sel_norm]

if st.session_state.get("align_owner") not in all_owners and all_owners:
    st.session_state["align_owner"] = all_owners[0]

proprietaire = st.selectbox(
    "Propriétaire",
    all_owners,
    index=all_owners.index(st.session_state["align_owner"]),
    key="align_owner_select",
)
st.session_state["align_owner"] = proprietaire
👉 Si tu me colles ton bloc, je te réponds exactement : correct / pas correct + ce qu’il faut ajuster.
You said:
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

    def _on_team_change():
        pick_team(st.session_state["sb_team_select"])

    cur = str(st.session_state.get("selected_team", "")).strip()
    if cur not in teams:
        cur = teams[0]
        st.session_state["selected_team"] = cur

    chosen = st.sidebar.selectbox(
        "Choisir une équipe",
        teams,
        index=teams.index(cur),
        key="sb_team_select",
        on_change=_on_team_change,
    )
ChatGPT said:
Oui — c’est presque correct, et ton on_change est bien fait ✅
Mais il te reste 2 petites améliorations importantes (sinon tu peux encore avoir des “états collés” / align_owner pas synchro selon les cas).

✅ Ce qui est bon
key="sb_team_select" + on_change=_on_team_change ✅
pick_team(st.session_state["sb_team_select"]) ✅
⚠️ À corriger / simplifier
1) Tu as du code en double (deux fois cur = ... + deux fois if cur not in teams)
Tu peux enlever la répétition : ça ne casse pas, mais ça rend le flow fragile/moins clair.
2) Quand tu forces cur = teams[0], tu ne mets plus align_owner
Tu as en haut :
st.session_state["align_owner"] = cur
mais en bas (dans le deuxième bloc) tu ne le fais plus.
➡️ Si jamais ça passe par le deuxième bloc, align_owner peut rester sur l’ancienne équipe.
✅ Version corrigée (bloc complet à remplacer)
Copie-colle ce bloc à la place du tien :
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
    def _on_team_change():
        pick_team(st.session_state["sb_team_select"])

    cur = str(st.session_state.get("selected_team", "")).strip()
    if cur not in teams:
        cur = teams[0]
        st.session_state["selected_team"] = cur
        st.session_state["align_owner"] = cur  # ✅ keep sync

    chosen = st.sidebar.selectbox(
        "Choisir une équipe",
        teams,
        index=teams.index(cur),
        key="sb_team_select",
        on_change=_on_team_change,
    )
✅ Là, c’est clean, stable, pas de duplication, et align_owner reste synchronisé.
Dernier point (si ça ne change toujours pas dans Alignement)
Même avec ça, si df["Propriétaire"] n’a pas EXACTEMENT les mêmes noms que LOGOS.keys(), ton tab Alignement ne “matchera” pas.
Si tu veux, colle-moi juste :

st.write(sorted(df["Propriétaire"].dropna().astype(str).unique().tolist()))
(et ton LOGOS.keys()), et je te dis si c’est un problème de matching.
You said:
je le cole ou?
ChatGPT said:
Très bonne question 👍
Voici exactement où coller le bloc, sans ambiguïté.
📍 Où coller le bloc “Équipe (selectbox) + logo”
👉 Dans le SIDEBAR, à la place de ton ancien bloc qui gère le choix d’équipe.
Concrètement dans ton app.py
1️⃣ Cherche dans ton fichier le bloc qui ressemble à ça (ou très proche) :
# -----------------------------
# Équipe (selectbox) + logo
# -----------------------------
st.sidebar.divider()
st.sidebar.markdown("### 🏒 Équipes")
...
st.sidebar.selectbox(...)
👉 SUPPRIME complètement ce bloc
2️⃣ COLLE le bloc corrigé EXACTEMENT au même endroit, donc dans le sidebar, avant tes tabs.
Voici le bloc à coller :

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
    def _on_team_change():
        pick_team(st.session_state["sb_team_select"])

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
        on_change=_on_team_change,
    )
🧠 Pourquoi ici (et pas ailleurs)
Le sidebar est évalué avant tes tabs
Le selectbox met à jour st.session_state["sb_team_select"]
on_change appelle pick_team() → synchronise :
selected_team
align_owner
Le tab Alignement lit align_owner → affichage mis à jour
✅ Checklist rapide après collage
Après avoir collé :
 Changer d’équipe dans le sidebar
 Aller dans l’onglet Alignement
 Le roster affiché correspond à la nouvelle équipe
Si ça ne change toujours pas :
👉 colle-moi la fonction pick_team() et le début du code du tab Alignement, et je te corrige ligne par ligne.
You said:
ca ne change pas 
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
    def _on_team_change():
        pick_team(st.session_state["sb_team_select"])

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
        on_change=_on_team_change,
    )

Voici le code du Tab Alignement
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
        if not all_owners:
            all_owners = ["—"]

        selected_team = get_selected_team()

        # Sync sélection d’équipe -> align_owner si possible
        if selected_team and selected_team in all_owners:
            st.session_state["align_owner"] = selected_team

        # ✅ Guard béton: si la valeur en session_state n'est plus dans options, reset
        cur_owner = st.session_state.get("align_owner")
        if cur_owner not in all_owners:
            st.session_state["align_owner"] = all_owners[0]

        proprietaire = st.selectbox(
            "Propriétaire",
            all_owners,
            key="align_owner",
        )
ChatGPT said:
OK je vois exactement pourquoi ça ne change pas ✅
🎯 La cause
Dans tabA, ton selectbox est :
proprietaire = st.selectbox("Propriétaire", all_owners, key="align_owner")
➡️ Avec key="align_owner", le widget contrôle la valeur et Streamlit refuse souvent de se laisser “forcer” par st.session_state["align_owner"] = selected_team si le widget a déjà une valeur interne.
Résultat : tu changes l’équipe dans le sidebar, align_owner est bien modifié… mais le selectbox reste “collé”.

✅ Fix simple (à faire dans Tab Alignement)
Remplace ton selectbox par ceci (bloc exact)
        # ✅ Sync sidebar -> align_owner (matching robuste)
        selected_team = get_selected_team()

        owners_norm = {str(o).strip().lower(): o for o in all_owners}
        sel_norm = str(selected_team).strip().lower()

        if sel_norm in owners_norm:
            st.session_state["align_owner"] = owners_norm[sel_norm]

        # ✅ Guard: align_owner doit être un choix valide
        if st.session_state.get("align_owner") not in all_owners:
            st.session_state["align_owner"] = all_owners[0]

        # ✅ IMPORTANT: ne pas utiliser key="align_owner" ici
        proprietaire = st.selectbox(
            "Propriétaire",
            all_owners,
            index=all_owners.index(st.session_state["align_owner"]),
            key="align_owner_select",   # <-- key différente
        )

        # keep sync
        st.session_state["align_owner"] = proprietaire
📌 Donc :
key="align_owner_select" (nouvelle clé)
index=... basé sur st.session_state["align_owner"]
puis tu remets align_owner = proprietaire
✅ Pourquoi ça marche
align_owner redevient ton état logique
align_owner_select devient l’état du widget
tu contrôles le widget via index=... donc il suit le sidebar
🔍 Mini debug (si jamais ça bug encore)
Ajoute temporairement juste après selected_team = get_selected_team() :
st.caption(f"DEBUG selected_team={selected_team} | owners={len(all_owners)} | align_owner={st.session_state.get('align_owner')}")
Si selected_team n’est pas dans all_owners, alors le vrai problème est que tes noms dans Propriétaire ne matchent pas tes équipes LOGOS.keys().
Si tu colles ce patch, ça va se mettre à suivre le sidebar immédiatement.
You said:
donne moi le bloc au complet stp
ChatGPT said:
Parfait — voici LE BLOC COMPLET du TAB Alignement, prêt à copier-coller tel quel.
👉 Il corrige définitivement le problème de synchronisation avec le sidebar.
Tu peux remplacer entièrement ton TAB A — Alignement par ceci.

# =====================================================
# TAB A — Alignement
# =====================================================
with tabA:
    st.subheader("🧾 Alignement")

    # -----------------------------
    # Data safe (source unique)
    # -----------------------------
    df = st.session_state.get("data")
    if df is None:
        df = pd.DataFrame(columns=REQUIRED_COLS)

    df = clean_data(df)
    st.session_state["data"] = df

    if df.empty:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
        st.stop()

    # -----------------------------
    # Propriétaires disponibles
    # -----------------------------
    all_owners = sorted(df["Propriétaire"].dropna().astype(str).unique().tolist())
    if not all_owners:
        st.info("Aucun propriétaire trouvé.")
        st.stop()

    # -----------------------------
    # 🔗 Sync SIDEBAR → Alignement
    # -----------------------------
    selected_team = get_selected_team()

    # Normalisation robuste (évite accents / espaces / casse)
    owners_norm = {str(o).strip().lower(): o for o in all_owners}
    sel_norm = str(selected_team).strip().lower()

    if sel_norm in owners_norm:
        st.session_state["align_owner"] = owners_norm[sel_norm]

    # Guard béton : align_owner doit être valide
    if st.session_state.get("align_owner") not in all_owners:
        st.session_state["align_owner"] = all_owners[0]

    # -----------------------------
    # Selectbox Alignement (clé différente!)
    # -----------------------------
    proprietaire = st.selectbox(
        "Propriétaire",
        all_owners,
        index=all_owners.index(st.session_state["align_owner"]),
        key="align_owner_select",   # ⚠️ clé différente du state logique
    )

    # Keep sync logique
    st.session_state["align_owner"] = proprietaire

    # -----------------------------
    # Affichage alignement
    # -----------------------------
    joueurs_prop = df[df["Propriétaire"].astype(str).str.strip() == proprietaire].copy()

    if joueurs_prop.empty:
        st.info("Aucun joueur pour cette équipe.")
        st.stop()

    # === À PARTIR D’ICI, TU REMETS TON CODE EXISTANT ===
    # Exemples :
    # - Actifs
    # - Banc
    # - Mineurs
    # - IR
    # - roster_click_list(...)
✅ Pourquoi ce bloc règle ton problème
❌ On n’utilise plus key="align_owner" dans un widget
✅ align_owner devient un état logique, pas un widget
✅ Le sidebar pilote l’alignement via normalisation
✅ Le selectbox de l’alignement suit toujours le sidebar
✅ Plus d’état “collé” Streamlit
🔍 Si jamais ça ne change TOUJOURS PAS
Ajoute temporairement juste après selected_team = get_selected_team() :
st.caption(
    f"DEBUG sidebar={selected_team} | "
    f"align_owner={st.session_state.get('align_owner')} | "
    f"owners={all_owners}"
)
Si sidebar n’est pas dans owners, alors le problème vient des noms différents entre :
LOGOS.keys()
df["Propriétaire"]
👉 Si tu veux, colle-moi une ligne de chaque, je te dis exactement quoi harmoniser.
Mais avec ce bloc, dans 99 % des cas, ça fonctionne immédiatement.

You said:
Uploaded image
# =====================================================
# TAB 1 — Tableau
# =====================================================
with tab1:
    st.subheader("📊 Tableau")

    if df is None or df.empty:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
        st.stop()

    # ... ton code Tableau ici ...





# =====================================================
# TAB A — Alignement
# =====================================================
with tabA:
    st.subheader("🧾 Alignement")

    # -----------------------------
    # Data safe (source unique)
    # -----------------------------
    df = st.session_state.get("data")
    if df is None:
        df = pd.DataFrame(columns=REQUIRED_COLS)

    df = clean_data(df)
    st.session_state["data"] = df

    if df.empty:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
        st.stop()

    # -----------------------------
    # Propriétaires disponibles
    # -----------------------------
    all_owners = sorted(df["Propriétaire"].dropna().astype(str).unique().tolist())
    if not all_owners:
        st.info("Aucun propriétaire trouvé.")
        st.stop()

    # -----------------------------
    # 🔗 Sync SIDEBAR → Alignement
    # -----------------------------
    selected_team = get_selected_team()

    # Normalisation robuste (évite accents / espaces / casse)
    owners_norm = {str(o).strip().lower(): o for o in all_owners}
    sel_norm = str(selected_team).strip().lower()

    if sel_norm in owners_norm:
        st.session_state["align_owner"] = owners_norm[sel_norm]

    # Guard béton : align_owner doit être valide
    if st.session_state.get("align_owner") not in all_owners:
        st.session_state["align_owner"] = all_owners[0]

    # -----------------------------
    # Selectbox Alignement (clé différente!)
    # -----------------------------
    proprietaire = st.selectbox(
        "Propriétaire",
        all_owners,
        index=all_owners.index(st.session_state["align_owner"]),
        key="align_owner_select",   # ⚠️ clé différente du state logique
    )

    # Keep sync logique
    st.session_state["align_owner"] = proprietaire

    # -----------------------------
    # Affichage alignement
    # -----------------------------
    joueurs_prop = df[df["Propriétaire"].astype(str).str.strip() == proprietaire].copy()

    if joueurs_prop.empty:
        st.info("Aucun joueur pour cette équipe.")
        st.stop()

    # === À PARTIR D’ICI, TU REMETS TON CODE EXISTANT ===
    # Exemples :
    # - Actifs
    # - Banc
    # - Mineurs
    # - IR
    # - roster_click_list(...)


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
            f"**Actifs** — F {_count_badge(nb_F, 12)} • D {_count_badge(nb_D, 6)} • G {_count_badge(nb_G, 2)}",
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
ChatGPT said:

Thought for 20s
Je vois exactement pourquoi ça ne bouge pas sur ta capture:
Le sidebar change bien (Cracheurs),
mais le selectbox du tab garde sa propre valeur en mémoire (st.session_state["align_owner_select"]) et Streamlit ne la remplace pas juste parce que tu changes l’index.
✅ Solution: quand le sidebar change, il faut forcer la valeur du widget align_owner_select avant d’afficher le selectbox.
Voici le bloc TAB A complet (remplace ton TAB Alignement au complet par ça) :

# =====================================================
# TAB A — Alignement
# =====================================================
with tabA:
    st.subheader("🧾 Alignement")

    # -----------------------------
    # Data safe (source unique)
    # -----------------------------
    df = st.session_state.get("data")
    if df is None:
        df = pd.DataFrame(columns=REQUIRED_COLS)

    df = clean_data(df)
    st.session_state["data"] = df

    if df.empty:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
        st.stop()

    # -----------------------------
    # Propriétaires disponibles
    # -----------------------------
    all_owners = sorted(df["Propriétaire"].dropna().astype(str).unique().tolist())
    if not all_owners:
        st.info("Aucun propriétaire trouvé.")
        st.stop()

    # -----------------------------
    # 🔗 Sync SIDEBAR → Alignement
    # -----------------------------
    selected_team = get_selected_team()

    owners_norm = {str(o).strip().lower(): o for o in all_owners}
    sel_norm = str(selected_team or "").strip().lower()

    # Valeur "désirée" venant du sidebar (si match)
    desired_owner = owners_norm.get(sel_norm, None)

    # Si pas match, fallback = valeur existante / sinon premier owner
    if not desired_owner:
        desired_owner = st.session_state.get("align_owner") if st.session_state.get("align_owner") in all_owners else all_owners[0]

    # État logique
    st.session_state["align_owner"] = desired_owner

    # ✅ IMPORTANT: forcer la valeur DU WIDGET (sinon il reste collé sur l'ancien choix)
    if st.session_state.get("align_owner_select") != desired_owner:
        st.session_state["align_owner_select"] = desired_owner

    # -----------------------------
    # Selectbox Alignement
    # -----------------------------
    proprietaire = st.selectbox(
        "Propriétaire",
        all_owners,
        index=all_owners.index(st.session_state["align_owner_select"]),
        key="align_owner_select",
    )

    # Keep sync logique (si l'utilisateur change manuellement dans le tab)
    st.session_state["align_owner"] = proprietaire

    # -----------------------------
    # Affichage alignement
    # -----------------------------
    dprop = df[df["Propriétaire"].astype(str).str.strip() == str(proprietaire).strip()].copy()

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
        f"**Actifs** — F {_count_badge(nb_F, 12)} • D {_count_badge(nb_D, 6)} • G {_count_badge(nb_G, 2)}",
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
Si après ça ça ne suit toujours pas…
Alors ton get_selected_team() ne renvoie pas la valeur du sidebar (sb_team_select).
Dans ce cas, colle-moi ton get_selected_team() + pick_team() et je te le corrige (souvent c’est juste une clé session_state pas la bonne).
You said:
ca ne fonctionne toujours pas
# -----------------------------
    # 🔗 Sync SIDEBAR → Alignement
    # -----------------------------
    selected_team = get_selected_team()

    owners_norm = {str(o).strip().lower(): o for o in all_owners}
    sel_norm = str(selected_team or "").strip().lower()

    # Valeur "désirée" venant du sidebar (si match)
    desired_owner = owners_norm.get(sel_norm, None)

    # Si pas match, fallback = valeur existante / sinon premier owner
    if not desired_owner:
        desired_owner = st.session_state.get("align_owner") if st.session_state.get("align_owner") in all_owners else all_owners[0]

    # État logique
    st.session_state["align_owner"] = desired_owner

    # ✅ IMPORTANT: forcer la valeur DU WIDGET (sinon il reste collé sur l'ancien choix)
    if st.session_state.get("align_owner_select") != desired_owner:
        st.session_state["align_owner_select"] = desired_owner

    # -----------------------------
    # Selectbox Alignement
    # -----------------------------
    proprietaire = st.selectbox(
        "Propriétaire",
        all_owners,
        index=all_owners.index(st.session_state["align_owner_select"]),
        key="align_owner_select",
    )
ChatGPT said:

Thought for 26s
OK — si ça ne bouge toujours pas, c’est presque certain que le problème vient de get_selected_team() (il ne lit pas la bonne clé), donc ton tab reçoit l’ancienne valeur.
👉 Sur ton sidebar, la valeur “réelle” est dans st.session_state["sb_team_select"] (c’est la key de ton selectbox).
Donc dans Alignement, arrête d’utiliser get_selected_team() et lis directement sb_team_select.

Voici le bloc complet à remplacer dans TAB Alignement, juste la section sync + selectbox (tu remets ton reste après) :

# -----------------------------
# Propriétaires disponibles
# -----------------------------
all_owners = sorted(df["Propriétaire"].dropna().astype(str).unique().tolist())
if not all_owners:
    st.info("Aucun propriétaire trouvé.")
    st.stop()

# -----------------------------
# 🔗 Sync SIDEBAR → Alignement (ROBUSTE)
#   source de vérité = sb_team_select
# -----------------------------
sidebar_team = str(st.session_state.get("sb_team_select", "") or "").strip()

owners_norm = {str(o).strip().lower(): o for o in all_owners}
sidebar_norm = sidebar_team.lower()

# si le sidebar match un owner -> on force le selectbox du tab
if sidebar_norm in owners_norm:
    desired_owner = owners_norm[sidebar_norm]
else:
    desired_owner = st.session_state.get("align_owner_select")
    if desired_owner not in all_owners:
        desired_owner = all_owners[0]

# ✅ IMPORTANT: forcer la valeur DU WIDGET AVANT sa création
st.session_state["align_owner_select"] = desired_owner

# -----------------------------
# Selectbox Alignement
# -----------------------------
proprietaire = st.selectbox(
    "Propriétaire",
    all_owners,
    index=all_owners.index(st.session_state["align_owner_select"]),
    key="align_owner_select",
)

# garder le state logique si tu l'utilises ailleurs
st.session_state["align_owner"] = proprietaire
Et maintenant, correction essentielle côté SIDEBAR
Ton callback pick_team() peut être inutile/confus. Fais simple: le selectbox sidebar écrit déjà dans sb_team_select. Donc ton on_change peut juste copier vers selected_team si tu en as besoin ailleurs.
Remplace ton bloc sidebar par celui-ci (complet) :

# -----------------------------
# Équipe (selectbox) + logo
# -----------------------------
st.sidebar.divider()
st.sidebar.markdown("### 🏒 Équipes")

teams = list(LOGOS.keys())
if not teams:
    st.sidebar.info("Aucune équipe configurée.")
else:
    # init
    if "sb_team_select" not in st.session_state or st.session_state["sb_team_select"] not in teams:
        st.session_state["sb_team_select"] = teams[0]

    def _on_team_change():
        # source de vérité
        st.session_state["selected_team"] = st.session_state["sb_team_select"]
        # (optionnel) aussi pousser dans l'alignement
        st.session_state["align_owner_select"] = st.session_state["sb_team_select"]

    st.sidebar.selectbox(
        "Choisir une équipe",
        teams,
        key="sb_team_select",
        on_change=_on_team_change,
    )
Si après ça ça ne change toujours pas
Alors ton problème n’est plus la valeur, mais le tab Alignement n’est pas recalculé parce qu’un st.stop() plus haut coupe l’exécution (ex: dans Tab1 tu as st.stop() quand df empty).
Dans ton code tu as:

with tab1:
    if df is None or df.empty:
        st.info(...)
        st.stop()
✅ Ça arrête TOUTE l’app, donc Alignement ne rerun jamais correctement.
Si Tab1 peut être vide, remplace ce st.stop() par un simple else: (ou un return via fonction), mais pas st.stop().

Si tu veux, colle-moi ton bloc des tabs (tab1/tabA au complet, juste les guards) et je te le répare proprement sans stopper l’app.

You said:
# -----------------------------
# Selectbox Alignement
# -----------------------------
proprietaire = st.selectbox(
    "Propriétaire",
    all_owners,
    index=all_owners.index(st.session_state["align_owner_select"]),
    key="align_owner_select",
)

# garder le state logique si tu l'utilises ailleurs
st.session_state["align_owner"] = proprietaire


# garder le state logique si tu l'utilises ailleurs
st.session_state["align_owner"] = proprietaire


# Keep sync logique (si l'utilisateur change manuellement dans le tab)
st.session_state["align_owner"] = proprietaire

    # -----------------------------
    # Affichage alignement
    # -----------------------------
    dprop = df[df["Propriétaire"].astype(str).str.strip() == str(proprietaire).strip()].copy()

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
ChatGPT said:
Tu as 2 problèmes dans ce que tu as collé :
Tu répètes 3x st.session_state["align_owner"] = proprietaire (c’est inutile).
Ton indentation est cassée : tu as un dprop = ... qui est indenté alors qu’il ne devrait pas l’être (ça peut carrément empêcher l’exécution / créer un comportement weird).
Voici le bloc complet propre (Selectbox + début affichage) à coller tel quel dans TAB Alignement, à la place de tout ce que tu viens de montrer (de # Selectbox Alignement jusqu’à def gm_metric...) :
# -----------------------------
# Selectbox Alignement
# -----------------------------
proprietaire = st.selectbox(
    "Propriétaire",
    all_owners,
    index=all_owners.index(st.session_state["align_owner_select"]),
    key="align_owner_select",
)

# Keep sync logique (si tu l'utilises ailleurs)
st.session_state["align_owner"] = proprietaire

# -----------------------------
# Affichage alignement
# -----------------------------
dprop = df[df["Propriétaire"].astype(str).str.strip() == str(proprietaire).strip()].copy()

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
Important (sinon le “sync sidebar → tab” marche pas)
Assure-toi que juste avant ce bloc tu as bien ceci (dans tabA), sinon align_owner_select ne sera jamais forcé :
sidebar_team = str(st.session_state.get("sb_team_select", "") or "").strip()
owners_norm = {str(o).strip().lower(): o for o in all_owners}
sidebar_norm = sidebar_team.lower()

if sidebar_norm in owners_norm:
    st.session_state["align_owner_select"] = owners_norm[sidebar_norm]
elif st.session_state.get("align_owner_select") not in all_owners:
    st.session_state["align_owner_select"] = all_owners[0]
Si tu veux, colle ton tabA complet (du with tabA: jusqu’à open_move_dialog()) et je te le renvoie “clean” en un seul bloc sans doublons ni indentation piège.
You said:
File "/mount/src/poolhockey/app.py", line 2269, in <module>
    if chosen != cur:
       ^^^^^^
ChatGPT said:
Ton erreur est simple: chosen n’existe pas à l’endroit où tu fais if chosen != cur:.
Ça arrive quand:

tu as mis if chosen != cur: en dehors du else: où chosen = st.sidebar.selectbox(...) est défini, ou
tu n’as pas chosen = "" dans le cas if not teams: (donc chosen peut ne jamais être assigné).
✅ Fix robuste: définis toujours chosen avant, puis fais la comparaison.
Colle ce bloc complet pour ton SIDEBAR “Équipes” (il évite 100% le chosen undefined et synchronise selected_team) :

# -----------------------------
# Équipe (selectbox) + logo
# -----------------------------
st.sidebar.divider()
st.sidebar.markdown("### 🏒 Équipes")

teams = list(LOGOS.keys())

# ✅ Always define these
chosen = ""
cur = str(st.session_state.get("selected_team", "")).strip()

if not teams:
    st.sidebar.info("Aucune équipe configurée.")
    st.session_state["selected_team"] = ""
else:
    # ✅ Ensure cur is valid
    if cur not in teams:
        cur = teams[0]
        st.session_state["selected_team"] = cur
        st.session_state["sb_team_select"] = cur

    def _on_team_change():
        pick_team(st.session_state["sb_team_select"])

    chosen = st.sidebar.selectbox(
        "Choisir une équipe",
        teams,
        index=teams.index(cur),
        key="sb_team_select",
        on_change=_on_team_change,
    )

    # ✅ If you still want a manual sync (optional)
    if chosen != cur:
        st.session_state["selected_team"] = chosen
📌 Important: si tu as un if chosen != cur: ailleurs dans ton fichier (en dehors de ce bloc), supprime-le ou assure-toi que chosen est défini avant.
Si tu me colles les ~15 lignes autour de la ligne 2269 (10 avant / 10 après), je te dis exactement quoi enlever/placer pour que ça compile du premier coup.

You said:
File "/mount/src/poolhockey/app.py", line 3314, in <module>
    st.session_state["align_owner_select"] = desired_owner
                                             ^^^^^^^^^^^^^
ChatGPT said:
Parfait, l’erreur est très claire 👍
Et tu es à 2 lignes de la solution.
❌ L’erreur exacte
st.session_state["align_owner_select"] = desired_owner
                                         ^^^^^^^^^^^^^
NameError: name 'desired_owner' is not defined
👉 desired_owner n’existe pas dans ce scope au moment où tu l’utilises.
Ça veut dire une seule chose :

tu as copié une ligne qui utilise desired_owner
mais tu n’as PAS défini desired_owner juste avant
✅ Fix IMMÉDIAT (le plus simple et le plus sûr)
👉 Ne calcule plus desired_owner séparément
👉 Utilise directement la valeur du sidebar (sb_team_select) comme source de vérité
🔧 Remplace TOUTE la section fautive par CE bloc (copier-coller)
Colle ceci dans le TAB Alignement, juste AVANT le st.selectbox("Propriétaire", ...) :
# -----------------------------
# 🔗 Sync SIDEBAR → Alignement (SANS desired_owner)
# -----------------------------
sidebar_team = str(st.session_state.get("sb_team_select", "") or "").strip()

owners_norm = {str(o).strip().lower(): o for o in all_owners}
sidebar_norm = sidebar_team.lower()

# Forcer la valeur du widget alignement depuis le sidebar
if sidebar_norm in owners_norm:
    st.session_state["align_owner_select"] = owners_norm[sidebar_norm]
elif st.session_state.get("align_owner_select") not in all_owners:
    st.session_state["align_owner_select"] = all_owners[0]
🚫 Supprime complètement toute ligne qui ressemble à :
desired_owner = ...
st.session_state["align_owner_select"] = desired_owner
✅ Ensuite ton selectbox DOIT être exactement comme ça
proprietaire = st.selectbox(
    "Propriétaire",
    all_owners,
    index=all_owners.index(st.session_state["align_owner_select"]),
    key="align_owner_select",
)

st.session_state["align_owner"] = proprietaire
🧠 Pourquoi cette version marche
sb_team_select = source de vérité unique
pas de variable temporaire (desired_owner) → impossible d’être undefined
Streamlit respecte la valeur du widget quand on la force avant sa création
🔥 Règle d’or Streamlit (à retenir)
Si une variable est utilisée dans st.session_state[...] = X,
elle DOIT être définie juste avant, dans le même bloc.
🧪 Checklist finale
Après ce fix :
 Plus d’erreur NameError
 Changer d’équipe dans le sidebar
 L’alignement change instantanément
 Le selectbox du tab suit le sidebar
Si tu veux, colle-moi les 20 lignes autour de la ligne 3314 et je te dis exactement quoi supprimer pour éviter tout doublon restant.
You said:
Uploaded image
rien ne s'affiche comme ca l'était au départ de la conversation
ChatGPT said:

Thought for 19s
Je vois exactement ce qui se passe sur ta capture :
Le “Propriétaire” reste sur Red Wings même si le sidebar est sur Nordiques ⇒ ton sync sidebar→tab n’est pas appliqué avant la création du selectbox (ou il est écrasé juste après).
Tes sections (Actifs / Mineur / Banc / IR) ne s’affichent plus ⇒ très souvent c’est parce que :
ton bloc d’affichage est indenté au mauvais niveau (ex: sous un if qui ne passe pas), ou
il y a un st.stop() ou return plus haut (même “caché” dans un guard), ou
tu as coupé le bloc “à partir d’ici” et tu ne l’exécutes plus.
Je te donne LE bloc complet (sidebar + tab Alignement) à coller, qui :
force la valeur du selectbox AVANT de le créer,
garde une seule clé de widget (align_owner_select),
évite les st.stop() qui cassent l’app,
et remet l’affichage complet comme avant.
✅ 1) BLOC SIDEBAR COMPLET (à mettre dans ta section sidebar, une seule fois)
Remplace ton bloc “Équipes” par ceci.
# -----------------------------
# SIDEBAR — Équipe (selectbox) + logo
# -----------------------------
st.sidebar.divider()
st.sidebar.markdown("### 🏒 Équipes")

teams = list(LOGOS.keys())
if not teams:
    st.sidebar.info("Aucune équipe configurée.")
else:
    # Valeur courante (source: sb_team_select -> selected_team -> fallback)
    cur = str(st.session_state.get("sb_team_select") or st.session_state.get("selected_team") or "").strip()
    if cur not in teams:
        cur = teams[0]

    def _on_team_change():
        chosen = str(st.session_state.get("sb_team_select") or "").strip()
        st.session_state["selected_team"] = chosen           # état logique global
        st.session_state["align_owner_select"] = chosen      # force le tab Alignement
        # rerun safe si tu as un helper
        if "do_rerun" in globals():
            do_rerun()
        else:
            st.rerun()

    st.sidebar.selectbox(
        "Choisir une équipe",
        teams,
        index=teams.index(cur),
        key="sb_team_select",
        on_change=_on_team_change,
    )

    # Logo (optionnel)
    logo_path = LOGOS.get(cur, "")
    if logo_path and os.path.exists(logo_path):
        st.sidebar.image(logo_path, width=64)
✅ 2) BLOC TAB A — ALIGNEMENT COMPLET (à remplacer au complet)
Remplace tout ton with tabA: par ceci (bloc entier).
# =====================================================
# TAB A — Alignement
# =====================================================
with tabA:
    st.subheader("🧾 Alignement")

    # -----------------------------
    # Data safe (source unique)
    # -----------------------------
    df = st.session_state.get("data")
    if df is None:
        df = pd.DataFrame(columns=REQUIRED_COLS)

    df = clean_data(df)
    st.session_state["data"] = df

    if df.empty:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
    else:
        # -----------------------------
        # Propriétaires disponibles
        # -----------------------------
        all_owners = sorted(df["Propriétaire"].dropna().astype(str).unique().tolist())
        if not all_owners:
            st.info("Aucun propriétaire trouvé.")
        else:
            # -----------------------------
            # 🔗 Force SIDEBAR → widget "Propriétaire"
            # IMPORTANT: doit arriver AVANT le selectbox
            # -----------------------------
            sidebar_team = str(st.session_state.get("sb_team_select") or st.session_state.get("selected_team") or "").strip()

            owners_norm = {str(o).strip().lower(): o for o in all_owners}
            sidebar_norm = sidebar_team.lower()

            # Si sidebar match un owner -> force le widget
            if sidebar_norm in owners_norm:
                st.session_state["align_owner_select"] = owners_norm[sidebar_norm]

            # Guard: si widget invalide -> fallback
            if st.session_state.get("align_owner_select") not in all_owners:
                st.session_state["align_owner_select"] = all_owners[0]

            # -----------------------------
            # Selectbox Alignement (UNE SEULE clé)
            # -----------------------------
            proprietaire = st.selectbox(
                "Propriétaire",
                all_owners,
                index=all_owners.index(st.session_state["align_owner_select"]),
                key="align_owner_select",
            )

            # garder l'état logique si utilisé ailleurs
            st.session_state["align_owner"] = proprietaire

            # (optionnel) si tu veux que changer dans le tab reflète le sidebar :
            st.session_state["selected_team"] = proprietaire
            st.session_state["sb_team_select"] = proprietaire

            # -----------------------------
            # Affichage alignement
            # -----------------------------
            dprop = df[df["Propriétaire"].astype(str).str.strip() == str(proprietaire).strip()].copy()

            if dprop.empty:
                st.info("Aucun joueur pour cette équipe.")
            else:
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

                cap_gc = int(st.session_state.get("PLAFOND_GC", 0) or 0)
                cap_ce = int(st.session_state.get("PLAFOND_CE", 0) or 0)
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
                    f"**Actifs** — F {_count_badge(nb_F, 12)} • D {_count_badge(nb_D, 6)} • G {_count_badge(nb_G, 2)}",
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
                                if "do_rerun" in globals(): do_rerun()
                                else: st.rerun()
                        else:
                            roster_click_list(gc_actif, proprietaire, "actifs_disabled")

                with colB:
                    with st.container(border=True):
                        st.markdown("### 🔵 Mineur")
                        if not popup_open:
                            p = roster_click_list(ce_all, proprietaire, "min")
                            if p:
                                set_move_ctx(proprietaire, p, "min")
                                if "do_rerun" in globals(): do_rerun()
                                else: st.rerun()
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
                                if "do_rerun" in globals(): do_rerun()
                                else: st.rerun()
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
                                if "do_rerun" in globals(): do_rerun()
                                else: st.rerun()
                        else:
                            roster_click_list(injured_all, proprietaire, "ir_disabled")

                # Pop-up toujours à la fin du tab
                open_move_dialog()
Pourquoi chez toi “rien ne s’affiche”
Dans ton extrait, on voit souvent ce pattern :
des morceaux du bloc d’affichage se retrouvent indentés sous autre chose (ex: sous le selectbox, ou sous un if),
ou tu avais des st.stop() (tu en as plusieurs dans les versions précédentes) → ça coupe le rendu avant les sections.
Le bloc que je te donne évite ça : aucun st.stop() après le message “pas de données”, et tout est au bon niveau d’indentation.
Si après ça le “Propriétaire” ne suit toujours pas le sidebar
Alors ça veut dire que ton sidebar n’est pas exécuté avant le tab (ordre d’exécution dans ton app), ou que tu as un autre endroit qui réécrit sb_team_select / selected_team.
Mais dans 95% des cas, en remplaçant ces deux blocs (sidebar + tabA) ça règle.

Si tu veux que je te dise exactement où ça se fait écraser : colle-moi juste les fonctions get_selected_team() et pick_team() (elles doivent être courtes).

You said:
File "/mount/src/poolhockey/app.py", line 3318, in <module>
    st.session_state["sb_team_select"] = proprietaire
    ~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^
File "/home/adminuser/venv/lib/python3.11/site-packages/streamlit/runtime/metrics_util.py", line 409, in wrapped_func
    result = non_optional_func(*args, **kwargs)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
File "/home/adminuser/venv/lib/python3.11/site-packages/streamlit/runtime/state/session_state_proxy.py", line 113, in __setitem__
    get_session_state()[key] = value
    ~~~~~~~~~~~~~~~~~~~^^^^^
File "/home/adminuser/venv/lib/python3.11/site-packages/streamlit/runtime/state/safe_session_state.py", line 99, in __setitem__
    self._state[key] = value
    ~~~~~~~~~~~^^^^^
File "/home/adminuser/venv/lib/python3.11/site-packages/streamlit/runtime/state/session_state.py", line 516, in __setitem__
    raise StreamlitAPIException(
ChatGPT said:
OK — cette erreur est 100% normale Streamlit : tu n’as pas le droit de faire
st.session_state["sb_team_select"] = ...
parce que sb_team_select est une clé de widget (le selectbox du sidebar). Streamlit bloque toute modification “manuelle” d’une valeur de widget après sa création.
✅ Solution : ne synchronise pas le tab → sidebar en écrivant dans sb_team_select.
On fait un sens seulement : SIDEBAR → TAB.

Donc, dans mon bloc tabA, tu dois enlever ces lignes :

st.session_state["selected_team"] = proprietaire
st.session_state["sb_team_select"] = proprietaire
et garder seulement align_owner_select.
Voici le bloc TAB A complet corrigé (remplace ton with tabA: au complet par ça) :

# =====================================================
# TAB A — Alignement
# =====================================================
with tabA:
    st.subheader("🧾 Alignement")

    # -----------------------------
    # Data safe (source unique)
    # -----------------------------
    df = st.session_state.get("data")
    if df is None:
        df = pd.DataFrame(columns=REQUIRED_COLS)

    df = clean_data(df)
    st.session_state["data"] = df

    if df.empty:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
    else:
        # -----------------------------
        # Propriétaires disponibles
        # -----------------------------
        all_owners = sorted(df["Propriétaire"].dropna().astype(str).unique().tolist())
        if not all_owners:
            st.info("Aucun propriétaire trouvé.")
        else:
            # -----------------------------
            # 🔗 Force SIDEBAR → widget "Propriétaire"
            # IMPORTANT: AVANT le selectbox
            # -----------------------------
            sidebar_team = str(st.session_state.get("sb_team_select") or st.session_state.get("selected_team") or "").strip()

            owners_norm = {str(o).strip().lower(): o for o in all_owners}
            sidebar_norm = sidebar_team.lower()

            # Si sidebar match un owner -> force le widget du tab
            if sidebar_norm in owners_norm:
                st.session_state["align_owner_select"] = owners_norm[sidebar_norm]

            # Guard: si invalide -> fallback
            if st.session_state.get("align_owner_select") not in all_owners:
                st.session_state["align_owner_select"] = all_owners[0]

            # -----------------------------
            # Selectbox Alignement (UNE SEULE clé)
            # -----------------------------
            proprietaire = st.selectbox(
                "Propriétaire",
                all_owners,
                index=all_owners.index(st.session_state["align_owner_select"]),
                key="align_owner_select",
            )

            # état logique si tu l'utilises ailleurs
            st.session_state["align_owner"] = proprietaire

            # -----------------------------
            # Affichage alignement
            # -----------------------------
            dprop = df[df["Propriétaire"].astype(str).str.strip() == str(proprietaire).strip()].copy()

            if dprop.empty:
                st.info("Aucun joueur pour cette équipe.")
            else:
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

                cap_gc = int(st.session_state.get("PLAFOND_GC", 0) or 0)
                cap_ce = int(st.session_state.get("PLAFOND_CE", 0) or 0)
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
                    f"**Actifs** — F {_count_badge(nb_F, 12)} • D {_count_badge(nb_D, 6)} • G {_count_badge(nb_G, 2)}",
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
                                if "do_rerun" in globals(): do_rerun()
                                else: st.rerun()
                        else:
                            roster_click_list(gc_actif, proprietaire, "actifs_disabled")

                with colB:
                    with st.container(border=True):
                        st.markdown("### 🔵 Mineur")
                        if not popup_open:
                            p = roster_click_list(ce_all, proprietaire, "min")
                            if p:
                                set_move_ctx(proprietaire, p, "min")
                                if "do_rerun" in globals(): do_rerun()
                                else: st.rerun()
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
                                if "do_rerun" in globals(): do_rerun()
                                else: st.rerun()
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
                                if "do_rerun" in globals(): do_rerun()
                                else: st.rerun()
                        else:
                            roster_click_list(injured_all, proprietaire, "ir_disabled")

                open_move_dialog()
Important (petit rappel)
✅ OK : st.session_state["align_owner_select"] = ... (c’est ton état interne)
❌ PAS OK : st.session_state["sb_team_select"] = ... (clé de widget)
Si tu veux quand même un “bidirectionnel” (tab → sidebar), ça se fait, mais il faut recréer le widget avec une autre clé (ou utiliser un état séparé), pas écrire directement dans la clé du widget.
You said:
revient au point ou quand on change l'équipe l'alignement ne suit pas
ChatGPT said:

Thought for 18s
Parfait — on revient au setup simple qui marche à coup sûr :
✅ 1 seule source de vérité : st.session_state["selected_team"]
✅ Le sidebar met à jour selected_team
✅ Le tab Alignement lit selected_team et force align_owner_select AVANT de créer son selectbox

Et surtout : on ne touche jamais à sb_team_select depuis le tab (sinon Streamlit plante).

1) Remplace ton bloc SIDEBAR “Équipes” au complet par ça
(Important : ce bloc définit toujours st.session_state["selected_team"])
# -----------------------------
# Équipes (SIDEBAR)
# -----------------------------
st.sidebar.divider()
st.sidebar.markdown("### 🏒 Équipes")

teams = list(LOGOS.keys())

if not teams:
    st.sidebar.info("Aucune équipe configurée.")
else:
    # init selected_team si absent
    if "selected_team" not in st.session_state or str(st.session_state["selected_team"]).strip() not in teams:
        st.session_state["selected_team"] = teams[0]

    def _on_team_change():
        # 1 seule action : mettre à jour la source de vérité
        st.session_state["selected_team"] = st.session_state["sb_team_select"]

    cur = str(st.session_state.get("selected_team", "")).strip()
    if cur not in teams:
        cur = teams[0]
        st.session_state["selected_team"] = cur

    st.sidebar.selectbox(
        "Choisir une équipe",
        teams,
        index=teams.index(cur),
        key="sb_team_select",
        on_change=_on_team_change,
    )
2) Dans TAB A — remplace seulement la section “Sync SIDEBAR → Alignement” + le selectbox
Tu dois mettre ce bloc juste avant le st.selectbox("Propriétaire", ...) dans tabA.
# -----------------------------
# 🔗 Sync SIDEBAR → Alignement (AVANT le widget)
# -----------------------------
selected_team = str(st.session_state.get("selected_team", "") or "").strip()

owners_norm = {str(o).strip().lower(): o for o in all_owners}
sel_norm = selected_team.lower()

# si le team du sidebar correspond à un owner -> on force la valeur du widget
desired_owner = owners_norm.get(sel_norm, None)
if desired_owner is None:
    desired_owner = st.session_state.get("align_owner_select")
    if desired_owner not in all_owners:
        desired_owner = all_owners[0]

# ✅ crucial: set AVANT la création du selectbox
st.session_state["align_owner_select"] = desired_owner

# -----------------------------
# Selectbox Alignement
# -----------------------------
proprietaire = st.selectbox(
    "Propriétaire",
    all_owners,
    index=all_owners.index(st.session_state["align_owner_select"]),
    key="align_owner_select",
)

st.session_state["align_owner"] = proprietaire
Pourquoi ça va fonctionner (et pourquoi ton ancien setup ne marchait pas)
Avant, tu avais 2 états (sidebar et tab) qui se battaient.
Ou tu essayais de modifier une clé de widget (sb_team_select) depuis le tab → Streamlit refuse.
Ici : sidebar écrit → selected_team, tab lit → selected_team, et force align_owner_select avant son widget.
Si après ça l’alignement “ne suit pas”, je veux juste 1 info (sans reposer de questions longues) :
➡️ Ton df["Propriétaire"] contient exactement les mêmes noms que LOGOS.keys() (ex: “Nordiques” vs “Nordiques ” ou accents/casse) ?
(Si ça diffère, je te donne un mapping auto ultra robuste.)
You said:
voici mon code Tab A, redonne moi le avec le changement
ChatGPT said:

Thought for a few seconds
Colle-moi ton Tab A complet ici et je te le renvoie tel quel avec la modif.
En attendant (pour que tu puisses avancer tout de suite), voici un TAB A complet “prêt à remplacer” avec le sync sidebar → alignement correct, et un gros commentaire “COLLE TON CODE ICI” exactement où remettre ta partie d’affichage (actifs/banc/mineur/IR/popup).

⚠️ Important : ce bloc suppose que ton sidebar met bien st.session_state["selected_team"] (comme dans le bloc sidebar que je t’ai donné).
✅ Et surtout : on ne touche pas à sb_team_select ici.
# =====================================================
# TAB A — Alignement
# =====================================================
with tabA:
    st.subheader("🧾 Alignement")

    # -----------------------------
    # Data safe (source unique)
    # -----------------------------
    df = st.session_state.get("data")
    if df is None:
        df = pd.DataFrame(columns=REQUIRED_COLS)

    df = clean_data(df)
    st.session_state["data"] = df

    if df.empty:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
        st.stop()

    # -----------------------------
    # Propriétaires disponibles
    # -----------------------------
    all_owners = sorted(df["Propriétaire"].dropna().astype(str).unique().tolist())
    if not all_owners:
        st.info("Aucun propriétaire trouvé.")
        st.stop()

    # -----------------------------
    # 🔗 Sync SIDEBAR → Alignement (AVANT le widget)
    # -----------------------------
    selected_team = str(st.session_state.get("selected_team", "") or "").strip()

    owners_norm = {str(o).strip().lower(): o for o in all_owners}
    sel_norm = selected_team.lower()

    desired_owner = owners_norm.get(sel_norm, None)

    if desired_owner is None:
        # fallback = valeur actuelle du widget si valide, sinon premier owner
        desired_owner = st.session_state.get("align_owner_select")
        if desired_owner not in all_owners:
            desired_owner = all_owners[0]

    # ✅ crucial: forcer la valeur AVANT de créer le selectbox
    st.session_state["align_owner_select"] = desired_owner

    # -----------------------------
    # Selectbox Alignement
    # -----------------------------
    proprietaire = st.selectbox(
        "Propriétaire",
        all_owners,
        index=all_owners.index(st.session_state["align_owner_select"]),
        key="align_owner_select",
    )

    # state logique si tu l'utilises ailleurs
    st.session_state["align_owner"] = proprietaire

    # -----------------------------
    # Affichage alignement (filtré)
    # -----------------------------
    dprop = df[df["Propriétaire"].astype(str).str.strip() == str(proprietaire).strip()].copy()

    if dprop.empty:
        st.info("Aucun joueur pour cette équipe.")
        st.stop()

    # =====================================================
    # ✅ COLLE ICI TON CODE D’AFFICHAGE EXISTANT
    # (actifs / banc / mineur / IR / métriques / popup)
    #
    # Ex:
    # injured_all = ...
    # gc_all, ce_all = ...
    # roster_click_list(...)
    # open_move_dialog()
    # =====================================================

    # --- EXEMPLE placeholder minimal (à enlever quand tu colles ton code) ---
    st.caption("⚠️ Remets ici ton code d’affichage (Actifs/Banc/Mineur/IR).")
Pourquoi ton écran “n’affiche plus rien” sur ta capture
Tu as probablement cassé l’indentation / mis ton code d’affichage en dehors du with tabA: ou après un st.stop().
Le bloc ci-dessus te redonne une structure “propre” pour recoller ton affichage au bon endroit.
✅ Maintenant : colle ton Tab A actuel (celui que tu utilises vraiment) et je te le renvoie au complet, avec ton affichage intact + le sync qui fonctionne.
You said:
# =====================================================
# TAB A — Alignement
# =====================================================
with tabA:
    st.subheader("🧾 Alignement")

    # -----------------------------
    # Data safe (source unique)
    # -----------------------------
    df = st.session_state.get("data")
    if df is None:
        df = pd.DataFrame(columns=REQUIRED_COLS)

    df = clean_data(df)
    st.session_state["data"] = df

    if df.empty:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
        st.stop()

    # -----------------------------
    # Propriétaires disponibles
    # -----------------------------
    all_owners = sorted(df["Propriétaire"].dropna().astype(str).unique().tolist())
    if not all_owners:
        st.info("Aucun propriétaire trouvé.")
        st.stop()

    # -----------------------------
    # 🔗 Sync SIDEBAR → Alignement (AVANT le widget)
    # -----------------------------
    selected_team = str(st.session_state.get("selected_team", "") or "").strip()

    owners_norm = {str(o).strip().lower(): o for o in all_owners}
    sel_norm = selected_team.lower()

    desired_owner = owners_norm.get(sel_norm, None)

    if desired_owner is None:
        # fallback = valeur actuelle du widget si valide, sinon premier owner
        desired_owner = st.session_state.get("align_owner_select")
        if desired_owner not in all_owners:
            desired_owner = all_owners[0]

    # ✅ crucial: forcer la valeur AVANT de créer le selectbox
    st.session_state["align_owner_select"] = desired_owner

    # -----------------------------
    # Selectbox Alignement
    # -----------------------------
    proprietaire = st.selectbox(
        "Propriétaire",
        all_owners,
        index=all_owners.index(st.session_state["align_owner_select"]),
        key="align_owner_select",
    )

    # state logique si tu l'utilises ailleurs
    st.session_state["align_owner"] = proprietaire

    # -----------------------------
    # Affichage alignement (filtré)
    # -----------------------------
    dprop = df[df["Propriétaire"].astype(str).str.strip() == str(proprietaire).strip()].copy()

    if dprop.empty:
        st.info("Aucun joueur pour cette équipe.")
        st.stop()

    # =====================================================
    # ✅ COLLE ICI TON CODE D’AFFICHAGE EXISTANT
    # (actifs / banc / mineur / IR / métriques / popup)
    #
    # Ex:
    # injured_all = ...
    # gc_all, ce_all = ...
    # roster_click_list(...)
    # open_move_dialog()
    # =====================================================

    # --- EXEMPLE placeholder minimal (à enlever quand tu colles ton code) ---
    st.caption("⚠️ Remets ici ton code d’affichage (Actifs/Banc/Mineur/IR).")
ChatGPT said:
Parfait, merci d’avoir collé ton Tab A réel 👍
On va faire le minimum de changements, sans casser ton affichage, et surtout sans refaire 10 variantes.
👉 Le problème clé, ici, n’est plus Streamlit :
c’est que selected_team du sidebar ne correspond PAS aux valeurs de df["Propriétaire"].

On le voit clairement sur ta capture :

Sidebar = Nordiques
Selectbox Alignement = Red Wings
Donc :
le sync fonctionne techniquement,
mais owners_norm.get(sel_norm) ne matche jamais → desired_owner reste None
fallback = ancien owner → Red Wings
🎯 LA CORRECTION À FAIRE (simple et robuste)
👉 On ne tente plus de matcher automatiquement selected_team → owner
👉 On force toujours l’alignement à suivre le sidebar si le nom existe, sinon on ne touche à rien
🔧 RÈGLE
Si selected_team est dans all_owners → on l’utilise
Sinon → on laisse l’alignement tel quel
✅ TON TAB A — VERSION CORRIGÉE (à remplacer tel quel)
Copie-colle tout ce bloc à la place de ton Tab A actuel :
# =====================================================
# TAB A — Alignement
# =====================================================
with tabA:
    st.subheader("🧾 Alignement")

    # -----------------------------
    # Data safe (source unique)
    # -----------------------------
    df = st.session_state.get("data")
    if df is None:
        df = pd.DataFrame(columns=REQUIRED_COLS)

    df = clean_data(df)
    st.session_state["data"] = df

    if df.empty:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
        st.stop()

    # -----------------------------
    # Propriétaires disponibles
    # -----------------------------
    all_owners = sorted(df["Propriétaire"].dropna().astype(str).unique().tolist())
    if not all_owners:
        st.info("Aucun propriétaire trouvé.")
        st.stop()

    # -----------------------------
    # 🔗 Sync SIDEBAR → Alignement (LOGIQUE SIMPLE)
    # -----------------------------
    selected_team = str(st.session_state.get("selected_team", "") or "").strip()

    # 👉 si le nom du sidebar EXISTE comme propriétaire, on force
    if selected_team in all_owners:
        st.session_state["align_owner_select"] = selected_team

    # Guard final
    if st.session_state.get("align_owner_select") not in all_owners:
        st.session_state["align_owner_select"] = all_owners[0]

    # -----------------------------
    # Selectbox Alignement
    # -----------------------------
    proprietaire = st.selectbox(
        "Propriétaire",
        all_owners,
        index=all_owners.index(st.session_state["align_owner_select"]),
        key="align_owner_select",
    )

    st.session_state["align_owner"] = proprietaire

    # -----------------------------
    # Affichage alignement (filtré)
    # -----------------------------
    dprop = df[df["Propriétaire"].astype(str).str.strip() == proprietaire].copy()

    if dprop.empty:
        st.info("Aucun joueur pour cette équipe.")
        st.stop()

    # =====================================================
    # ⬇️ ICI : TON CODE EXISTANT (actifs / banc / IR / etc.)
    # =====================================================
🧠 Pourquoi CETTE version fonctionne (et les autres non)
Tu n’as pas besoin de normalisation compliquée
Tu n’as pas besoin de mapping
Tu respectes ta règle métier réelle :
“Une équipe du sidebar = un propriétaire Fantrax”
Si un jour tu veux :
LOGOS.keys() ≠ df["Propriétaire"]
➡️ là on fera un mapping explicite (ex: { "Nordiques": "Nordiques PMS" })
✅ Résultat attendu après ce changement
Tu changes l’équipe dans le sidebar
Le selectbox Propriétaire change instantanément
L’alignement suit
Ton affichage redevient exactement comme au début
Si tu veux, prochaine étape possible :
ajouter un toast quand l’équipe change
ou empêcher le changement d’équipe si un popup de déplacement est ouvert
Dis-moi 👍
You said:
# -----------------------------
    # Affichage alignement (filtré)
    # -----------------------------
    dprop = df[df["Propriétaire"].astype(str).str.strip() == proprietaire].copy()

    if dprop.empty:
        st.info("Aucun joueur pour cette équipe.")
        st.stop()

    # =====================================================
    # ⬇️ ICI : TON CODE EXISTANT (actifs / banc / IR / etc.)
    # =====================================================

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

                cap_gc = int(st.session_state.get("PLAFOND_GC", 0) or 0)
                cap_ce = int(st.session_state.get("PLAFOND_CE", 0) or 0)
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
                    f"**Actifs** — F {_count_badge(nb_F, 12)} • D {_count_badge(nb_D, 6)} • G {_count_badge(nb_G, 2)}",
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
                                if "do_rerun" in globals(): do_rerun()
                                else: st.rerun()
                        else:
                            roster_click_list(gc_actif, proprietaire, "actifs_disabled")

                with colB:
                    with st.container(border=True):
                        st.markdown("### 🔵 Mineur")
                        if not popup_open:
                            p = roster_click_list(ce_all, proprietaire, "min")
                            if p:
                                set_move_ctx(proprietaire, p, "min")
                                if "do_rerun" in globals(): do_rerun()
                                else: st.rerun()
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
                                if "do_rerun" in globals(): do_rerun()
                                else: st.rerun()
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
                                if "do_rerun" in globals(): do_rerun()
                                else: st.rerun()
                        else:
                            roster_click_list(injured_all, proprietaire, "ir_disabled")

                open_move_dialog()
ChatGPT said:
Ton affichage ne s’affiche plus parce que tu as collé ton “code existant” avec une indentation en trop (il commence par injured_all = ...).
Ça met tout ton bloc dans un niveau de bloc inexistant → Streamlit n’exécute pas comme tu penses (ou ça plante selon le contexte).
✅ Solution : je te redonne le TAB A COMPLET, avec :

le sync sidebar → alignement (version simple qui marche)
ton bloc d’affichage remis au bon niveau d’indentation (0 indentation de plus)
sans toucher à ta logique
Copie-colle tout ce bloc en remplacement de ton TAB A.
# =====================================================
# TAB A — Alignement
# =====================================================
with tabA:
    st.subheader("🧾 Alignement")

    # -----------------------------
    # Data safe (source unique)
    # -----------------------------
    df = st.session_state.get("data")
    if df is None:
        df = pd.DataFrame(columns=REQUIRED_COLS)

    df = clean_data(df)
    st.session_state["data"] = df

    if df.empty:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
        st.stop()

    # -----------------------------
    # Propriétaires disponibles
    # -----------------------------
    all_owners = sorted(df["Propriétaire"].dropna().astype(str).unique().tolist())
    if not all_owners:
        st.info("Aucun propriétaire trouvé.")
        st.stop()

    # -----------------------------
    # 🔗 Sync SIDEBAR → Alignement (AVANT le widget)
    # -----------------------------
    selected_team = str(st.session_state.get("selected_team", "") or "").strip()

    # si le nom du sidebar EXISTE comme propriétaire -> on force
    if selected_team in all_owners:
        st.session_state["align_owner_select"] = selected_team

    # Guard final: valeur valide
    if st.session_state.get("align_owner_select") not in all_owners:
        st.session_state["align_owner_select"] = all_owners[0]

    # -----------------------------
    # Selectbox Alignement
    # -----------------------------
    proprietaire = st.selectbox(
        "Propriétaire",
        all_owners,
        index=all_owners.index(st.session_state["align_owner_select"]),
        key="align_owner_select",
    )

    # state logique si utilisé ailleurs
    st.session_state["align_owner"] = proprietaire

    # -----------------------------
    # Affichage alignement (filtré)
    # -----------------------------
    dprop = df[df["Propriétaire"].astype(str).str.strip() == str(proprietaire).strip()].copy()

    if dprop.empty:
        st.info("Aucun joueur pour cette équipe.")
        st.stop()

    # =====================================================
    # ✅ TON CODE EXISTANT (actifs / banc / mineur / IR)
    # =====================================================
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

    cap_gc = int(st.session_state.get("PLAFOND_GC", 0) or 0)
    cap_ce = int(st.session_state.get("PLAFOND_CE", 0) or 0)
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
        f"**Actifs** — F {_count_badge(nb_F, 12)} • D {_count_badge(nb_D, 6)} • G {_count_badge(nb_G, 2)}",
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
                    if "do_rerun" in globals():
                        do_rerun()
                    else:
                        st.rerun()
            else:
                roster_click_list(gc_actif, proprietaire, "actifs_disabled")

    with colB:
        with st.container(border=True):
            st.markdown("### 🔵 Mineur")
            if not popup_open:
                p = roster_click_list(ce_all, proprietaire, "min")
                if p:
                    set_move_ctx(proprietaire, p, "min")
                    if "do_rerun" in globals():
                        do_rerun()
                    else:
                        st.rerun()
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
                    if "do_rerun" in globals():
                        do_rerun()
                    else:
                        st.rerun()
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
                    if "do_rerun" in globals():
                        do_rerun()
                    else:
                        st.rerun()
            else:
                roster_click_list(injured_all, proprietaire, "ir_disabled")

    # Pop-up toujours à la fin du tab
    open_move_dialog()
⚠️ Important (1 ligne)
Assure-toi que ton sidebar met bien à jour st.session_state["selected_team"] (c’est ça que Tab A lit).
Si après ça ça ne suit toujours pas, colle-moi juste le bloc sidebar “Équipes” (celui avec selectbox + pick_team) et je te le corrige pour que selected_team soit garanti à jour.

You said:
peu importe quel autre propriétaire est sélectionne, c'est toujours l'alignement des Red Wings
 # -----------------------------
    # 🔗 Sync SIDEBAR → Alignement (AVANT le widget)
    # -----------------------------
    selected_team = str(st.session_state.get("selected_team", "") or "").strip()

    # si le nom du sidebar EXISTE comme propriétaire -> on force
    if selected_team in all_owners:
        st.session_state["align_owner_select"] = selected_team

    # Guard final: valeur valide
    if st.session_state.get("align_owner_select") not in all_owners:
        st.session_state["align_owner_select"] = all_owners[0]

    # -----------------------------
    # Selectbox Alignement
    # -----------------------------
    proprietaire = st.selectbox(
        "Propriétaire",
        all_owners,
        index=all_owners.index(st.session_state["align_owner_select"]),
        key="align_owner_select",
    )
ChatGPT said:
Oui — là tu forces align_owner_select à chaque rerun dès que selected_team (sidebar) existe. Donc même si tu choisis un autre propriétaire dans le tab, au rerun suivant ça revient au selected_team (Red Wings).
✅ Fix: ne synchroniser depuis le sidebar QUE quand le sidebar change (pas à chaque rerun).
On garde une variable last_sidebar_team en session_state.

Remplace ton bloc Sync + selectbox par celui-ci :

# -----------------------------
# 🔗 Sync SIDEBAR → Alignement (SEULEMENT quand le sidebar change)
# -----------------------------
selected_team = str(st.session_state.get("selected_team", "") or "").strip()

# init (premier run)
if "last_sidebar_team" not in st.session_state:
    st.session_state["last_sidebar_team"] = selected_team

# Si le sidebar a changé depuis la dernière fois → on force l'alignement
if selected_team and selected_team != st.session_state["last_sidebar_team"]:
    if selected_team in all_owners:
        st.session_state["align_owner_select"] = selected_team
        st.session_state["align_owner"] = selected_team
    st.session_state["last_sidebar_team"] = selected_team  # update tracker

# Guard final: valeur valide pour le widget
if st.session_state.get("align_owner_select") not in all_owners:
    st.session_state["align_owner_select"] = all_owners[0]

# -----------------------------
# Selectbox Alignement
# -----------------------------
proprietaire = st.selectbox(
    "Propriétaire",
    all_owners,
    index=all_owners.index(st.session_state["align_owner_select"]),
    key="align_owner_select",
)

# State logique (si tu l'utilises ailleurs)
st.session_state["align_owner"] = proprietaire
Pourquoi ça règle ton bug
Le sidebar (Red Wings) n’écrase plus ta sélection du tab à chaque rerun.
Il ne reprend la main que quand tu changes réellement l’équipe dans le sidebar.
Si après ça tu vois encore “Red Wings” partout, le problème sera ailleurs (souvent roster_click_list(...) qui lit get_selected_team() au lieu du proprietaire passé, ou un filtre qui utilise selected_team au lieu de proprietaire). Dans ce cas, colle-moi la fonction roster_click_list et/ou get_selected_team() et je te pointe la ligne fautive.
You said:
Uploaded image
il y a toujours que Red wings dans le proprietaire
ChatGPT said:

Thought for 14s
Si dans le selectbox il n’y a que “Red Wings”, ça veut dire une chose très simple :
👉 all_owners ne contient qu’un seul propriétaire parce que ton df (st.session_state["data"]) ne contient déjà plus que Red Wings.

Donc le bug n’est plus dans le sync sidebar/tab — il est en amont : quelque part, quand tu changes l’équipe, tu filtre / écrases st.session_state["data"] pour ne garder que cette équipe.

Le coupable le plus fréquent : ta fonction pick_team() (ou un get_selected_team()/sidebar callback) qui fait un truc du genre :

st.session_state["data"] = st.session_state["data"][st.session_state["data"]["Propriétaire"] == owner]
1) Debug ultra rapide (mets ça dans Tab A juste après df = clean_data(df))
st.caption("DEBUG owners in df:")
st.write(sorted(df["Propriétaire"].astype(str).str.strip().unique().tolist()))
st.write(df["Propriétaire"].astype(str).value_counts().head(20))
Si ça affiche seulement ["Red Wings"], on a confirmé : tes données en mémoire sont filtrées.
2) Fix : pick_team() NE DOIT PAS toucher à st.session_state["data"]
Voici une version “safe” de pick_team (tu peux remplacer la tienne) :
def pick_team(owner: str):
    owner = str(owner or "").strip()
    if not owner:
        return

    # ✅ ne filtre PAS les données
    st.session_state["selected_team"] = owner

    # optionnel : synchro immédiate du tab alignement
    st.session_state["align_owner_select"] = owner
    st.session_state["align_owner"] = owner

    # (facultatif) ferme un popup si tu veux éviter un état bizarre
    # st.session_state["move_ctx"] = None

    if "do_rerun" in globals():
        do_rerun()
    else:
        st.rerun()
IMPORTANT : assure-toi qu’il n’y a NULLE PART ailleurs une ligne qui réassigne st.session_state["data"] en le filtrant par équipe.
3) Où chercher exactement
Fais une recherche texte dans ton app.py pour :
st.session_state["data"] =
["Propriétaire"] ==
pick_team(
selected_team
.query("Propriétaire")
Tu vas trouver l’endroit qui “coupe” le dataset.
Si tu colles ici ta fonction pick_team() actuelle (et/ou le bloc sidebar où tu l’appelles), je te dis exactement quelle ligne filtre tes données et je te renvoie le bloc corrigé au complet.



ChatGPT can make mistakes. Check important info. See Cookie Preferences.

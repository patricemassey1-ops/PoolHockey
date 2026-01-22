from __future__ import annotations



import time
# ==============================
# Safe caller for update_players_db (filters unsupported kwargs)
# ==============================
def _call_update_players_db(**kwargs):
    import inspect
    fn = globals().get("update_players_db")
    if not callable(fn):
        raise RuntimeError("update_players_db is not defined")
    try:
        sig = inspect.signature(fn)
    except Exception:
        sig = None

    roster_only = bool(kwargs.get("roster_only", False))
    roster_df = kwargs.get("roster_df")

    if roster_only and sig is not None:
        params = set(sig.parameters.keys())
        if "roster_only" not in params:
            kwargs.pop("roster_only", None)
            if roster_df is None:
                roster_df = st.session_state.get("data")
            if "roster_df" in params:
                kwargs["roster_df"] = roster_df
            try:
                if roster_df is not None and hasattr(roster_df, "__len__"):
                    kwargs["max_calls"] = min(int(kwargs.get("max_calls") or 5000), max(50, int(len(roster_df) * 2)))
            except Exception:
                pass

    if sig is not None:
        params = sig.parameters
        accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
        if not accepts_kwargs:
            kwargs = {k: v for k, v in kwargs.items() if k in params}

    return fn(**kwargs)

# =====================================================
# Players DB fill LOCK (prevents Drive sync overwrite)
# =====================================================
def _pdb_lock_on():
    try: st.session_state["pdb_lock"] = True
    except Exception: pass

def _pdb_lock_off():
    try: st.session_state["pdb_lock"] = False
    except Exception: pass

def _pdb_is_locked() -> bool:
    try: return bool(st.session_state.get("pdb_lock", False))
    except Exception: return False

import os
import io
import re
import unicodedata
import json
import html
import base64
import hashlib
import uuid
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
st.set_page_config(page_title="PMS", layout="wide")

# =====================================================
# Players DB loader (cached) — used across app
#   - 'mtime' is passed only to bust Streamlit cache when file changes
# =====================================================
@st.cache_data(show_spinner=False)
def load_players_db(csv_path: str, mtime: float | None = None) -> pd.DataFrame:
    """Load hockey.players database (CSV/TSV) robustly.

    - Tries comma-separated first, then auto-detects, then tab-separated.
    - Handles common Streamlit Cloud issues where a CSV is actually tab-delimited.
    """
    try:
        if not csv_path or not os.path.exists(csv_path):
            return pd.DataFrame()

        # 1) Standard CSV
        try:
            df = pd.read_csv(csv_path)
        except Exception:
            df = pd.DataFrame()

        # If it looks like a single-column TSV (header contains tabs), re-read as TSV.
        if isinstance(df, pd.DataFrame) and (df.shape[1] <= 1):
            try:
                with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
                    head = f.readline()
                if "\t" in head:
                    df = pd.read_csv(csv_path, sep="\t")
            except Exception:
                pass

        # 2) Auto-detect delimiter if still single column
        if isinstance(df, pd.DataFrame) and (df.shape[1] <= 1):
            try:
                df2 = pd.read_csv(csv_path, sep=None, engine="python")
                if isinstance(df2, pd.DataFrame) and df2.shape[1] > df.shape[1]:
                    df = df2
            except Exception:
                pass

        # Light column cleanup
        if isinstance(df, pd.DataFrame) and not df.empty:
            df.columns = [str(c).strip() for c in df.columns]

        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


# =====================================================
# 🩺 PING endpoint (pour pinger externe / uptime monitor)
#   URL: https://<ton-app>.streamlit.app/?ping=1&token=...
#   - Optionnel: secrets [pinger].token pour protéger
# =====================================================
try:
    _qp = None
    try:
        _qp = dict(st.query_params)
    except Exception:
        _qp = st.experimental_get_query_params()
    _ping = _qp.get('ping')
    if isinstance(_ping, list):
        _ping = _ping[0] if _ping else None
    if str(_ping or '').strip() == '1':
        _tok = _qp.get('token')
        if isinstance(_tok, list):
            _tok = _tok[0] if _tok else ''
        _need = ''
        try:
            _need = str((st.secrets.get('pinger', {}) or {}).get('token','') or '').strip()
        except Exception:
            _need = ''
        if _need and str(_tok or '').strip() != _need:
            st.error('unauthorized')
            st.stop()
        st.write('ok')
        st.stop()
except Exception:
    pass



import streamlit.components.v1 as components
import requests


# =====================================================
# SAFE IMAGE (évite MediaFileHandler: Missing file)
#   ⚠️ IMPORTANT: une seule définition (sinon récursion / écran noir)
# =====================================================
def safe_image(image, *args, **kwargs):
    """Wrapper st.image safe: accepte path str ou objet image.

    - Si path manquant: n'explose pas, affiche caption si fournie.
    - Une seule fonction (pas de double def) pour éviter la récursion.
    """
    try:
        if isinstance(image, str):
            p = image.strip()
            if p and os.path.exists(p):
                return st.image(p, *args, **kwargs)
            cap = kwargs.get("caption", "")
            if cap:
                st.caption(cap)
            return None
        return st.image(image, *args, **kwargs)
    except Exception:
        cap = kwargs.get("caption", "")
        if cap:
            st.caption(cap)
        return None

# =====================================================
# app.py — PMS Pool (version propre + corrections + Admin complet)
#   ✅ 1 seule section Alignement (dans le routing)
#   ✅ sidebar = source de vérité (sync selected_team / align_owner)
#   ✅ Admin Import (preview + confirmer + tri imports)
# =====================================================

# =====================================================
# IMPORTS


# =====================================================

# =====================================================
# Level override helper (alias) — must exist before Admin import preview
# =====================================================
def force_level_from_players(df: pd.DataFrame) -> pd.DataFrame:
    """Compat wrapper: Admin import calls this; delegates to apply_players_level when available."""
    try:
        fn = globals().get("apply_players_level")
        if callable(fn):
            return fn(df)
    except Exception:
        pass
    return df








# =====================================================
# Google Drive (OAuth refresh_token) + Backups helpers
#   - Admin only UI later in routing
#   - Requires secrets:
#       [gdrive_oauth]
#       client_id, client_secret, refresh_token, folder_id
#   Optional alerts:
#       [alerts]
#       slack_webhook, smtp_host, smtp_port, smtp_user, smtp_password, email_to, email_from
# =====================================================
try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    import httplib2
    try:
        from google_auth_httplib2 import AuthorizedHttp
    except Exception:
        AuthorizedHttp = None
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaInMemoryUpload
except Exception:
    Credentials = None
    Request = None
    httplib2 = None
    AuthorizedHttp = None
    build = None
    MediaInMemoryUpload = None

import smtplib
import ssl
from email.message import EmailMessage

# =====================================================
# Name key helpers (handle "Last, First" vs "First Last")
# =====================================================
def _to_first_last(name: str) -> str:
    s = str(name or "").strip()
    if "," in s:
        last, first = [p.strip() for p in s.split(",", 1)]
        if last and first:
            return f"{first} {last}".strip()
    return s

def _to_last_comma_first(name: str) -> str:
    s = str(name or "").strip()
    if not s or "," in s:
        return s
    tokens = [t for t in s.split() if t.strip()]
    if len(tokens) < 2:
        return s
    last = tokens[-1]
    first = " ".join(tokens[:-1])
    return f"{last}, {first}".strip()


MTL_TZ = ZoneInfo('America/Montreal')


def drive_creds_from_secrets(show_error: bool = False):
    'Build OAuth Credentials from Streamlit Secrets and refresh access token.'
    cfg = st.secrets.get('gdrive_oauth', {}) or {}
    client_id = str(cfg.get('client_id', '')).strip()
    client_secret = str(cfg.get('client_secret', '')).strip()
    refresh_token = str(cfg.get('refresh_token', '')).strip()
    token_uri = str(cfg.get('token_uri', 'https://oauth2.googleapis.com/token')).strip()

    if not (client_id and client_secret and refresh_token):
        if show_error:
            st.error('Drive: Secrets incomplets (client_id / client_secret / refresh_token).')
        return None

    if Credentials is None or Request is None:
        if show_error:
            st.error('Drive: dépendances Google manquantes (google-auth / google-api-python-client).')
        return None

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=token_uri,
        client_id=client_id,
        client_secret=client_secret,
        scopes=['https://www.googleapis.com/auth/drive.file'],
    )

    try:
        creds.refresh(Request())
    except Exception as e:
        if show_error:
            st.error(f'Drive: échec refresh token — {type(e).__name__}: {e}')
        return None

    return creds


@st.cache_resource(show_spinner=False)
def _drive_cached(_rt: str):
    'Cached Drive service per refresh_token.'
    if build is None:
        raise RuntimeError('google-api-python-client manquant')
    creds = drive_creds_from_secrets(show_error=False)
    if not creds:
        raise RuntimeError('Drive creds invalides (Secrets)')
    # Use an explicit HTTP client with timeout to avoid hanging SSL reads.
    # If google_auth_httplib2 isn't available, fall back to default build().
    if 'httplib2' in globals() and AuthorizedHttp is not None:
        http = httplib2.Http(timeout=20)
        authed_http = AuthorizedHttp(creds, http=http)
        return build('drive', 'v3', http=authed_http, cache_discovery=False)
    return build('drive', 'v3', credentials=creds, cache_discovery=False)


def _drive():
    cfg = st.secrets.get('gdrive_oauth', {}) or {}
    rt = str(cfg.get('refresh_token', '')).strip()
    if not rt:
        raise RuntimeError('Drive: refresh_token manquant dans Secrets')
    return _drive_cached(rt)


def _drive_find_file(s, folder_id: str, name: str):
    if not folder_id:
        return None
    safe = str(name or '').replace("'", "\'")
    q = f"'{folder_id}' in parents and trashed=false and name='{safe}'"
    try:
        res = s.files().list(q=q, fields='files(id,name,modifiedTime,size)', pageSize=1).execute(num_retries=1)
        files = res.get('files', [])
        return files[0] if files else None
    except BaseException as e:
        # Do not crash the whole app on transient network/SSL issues.
        st.session_state['__drive_last_error'] = f"{type(e).__name__}: {e}"
        return None


def _drive_safe_find_file(s, folder_id: str, name: str):
    """Wrapper used by UI code. Never raises."""
    try:
        return _drive_find_file(s, folder_id, name)
    except BaseException as e:
        st.session_state['__drive_last_error'] = f"{type(e).__name__}: {e}"
        return None


def _drive_list_backups(s, folder_id: str, base_filename: str):
    'List backups for base_filename (vNNN or timestamp) newest->oldest.'
    safe = str(base_filename or '').replace("'", "\'")
    q = (
        f"'{folder_id}' in parents and trashed=false and "
        f"name contains '{safe}_v' or name contains '{safe}_20'"
    )
    # more robust: just list folder and filter client-side if query fails
    try:
        res = s.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields='files(id,name,modifiedTime,size)',
            pageSize=1000
        ).execute()
        files = res.get('files', [])
    except Exception:
        files = []

    base = str(base_filename)
    out = []
    for f in files:
        n = str(f.get('name',''))
        if n.startswith(base + '_v') or n.startswith(base + '_20'):
            out.append(f)
    out.sort(key=lambda x: str(x.get('modifiedTime','')), reverse=True)
    return out


def _drive_next_vname(backups, base_filename: str):
    mx = 0
    base = str(base_filename)
    for b in backups:
        n = str(b.get('name',''))
        if n.startswith(base + '_v'):
            m = re.match(re.escape(base) + r'_v(\d{3})\.csv$', n)
            if m:
                try:
                    mx = max(mx, int(m.group(1)))
                except Exception:
                    pass
    return f"{base}_v{mx+1:03d}.csv"


def _backup_copy_both(s, folder_id: str, base_filename: str) -> dict:
    'Create two backups: versioned _vNNN.csv and timestamp _YYYY-MM-DD_HHMM.csv. Returns names.'
    src = _drive_find_file(s, folder_id, base_filename)
    if not src:
        raise FileNotFoundError(base_filename)

    backups = _drive_list_backups(s, folder_id, base_filename)
    v_name = _drive_next_vname(backups, base_filename)
    ts = datetime.now(MTL_TZ).strftime('%Y-%m-%d_%H%M')
    ts_name = f"{base_filename}_{ts}.csv"

    # copy
    s.files().copy(fileId=src['id'], body={'name': v_name, 'parents':[folder_id]}).execute()
    s.files().copy(fileId=src['id'], body={'name': ts_name, 'parents':[folder_id]}).execute()
    return {'v_name': v_name, 'ts_name': ts_name}


def _restore_from_backup(s, folder_id: str, base_filename: str, backup_id: str) -> str:
    'Restore by downloading backup content and updating main file content.'
    main = _drive_find_file(s, folder_id, base_filename)
    if not main:
        raise FileNotFoundError(base_filename)

    data = s.files().get_media(fileId=backup_id).execute()
    media = MediaInMemoryUpload(data, mimetype='text/csv', resumable=False)
    s.files().update(fileId=main['id'], media_body=media).execute()
    return main['id']


def _drive_cleanup_backups(s, folder_id: str, base_filename: str, keep_v: int = 20, keep_ts: int = 20) -> dict:
    """
    Supprime les backups anciens en gardant keep_v (vNNN) et keep_ts (timestamp).
    Retourne un résumé.
    """
    backups = _drive_list_backups(s, folder_id, base_filename)

    v_list = [b for b in backups if _drive_kind(b.get("name",""), base_filename) == "v"]
    ts_list = [b for b in backups if _drive_kind(b.get("name",""), base_filename) == "ts"]

    keep = set()
    for b in v_list[:max(0, int(keep_v or 0))]:
        keep.add(b.get("id"))
    for b in ts_list[:max(0, int(keep_ts or 0))]:
        keep.add(b.get("id"))

    to_delete = [b for b in backups if b.get("id") not in keep]

    deleted = 0
    errors = []
    for b in to_delete:
        try:
            s.files().delete(fileId=b["id"]).execute()
            deleted += 1
        except Exception as e:
            errors.append(f"{b.get('name','?')} — {type(e).__name__}: {e}")

    return {
        "total_backups": len(backups),
        "kept_v": len(v_list[:max(0, int(keep_v or 0))]),
        "kept_ts": len(ts_list[:max(0, int(keep_ts or 0))]),
        "deleted": deleted,
        "delete_errors": errors[:10],
        "remaining": len(backups) - deleted,
    }

def nightly_backup_once_per_day(s, folder_id: str, files: list[str], hour_mtl: int = 3):
    """
    Runs at most once per calendar day after hour_mtl (MTL time).
    Uses a small marker file on Drive to avoid repeating.
    """
    now = datetime.now(MTL_TZ)
    if now.hour < int(hour_mtl):
        return {"ran": False, "reason": "before_hour"}

    marker = f"_nightly_backup_done_{now.strftime('%Y-%m-%d')}.txt"
    if _drive_find_file(s, folder_id, marker):
        return {"ran": False, "reason": "already_done"}

    # Create marker FIRST (prevents double-run if reruns happen)
    _drive_upsert_csv_bytes(s, folder_id, marker, b"ok\n")

    ok = 0
    fail = 0
    for fn in files:
        existing = _drive_find_file(s, folder_id, fn)
        if not existing:
            log_backup_event(s, folder_id, {
                "action": "nightly_backup",
                "file": fn,
                "result": "SKIP (missing)",
                "note": "fichier absent sur Drive",
                "by": "nightly",
            })
            continue
        try:
            res = _backup_copy_both(s, folder_id, fn)
            ok += 1
            log_backup_event(s, folder_id, {
                "action": "nightly_backup",
                "file": fn,
                "result": "OK",
                "v_name": res.get("v_name",""),
                "ts_name": res.get("ts_name",""),
                "by": "nightly",
            })
        except Exception as e:
            fail += 1
            log_backup_event(s, folder_id, {
                "action": "nightly_backup",
                "file": fn,
                "result": f"FAIL ({type(e).__name__})",
                "note": str(e),
                "by": "nightly",
            })

    return {"ran": True, "ok": ok, "fail": fail, "marker": marker}



BACKUP_HISTORY_FILE = 'backup_history.csv'


def _drive_download_csv_df(s, folder_id: str, filename: str):
    f = _drive_find_file(s, folder_id, filename)
    if not f:
        return pd.DataFrame()
    data = s.files().get_media(fileId=f['id']).execute()
    try:
        return pd.read_csv(io.BytesIO(data))
    except Exception:
        return pd.DataFrame()


def _drive_upsert_csv_bytes(s, folder_id: str, filename: str, csv_bytes: bytes):
    media = MediaInMemoryUpload(csv_bytes, mimetype='text/csv', resumable=False)
    f = _drive_find_file(s, folder_id, filename)
    if f:
        s.files().update(fileId=f['id'], media_body=media).execute()
        return f['id']
    created = s.files().create(body={'name': filename, 'parents':[folder_id]}, media_body=media, fields='id').execute()
    return created['id']


def log_backup_event(s, folder_id: str, event: dict):
    row = {
        'ts': event.get('ts', datetime.now(MTL_TZ).strftime('%Y-%m-%d %H:%M:%S')),
        'action': event.get('action',''),
        'file': event.get('file',''),
        'result': event.get('result',''),
        'v_name': event.get('v_name',''),
        'ts_name': event.get('ts_name',''),
        'note': event.get('note',''),
        'by': event.get('by',''),
    }
    df = _drive_download_csv_df(s, folder_id, BACKUP_HISTORY_FILE)
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    _drive_upsert_csv_bytes(s, folder_id, BACKUP_HISTORY_FILE, df.to_csv(index=False).encode('utf-8'))


def send_slack_alert(msg: str) -> bool:
    cfg = st.secrets.get('alerts', {}) or {}
    url = str(cfg.get('slack_webhook', '')).strip()
    if not url:
        return False
    try:
        r = requests.post(url, json={'text': msg}, timeout=10)
        return bool(r.status_code in (200, 204))
    except Exception:
        return False


def send_email_alert(subject: str, body: str) -> bool:
    cfg = st.secrets.get('alerts', {}) or {}
    host = str(cfg.get('smtp_host','')).strip()
    port = int(cfg.get('smtp_port', 587) or 587)
    user = str(cfg.get('smtp_user','')).strip()
    pwd = str(cfg.get('smtp_password','')).strip()
    to_ = str(cfg.get('email_to','')).strip()
    from_ = str(cfg.get('email_from', user)).strip()
    if not (host and user and pwd and to_ and from_):
        return False

    try:
        em = EmailMessage()
        em['From'] = from_
        em['To'] = to_
        em['Subject'] = subject
        em.set_content(body)

        context = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.starttls(context=context)
            s.login(user, pwd)
            s.send_message(em)
        return True
    except Exception:
        return False

# =====================================================
# NHL APIs - Enrich / Build Players DB (Admin action)
#   - api-web.nhle.com (roster + player landing)
#   - statsapi.web.nhl.com (fallback roster + teams)
#   - api.nhle.com/stats/rest (optional, not required for identity)
#
# Design goals:
#   - One button in Admin to update data/hockey.players.csv
#   - Cache on disk (CSV) so app works even if API is down
#   - Preserve user's columns: Level (ELC/STD) + Cap Hit (contracts)
# =====================================================

NHL_APIWEB_BASE = "https://api-web.nhle.com"
NHL_STATSAPI_BASE = "https://statsapi.web.nhl.com"
NHL_STATSREST_BASE = "https://api.nhle.com/stats/rest"


def _soft_player_key(name: str) -> str:
    """Soft normalize for matching when playerId is missing."""
    s = str(name or "").strip()
    # Remove team suffixes like " (COL)" or " - COL" if present
    s = re.sub(r"\s*\([^\)]*\)\s*$", "", s)
    s = re.sub(r"\s*[-\u2013\u2014]\s*[A-Z]{2,4}\s*$", "", s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"\s+", " ", s).strip().lower()
    # Handle "Last, First" to "First Last"
    if "," in s:
        parts = [x.strip() for x in s.split(",", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            s = f"{parts[1]} {parts[0]}".strip()
    return s


def _http_get_json(url: str, timeout: int = 20):
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; PMSPool/1.0; +https://streamlit.app)",
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _nhl_get_teams() -> list[dict]:
    """Get team list from StatsAPI (stable)."""
    try:
        j = _http_get_json(f"{NHL_STATSAPI_BASE}/api/v1/teams")
        teams = j.get("teams", []) if isinstance(j, dict) else []
        out = []
        for t in teams:
            out.append(
                {
                    "teamId": t.get("id"),
                    "abbrev": t.get("abbreviation") or (t.get("triCode") if isinstance(t.get("triCode"), str) else None),
                    "name": t.get("name") or t.get("teamName") or "",
                }
            )
        return [x for x in out if x.get("teamId") and x.get("abbrev")]
    except Exception:
        return []


def _apiweb_roster_current(abbrev: str) -> list[int]:
    """api-web roster may be incomplete sometimes; we treat it as one source."""
    ids: set[int] = set()
    try:
        j = _http_get_json(f"{NHL_APIWEB_BASE}/v1/roster/{abbrev}/current")
        if isinstance(j, dict):
            # The response typically contains keys like forwards/defensemen/goalies
            for v in j.values():
                if isinstance(v, list):
                    for row in v:
                        if not isinstance(row, dict):
                            continue
                        pid = row.get("id") or row.get("playerId") or (row.get("person", {}) or {}).get("id")
                        try:
                            if pid is not None:
                                ids.add(int(pid))
                        except Exception:
                            pass
    except Exception:
        pass
    return sorted(ids)


def _statsapi_roster(team_id: int) -> list[int]:
    ids: set[int] = set()
    try:
        j = _http_get_json(f"{NHL_STATSAPI_BASE}/api/v1/teams/{int(team_id)}/roster")
        roster = (j.get("roster") if isinstance(j, dict) else None) or []
        for r0 in roster:
            if not isinstance(r0, dict):
                continue
            person = r0.get("person") or {}
            pid = person.get("id")
            try:
                if pid is not None:
                    ids.add(int(pid))
            except Exception:
                pass
    except Exception:
        pass
    return sorted(ids)


def _apiweb_player_landing(player_id: int) -> dict:
    try:
        return _http_get_json(f"{NHL_APIWEB_BASE}/v1/player/{int(player_id)}/landing")
    except Exception:
        return {}

@st.cache_data(ttl=24*3600, show_spinner=False)
def nhl_player_landing_cached(player_id: int) -> dict:
    """Cache 24h: player landing from api-web.nhle.com.
    Avoids repeated HTTP calls on reruns / dialogs."""
    try:
        pid = int(player_id or 0)
    except Exception:
        pid = 0
    if pid <= 0:
        return {}
    return _apiweb_player_landing(pid) or {}


# -------------------------------------------------
# NHL playerId lookup by name (fallback) + single-player DB upsert
# -------------------------------------------------

def _norm_fullname_for_match(s: str) -> str:
    s = str(s or "").strip().lower()
    # remove team suffixes like "(COL)" or "- COL"
    s = re.sub(r"\([^\)]*\)", " ", s)
    s = re.sub(r"\s+-\s+[a-z]{2,4}\s*$", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # remove punctuation
    s = re.sub(r"[^a-z0-9\s'-]", "", s)
    return s


@st.cache_data(ttl=24*3600, show_spinner=False)
def nhl_statsrest_all_players_cached(season_lbl: str | None) -> list[dict]:
    """Liste globale des joueurs via api.nhle.com/stats/rest (skaters + goalies).
    Retourne une liste de dicts contenant au moins: playerId, fullName, teamAbbrev, position.
    Cache 24h.
    """
    season_id = _nhl_season_id_from_label(season_lbl)
    if not season_id:
        return []

    def _fetch(kind: str) -> list[dict]:
        base = f"{NHL_STATSREST_BASE}/stats/rest/en/{kind}/summary"
        params = {
            "cayenneExp": f"seasonId={season_id}",
        }
        try:
            j = _http_get_json(base, params=params)
        except Exception:
            j = {}
        rows = (j.get("data") if isinstance(j, dict) else None) or []
        out = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            pid = r.get("playerId")
            if not pid:
                continue
            full = r.get("skaterFullName") or r.get("goalieFullName") or r.get("playerFullName") or r.get("fullName")
            full = str(full or "").strip()
            team = str(r.get("teamAbbrev") or "").strip()
            pos = str(r.get("positionCode") or r.get("position") or ("G" if kind=="goalie" else "") or "").strip()
            try:
                out.append({"playerId": int(pid), "fullName": full, "teamAbbrev": team, "position": pos})
            except Exception:
                continue
        return out

    # skaters + goalies
    players = _fetch("skater") + _fetch("goalie")
    return players

@st.cache_data(ttl=24*3600, show_spinner=False)
def nhl_find_playerid_by_name_cached(full_name: str, season_lbl: str | None = None) -> int:
    """Best-effort playerId lookup by player full name.

    ✅ Utilise api.nhle.com/stats/rest (liste globale skaters+goalies) plutôt que les rosters,
    car les endpoints roster sont parfois vides/instables.

    Retourne 0 si non trouvé.
    """
    target = _norm_fullname_for_match(full_name)
    if not target:
        return 0
    try:
        players = nhl_statsrest_all_players_cached(season_lbl)
        for p in players:
            nm = _norm_fullname_for_match(p.get("fullName",""))
            if nm and nm == target:
                try:
                    return int(p.get("playerId") or 0)
                except Exception:
                    return 0
    except Exception:
        return 0
    return 0
    try:
        teams_json = _http_get_json(f"{NHL_STATSAPI_BASE}/api/v1/teams")
        teams = (teams_json.get("teams") if isinstance(teams_json, dict) else None) or []
        for t in teams:
            if not isinstance(t, dict):
                continue
            tid = t.get("id")
            if tid is None:
                continue
            roster_json = _http_get_json(f"{NHL_STATSAPI_BASE}/api/v1/teams/{int(tid)}/roster")
            roster = (roster_json.get("roster") if isinstance(roster_json, dict) else None) or []
            for r0 in roster:
                if not isinstance(r0, dict):
                    continue
                person = r0.get("person") or {}
                pid = person.get("id")
                nm = person.get("fullName")
                if not pid or not nm:
                    continue
                if _norm_fullname_for_match(nm) == target:
                    try:
                        return int(pid)
                    except Exception:
                        return 0
    except Exception:
        return 0
    return 0

def upsert_single_player_from_api(player_id: int) -> bool:
    """Fetch landing and upsert minimal identity fields into hockey.players.csv.

    Preserves existing Level/Cap Hit if present.
    """
    try:
        pid = int(player_id or 0)
    except Exception:
        pid = 0
    if pid <= 0:
        return False

    landing = nhl_player_landing_cached(pid)
    if not landing:
        return False

    ident = _extract_player_identity(pid, landing)
    if not ident or not ident.get("Player"):
        return False

    # Load existing DB
    path = _first_existing(PLAYERS_DB_FALLBACKS)
    if not path:
        path = os.path.join(DATA_DIR, "hockey.players.csv")

    if os.path.exists(path):
        try:
            df = pd.read_csv(path)
        except Exception:
            df = pd.DataFrame()
    else:
        df = pd.DataFrame()

    if df is None or df.empty:
        df = pd.DataFrame(columns=["playerId","Player","Pos","Equipe","Shoots","Country","Level","Cap Hit"])

    # Ensure columns
    for col in ["playerId","Player","Pos","Equipe","Shoots","Country","Level","Cap Hit"]:
        if col not in df.columns:
            df[col] = ""

    # Match by playerId first
    try:
        df_pid = pd.to_numeric(df["playerId"], errors="coerce").fillna(0).astype(int)
    except Exception:
        df_pid = pd.Series([0]*len(df), dtype=int)

    mask = df_pid.eq(pid)
    if mask.any():
        i = int(df.index[mask][0])
        # Preserve Country/Level/Cap Hit
        ctry = df.at[i, "Country"] if "Country" in df.columns else ""
        lvl = df.at[i, "Level"] if "Level" in df.columns else ""
        cap = df.at[i, "Cap Hit"] if "Cap Hit" in df.columns else ""
        df.at[i, "playerId"] = pid
        df.at[i, "Player"] = ident.get("Player","")
        df.at[i, "Pos"] = ident.get("Pos","")
        df.at[i, "Equipe"] = ident.get("Equipe","")
        df.at[i, "Shoots"] = ident.get("Shoots","")
        df.at[i, "Country"] = ctry
        df.at[i, "Level"] = lvl
        df.at[i, "Cap Hit"] = cap
    else:
        # Append new row
        df = pd.concat([df, pd.DataFrame([{
            "playerId": pid,
            "Player": ident.get("Player",""),
            "Pos": ident.get("Pos",""),
            "Equipe": ident.get("Equipe",""),
            "Shoots": ident.get("Shoots",""),
            "Country": "",
            "Level": "",
            "Cap Hit": "",
        }])], ignore_index=True)

    try:
        df.to_csv(path, index=False)
        return True
    except Exception:
        return False

def _landing_field(landing: dict, path: list, default=""):
    cur = landing
    for key in path:
        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return default
    return cur if cur is not None else default


def _extract_player_identity(player_id: int, landing: dict) -> dict:
    """Best-effort extraction. We keep it flexible because NHL may evolve payloads."""
    def _g(path, default=""):
        cur = landing
        for key in path:
            if isinstance(cur, dict):
                cur = cur.get(key)
            else:
                return default
        return cur if cur is not None else default

    first = _g(["firstName", "default"], "") or _g(["firstName"], "")
    last = _g(["lastName", "default"], "") or _g(["lastName"], "")
    full = ("%s %s" % (str(first).strip(), str(last).strip())).strip() or str(_g(["fullName"], "") or "").strip()

    pos = str(_g(["position"], "") or _g(["positionCode"], "") or "").strip()
    shoots = str(_g(["shootsCatches"], "") or "").strip()

    team_abbrev = ""
    team = landing.get("currentTeam") if isinstance(landing, dict) else None
    if isinstance(team, dict):
        team_abbrev = str(team.get("abbrev") or team.get("triCode") or "").strip()

    return {
        "playerId": int(player_id),
        "Player": full,
        "Pos": pos,
        "Equipe": team_abbrev,
        "Shoots": shoots,
        "_player_key": _soft_player_key(full),
    }


def _nhl_season_id_from_label(season_lbl: str | None) -> str | None:
    """Convertit une saison UI (ex: '2025' ou '2025-2026') en seasonId NHL (ex: '20242025').
    Retourne None si impossible.
    """
    s = str(season_lbl or "").strip()
    if not s:
        return None
    # formats possibles: '2025', '2026', '2025-2026', '2025/2026', '2025 2026'
    s2 = re.sub(r"[^0-9]+", " ", s).strip()
    parts = [x for x in s2.split() if x.isdigit()]
    try:
        if len(parts) >= 2:
            y1, y2 = int(parts[0]), int(parts[1])
            if 1900 < y1 < 3000 and 1900 < y2 < 3000:
                return f"{y1:04d}{y2:04d}"
        if len(parts) == 1:
            y = int(parts[0])
            if 1900 < y < 3000:
                # convention: label '2025' => saison NHL 2024-2025
                return f"{y-1:04d}{y:04d}"
    except Exception:
        return None
    return None


def _statsrest_fetch_summary(kind: str, season_id: str) -> list[dict]:
    """Récupère un résumé (skater/goalie) via api.nhle.com/stats/rest.
    kind: 'skater' ou 'goalie'
    """
    kind = str(kind or "").strip().lower()
    if kind not in {"skater", "goalie"}:
        return []
    # Endpoint stats/rest (tables)
    # NOTE: l'API applique souvent un plafond de page (ex: 100) même si "limit" est plus grand.
    # => On pagine avec start/limit et on concatène.
    base = f"https://api.nhle.com/stats/rest/en/{kind}/summary"
    page_size = 100
    out: list[dict] = []

    start = 0
    # garde-fou (au cas où l'API boucle)
    for _ in range(0, 500):
        params = {
            "cayenneExp": f"seasonId={season_id}",
            "limit": str(page_size),
            "start": str(start),
        }
        try:
            r = requests.get(base, params=params, timeout=20)
            if r.status_code != 200:
                break
            js = r.json()
            data = js.get("data") if isinstance(js, dict) else None
            if not isinstance(data, list) or not data:
                break
            out.extend([d for d in data if isinstance(d, dict)])
            # dernière page
            if len(data) < page_size:
                break
            start += page_size
        except Exception:
            break

    return out



def update_players_db(
    path: str,
    season_lbl=None,
    fill_country: bool = True,
    resume_only: bool = False,
    roster_only: bool = False,
    save_every: int = 500,
    cache_path: str | None = None,
    progress_cb=None,
    max_calls: int = 5000,
    **_ignored,
):
    return _update_players_db_impl(
        path=path,
        season_lbl=season_lbl,
        fill_country=fill_country,
        resume_only=resume_only,
        roster_only=roster_only,
        save_every=save_every,
        cache_path=cache_path,
        progress_cb=progress_cb,
        max_calls=max_calls,
        **_ignored,
    )


# ==============================
# Backward-compatible alias
# ==============================

# ==============================
# Backward-compatible aliases (avoid recursion)
# ==============================
def update_players_db_via_nhl_api(*args, **kwargs):
    """Legacy alias used by some UI paths (singular)."""
    impl = globals().get("_update_players_db_impl_via_nhl_apis") or globals().get("_update_players_db_impl")
    if not callable(impl):
        raise RuntimeError("No NHL update implementation found")
    # This impl expects season_lbl only; ignore extra kwargs safely
    season_lbl = kwargs.get("season_lbl", None)
    return impl(season_lbl=season_lbl)

def update_players_db_via_nhl_apis(*args, **kwargs):
    """Legacy alias used by some UI paths (plural)."""
    return update_players_db_via_nhl_api(*args, **kwargs)


def _update_players_db_impl_via_nhl_apis(season_lbl: str | None = None) -> tuple[pd.DataFrame, dict]:
    """Met à jour data/hockey.players.csv en fusionnant des APIs NHL publiques.

    Source robuste (2026): api.nhle.com/stats/rest (skater/goalie summary) pour la liste des joueurs actifs.

    - Ajoute/MAJ identité: playerId, Player, Pos, Equipe
    - Préserve: Level (ELC/STD) et Cap Hit (ne jamais écraser si déjà présent)

    Retourne: (df_updated, stats)
    """
    # Load existing DB if present
    path = _first_existing(PLAYERS_DB_FALLBACKS)
    if not path:
        path = os.path.join(DATA_DIR, "hockey.players.csv")

    if os.path.exists(path):
        try:
            df0 = pd.read_csv(path)
        except Exception:
            df0 = pd.DataFrame()
    else:
        df0 = pd.DataFrame()

    # Normalize columns
    if "Player" not in df0.columns:
        for alt in ["Joueur", "Name", "Nom"]:
            if alt in df0.columns:
                df0["Player"] = df0[alt]
                break
    if "Player" not in df0.columns:
        df0["Player"] = ""

    if "Level" not in df0.columns:
        df0["Level"] = ""
    if "Cap Hit" not in df0.columns:
        for alt in ["Salaire", "Salary", "CapHit", "AAV"]:
            if alt in df0.columns:
                df0["Cap Hit"] = df0[alt]
                break
        if "Cap Hit" not in df0.columns:
            df0["Cap Hit"] = ""

    if "playerId" not in df0.columns:
        df0["playerId"] = pd.NA

    for c in ["Pos", "Equipe", "Shoots"]:
        if c not in df0.columns:
            df0[c] = ""

    df0["Player"] = df0["Player"].astype(str).fillna("").map(lambda x: x.strip())
    df0["_player_key"] = df0["Player"].map(_soft_player_key)

    # Index existant par playerId
    existing_by_id: dict[int, int] = {}
    for i, row in df0.iterrows():
        pid = row.get("playerId")
        try:
            if pd.notna(pid):
                existing_by_id[int(pid)] = i
        except Exception:
            pass

    # SeasonId NHL
    season_id = _nhl_season_id_from_label(season_lbl) or _nhl_season_id_from_label(st.session_state.get("season"))

    stats = {
        "season_lbl": str(season_lbl or "").strip(),
        "season_id": season_id or "",
        "unique_player_ids": 0,
        "from_statsrest_skaters": 0,
        "from_statsrest_goalies": 0,
        "updated_rows": 0,
        "added_rows": 0,
        "kept_level": 0,
        "kept_cap_hit": 0,
        "landing_ok": 0,
        "landing_fail": 0,
    }

    # If roster_only is enabled but roster isn't loaded in this context,
    # we will fallback to full DB (roster_set=None). If roster_set becomes empty, we'd get 0 candidates.
    # (Handled above by setting roster_set=None when empty.)
    if not season_id:
        # Pas de seasonId => on ne peut pas requêter stats/rest
        if "_player_key" in df0.columns:
            df0 = df0.drop(columns=["_player_key"], errors="ignore")
        out_path = _first_existing(PLAYERS_DB_FALLBACKS) or os.path.join(DATA_DIR, "hockey.players.csv")
        df0.to_csv(out_path, index=False)
        return df0, stats

    skaters = _statsrest_fetch_summary("skater", season_id)
    goalies = _statsrest_fetch_summary("goalie", season_id)
    stats["from_statsrest_skaters"] = len(skaters)
    stats["from_statsrest_goalies"] = len(goalies)

    def _row_from_statsrest(d: dict, is_goalie: bool) -> dict | None:
        if not isinstance(d, dict):
            return None
        pid = d.get("playerId")
        try:
            pid = int(pid)
        except Exception:
            return None

        name = str(d.get("skaterFullName") or d.get("goalieFullName") or d.get("playerName") or d.get("fullName") or "").strip()
        team = str(d.get("teamAbbrev") or d.get("team" ) or "").strip()
        pos = str(d.get("positionCode") or d.get("position") or ("G" if is_goalie else "")).strip()
        if is_goalie:
            pos = "G"

        return {
            "playerId": pid,
            "Player": name,
            "Pos": pos,
            "Equipe": team,
            "Shoots": "",  # pas fourni par stats/rest summary
            "_player_key": _soft_player_key(name),
        }

    api_rows: dict[int, dict] = {}
    for d in skaters:
        r = _row_from_statsrest(d, is_goalie=False)
        if r:
            api_rows[r["playerId"]] = r
    for d in goalies:
        r = _row_from_statsrest(d, is_goalie=True)
        if r:
            api_rows[r["playerId"]] = r

    all_ids = sorted(api_rows.keys())
    stats["unique_player_ids"] = len(all_ids)

    new_rows = []

    for pid in all_ids:
        info = api_rows[pid]
        if pid in existing_by_id:
            i = existing_by_id[pid]
            level_before = str(df0.at[i, "Level"] if "Level" in df0.columns else "").strip()
            cap_before = str(df0.at[i, "Cap Hit"] if "Cap Hit" in df0.columns else "").strip()

            df0.at[i, "playerId"] = pid
            df0.at[i, "Player"] = info.get("Player", "")
            df0.at[i, "Pos"] = info.get("Pos", "")
            df0.at[i, "Equipe"] = info.get("Equipe", "")
            df0.at[i, "Shoots"] = info.get("Shoots", "")

            if level_before:
                df0.at[i, "Level"] = level_before
                stats["kept_level"] += 1
            if cap_before:
                df0.at[i, "Cap Hit"] = cap_before
                stats["kept_cap_hit"] += 1

            stats["updated_rows"] += 1
        else:
            # Match par nom (fallback) si déjà dans DB sans playerId
            key = info.get("_player_key", "")
            matched_i = None
            if key:
                hits = df0.index[df0.get("_player_key", pd.Series([], dtype=str)).astype(str) == key].tolist()
                if hits:
                    matched_i = hits[0]
            if matched_i is not None:
                i = matched_i
                df0.at[i, "playerId"] = pid
                df0.at[i, "Player"] = info.get("Player", "")
                df0.at[i, "Pos"] = info.get("Pos", "")
                df0.at[i, "Equipe"] = info.get("Equipe", "")
                df0.at[i, "Shoots"] = info.get("Shoots", "")
                stats["updated_rows"] += 1
            else:
                new_rows.append(
                    {
                        "playerId": pid,
                        "Player": info.get("Player", ""),
                        "Pos": info.get("Pos", ""),
                        "Equipe": info.get("Equipe", ""),
                        "Shoots": info.get("Shoots", ""),
                        "Level": "",
                        "Cap Hit": "",
                    }
                )
                stats["added_rows"] += 1

    if new_rows:
        df_add = pd.DataFrame(new_rows)
        df0 = pd.concat([df0.drop(columns=[c for c in ["_player_key"] if c in df0.columns]), df_add], ignore_index=True)
    else:
        df0 = df0.drop(columns=["_player_key"], errors="ignore")

    # Final cleanup
    for c in ["Player", "Level", "Cap Hit", "Pos", "Equipe", "Shoots"]:
        if c not in df0.columns:
            df0[c] = ""
        df0[c] = df0[c].astype(str).fillna("").map(lambda x: x.strip())

    df0["Level"] = df0["Level"].astype(str).map(lambda x: (x or "").strip().upper())
    df0.loc[~df0["Level"].isin(["ELC", "STD"]), "Level"] = ""

    out_path = _first_existing(PLAYERS_DB_FALLBACKS) or os.path.join(DATA_DIR, "hockey.players.csv")
    df0.to_csv(out_path, index=False)
    return df0, stats


# =====================================================
# PLAYERS DB — wrappers (used by Admin UI + other tabs)
#   ✅ expose update_players_db() so older UI/buttons work
#   ✅ fill missing playerId via NHL search as fallback
#   ✅ (optionnel) fill Country using player landing endpoint
# =====================================================

_COUNTRYNAME_TO2 = {
    "canada": "CA",
    "united states": "US",
    "usa": "US",
    "sweden": "SE",
    "finland": "FI",
    "czechia": "CZ",
    "czech republic": "CZ",
    "slovakia": "SK",
    "switzerland": "CH",
    "germany": "DE",
    "russia": "RU",
    "latvia": "LV",
    "norway": "NO",
    "denmark": "DK",
    "austria": "AT",
    "france": "FR",
}

_COUNTRY3_TO2 = {
    "CAN": "CA",
    "USA": "US",
    "SWE": "SE",
    "FIN": "FI",
    "CZE": "CZ",
    "SVK": "SK",
    "CHE": "CH",
    "DEU": "DE",
    "RUS": "RU",
    "LVA": "LV",
    "NOR": "NO",
    "DNK": "DK",
    "AUT": "AT",
    "FRA": "FR",
}


def _to_iso2_country(raw: str) -> str:
    s = str(raw or "").strip()
    if not s or s.lower() in {"nan", "none", "null", "0", "-"}:
        return ""
    # already ISO2
    if len(s) == 2 and s.isalpha():
        return s.upper()
    # ISO3
    if len(s) == 3 and s.isalpha():
        return _COUNTRY3_TO2.get(s.upper(), "")
    # country name
    return _COUNTRYNAME_TO2.get(s.lower(), "")


def _nhl_search_playerid(name: str) -> int | None:
    """Fallback search when playerId is missing (SECURE).

    Uses NHL public search endpoint and returns a playerId ONLY if:
      - an exact (soft-normalized) name match exists, OR
      - there is a single result whose last name matches and first initial matches.

    Otherwise returns None (prevents wrong IDs).
    """
    q = str(name or "").strip()
    if not q:
        return None

    nk = _soft_player_key(q)
    url = "https://search.d3.nhle.com/api/v1/search/player"
    try:
        r = requests.get(url, params={"culture": "en-us", "limit": "10", "q": q}, timeout=15)
        if r.status_code != 200:
            return None
        js = r.json()
        items = js.get("docs") if isinstance(js, dict) else None
        if not isinstance(items, list) or not items:
            return None

        # 1) exact soft match
        for it in items:
            try:
                pid_i = int(it.get("playerId") or it.get("id") or 0)
            except Exception:
                continue
            nm = str(it.get("name") or it.get("playerName") or "").strip()
            if nm and _soft_player_key(nm) == nk:
                return pid_i

        # 2) safe single-candidate heuristic (last name + first initial)
        # Split requested name
        parts = q.split()
        if len(parts) >= 2:
            first = parts[0].strip().lower()
            last = parts[-1].strip().lower()
            first_init = first[:1]
            candidates = []
            for it in items:
                nm = str(it.get("name") or it.get("playerName") or "").strip()
                if not nm:
                    continue
                nm_parts = nm.split()
                if len(nm_parts) < 2:
                    continue
                f2 = nm_parts[0].strip().lower()
                l2 = nm_parts[-1].strip().lower()
                if l2 == last and f2[:1] == first_init:
                    candidates.append(it)
            if len(candidates) == 1:
                it = candidates[0]
                try:
                    return int(it.get("playerId") or it.get("id") or 0) or None
                except Exception:
                    return None

        return None
    except Exception:
        return None


def _nhl_landing_country(pid: int) -> str:
    """Get Country (ISO2) from NHL player landing endpoint (best-effort).

    Returns ISO2 (CA/US/SE/FI/...) when possible.
    Accepts birthCountryCode/nationalityCode as ISO3 or ISO2, plus some older keys.
    """
    try:
        pid_i = int(pid)
    except Exception:
        return ""
    url = f"https://api-web.nhle.com/v1/player/{pid_i}/landing"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return ""
        js = r.json() if r.text else {}
        if not isinstance(js, dict):
            return ""

        # Prefer codes (most reliable)
        code = (
            js.get("birthCountryCode")
            or js.get("nationalityCode")
            or js.get("countryCode")
            or ""
        )
        code = str(code or "").strip().upper()

        # Some payloads provide names instead of codes
        raw = (
            js.get("nationality")
            or js.get("birthCountry")
            or (js.get("birthPlace") or {}).get("country")
            or ""
        )
        raw = str(raw or "").strip()

        # Convert ISO3 -> ISO2 if needed
        if len(code) == 2 and code.isalpha():
            return code
        if len(code) == 3 and code.isalpha():
            # minimal ISO3 -> ISO2 mapping for hockey countries
            iso3_to2 = {
                "CAN":"CA","USA":"US","SWE":"SE","FIN":"FI","RUS":"RU","CZE":"CZ","SVK":"SK",
                "DEU":"DE","CHE":"CH","AUT":"AT","DNK":"DK","NOR":"NO","LVA":"LV","SVN":"SI",
                "FRA":"FR","GBR":"GB","IRL":"IE","ITA":"IT","NLD":"NL","BEL":"BE","POL":"PL",
                "UKR":"UA","BLR":"BY","KAZ":"KZ","AUS":"AU","JPN":"JP","KOR":"KR","CHN":"CN",
            }
            return iso3_to2.get(code, "")

        # Last resort: country name -> ISO2
        return _to_iso2_country(raw)
    except Exception:
        return ""



def update_players_db(
    path: str | None = None,
    season_lbl: str | None = None,
    fill_country: bool = True,
    *,
    resume_only: bool = False,
    roster_only: bool = False,
    save_every: int = 500,
    cache_path: str | None = None,
    progress_cb=None,
    max_calls: int = 300,
    **_ignored,
) -> tuple[pd.DataFrame, dict]:
    """Chunked, resume-safe country fill for hockey.players.csv.

    Key goals:
    - Never time out: processes at most `max_calls` rows per click.
    - Real resume: persists cursor + phase in data/nhl_country_checkpoint.json
    - Uses persistent JSON cache (data/nhl_country_cache.json) for name->id and id->country.
    - Optional roster_only: restrict to players present in current roster dataframe (st.session_state['data']).
    """

    # ---- paths
    path = str(path or os.path.join(DATA_DIR, "hockey.players.csv"))
    if not os.path.isabs(path):
        path = os.path.join(DATA_DIR, path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    if not cache_path:
        cache_path = _nhl_cache_path_default() if "_nhl_cache_path_default" in globals() else os.path.join(DATA_DIR, "nhl_country_cache.json")
    if not os.path.isabs(cache_path):
        cache_path = os.path.join(DATA_DIR, cache_path)

    ckpt_path = os.path.join(DATA_DIR, "nhl_country_checkpoint.json")

    # ---- load df
    try:
        df = pd.read_csv(path) if os.path.exists(path) else pd.DataFrame()
    except Exception:
        df = pd.DataFrame()

    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df, {"error": "Players DB vide ou introuvable", "path": path}

    # normalize columns
    if "Player" not in df.columns and "Joueur" in df.columns:
        df["Player"] = df["Joueur"]
    if "Player" not in df.columns:
        return df, {"error": "Colonne 'Player' manquante dans hockey.players.csv", "path": path}
    if "playerId" not in df.columns:
        df["playerId"] = ""
    if "Country" not in df.columns:
        df["Country"] = ""

    # ---- roster_only filter (by Player name)
    roster_set = None
    if roster_only:
        try:
            roster_df = st.session_state.get("data")
            # If roster isn't loaded in this context, do NOT block processing (fallback to full DB)
            if not (isinstance(roster_df, pd.DataFrame) and not roster_df.empty):
                roster_set = None
            else:
                col = "Joueur" if "Joueur" in roster_df.columns else ("Player" if "Player" in roster_df.columns else None)
                if not col:
                    roster_set = None
                else:
                    vals = [str(x).strip() for x in roster_df[col].dropna().tolist()]
                    vals = [v for v in vals if v]
                    roster_set = set(vals) if vals else None
        except Exception:
            roster_set = None

    def _in_scope(player_name: str) -> bool:
        if roster_set is None:
            return True
        return str(player_name or "").strip() in roster_set

    # ---- cache helpers (expects dict; tolerate missing)
    def _load_cache():
        try:
            if os.path.exists(cache_path):
                with open(cache_path, "r", encoding="utf-8") as f:
                    return json.load(f) or {}
        except Exception:
            pass
        return {}

    def _save_json_atomic(pth: str, obj: dict):
        os.makedirs(os.path.dirname(pth) or ".", exist_ok=True)
        tmp = pth + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, pth)

    def _save_csv_atomic(pth: str, dff: pd.DataFrame):
        os.makedirs(os.path.dirname(pth) or ".", exist_ok=True)
        tmp = pth + ".tmp"
        dff.to_csv(tmp, index=False)
        os.replace(tmp, pth)

    cache = _load_cache()

    # ---- checkpoint
    ckpt = {}
    try:
        if os.path.exists(ckpt_path):
            with open(ckpt_path, "r", encoding="utf-8") as f:
                ckpt = json.load(f) or {}
    except Exception:
        ckpt = {}

    # Reset cursor when starting fresh (not resume) OR when roster_only setting changed
    if not resume_only:
        ckpt = {}
    if ckpt.get("roster_only") != bool(roster_only):
        ckpt = {}

    phase = ckpt.get("phase") or "playerId"  # playerId -> Country
    cursor = int(ckpt.get("cursor") or 0)

    stats = {
        "path": path,
        "cache_path": cache_path,
        "phase": phase,
        "cursor_start": cursor,
        "max_calls": int(max_calls or 0),
        "roster_only": bool(roster_only),
        "filled_playerid_search": 0,
        "filled_country_landing": 0,
        "nhl_ids_added": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "skipped_cached_fail": 0,
        "saved_increments": 0,
        "last_phase": phase,
        "last_index": cursor,
        "last_total": 0,
        "remaining": 0,
    }

    # ---- normalization key helpers
    def _norm_name(name: str) -> str:
        return re.sub(r"\s+", " ", str(name or "").strip()).lower()

    def _name_key(name: str) -> str:
        return "name:" + _norm_name(name)

    def _id_key(pid: str) -> str:
        return "id:" + str(pid or "").strip()

    # ---- NHL lookup helpers (expected to exist in your app)
    # _nhl_search_player_id_by_name(name)->str  and _nhl_country_from_player_id(pid)->str
    nhl_search = globals().get("_nhl_search_player_id_by_name")
    nhl_country = globals().get("_nhl_country_from_player_id")

    if not callable(nhl_search) or not callable(nhl_country):
        # fallback to legacy helper names if present
        nhl_search = nhl_search or globals().get("nhl_search_player_id_by_name")
        nhl_country = nhl_country or globals().get("nhl_country_from_player_id")

    if not callable(nhl_search) or not callable(nhl_country):
        return df, {"error": "Helpers NHL manquants (_nhl_search_player_id_by_name / _nhl_country_from_player_id)", "phase": phase}

    # ---- candidate builders
    def build_candidates_playerid():
        idxs = []
        for i, row in df.iterrows():
            if not _in_scope(row.get("Player","")):
                continue
            if str(row.get("playerId","")).strip():
                continue
            idxs.append(int(i))
        return idxs

    def build_candidates_country():
        idxs = []
        for i, row in df.iterrows():
            if not _in_scope(row.get("Player","")):
                continue
            if not str(row.get("playerId","")).strip():
                continue
            if str(row.get("Country","")).strip():
                continue
            idxs.append(int(i))
        return idxs

    # ---- run chunk
    processed = 0
    save_counter = 0

    while processed < int(max_calls or 0):
        if phase == "playerId":
            cands = build_candidates_playerid()
        else:
            cands = build_candidates_country()

        total = len(cands)
        stats["last_total"] = total
        remaining = max(total - cursor, 0)
        stats["remaining"] = remaining

        # Update UI progress (show remaining-based total)
        if progress_cb:
            try:
                progress_cb(min(cursor, total), max(total, 1), phase)
            except Exception:
                pass

        # Finished this phase -> switch
        if cursor >= total:
            if phase == "playerId":
                phase = "Country"
                cursor = 0
                stats["last_phase"] = phase
                stats["last_index"] = 0
                # save checkpoint immediately
                ckpt = {"phase": phase, "cursor": cursor, "roster_only": bool(roster_only)}
                _save_json_atomic(ckpt_path, ckpt)
                continue
            break  # done

        idx = cands[cursor]
        row = df.loc[idx]
        player = str(row.get("Player","")).strip()

        # ---- playerId fill
        if phase == "playerId":
            k = _name_key(player)
            cached = cache.get(k)
            if cached is not None:
                # already attempted
                pid = str((cached or {}).get("nhl_id") or "").strip()
                if pid:
                    df.at[idx, "playerId"] = pid
                    stats["filled_playerid_search"] += 1
                    stats["cache_hits"] += 1
                else:
                    stats["skipped_cached_fail"] += 1
                    stats["cache_hits"] += 1
            else:
                pid = ""
                try:
                    pid = str(nhl_search(player) or "").strip()
                except Exception:
                    pid = ""
                cache[k] = {"nhl_id": pid, "ok": bool(pid), "ts": time.time()}
                stats["cache_misses"] += 1
                if pid:
                    df.at[idx, "playerId"] = pid
                    stats["filled_playerid_search"] += 1
                    stats["nhl_ids_added"] += 1

        # ---- country fill
        else:
            pid = str(row.get("playerId","")).strip()
            k = _id_key(pid)
            cached = cache.get(k)
            if cached is not None and str((cached or {}).get("country") or "").strip():
                df.at[idx, "Country"] = str(cached.get("country") or "").strip()
                stats["filled_country_landing"] += 1
                stats["cache_hits"] += 1
            elif cached is not None and not str((cached or {}).get("country") or "").strip():
                stats["skipped_cached_fail"] += 1
                stats["cache_hits"] += 1
            else:
                cc = ""
                try:
                    cc = str(nhl_country(pid) or "").strip()
                except Exception:
                    cc = ""
                cache[k] = {"country": cc, "ok": bool(cc), "ts": time.time()}
                stats["cache_misses"] += 1
                if cc:
                    df.at[idx, "Country"] = cc
                    stats["filled_country_landing"] += 1

        # advance cursor
        cursor += 1
        processed += 1
        save_counter += 1

        # update stats + UI sticky last index
        stats["last_phase"] = phase
        stats["last_index"] = cursor
        try:
            st.session_state["pdb_last"] = {"phase": phase, "index": cursor, "total": max(total, 1)}
        except Exception:
            pass

        # save incrementally
        if save_every and save_counter >= int(save_every):
            try:
                _save_csv_atomic(path, df)
                _save_json_atomic(cache_path, cache)
                ckpt = {"phase": phase, "cursor": cursor, "roster_only": bool(roster_only)}
                _save_json_atomic(ckpt_path, ckpt)
                stats["saved_increments"] += 1
            except Exception as e:
                stats["save_error"] = f"{type(e).__name__}: {e}"
            save_counter = 0

        # micro-yield to keep session alive
        if processed % 50 == 0:
            try:
                time.sleep(0.05)
            except Exception:
                pass

    # final save + checkpoint
    try:
        _save_csv_atomic(path, df)
        _save_json_atomic(cache_path, cache)
        ckpt = {"phase": phase, "cursor": cursor, "roster_only": bool(roster_only)}
        _save_json_atomic(ckpt_path, ckpt)
        stats["saved_increments"] += 1
    except Exception as e:
        stats["save_error"] = f"{type(e).__name__}: {e}"

    return df, stats


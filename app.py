from __future__ import annotations

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
    try:
        if not csv_path or not os.path.exists(csv_path):
            return pd.DataFrame()
        return pd.read_csv(csv_path)
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


def update_players_db_via_nhl_apis(season_lbl: str | None = None) -> tuple[pd.DataFrame, dict]:
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
    """Fallback search when playerId is missing.

    Uses NHL public search endpoint (best-effort).
    Returns best-matching playerId or None.
    """
    q = str(name or "").strip()
    if not q:
        return None
    # Endpoint used by nhl.com search (stable-ish)
    url = "https://search.d3.nhle.com/api/v1/search/player"
    try:
        r = requests.get(url, params={"culture": "en-us", "limit": "10", "q": q}, timeout=15)
        if r.status_code != 200:
            return None
        js = r.json()
        items = js.get("players") if isinstance(js, dict) else js
        if not isinstance(items, list) or not items:
            return None
        # Pick first exact-ish match by normalized name
        nk = _soft_player_key(q)
        best = None
        for it in items:
            if not isinstance(it, dict):
                continue
            pid = it.get("playerId") or it.get("id")
            try:
                pid_i = int(pid)
            except Exception:
                continue
            nm = str(it.get("name") or it.get("playerName") or "").strip()
            if nm and _soft_player_key(nm) == nk:
                return pid_i
            if best is None:
                best = pid_i
        return best
    except Exception:
        return None


def _nhl_landing_country(pid: int) -> str:
    """Get Country from player landing endpoint (best-effort)."""
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
        raw = (
            js.get("nationality")
            or js.get("birthCountry")
            or (js.get("birthPlace") or {}).get("country")
            or ""
        )
        return _to_iso2_country(raw)
    except Exception:
        return ""


def update_players_db(path: str | None = None, season_lbl: str | None = None, fill_country: bool = True) -> tuple[pd.DataFrame, dict]:
    """Wrapper attendu par l'UI Admin.

    - Met à jour via stats/rest (skaters+goalies)
    - Puis complète les playerId manquants par search (fallback)
    - Puis (optionnel) complète Country via landing endpoint
    """
    # 1) Base update
    df_upd, stats = update_players_db_via_nhl_apis(season_lbl=season_lbl)

    # Determine path
    if not path:
        path = _first_existing(PLAYERS_DB_FALLBACKS) or os.path.join(DATA_DIR, "hockey.players.csv")

    df = df_upd.copy() if isinstance(df_upd, pd.DataFrame) else pd.DataFrame()
    if df.empty:
        try:
            df.to_csv(path, index=False)
        except Exception:
            pass
        return df, stats

    # Ensure columns
    if "Player" not in df.columns:
        df["Player"] = ""
    if "playerId" not in df.columns:
        df["playerId"] = pd.NA
    if "Country" not in df.columns:
        df["Country"] = ""

    # 2) Fill missing playerId using search
    missing_pid = df["playerId"].isna() | df["playerId"].astype(str).str.strip().eq("")
    stats["filled_playerid_search"] = 0
    if missing_pid.any():
        for i in df.index[missing_pid].tolist():
            nm = str(df.at[i, "Player"] or "").strip()
            if not nm:
                continue
            pid = _nhl_search_playerid(nm)
            if pid:
                df.at[i, "playerId"] = int(pid)
                stats["filled_playerid_search"] += 1

    # 3) Fill Country (only if empty) using landing
    stats["filled_country_landing"] = 0
    if fill_country:
        miss_cty = df["Country"].astype(str).str.strip().eq("")
        if miss_cty.any():
            for i in df.index[miss_cty].tolist():
                pid = df.at[i, "playerId"]
                try:
                    pid_i = int(pid)
                except Exception:
                    continue
                iso2 = _nhl_landing_country(pid_i)
                if iso2:
                    df.at[i, "Country"] = iso2
                    stats["filled_country_landing"] += 1

    # Save back
    try:
        df.to_csv(path, index=False)
    except Exception:
        pass

    # Refresh session cache if present
    try:
        st.session_state["players_db"] = df
    except Exception:
        pass

    return df, stats


# =====================================================
# PATHS — repo local (Streamlit Cloud safe)
#   ✅ Place tes logos à côté de app.py:
#      - logo_pool.png
#      - gm_logo.png
# =====================================================
APP_DIR = os.path.dirname(os.path.abspath(__file__))

def _resolve_local_logo(candidates: list[str]) -> str:
    """Retourne le 1er fichier existant (recherche robuste).

    Ordre de recherche:
      1) APP_DIR (dossier de app.py)
      2) CWD (working dir Streamlit)
      3) data/ (si présent)
    """
    search_dirs = [APP_DIR, os.getcwd(), os.path.join(os.getcwd(), "data"), os.path.join(APP_DIR, "data")]
    for name in candidates:
        for d in search_dirs:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
    # chemin attendu (même si absent) pour diagnostic
    return os.path.join(APP_DIR, candidates[0])  # chemin attendu (même si absent)

# Logos critiques (local, stable) — mets-les à côté de app.py
LOGO_POOL_FILE = _resolve_local_logo(["logo_pool.png","Logo_Pool.png","LOGO_POOL.png","logo_pool.jpg","Logo_Pool.jpg"])
GM_LOGO_FILE = _resolve_local_logo(["gm_logo.png","GM_LOGO.png","gm_logo.jpg"])
# =====================================================
# STREAMLIT CONFIG (MUST BE FIRST STREAMLIT COMMAND)
# =====================================================
# --- plafonds par défaut (évite cap=0)
if "PLAFOND_GC" not in st.session_state or int(st.session_state.get("PLAFOND_GC") or 0) <= 0:
    st.session_state["PLAFOND_GC"] = 95_500_000
if "PLAFOND_CE" not in st.session_state or int(st.session_state.get("PLAFOND_CE") or 0) <= 0:
    st.session_state["PLAFOND_CE"] = 47_750_000

# =====================================================
# GM LOGO (cute) — place gm_logo.png in the project root (same folder as app.py)
# =====================================================
LEGACY_GM_LOGO_FILE = None  # v20: removed duplicate


def _gm_logo_data_uri() -> str | None:
    """Return gm_logo.png as a data URI (base64) so we can style it via HTML/CSS."""
    path = str(GM_LOGO_FILE or "").strip()
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        # PNG expected; if you switch formats, update mime.
        return f"data:image/png;base64,{b64}"
    except Exception:
        return None


def render_gm_logo(active: bool, width: int = 40, tooltip: str = "Gestion d’équipe"):
    """
    GM logo with:
      - grayscale when inactive
      - small hover tooltip
    (Same approach can be reused for Admin later.)
    """
    uri = _gm_logo_data_uri()
    if not uri:
        return

    cls = "gm-logo active" if active else "gm-logo inactive"
    # title = native browser tooltip (simple + reliable)
    st.session_state['_theme_css_injected'] = True
    st.markdown(
        f"""
        <div class="gm-logo-wrap" title="{html.escape(tooltip)}">
            <img class="{cls}" src="{uri}" width="{int(width)}" />
        </div>
        """,
        unsafe_allow_html=True,
    )


# Backward compatibility (if some older blocks still call it)
def _render_gm_logo(width: int = 36):
    render_gm_logo(active=True, width=width)


# Anti double rerun (zéro surprise)
st.session_state["_rerun_requested"] = False

# =====================================================
# THEME
#   (retiré: pas de Dark/Light)
# =====================================================


# =====================================================
# CSS — Micro-animations + Alertes visuelles + UI polish
#   ✅ coller UNE seule fois, au top du fichier
# =====================================================
# =====================================================
# THEME — une seule injection CSS (Règles d’or)
#   ✅ 1 thème, 1 injection
#   ✅ aucun CSS ailleurs
# =====================================================
THEME_CSS = """<style>

/* v35 Level badges */
.levelBadge{
  display:inline-block;
  padding:2px 10px;
  border-radius:999px;
  font-weight:800;
  font-size:0.82rem;
  letter-spacing:0.4px;
  border:1px solid rgba(255,255,255,0.14);
  background: rgba(255,255,255,0.06);
}
.levelBadge.std{ }
.levelBadge.elc{ }
.levelBadge.unk{
  opacity:0.85;
}
.levelWarn{
  display:inline-block;
  padding:2px 10px;
  border-radius:999px;
  font-weight:800;
  font-size:0.82rem;
  border:1px solid rgba(255,166,0,0.35);
  background: rgba(255,166,0,0.10);
}



/* v28 centered broadcast */
.pms-center-stack { padding: 18px 16px; }
.pms-center-stack img { max-height: 260px; width: auto; }
.pms-under{
  text-align:center;
  font-weight: 800;
  font-size: 2.2rem;
  letter-spacing: 2px;
  margin-top: 6px;
  text-shadow: 0 10px 28px rgba(0,0,0,0.35);
}
.pms-side-emoji{
  font-size: 2.2rem;
  line-height: 1;
  opacity: 0.95;
  filter: drop-shadow(0 12px 24px rgba(0,0,0,0.35));
  display:flex;
  justify-content:center;
  align-items:center;
  height: 100%;
}
/* réduire l’espace au-dessus (blend avec toolbar streamlit) */
section.main > div { padding-top: 0.25rem; }



/* v27: blend the Streamlit top bar line */
section.main > div { padding-top: 0.5rem; }



/* v26 broadcast header */
.pms-broadcast-bar{
  border-radius: 18px;
  padding: 18px 16px;
  margin-top: -6px;
  background: linear-gradient(90deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02), rgba(255,255,255,0.05));
  border: 1px solid rgba(255,255,255,0.10);
  box-shadow: 0 14px 40px rgba(0,0,0,0.30);

}
.pms-title{
  text-shadow: 0 10px 28px rgba(0,0,0,0.35);
  letter-spacing: 1px;
}


/* =========================================
       ✨ Micro animations (douces)
       ========================================= */
    .fade-in { animation: fadeIn 180ms ease-out both; }
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(2px); }
        to   { opacity: 1; transform: translateY(0); }
    }

    .lift { transition: transform 120ms ease, box-shadow 120ms ease; }
    .lift:hover { transform: translateY(-1px); box-shadow: 0 6px 18px rgba(0,0,0,0.35); }

    .pulse-soft { animation: pulseSoft 1.6s ease-in-out infinite; }
    @keyframes pulseSoft {
        0%, 100% { box-shadow: 0 0 0 rgba(0,0,0,0); }
        50% { box-shadow: 0 0 0 6px rgba(34,197,94,0.06); }
    }

    .pulse-warn { animation: pulseWarn 1.8s ease-in-out infinite; }
    @keyframes pulseWarn {
        0%, 100% { box-shadow: 0 0 0 rgba(0,0,0,0); }
        50% { box-shadow: 0 0 0 7px rgba(245,158,11,0.10); }
    }

    .pulse-danger { animation: pulseDanger 1.7s ease-in-out infinite; }
    @keyframes pulseDanger {
        0%, 100% { box-shadow: 0 0 0 rgba(0,0,0,0); }
        50% { box-shadow: 0 0 0 7px rgba(239,68,68,0.10); }
    }

    /* =========================================
       🏷️ Pills / Badges (OK / Warning / Danger)
       ========================================= */
    .pill {
        display: inline-flex;
        align-items: center;
        gap: 0.45rem;
        padding: 0.24rem 0.55rem;
        border-radius: 999px;
        border: 1px solid #374151;
        background: #111827;
        color: #e5e7eb;
        font-size: 0.82rem;
        line-height: 1;
        white-space: nowrap;
        user-select: none;
        transition: transform 120ms ease, background 120ms ease, border-color 120ms ease;
    }
    .pill:hover { transform: translateY(-1px); }

    .pill .dot {
        width: 8px; height: 8px;
        border-radius: 999px;
        background: #6b7280;
    }

    .pill-ok     { border-color: rgba(34,197,94,0.35);  background: rgba(34,197,94,0.08); }
    .pill-ok .dot { background: #22c55e; }

    .pill-warn     { border-color: rgba(245,158,11,0.40); background: rgba(245,158,11,0.10); }
    .pill-warn .dot { background: #f59e0b; }

    .pill-danger     { border-color: rgba(239,68,68,0.45); background: rgba(239,68,68,0.10); }
    .pill-danger .dot { background: #ef4444; }

    /* =========================================
       🧾 Carte d’alerte (bande à gauche)
       ========================================= */
    .alert-card {
        border: 1px solid #1f2937;
        background: #111827;
        border-radius: 12px;
        padding: 0.65rem 0.8rem;
    }
    .alert-card.ok     { border-left: 4px solid #22c55e; }
    .alert-card.warn   { border-left: 4px solid #f59e0b; }
    .alert-card.danger { border-left: 4px solid #ef4444; }

    .muted { color: #9ca3af; font-size: 0.85rem; }

    /* =========================================
       🔝 NAV (radio horizontale) — actif/inactif clair
       ========================================= */
    div[role="radiogroup"] > label {
        background-color: transparent;
        padding: 0.4rem 0.8rem;
        border-radius: 8px;
        font-weight: 500;
        color: #9ca3af;
        transition: all 0.15s ease-in-out;
    }
    div[role="radiogroup"] > label:hover {
        background-color: #1f2937;
        color: #e5e7eb;
    }
    div[role="radiogroup"] > label[data-selected="true"] {
        background-color: #1f2937;
        color: #f9fafb;
        box-shadow: inset 0 -2px 0 #22c55e;
    }

    /* =========================================
       🔘 Boutons uniformes (global)
       ========================================= */
    button {
        background-color: #1f2937 !important;
        color: #f9fafb !important;
        border-radius: 10px !important;
        border: 1px solid #374151 !important;
        font-weight: 500;
        padding: 0.45rem 0.9rem !important;
        transition: all 0.15s ease-in-out;
    }
    button:hover { background-color: #374151 !important; transform: translateY(-1px); }
    button:active { transform: translateY(0); }

    button[kind="primary"] {
        background-color: #16a34a !important;
        border-color: #16a34a !important;
        color: white !important;
    }
    button[kind="primary"]:hover { background-color: #22c55e !important; }

    /* =========================================
       📊 Dataframe (si applicable)
       ========================================= */
    .stDataFrame tbody tr:hover { background-color: rgba(255,255,255,0.04); }
    .stDataFrame thead tr th {
        background-color: #020617 !important;
        color: #9ca3af !important;
        font-weight: 600;
    }



.dlg-title{font-weight:1000;font-size:16px;line-height:1.1}
      .dlg-sub{opacity:.75;font-weight:800;font-size:12px;margin-top:2px}
      .pill{display:inline-block;padding:2px 10px;border-radius:999px;
            background:rgba(255,255,255,.08);
            border:1px solid rgba(255,255,255,.12);
            font-weight:900;font-size:12px}

div[data-testid="stButton"] > button{
                padding: 0.16rem 0.42rem;
                font-weight: 900;
                font-size: 0.98rem;
                text-align: left;
                justify-content: flex-start;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
              }
              .salaryCell{
                white-space: nowrap;
                word-break: keep-all;
                text-align: right;
                font-weight: 900;
                display: block;
              }
              .levelCell{
                white-space: nowrap;
                opacity: .85;
                font-weight: 800;
              }
              .lvlSTD{ color:#60a5fa; font-weight:900; }
              .lvlELC{ color:#a78bfa; font-weight:900; }

              /* Contract / Expiry pills */
              .expiryPill{display:inline-block;padding:2px 8px;border-radius:999px;
                border:1px solid rgba(255,255,255,.14);
                background:rgba(255,255,255,.06);
                font-weight:900;font-size:12px;white-space:nowrap;}
              .expirySoon{border-color:rgba(239,68,68,.35);background:rgba(239,68,68,.10);}
              .expiryMid{border-color:rgba(245,158,11,.35);background:rgba(245,158,11,.10);}
              .expiryOk{border-color:rgba(34,197,94,.30);background:rgba(34,197,94,.08);}

              .contractWrap{display:flex;align-items:center;gap:8px;justify-content:flex-start;}
              .contractBar{width:76px;height:8px;border-radius:999px;overflow:hidden;
                background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.12)}
              .contractFill{height:100%;border-radius:999px;background:rgba(96,165,250,.85)}
              .contractFillELC{background:rgba(167,139,250,.85)}
              .remainText{font-weight:900;font-size:12px;opacity:.85;white-space:nowrap}


.pms-mobile .block-container{padding-top:0.8rem !important; padding-left:0.8rem !important; padding-right:0.8rem !important;}
/* =========================================
   🔐 Login header (password page)
   ========================================= */
.pms-header-wrap{
  display:flex;
  align-items:center;
  gap:12px;
}
.pms-left{
  display:flex;
  align-items:center;
  gap:10px;
}
.pms-right{
  display:flex;
  justify-content:flex-end;
  align-items:center;
}
.pms-title{
  font-weight:800;
  letter-spacing:0.5px;
  font-size:3.6rem;
  line-height:1;
}
.pms-emoji-big{
  font-size:3.9rem; /* bigger sticks + net */
  line-height:1;
}



/* v13: pool logo sizing (pro) */
/* =========================================
   🧑‍💼 GM logo (sidebar): grayscale when inactive
   ========================================= */
.gm-logo-wrap{
  display:flex;
  justify-content:center;
  margin: 2px 0 8px 0;
}
.gm-logo{
  border-radius:10px;
  transition: filter 160ms ease, transform 160ms ease, opacity 160ms ease;
  cursor: default;
}
.gm-logo.inactive{
  filter: grayscale(100%);
  opacity: 0.72;
}
.gm-logo.active{
  filter: none;
  opacity: 1;
}
.gm-logo-wrap:hover .gm-logo{
  transform: translateY(-1px);
}

/* =========================
   GM TAB UI TWEAKS
   ========================= */
.gm-header { display:flex; align-items:center; gap:14px; margin: 0 0 8px 0; }
.gm-header .gm-title { font-size: 18px; font-weight: 800; opacity: .9; }
.gm-mass { font-size: 34px; font-weight: 900; line-height: 1.05; }
.gm-sub { font-size: 12px; opacity: .75; margin-top: 2px; }

.pick-mini {
  display:inline-block;
  width:100%;
  padding:8px 10px;
  border-radius: 14px;
  border: 1px solid rgba(255,255,255,.10);
  background: rgba(255,255,255,.04);
  font-size: 12px;
  line-height: 1.2;
  text-align:center;
  white-space: nowrap;
  overflow:hidden;
  text-overflow: ellipsis;
}
.pick-mini b { font-size: 13px; }



/* =====================================================
   GM TAB (migré depuis st.markdown <style> inline)
   ===================================================== */
.gm-top { display:flex; align-items:center; gap:16px; margin-top:4px; }
.gm-top img { width:132px; } /* 3x */

.gm-team { font-weight:800; font-size:22px; opacity:0.92; }

.gm-grid {
  display:grid;
  grid-template-columns: 1fr 1fr;
  gap:22px;
  margin-top:10px;
}

.gm-card {
  border:1px solid rgba(255,255,255,0.10);
  background: rgba(255,255,255,0.04);
  border-radius:14px;
  padding:14px 14px;
}

.gm-label { font-size:12px; opacity:0.75; margin-bottom:6px; }
.gm-value { font-size:34px; font-weight:900; letter-spacing:0.2px; }

.gm-sub {
  font-size:12px;
  opacity:0.75;
  margin-top:4px;
  display:flex;
  justify-content:space-between;
}

.pick-row { display:flex; gap:8px; flex-wrap:wrap; margin-top:8px; }

.pick-pill {
  padding:6px 10px;
  border-radius:999px;
  font-weight:700;
  border:1px solid rgba(255,255,255,0.14);
  background: rgba(255,255,255,0.04);
}

.pick-pill.mine {
  border-color: rgba(34,197,94,0.55);
  background: rgba(34,197,94,0.10);
}

.pick-pill.other { opacity:0.75; }

.section-title { font-size:22px; font-weight:900; margin: 6px 0 2px; }
.muted { opacity:0.75; font-size:13px; }


/* =====================================================
   GM PICKS — lignes par année
   ===================================================== */
.pick-line { display:flex; align-items:flex-start; gap:12px; margin-top:10px; }
.pick-year { width:88px; min-width:88px; display:flex; flex-direction:column; gap:6px; }
.pick-year .pick-sub { font-size:12px; opacity:0.75; padding-left:4px; }

</style>


/* ===============================
   PICKS — layout fixe & responsive
   =============================== */
.pick-line{
  display: grid;
  grid-template-columns: 84px 1fr;
  gap: 12px;
  align-items: start;
  margin: 10px 0;
}

.pick-year{
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.pick-year-badge{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 8px 10px;
  border-radius: 999px;
  font-weight: 800;
  letter-spacing: .3px;
  border: 1px solid rgba(34,197,94,.55);
  background: rgba(34,197,94,.10);
}

.pick-sub{
  font-size: 12px;
  opacity: .8;
  padding-left: 6px;
}

.pick-row{
  display: flex;
  gap: 10px;
  flex-wrap: nowrap;
  max-width: 100%;
  overflow-x: auto;
  overflow-y: hidden;
  white-space: nowrap;
  -webkit-overflow-scrolling: touch;
  padding-bottom: 6px;
}

.pick-row::-webkit-scrollbar{ height: 8px; }
.pick-row::-webkit-scrollbar-thumb{ background: rgba(255,255,255,.15); border-radius: 999px; }
.pick-row::-webkit-scrollbar-track{ background: transparent; }

.pick-pill{
  font-size: 13px;
  padding: 7px 10px;
}

/* Mobile */
.mobile .pick-line{
  grid-template-columns: 72px 1fr;
  gap: 10px;
}
.mobile .pick-pill{
  font-size: 12px;
  padding: 6px 8px;
}
.mobile .pick-year-badge{
  padding: 7px 9px;
}


/* ===============================
   GM — petits styles pro
   =============================== */
.gm-card-head{
  margin: 2px 0 12px 0;
}
.gm-card-title{
  font-size: 18px;
  font-weight: 800;
  letter-spacing: 0.2px;
}
.gm-card-sub{
  margin-top: 4px;
  font-size: 13px;
  opacity: 0.75;
}
.gm-metric{
  font-size: 18px;
  font-weight: 800;
  margin-top: 2px;
}


/* ===== Contracts UI polish ===== */
.ctrAlert{ margin-left:6px; font-size:14px; vertical-align:middle; opacity:0.95;}
.contractWrap{ display:flex; align-items:center; gap:8px;}
.expiryPill{ padding:2px 8px; border-radius:999px; font-size:12px; border:1px solid rgba(255,255,255,.12); }
.expiryPill.expirySoon{ background:rgba(255,80,80,.18); border-color:rgba(255,80,80,.35);}
.expiryPill.expiryMid{ background:rgba(255,180,80,.18); border-color:rgba(255,180,80,.35);}
.expiryPill.expiryOk{ background:rgba(80,255,120,.12); border-color:rgba(80,255,120,.25);}
.remainText{ font-size:12px; opacity:.85; font-weight:700;}

"""

def apply_theme():
    if st.session_state.get('_theme_css_injected', False):
        return
    st.markdown(THEME_CSS, unsafe_allow_html=True)

def _set_mobile_class(enabled: bool):
    """No-op (v20): évite les erreurs frontend liées aux <script> inline."""
    return

# Appel UNIQUE
# =====================================================
# DATE FORMAT — Français (cloud-proof, no locale)
# =====================================================
MOIS_FR = [
    "", "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre"
]

TZ_TOR = ZoneInfo("America/Montreal")

def to_dt_local(x):
    if x is None:
        return pd.NaT
    dt = pd.to_datetime(x, errors="coerce", utc=False)
    if pd.isna(dt):
        return pd.NaT
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert(TZ_TOR).tz_localize(None)
    return dt

def format_date_fr(x) -> str:
    dt = to_dt_local(x)
    if pd.isna(dt):
        return ""
    return f"{dt.day} {MOIS_FR[int(dt.month)]} {dt.year} {dt:%H:%M:%S}"


# =====================================================
# PATHS / CONSTANTS
# =====================================================
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)


# =====================================================
# ✅ Data Pipeline Lock (schema + defaults + version)
#   - évite les blancs silencieux
#   - ajoute les colonnes manquantes avec des valeurs par défaut
# =====================================================
DATA_PIPELINE_VERSION = "1.0"

def _ensure_columns(df: pd.DataFrame, defaults: dict) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame):
        return pd.DataFrame()
    out = df.copy()
    for col, default in (defaults or {}).items():
        if col not in out.columns:
            out[col] = default
    return out

def validate_players_db(dfp: pd.DataFrame):
    """Ensure hockey.players.csv schema is safe for the app."""
    issues = []
    if dfp is None or not isinstance(dfp, pd.DataFrame) or dfp.empty:
        return (dfp if isinstance(dfp, pd.DataFrame) else pd.DataFrame()), issues

    # Core columns expected by the app
    dfp = _ensure_columns(dfp, {
        "Player": "",
        "Team": "",
        "Position": "",
        "Country": "",
        "FlagISO2": "",
        "Flag": "",
        "Level": "",
        "Expiry Year": "",
        "Cap Hit": "",
        "nhl_id": "",
        "contract_end": "",
        "contract_level": "",
    })

    # Normalize Level values
    try:
        dfp["Level"] = (
            dfp["Level"].astype(str).str.strip().str.upper()
            .replace({
                "ENTRY_LEVEL": "ELC",
                "STANDARD_LEVEL": "STD",
                "0": "",
                "0.0": "",
                "NONE": "",
                "NAN": "",
            })
        )
    except Exception:
        issues.append("Level_normalization_failed")

    # Normalize Expiry Year as 4-digit year string
    try:
        dfp["Expiry Year"] = (
            dfp["Expiry Year"].astype(str)
            .str.extract(r"(20\d{2})", expand=False)
            .fillna("")
        )
    except Exception:
        issues.append("ExpiryYear_normalization_failed")

    return dfp, issues

# =====================================================
# AUTO — Players DB enrichment (no button needed)
#   Goal: Always show country flags in Alignement without pressing buttons.
#   We keep it lightweight:
#     - Fill a limited number of missing playerId via NHL search
#     - Fill a limited number of missing Country via NHL landing
#   Runs once per session (session_state) and writes back to hockey.players.csv.
# =====================================================

def _players_db_path() -> str:
    # Prefer existing fallback list if available
    try:
        p = _first_existing(PLAYERS_DB_FALLBACKS) if 'PLAYERS_DB_FALLBACKS' in globals() else ''
    except Exception:
        p = ''
    return p or os.path.join(DATA_DIR, 'hockey.players.csv')


def auto_enrich_players_db(max_fill_playerid: int = 50, max_fill_country: int = 200) -> dict:
    """Auto-enrich Players DB so flags are always available.

    Returns a small stats dict for debugging.
    """
    stats = {
        'ran': False,
        'path': '',
        'filled_playerid': 0,
        'filled_country': 0,
        'skipped_reason': '',
    }

    # Run once per session
    if st.session_state.get('_players_db_auto_enriched'):
        stats['skipped_reason'] = 'already_ran_this_session'
        return stats

    path = _players_db_path()
    stats['path'] = path
    if not path or not os.path.exists(path):
        stats['skipped_reason'] = 'missing_players_db_file'
        st.session_state['_players_db_auto_enriched'] = True
        return stats

    try:
        df = pd.read_csv(path)
    except Exception:
        stats['skipped_reason'] = 'read_error'
        st.session_state['_players_db_auto_enriched'] = True
        return stats

    if df is None or df.empty:
        stats['skipped_reason'] = 'empty'
        st.session_state['_players_db_auto_enriched'] = True
        return stats

    # Normalize columns
    if 'Player' not in df.columns:
        # Try to infer a name column
        for c in df.columns:
            if str(c).strip().lower() in {'player','joueur','name','full name','fullname'}:
                df = df.rename(columns={c: 'Player'})
                break
    if 'Player' not in df.columns:
        stats['skipped_reason'] = 'no_player_name_column'
        st.session_state['_players_db_auto_enriched'] = True
        return stats

    if 'playerId' not in df.columns:
        df['playerId'] = pd.NA
    if 'Country' not in df.columns:
        df['Country'] = ''

    # 1) Fill missing playerId (limited)
    try:
        miss_pid = df['playerId'].isna() | df['playerId'].astype(str).str.strip().eq('')
    except Exception:
        miss_pid = pd.Series([False] * len(df), index=df.index)

    if bool(miss_pid.any()) and max_fill_playerid > 0:
        for i in df.index[miss_pid].tolist()[: int(max_fill_playerid)]:
            nm = str(df.at[i, 'Player'] or '').strip()
            if not nm:
                continue
            try:
                pid = _nhl_search_playerid(nm)
            except Exception:
                pid = 0
            if pid:
                df.at[i, 'playerId'] = int(pid)
                stats['filled_playerid'] += 1

    # 2) Fill missing Country using landing (limited)
    try:
        miss_cty = df['Country'].astype(str).str.strip().eq('')
    except Exception:
        miss_cty = pd.Series([False] * len(df), index=df.index)

    if bool(miss_cty.any()) and max_fill_country > 0:
        filled = 0
        for i in df.index[miss_cty].tolist():
            if filled >= int(max_fill_country):
                break
            pid = df.at[i, 'playerId']
            try:
                pid_i = int(pid)
            except Exception:
                continue
            if pid_i <= 0:
                continue
            try:
                iso2 = _nhl_landing_country(pid_i)
            except Exception:
                iso2 = ''
            if iso2:
                df.at[i, 'Country'] = str(iso2).strip().upper()
                stats['filled_country'] += 1
                filled += 1

    # Save only if we changed something
    stats['ran'] = True
    if stats['filled_playerid'] or stats['filled_country']:
        try:
            df.to_csv(path, index=False)
        except Exception:
            pass

        # Invalidate cached load_players_db by bumping session copy
        try:
            st.session_state['players_db'] = df
        except Exception:
            pass

    st.session_state['_players_db_auto_enriched'] = True
    return stats

PLAYERS_DB_FILE = os.path.join(DATA_DIR, "Hockey.players.csv")  # source: /data/Hockey.players.csv
PLAYERS_DB_FALLBACKS = [
    "data/hockey.players.csv",
    "/data/hockey.players.csv",
    "data/Hockey.players.csv",
    "/data/Hockey.players.csv",
    "data/Hockey.Players.csv",
    "/data/Hockey.Players.csv",
    "Hockey.players.csv",
    "Hockey.Players.csv",
]

# (v18) Logos critiques chargés localement (à côté de app.py)
INIT_MANIFEST_FILE = os.path.join(DATA_DIR, "init_manifest.json")


def _first_existing(paths: list[str]) -> str:
    for p in paths:
        try:
            if p and os.path.exists(p):
                return p
        except Exception:
            pass
    return paths[0] if paths else ""

REQUIRED_COLS = [
    "Propriétaire", "Joueur", "Pos", "Equipe", "Salaire",
    "Level",
    "Statut", "Slot", "IR Date"
]

# Slots
SLOT_ACTIF = "Actif"
SLOT_BANC = "Banc"
SLOT_IR = "Blessé"

SLOT_RACHAT = "RACHAT"
STATUT_GC = "Grand Club"
STATUT_CE = "Club École"


# =====================================================
# 🔐 PASSWORD GATE + HEADER
# =====================================================
def _sha256(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()





def _login_header():
    # =========================
    # LOGIN HEADER — v28 (Broadcast centered)
    #   ✅ Logo pool énorme centré
    #   ✅ PMS en dessous (centré)
    #   ✅ Icônes en support gauche/droite
    # =========================
    logo_file = LOGO_POOL_FILE

    with st.container():
        st.markdown('<div class="pms-broadcast-bar pms-center-stack">', unsafe_allow_html=True)

        left, center, right = st.columns([2, 10, 2], vertical_alignment="center")

        with left:
            st.markdown('<div class="pms-side-emoji">🏒</div>', unsafe_allow_html=True)

        with center:
            # Logo pool (plein espace disponible) — plus "broadcast"
            if isinstance(logo_file, str) and os.path.exists(logo_file):
                st.image(logo_file, use_container_width=True)
            else:
                st.caption("⚠️ logo_pool introuvable. Mets logo_pool.png à côté de app.py.")

            # PMS sous le logo (centré)
            st.markdown('<div class="pms-under">PMS</div>', unsafe_allow_html=True)

        with right:
            st.markdown('<div class="pms-side-emoji">🥅</div>', unsafe_allow_html=True)

        st.markdown('</div>', unsafe_allow_html=True)

    st.divider()


def require_password():
    cfg = st.secrets.get("security", {}) or {}

    if bool(cfg.get("enable_hash_tool", False)):
        return

    expected = str(cfg.get("password_sha256", "")).strip()
    if not expected:
        return

    if st.session_state.get("authed", False):
        return

    _login_header()
    st.title("🔐 Accès sécurisé")
    st.caption("Entre le mot de passe partagé pour accéder à l’application.")

    pwd = st.text_input("Mot de passe", type="password")
    col1, col2 = st.columns([1, 2], vertical_alignment="center")

    with col1:
        if st.button("Se connecter", type="primary", use_container_width=True):
            if _sha256(pwd) == expected:
                st.session_state["authed"] = True
                st.success("✅ Accès autorisé")
                st.rerun()
            else:
                st.error("❌ Mot de passe invalide")

    with col2:
        st.info("Astuce: si tu changes le mot de passe, regénère un nouveau hash et remplace-le dans Secrets.")

    st.stop()

require_password()

# =====================================================
# MAIN HEADER — Logo_Pool + 🏒 (gauche) + 🥅 (droite)
#   ✅ affiché après login (pas seulement sur l'écran mot de passe)
#   ✅ PAS de nouvelle injection CSS (on respecte tes règles d'or)
# =====================================================
# (header global retiré: logo uniquement sur écran mot de passe)

if bool(st.secrets.get("security", {}).get("enable_hash_tool", False)):
    st.markdown("### 🔐 Générateur de hash (temporaire)")
    pwd = st.text_input("Mot de passe à hasher", type="password")
    if pwd:
        h = hashlib.sha256(pwd.encode("utf-8")).hexdigest()
        st.code(h)
        st.info("⬆️ Copie ce hash dans Streamlit Secrets puis remet enable_hash_tool=false.")
    st.divider()


# =====================================================
# AUTO Players DB enrichment (flags always available)
#   - Runs once per session
#   - Lightweight (limited fills)
# =====================================================
try:
    st.session_state["_players_db_auto_stats"] = auto_enrich_players_db(
        max_fill_playerid=60,
        max_fill_country=250,
    )
except Exception:
    # Never block the app UI for an enrichment attempt
    pass


# =====================================================
# BASIC HELPERS
# =====================================================
def do_rerun():
    # Guard: éviter plusieurs rerun dans le même run
    if st.session_state.get("_rerun_requested", False):
        return
    st.session_state["_rerun_requested"] = True
    try:
        st.rerun()
    except Exception:
        try:
            st.experimental_rerun()
        except Exception:
            pass

def money(v) -> str:
    try:
        return f"{int(v):,}".replace(",", " " ) + " $"
    except Exception:
        return "0 $"


# =====================================================
# PERFORMANCE GUARDS (fast navigation)
#   - Avoid expensive recomputes on every widget change
# =====================================================

def bump_data_version(reason: str = ''):
    """Increment a lightweight version counter whenever roster data changes."""
    try:
        st.session_state['data_version'] = int(st.session_state.get('data_version', 0) or 0) + 1
        st.session_state['data_version_reason'] = str(reason or '')
    except Exception:
        pass


def ensure_plafonds_uptodate(force: bool = False):
    """Rebuild plafonds only when needed (data_version or caps changed)."""
    try:
        dv = int(st.session_state.get('data_version', 0) or 0)
        cap_gc = int(st.session_state.get('PLAFOND_GC', 95_500_000) or 0)
        cap_ce = int(st.session_state.get('PLAFOND_CE', 47_750_000) or 0)
        sig = (dv, cap_gc, cap_ce)
        if (not force) and st.session_state.get('_plafonds_sig') == sig and isinstance(st.session_state.get('plafonds'), pd.DataFrame):
            return
        df0 = st.session_state.get('data', pd.DataFrame(columns=REQUIRED_COLS))
        df0 = df0 if isinstance(df0, pd.DataFrame) else pd.DataFrame(columns=REQUIRED_COLS)
        st.session_state['plafonds'] = rebuild_plafonds(df0)
        st.session_state['_plafonds_sig'] = sig
    except Exception:
        # never crash navigation for plafonds
        st.session_state['plafonds'] = st.session_state.get('plafonds', pd.DataFrame())



def _cap_to_int(x) -> int:
    """Parse un salaire/cap hit en entier.

    Supporte:
      - 1250000, "1,250,000", "$1 250 000"
      - "1.25M", "950K"
    """
    if x is None:
        return 0
    if isinstance(x, (int, float)):
        try:
            if pd.isna(x):
                return 0
        except Exception:
            pass
        try:
            return int(float(x))
        except Exception:
            return 0
    s = str(x).strip()
    if not s:
        return 0
    s = s.replace("$", "").replace(" ", "").replace(",", "")
    s_up = s.upper()
    mult = 1
    if s_up.endswith("M"):
        mult = 1_000_000
        s_up = s_up[:-1]
    elif s_up.endswith("K"):
        mult = 1_000
        s_up = s_up[:-1]
    try:
        return int(float(s_up) * mult)
    except Exception:
        # fallback: extraire un nombre
        m = re.findall(r"\d+(?:\.\d+)?", s_up)
        if not m:
            return 0
        try:
            return int(float(m[0]) * mult)
        except Exception:
            return 0

def normalize_pos(pos: str) -> str:
    p = str(pos or "").upper()
    if "G" in p:
        return "G"
    if "D" in p:
        return "D"
    return "F"

def pos_sort_key(pos: str) -> int:
    return {"F": 0, "D": 1, "G": 2}.get(str(pos).upper(), 99)

def saison_auto() -> str:
    now = datetime.now(TZ_TOR)
    return f"{now.year}-{now.year+1}" if now.month >= 9 else f"{now.year-1}-{now.year}"

def saison_verrouillee(season: str) -> bool:
    try:
        return int(str(season)[:4]) < int(saison_auto()[:4])
    except Exception:
        return False

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

def _count_badge(n: int, limit: int) -> str:
    if n > limit:
        return f"<span style='color:#ef4444;font-weight:1000'>{n}</span>/{limit} ⚠️"
    return f"<span style='color:#22c55e;font-weight:1000'>{n}</span>/{limit}"

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

def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame):
        return pd.DataFrame(columns=REQUIRED_COLS)

    out = df.copy()

    for c in REQUIRED_COLS:
        if c not in out.columns:
            out[c] = "" if c in {"Propriétaire", "Joueur", "Pos", "Equipe", "Statut", "Slot", "IR Date"} else 0

    out["Propriétaire"] = out["Propriétaire"].astype(str).str.strip()
    out["Joueur"] = out["Joueur"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    out["Pos"] = out["Pos"].astype(str).apply(normalize_pos)
    out["Equipe"] = out["Equipe"].astype(str).str.strip()
    # Salaire/Cap Hit: parse robuste (Fantrax peut contenir $ / virgules / M/K)
    out["Salaire"] = out["Salaire"].apply(_cap_to_int).astype(int)

    # Level (STD / ELC) — peut être ajouté depuis hockey.players.csv
    out["Level"] = out["Level"].astype(str).str.strip()

    out["Statut"] = out["Statut"].astype(str).str.strip().replace({"": STATUT_GC})
    out["Slot"] = out["Slot"].astype(str).str.strip()
    out["IR Date"] = out["IR Date"].astype(str).str.strip()

    bad = {"", "none", "nan", "null"}
    out = out[~out["Joueur"].str.lower().isin(bad)].copy()
    return out.reset_index(drop=True)


# =====================================================
# ENRICH — Level depuis hockey.players.csv (players_db)
# =====================================================
def enrich_level_from_players_db(df: pd.DataFrame) -> pd.DataFrame:
    """Complète df (roster) à partir de st.session_state['players_db'] (hockey.players.csv).

    Priorité de matching:
      1) playerId (si disponible / résolu)
      2) nom normalisé (avec variantes)

    Ne remplace PAS des valeurs déjà présentes (Level, Salaire/Cap Hit) sauf si vides/0.
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df

    players_db = st.session_state.get("players_db")
    if players_db is None or not isinstance(players_db, pd.DataFrame) or players_db.empty:
        return df

    db = players_db.copy()

    # Colonnes clés DB
    name_col = None
    for cand in ["Player", "Joueur", "Name", "Full Name", "fullname", "player"]:
        if cand in db.columns:
            name_col = cand
            break
    if name_col is None:
        return df

    pid_col = None
    for cand in ["playerId", "player_id", "PlayerId", "PLAYERID", "id"]:
        if cand in db.columns:
            pid_col = cand
            break

    # Colonnes optionnelles DB
    team_col = None
    for cand in ["Equipe", "Équipe", "Team", "team", "Abbrev", "abbrev"]:
        if cand in db.columns:
            team_col = cand
            break

    # Salary / Cap Hit / AAV
    sal_col = None
    for cand in ["Cap Hit", "CapHit", "Salary", "AAV", "Salaire", "cap hit", "caphit", "salary", "aav"]:
        if cand in db.columns:
            sal_col = cand
            break

    has_level = "Level" in db.columns
    has_exp   = "Expiry Year" in db.columns

    if (not has_level) and (not has_exp) and (sal_col is None):
        return df

    def _n(x: str) -> str:
        """Normalise un nom joueur pour matching robuste (ordre, suffixes équipe, ponctuation)."""
        s = str(x or "").strip().lower()
        s = s.replace("’", "'")
        # Enlever équipe entre parenthèses: "Player (COL)" -> "Player"
        s = re.sub(r"\s*\([^)]*\)\s*", " ", s)
        # Enlever suffixes type " - COL" ou " — COL" (2-4 lettres)
        s = re.sub(r"\s*[-–—]\s*[a-z]{2,4}\s*$", "", s)
        # Enlever points
        s = re.sub(r"[\.]", "", s)
        # Compacter espaces
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _swap_last_first(s: str) -> str:
        # 'Last, First' -> 'First Last'
        if "," in s:
            parts = [p.strip() for p in s.split(",", 1)]
            if len(parts) == 2 and parts[0] and parts[1]:
                return f"{parts[1]} {parts[0]}".strip()
        return s

    def _team(x: str) -> str:
        t = str(x or "").strip().upper()
        # garder 2-4 lettres seulement (COL, NYR, etc.) si possible
        t = re.sub(r"[^A-Z]", "", t)
        return t[:4]

    base_names = db[name_col].astype(str).fillna("")
    base_pid   = db[pid_col].astype(str).fillna("") if pid_col else pd.Series([""]*len(db))
    base_team  = db[team_col].astype(str).fillna("") if team_col else pd.Series([""]*len(db))

    # -----------------------------
    # 1) Construire mappings par playerId (si dispo)
    # -----------------------------
    mp_level_pid: dict[str, str] = {}
    mp_exp_pid: dict[str, str] = {}
    mp_sal_pid: dict[str, int] = {}

    if pid_col:
        if has_level:
            lvl_series = db["Level"].astype(str).str.strip().str.upper()
            for pid, lvl in zip(base_pid.tolist(), lvl_series.tolist()):
                pid = str(pid or "").strip()
                if not pid:
                    continue
                if lvl in ("ELC", "STD") and pid not in mp_level_pid:
                    mp_level_pid[pid] = lvl

        if has_exp:
            exp_series = pd.to_numeric(db["Expiry Year"], errors="coerce")
            for pid, exp in zip(base_pid.tolist(), exp_series.tolist()):
                pid = str(pid or "").strip()
                if not pid or exp is None or (isinstance(exp, float) and pd.isna(exp)):
                    continue
                try:
                    mp_exp_pid[pid] = str(int(float(exp)))
                except Exception:
                    continue

        if sal_col is not None:
            for pid, sv in zip(base_pid.tolist(), db[sal_col].tolist()):
                pid = str(pid or "").strip()
                if not pid:
                    continue
                sal_int = _cap_to_int(sv)
                if sal_int > 0 and pid not in mp_sal_pid:
                    mp_sal_pid[pid] = int(sal_int)

    # -----------------------------
    # 2) Construire mappings par nom (fallback)
    # -----------------------------
    mp_level_name: dict[str, str] = {}
    mp_exp_name: dict[str, str] = {}
    mp_sal_name: dict[str, int] = {}

    if has_level:
        lvl_series = db["Level"].astype(str).str.strip().str.upper()
        for nm, lvl in zip(base_names.tolist(), lvl_series.tolist()):
            if lvl not in ("ELC", "STD"):
                continue
            n0 = _n(nm)
            n1 = _n(_swap_last_first(nm))
            if n0 and n0 not in mp_level_name:
                mp_level_name[n0] = lvl
            if n1 and n1 not in mp_level_name:
                mp_level_name[n1] = lvl

    if has_exp:
        exp_series = pd.to_numeric(db["Expiry Year"], errors="coerce")
        for nm, exp in zip(base_names.tolist(), exp_series.tolist()):
            if exp is None or (isinstance(exp, float) and pd.isna(exp)):
                continue
            try:
                expv = str(int(float(exp)))
            except Exception:
                continue
            n0 = _n(nm)
            n1 = _n(_swap_last_first(nm))
            if n0 and n0 not in mp_exp_name:
                mp_exp_name[n0] = expv
            if n1 and n1 not in mp_exp_name:
                mp_exp_name[n1] = expv

    if sal_col is not None:
        for nm, sv in zip(base_names.tolist(), db[sal_col].tolist()):
            sal_int = _cap_to_int(sv)
            if sal_int <= 0:
                continue
            n0 = _n(nm)
            n1 = _n(_swap_last_first(nm))
            if n0 and n0 not in mp_sal_name:
                mp_sal_name[n0] = int(sal_int)
            if n1 and n1 not in mp_sal_name:
                mp_sal_name[n1] = int(sal_int)

    # -----------------------------
    # 3) Résoudre playerId dans le roster si absent
    # -----------------------------
    out = df.copy()
    if "playerId" not in out.columns:
        out["playerId"] = ""

    # Construire un mapping nom+team -> playerId depuis DB (si pid + team dispo)
    mp_pid_name_team: dict[str, str] = {}
    mp_pid_name_only: dict[str, str] = {}

    if pid_col:
        for nm, pid, tm in zip(base_names.tolist(), base_pid.tolist(), base_team.tolist()):
            pid = str(pid or "").strip()
            if not pid:
                continue
            k0 = _n(nm)
            k1 = _n(_swap_last_first(nm))
            t0 = _team(tm)
            if k0 and t0:
                mp_pid_name_team.setdefault(f"{k0}|{t0}", pid)
            if k1 and t0:
                mp_pid_name_team.setdefault(f"{k1}|{t0}", pid)

            # nom-only (mais seulement si unique)
            if k0:
                if k0 in mp_pid_name_only and mp_pid_name_only[k0] != pid:
                    mp_pid_name_only[k0] = ""  # ambigu
                else:
                    mp_pid_name_only[k0] = pid
            if k1:
                if k1 in mp_pid_name_only and mp_pid_name_only[k1] != pid:
                    mp_pid_name_only[k1] = ""
                else:
                    mp_pid_name_only[k1] = pid

    # Remplir playerId manquant en utilisant Joueur + Equipe
    if pid_col and "Joueur" in out.columns:
        roster_team_col = "Equipe" if "Equipe" in out.columns else ("Équipe" if "Équipe" in out.columns else None)
        cur_pid = out["playerId"].astype(str).str.strip()
        need_pid = cur_pid.eq("") | cur_pid.str.lower().isin({"none","nan","null","0","0.0"})
        if need_pid.any():
            def _pid_lookup(row) -> str:
                nm = str(row.get("Joueur", "") or "")
                n0 = _n(nm)
                n1 = _n(_swap_last_first(nm))
                t = _team(row.get(roster_team_col, "") if roster_team_col else "")
                if t:
                    pid = mp_pid_name_team.get(f"{n0}|{t}") or mp_pid_name_team.get(f"{n1}|{t}")
                    if pid:
                        return pid
                pid = mp_pid_name_only.get(n0) or mp_pid_name_only.get(n1)
                return pid or ""
            out.loc[need_pid, "playerId"] = out.loc[need_pid].apply(_pid_lookup, axis=1)

    # Ensure cols exist
    if "Level" not in out.columns:
        out["Level"] = ""
    if "Expiry Year" not in out.columns:
        out["Expiry Year"] = ""
    if "Salaire" not in out.columns:
        out["Salaire"] = 0

    bad = {"", "none", "nan", "null"}

    # -----------------------------
    # 4) Fill Level (playerId -> nom)
    # -----------------------------
    cur_lvl = out["Level"].astype(str).str.strip()
    need_lvl = cur_lvl.eq("") | cur_lvl.str.lower().isin(bad) | cur_lvl.isin(["0", "0.0"]) | cur_lvl.str.lower().isin({"0", "0.0"})

    if need_lvl.any():
        # playerId d'abord
        if mp_level_pid and "playerId" in out.columns:
            pid_series = out.loc[need_lvl, "playerId"].astype(str).str.strip()
            mapped_pid = pid_series.map(lambda pid: mp_level_pid.get(pid, ""))
            mask_pid = mapped_pid.astype(str).str.strip().str.upper().isin(["ELC","STD"]) & pid_series.ne("")
            out.loc[need_lvl[need_lvl].index[mask_pid], "Level"] = mapped_pid[mask_pid].astype(str).str.strip().str.upper()

        # fallback nom
        still_need = out["Level"].astype(str).str.strip().eq("")
        if still_need.any() and mp_level_name:
            def _lvl_lookup(name: str) -> str:
                n0 = _n(name)
                if n0 in mp_level_name:
                    return mp_level_name.get(n0, "")
                n1 = _n(_swap_last_first(name))
                return mp_level_name.get(n1, "")
            out.loc[still_need, "Level"] = out.loc[still_need, "Joueur"].astype(str).map(_lvl_lookup)

        out["Level"] = out["Level"].astype(str).str.strip().str.upper()
        out.loc[~out["Level"].isin(["ELC","STD"]), "Level"] = ""

    # -----------------------------
    # 5) Fill Expiry Year (playerId -> nom)
    # -----------------------------
    cur_exp = out["Expiry Year"].astype(str).str.strip()
    need_exp = cur_exp.eq("") | cur_exp.str.lower().isin(bad)
    if need_exp.any():
        if mp_exp_pid and "playerId" in out.columns:
            pid_series = out.loc[need_exp, "playerId"].astype(str).str.strip()
            mapped_pid = pid_series.map(lambda pid: mp_exp_pid.get(pid, ""))
            mask_pid = pid_series.ne("") & mapped_pid.astype(str).str.strip().ne("")
            out.loc[need_exp[need_exp].index[mask_pid], "Expiry Year"] = mapped_pid[mask_pid]

        still_need = out["Expiry Year"].astype(str).str.strip().eq("")
        if still_need.any() and mp_exp_name:
            def _exp_lookup(name: str) -> str:
                n0 = _n(name)
                if n0 in mp_exp_name:
                    return mp_exp_name.get(n0, "")
                n1 = _n(_swap_last_first(name))
                return mp_exp_name.get(n1, "")
            out.loc[still_need, "Expiry Year"] = out.loc[still_need, "Joueur"].astype(str).map(_exp_lookup)

        out["Expiry Year"] = out["Expiry Year"].astype(str).str.strip()

    # -----------------------------
    # 6) Fill Salaire (Cap Hit) (playerId -> nom)
    # -----------------------------
    try:
        cur_sal = pd.to_numeric(out["Salaire"], errors="coerce").fillna(0).astype(int)
        need_sal = cur_sal.le(0)
        if need_sal.any():
            if mp_sal_pid and "playerId" in out.columns:
                pid_series = out.loc[need_sal, "playerId"].astype(str).str.strip()
                mapped_pid = pid_series.map(lambda pid: int(mp_sal_pid.get(pid, 0) or 0))
                mask_pid = pid_series.ne("") & (mapped_pid > 0)
                out.loc[need_sal[need_sal].index[mask_pid], "Salaire"] = mapped_pid[mask_pid].astype(int)

            still_need = pd.to_numeric(out["Salaire"], errors="coerce").fillna(0).astype(int).le(0)
            if still_need.any() and mp_sal_name:
                def _sal_lookup(name: str) -> int:
                    n0 = _n(name)
                    if n0 in mp_sal_name:
                        return int(mp_sal_name.get(n0, 0) or 0)
                    n1 = _n(_swap_last_first(name))
                    return int(mp_sal_name.get(n1, 0) or 0)
                out.loc[still_need, "Salaire"] = out.loc[still_need, "Joueur"].astype(str).map(_sal_lookup).fillna(0).astype(int)
    except Exception:
        pass

    out["Level"] = out["Level"].astype(str).str.strip()
    out["Expiry Year"] = out["Expiry Year"].astype(str).str.strip()
    return out
# Alias rétro-compat (certaines versions appellent ce nom)
def fill_level_and_expiry_from_players_db(df: pd.DataFrame, players_db: pd.DataFrame) -> pd.DataFrame:
    """Compat: délègue à enrich_level_from_players_db() (qui lit st.session_state['players_db'])."""
    # On accepte le param players_db pour compat, mais la fonction source lit le session_state.
    try:
        if isinstance(players_db, pd.DataFrame):
            st.session_state["players_db"] = players_db
    except Exception:
        pass
    return enrich_level_from_players_db(df)


# =====================================================
# Level mapping — single source of truth
#   - Used by Alignement rendering to guarantee Level is filled (STD/ELC)
# =====================================================
def apply_players_level(df: pd.DataFrame) -> pd.DataFrame:
    """Fill df['Level'] (STD/ELC) and df['Expiry Year'] using the local Players DB.

    This wrapper prevents "Level = 0" / blank issues in Alignement (ex: Juraj Slafkovský).
    """
    try:
        if df is None or not hasattr(df, 'empty') or df.empty:
            return df
    except Exception:
        return df

    try:
        # Prefer session_state DB if already loaded
        pdb = st.session_state.get('players_db')
    except Exception:
        pdb = None

    # If not loaded yet, try reading default path
    if (pdb is None) or (not isinstance(pdb, pd.DataFrame)) or pdb.empty:
        try:
            pdb_path = os.path.join(DATA_DIR, 'hockey.players.csv') if 'DATA_DIR' in globals() else 'data/hockey.players.csv'
            if os.path.exists(pdb_path):
                pdb = pd.read_csv(pdb_path)
                st.session_state['players_db'] = pdb
        except Exception:
            pdb = pd.DataFrame()

    try:
        if isinstance(pdb, pd.DataFrame) and not pdb.empty and 'enrich_level_from_players_db' in globals() and callable(globals()['enrich_level_from_players_db']):
            # enrich_level_from_players_db reads st.session_state['players_db']
            return enrich_level_from_players_db(df)
    except Exception:
        pass

    return df


# =====================================================
# HELPERS UI — Pills + Alert cards (1 seule fois)
# =====================================================
def pill(label: str, value: str, level: str = "ok", pulse: bool = False):
    level_class = {"ok": "pill-ok", "warn": "pill-warn", "danger": "pill-danger"}.get(level, "pill-ok")
    pulse_class = {"ok": "pulse-soft", "warn": "pulse-warn", "danger": "pulse-danger"}.get(level, "")
    pulse_class = pulse_class if pulse else ""
    st.markdown(
        f"""
        <span class="pill {level_class} {pulse_class} fade-in">
            <span class="dot"></span>
            <b>{label}</b>
            <span class="muted">{value}</span>
        </span>
        """,
        unsafe_allow_html=True
    )

def alert_card(title: str, subtitle: str, level: str = "ok", pulse: bool = False):
    lvl = level if level in ("ok", "warn", "danger") else "ok"
    pulse_class = {"ok": "pulse-soft", "warn": "pulse-warn", "danger": "pulse-danger"}.get(lvl, "")
    pulse_class = pulse_class if pulse else ""
    st.markdown(
        f"""
        <div class="alert-card {lvl} {pulse_class} fade-in lift">
            <div style="font-weight:600; color:#f9fafb;">{title}</div>
            <div class="muted">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

# =====================================================
# ALERTES — Cap GC/CE + IR + Toasts (1 seule fois)
#   Utilisation: show_status_alerts(...)
# =====================================================
def _level_for_cap(total: int, cap: int) -> str:
    if cap <= 0:
        return "ok"
    if total > cap:
        return "danger"
    reste = cap - total
    pct_reste = reste / cap if cap else 0
    if pct_reste < 0.05:
        return "warn"
    return "ok"

def show_status_alerts(
    *,
    total_gc: int, cap_gc: int,
    total_ce: int, cap_ce: int,
    ir_count: int = 0,
    banc_count: int = 0,
    toast: bool = False,
    context: str = ""
):
    # niveaux
    lvl_gc = _level_for_cap(total_gc, cap_gc)
    lvl_ce = _level_for_cap(total_ce, cap_ce)

    reste_gc = cap_gc - total_gc
    reste_ce = cap_ce - total_ce

    lvl_ir = "ok"
    if ir_count >= 3:
        lvl_ir = "danger"
    elif ir_count > 0:
        lvl_ir = "warn"

    # Pills en haut
    # ✅ ordre demandé: GC (gauche) • IR/Banc (milieu) • CE (droite)
    c1, c_mid, c2 = st.columns([2, 1.4, 2], vertical_alignment="center")
    with c1:
        pill("GC", f"{total_gc:,.0f} / {cap_gc:,.0f} $", level=lvl_gc, pulse=(lvl_gc != "ok"))
        st.write("")
        pill("Reste GC", f"{reste_gc:,.0f} $", level=("danger" if reste_gc < 0 else lvl_gc), pulse=(lvl_gc != "ok"))
    with c_mid:
        pill("IR", f"{ir_count} joueur(s)", level=lvl_ir, pulse=(lvl_ir != "ok"))
        st.write("")
        lvl_banc = "ok" if int(banc_count or 0) == 0 else "warn"
        pill("Banc", f"{int(banc_count or 0)} joueur(s)", level=lvl_banc, pulse=(lvl_banc != "ok"))
    with c2:
        pill("CE", f"{total_ce:,.0f} / {cap_ce:,.0f} $", level=lvl_ce, pulse=(lvl_ce != "ok"))
        st.write("")
        pill("Reste CE", f"{reste_ce:,.0f} $", level=("danger" if reste_ce < 0 else lvl_ce), pulse=(lvl_ce != "ok"))

    st.write("")

    # Cartes d’alerte (seulement si warn/danger)
    if lvl_gc == "danger":
        alert_card("🚨 Plafond GC dépassé", "Réduis la masse salariale ou déplace un joueur.", level="danger", pulse=True)
    elif lvl_gc == "warn":
        alert_card("⚠️ Reste GC faible", "Tu approches du plafond — attention aux moves.", level="warn", pulse=True)

    if lvl_ce == "danger":
        alert_card("🚨 Plafond CE dépassé", "Ajuste le Club École (CE) pour revenir sous le plafond.", level="danger", pulse=True)
    elif lvl_ce == "warn":
        alert_card("⚠️ Reste CE faible", "Tu approches du plafond CE — attention aux moves.", level="warn", pulse=True)

    if lvl_ir != "ok":
        alert_card("🩹 Joueurs blessés (IR)", "Des joueurs sont sur IR — vérifie tes remplacements.", level=lvl_ir, pulse=(lvl_ir == "danger"))

    # Toasts optionnels (utile après un move)
    if toast:
        prefix = f"{context} — " if context else ""
        if lvl_gc == "danger" or lvl_ce == "danger":
            st.toast(prefix + "🚨 Plafond dépassé", icon="🚨")
        elif lvl_gc == "warn" or lvl_ce == "warn":
            st.toast(prefix + "⚠️ Proche du plafond", icon="⚠️")
        if lvl_ir != "ok":
            st.toast(prefix + f"🩹 IR: {ir_count} joueur(s)", icon="🩹")



# =====================================================
# LOGOS
# =====================================================
LOGOS = {
    "Nordiques": os.path.join(DATA_DIR, "Nordiques_Logo.png"),
    "Cracheurs": os.path.join(DATA_DIR, "Cracheurs_Logo.png"),
    "Prédateurs": os.path.join(DATA_DIR, "Predateurs_logo.png"),
    "Red Wings": os.path.join(DATA_DIR, "Red_Wings_Logo.png"),
    "Whalers": os.path.join(DATA_DIR, "Whalers_Logo.png"),
    "Canadiens": os.path.join(DATA_DIR, "montreal-canadiens-logo.png"),
}

def team_logo_path(team: str) -> str:
    """Retourne le chemin logo si trouvé.
    ✅ supporte le case-insensitive (Streamlit Cloud / macOS vs Linux)
    """
    team = str(team or "").strip()
    path = str(LOGOS.get(team, "")).strip()
    if path and os.path.exists(path):
        return path

    # fallback: chercher dans DATA_DIR par nom de fichier (insensible à la casse)
    try:
        if path:
            want = os.path.basename(path).lower()
            for fn in os.listdir(DATA_DIR):
                if fn.lower() == want:
                    p = os.path.join(DATA_DIR, fn)
                    if os.path.exists(p):
                        return p
    except Exception:
        pass

    # fallback 2: si LOGOS a une clé proche (espaces/accents)
    try:
        for k, v in (LOGOS or {}).items():
            if str(k).strip().lower() == team.lower():
                v = str(v).strip()
                if v and os.path.exists(v):
                    return v
    except Exception:
        pass

    return ""

# =====================================================
# TEAM SELECTION (single source of truth)
# =====================================================
def pick_team(team: str):
    team = str(team or "").strip()
    st.session_state["selected_team"] = team
    st.session_state["align_owner"] = team
    do_rerun()

def get_selected_team() -> str:
    v = str(st.session_state.get("selected_team") or "").strip()
    if v:
        return v
    v = str(st.session_state.get("align_owner") or "").strip()
    return v

def _is_admin_whalers() -> bool:
    if bool(st.session_state.get("IS_ADMIN", False)):
        return True
    return get_selected_team().strip().lower() == "whalers"


# =====================================================
# INIT MANIFEST
# =====================================================
def load_init_manifest() -> dict:
    try:
        if os.path.exists(INIT_MANIFEST_FILE):
            with open(INIT_MANIFEST_FILE, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {}

def save_init_manifest(manifest: dict) -> None:
    try:
        with open(INIT_MANIFEST_FILE, "w", encoding="utf-8") as f:
            json.dump(manifest or {}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# =====================================================
# PERSISTENCE
# =====================================================
def persist_data(df: pd.DataFrame, season_lbl: str) -> None:
    season_lbl = str(season_lbl or "").strip() or "season"
    # Main roster file (must survive Streamlit Cloud disk resets)
    # Requested naming: equipes_joueurs_2025-2026.csv
    path = os.path.join(DATA_DIR, f"equipes_joueurs_{season_lbl}.csv")
    st.session_state["DATA_FILE"] = path

    # Local atomic write
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        df.to_csv(tmp, index=False)
        os.replace(tmp, path)
    except Exception:
        pass

    # Mirror to Drive (if configured) so it survives disk resets
    try:
        cfg = st.secrets.get("gdrive_oauth", {}) or {}
        folder_id = str(cfg.get("folder_id", "")).strip()
        if folder_id:
            s = _drive()
            _drive_upsert_csv_bytes(s, folder_id, os.path.basename(path), df.to_csv(index=False).encode("utf-8"))
    except Exception:
        # Never crash the app on Drive issues.
        pass
    # perf: signal data changed (so plafonds will rebuild only once)
    bump_data_version('persist_data')

def persist_history(h: pd.DataFrame, season_lbl: str) -> None:
    season_lbl = str(season_lbl or "").strip() or "season"
    path = os.path.join(DATA_DIR, f"history_{season_lbl}.csv")
    st.session_state["HISTORY_FILE"] = path
    try:
        h.to_csv(path, index=False)
    except Exception:
        pass



# =====================================================
# 🏆 POINTS — cumul seulement quand le joueur est ACTIF
#   - On enregistre des périodes ACTIF (start/end) par équipe/joueur.
#   - Quand le joueur passe banc/mineur/IR: la période se ferme et les points restent acquis.
#   - Les points sont calculés via nhl_player_stats_combo + compute_points_from_rules (même règles que Classement).
#   - Persisté local + mirror Drive (survit aux resets de disque Streamlit Cloud).
# =====================================================

def _points_periods_path(season_lbl: str) -> str:
    season_lbl = str(season_lbl or '').strip() or 'season'
    return os.path.join(DATA_DIR, f"points_periods_{season_lbl}.csv")

def _points_periods_cols():
    return [
        'season','owner','player','playerId','pos',
        'start_ts','end_ts',
        'points_start','points_end','points_delta',
    ]

def load_points_periods(season_lbl: str) -> pd.DataFrame:
    path = _points_periods_path(season_lbl)
    _ensure_local_csv_from_drive(path)
    try:
        if path and os.path.exists(path):
            df = pd.read_csv(path)
        else:
            df = pd.DataFrame(columns=_points_periods_cols())
    except Exception:
        df = pd.DataFrame(columns=_points_periods_cols())

    for c in _points_periods_cols():
        if c not in df.columns:
            df[c] = ''
    return df[_points_periods_cols()].copy()

def persist_points_periods(df: pd.DataFrame, season_lbl: str) -> None:
    season_lbl = str(season_lbl or '').strip() or 'season'
    path = _points_periods_path(season_lbl)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        df.to_csv(tmp, index=False)
        os.replace(tmp, path)
    except Exception:
        pass

    # Mirror to Drive (if configured)
    try:
        cfg = st.secrets.get('gdrive_oauth', {}) or {}
        folder_id = str(cfg.get('folder_id','')).strip()
        if folder_id:
            s = _drive()
            _drive_upsert_csv_bytes(s, folder_id, os.path.basename(path), df.to_csv(index=False).encode('utf-8'))
    except Exception:
        pass


# =====================================================
# ⚙️ GM SETTINGS — persistant (local + Drive mirror)
#   - Stocke des toggles par équipe (ex: auto-update points)
#   - Survit aux resets Streamlit Cloud via Drive
# =====================================================

def _gm_settings_path(season_lbl: str) -> str:
    season_lbl = str(season_lbl or '').strip() or 'season'
    return os.path.join(DATA_DIR, f"gm_settings_{season_lbl}.csv")

def _gm_settings_cols():
    return ['season','owner','auto_update_points','interval_min']

def load_gm_settings(season_lbl: str) -> pd.DataFrame:
    path = _gm_settings_path(season_lbl)
    _ensure_local_csv_from_drive(path)
    try:
        if path and os.path.exists(path):
            df = pd.read_csv(path)
        else:
            df = pd.DataFrame(columns=_gm_settings_cols())
    except Exception:
        df = pd.DataFrame(columns=_gm_settings_cols())

    for c in _gm_settings_cols():
        if c not in df.columns:
            df[c] = ''

    # types
    try:
        df['auto_update_points'] = df['auto_update_points'].astype(str)
    except Exception:
        pass
    try:
        df['interval_min'] = pd.to_numeric(df['interval_min'], errors='coerce').fillna(15).astype(int)
    except Exception:
        df['interval_min'] = 15

    return df[_gm_settings_cols()].copy()

def persist_gm_settings(df: pd.DataFrame, season_lbl: str) -> None:
    season_lbl = str(season_lbl or '').strip() or 'season'
    path = _gm_settings_path(season_lbl)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        df.to_csv(tmp, index=False)
        os.replace(tmp, path)
    except Exception:
        pass

    # Mirror to Drive
    try:
        cfg = st.secrets.get('gdrive_oauth', {}) or {}
        folder_id = str(cfg.get('folder_id','')).strip()
        if folder_id:
            s = _drive()
            _drive_upsert_csv_bytes(s, folder_id, os.path.basename(path), df.to_csv(index=False).encode('utf-8'))
    except Exception:
        pass

def get_gm_setting_auto_update_points(season_lbl: str, owner: str) -> tuple[bool, int]:
    owner = str(owner or '').strip()
    df = load_gm_settings(season_lbl)
    row = df[df['owner'].astype(str).str.strip().eq(owner)].head(1)
    if row.empty:
        return False, 15
    v = str(row.iloc[0].get('auto_update_points','')).strip().lower()
    enabled = v in {'1','true','yes','on','y'}
    try:
        interval = int(row.iloc[0].get('interval_min', 15) or 15)
    except Exception:
        interval = 15
    interval = max(5, min(180, interval))
    return enabled, interval

def set_gm_setting_auto_update_points(season_lbl: str, owner: str, enabled: bool, interval_min: int = 15) -> None:
    owner = str(owner or '').strip()
    interval_min = int(interval_min or 15)
    interval_min = max(5, min(180, interval_min))

    df = load_gm_settings(season_lbl)
    m = df['owner'].astype(str).str.strip().eq(owner)
    if m.any():
        df.loc[m, 'auto_update_points'] = 'true' if enabled else 'false'
        df.loc[m, 'interval_min'] = interval_min
        df.loc[m, 'season'] = str(season_lbl)
    else:
        df = pd.concat([df, pd.DataFrame([{
            'season': str(season_lbl),
            'owner': owner,
            'auto_update_points': 'true' if enabled else 'false',
            'interval_min': interval_min,
        }])], ignore_index=True)

    persist_gm_settings(df[_gm_settings_cols()].copy(), season_lbl)


def _auto_update_last_key(season_lbl: str, owner: str) -> str:
    return f"_auto_update_points_last_ts__{season_lbl}__{owner}"

def _should_run_auto_update_points(season_lbl: str, owner: str, minutes: int = 15) -> bool:
    # Throttle: max 1 run per <minutes> for owner+season in this session
    try:
        now = datetime.now(ZoneInfo('America/Montreal')).timestamp()
    except Exception:
        now = datetime.utcnow().timestamp()
    last_k = _auto_update_last_key(season_lbl, owner)
    last = float(st.session_state.get(last_k, 0.0) or 0.0)
    if (now - last) < (int(minutes) * 60):
        return False
    st.session_state[last_k] = now
    return True


def _is_active_row(row: dict) -> bool:
    """Best-effort: détecte un joueur 'actif' selon Statut/Slot."""
    s1 = str(row.get('Statut','') or '').lower().strip()
    s2 = str(row.get('Slot','') or '').lower().strip()
    blob = f"{s1} {s2}"
    # 'actif/active/lineup/starter' + support 'actifs'
    if re.search(r"\b(actif|actifs|active|lineup|starter)\b", blob):
        return True
    # Exclusions explicites
    if re.search(r"\b(ir|injur|bless|bench|banc|minor|mineur|reserve)\b", blob):
        return False
    return False


def _now_mtl_iso() -> str:
    try:
        return datetime.now(ZoneInfo('America/Montreal')).isoformat(timespec='seconds')
    except Exception:
        return datetime.utcnow().isoformat(timespec='seconds')


def _fantasy_points_for_player(player_id_raw: str, pos_raw: str, season_lbl: str, rules_df: pd.DataFrame) -> float:
    stats = nhl_player_stats_combo(player_id_raw, season_lbl)
    # compute_points_from_rules attend keys 'goals/assists/wins/otLosses'.
    return float(compute_points_from_rules(pos_raw, stats, rules_df) or 0.0)


def update_points_periods_from_roster(season_lbl: str) -> pd.DataFrame:
    """Crée/ferme des périodes ACTIF selon le roster courant.

    IMPORTANT: on ne fait des appels API que pour:
      - ouvrir une période (points_start)
      - fermer une période (points_end)

    Les périodes ouvertes sont calculées à l'affichage via current - points_start.
    """
    season_lbl = str(season_lbl or '').strip() or 'season'
    df_roster = st.session_state.get('data', pd.DataFrame())
    if not isinstance(df_roster, pd.DataFrame) or df_roster.empty:
        return load_points_periods(season_lbl)

    # columns
    if 'Propriétaire' not in df_roster.columns or 'Joueur' not in df_roster.columns:
        return load_points_periods(season_lbl)

    col_pid = None
    for c in ['playerId','PlayerId','player_id','id_player']:
        if c in df_roster.columns:
            col_pid = c
            break
    if not col_pid:
        return load_points_periods(season_lbl)

    col_pos = None
    for c in ['Pos','POS','Position','position']:
        if c in df_roster.columns:
            col_pos = c
            break
    if not col_pos:
        col_pos = 'Pos'
        df_roster[col_pos] = ''

    d = df_roster.copy()
    d['Propriétaire'] = d['Propriétaire'].astype(str).str.strip()
    d['Joueur'] = d['Joueur'].astype(str).str.strip()
    d[col_pid] = d[col_pid].astype(str).str.strip()
    d[col_pos] = d[col_pos].astype(str).str.strip()
    if 'Statut' not in d.columns:
        d['Statut'] = ''
    if 'Slot' not in d.columns:
        d['Slot'] = d.get('Slot','')

    # set actif current
    cur_actifs = set()
    for _, r in d.iterrows():
        if not str(r.get('Joueur','')).strip():
            continue
        if not str(r.get(col_pid,'')).strip():
            continue
        rr = r.to_dict()
        if _is_active_row(rr):
            cur_actifs.add((str(rr.get('Propriétaire','')).strip(), str(rr.get('Joueur','')).strip()))

    periods = load_points_periods(season_lbl)

    # Identify open periods
    periods['owner'] = periods['owner'].astype(str).str.strip()
    periods['player'] = periods['player'].astype(str).str.strip()
    open_mask = periods['end_ts'].astype(str).str.strip().eq('')
    open_set = set(zip(periods.loc[open_mask,'owner'], periods.loc[open_mask,'player']))

    rules = load_scoring_rules()

    # Open new periods for newly active players
    to_open = cur_actifs - open_set
    if to_open:
        now = _now_mtl_iso()
        add_rows = []
        # map pid/pos quickly
        pid_map = {}
        pos_map = {}
        sub = d.drop_duplicates(subset=['Propriétaire','Joueur'], keep='last')
        for _, r in sub.iterrows():
            k = (str(r.get('Propriétaire','')).strip(), str(r.get('Joueur','')).strip())
            pid_map[k] = str(r.get(col_pid,'') or '').strip()
            pos_map[k] = str(r.get(col_pos,'') or '').strip()

        for (owner, player) in sorted(to_open):
            pid = pid_map.get((owner,player),'')
            pos = pos_map.get((owner,player),'')
            pts0 = 0.0
            if pid:
                try:
                    pts0 = _fantasy_points_for_player(pid, pos, season_lbl, rules)
                except Exception:
                    pts0 = 0.0
            add_rows.append({
                'season': season_lbl,
                'owner': owner,
                'player': player,
                'playerId': pid,
                'pos': pos,
                'start_ts': now,
                'end_ts': '',
                'points_start': float(pts0),
                'points_end': '',
                'points_delta': '',
            })
        if add_rows:
            periods = pd.concat([periods, pd.DataFrame(add_rows)], ignore_index=True)

    # Close periods for players no longer active
    to_close = open_set - cur_actifs
    if to_close:
        now = _now_mtl_iso()
        # map pid/pos in case updated
        pid_map = {}
        pos_map = {}
        sub = d.drop_duplicates(subset=['Propriétaire','Joueur'], keep='last')
        for _, r in sub.iterrows():
            k = (str(r.get('Propriétaire','')).strip(), str(r.get('Joueur','')).strip())
            pid_map[k] = str(r.get(col_pid,'') or '').strip()
            pos_map[k] = str(r.get(col_pos,'') or '').strip()

        for (owner, player) in sorted(to_close):
            mask = open_mask & periods['owner'].astype(str).str.strip().eq(owner) & periods['player'].astype(str).str.strip().eq(player)
            if not mask.any():
                continue
            i = periods.index[mask][0]
            pid = str(periods.at[i,'playerId'] or '').strip() or pid_map.get((owner,player),'')
            pos = str(periods.at[i,'pos'] or '').strip() or pos_map.get((owner,player),'')
            pts_end = 0.0
            try:
                pts_end = _fantasy_points_for_player(pid, pos, season_lbl, rules) if pid else 0.0
            except Exception:
                pts_end = 0.0
            try:
                pts_start = float(periods.at[i,'points_start'] or 0)
            except Exception:
                pts_start = 0.0
            delta = float(pts_end - pts_start)
            periods.at[i,'end_ts'] = now
            periods.at[i,'points_end'] = float(pts_end)
            periods.at[i,'points_delta'] = float(delta)

    # Normalize
    for c in _points_periods_cols():
        if c not in periods.columns:
            periods[c] = ''
    periods = periods[_points_periods_cols()].copy()

    # Persist only if changed
    try:
        persist_points_periods(periods, season_lbl)
    except Exception:
        pass

    return periods


def team_points_snapshot(owner: str, season_lbl: str) -> tuple[float, pd.DataFrame]:
    """Retourne (points_total, breakdown_par_joueur).

    points_total = somme(des périodes fermées delta) + somme(des périodes ouvertes (current - start)).
    """
    owner = str(owner or '').strip()
    season_lbl = str(season_lbl or '').strip() or 'season'
    periods = update_points_periods_from_roster(season_lbl)
    if periods.empty:
        return 0.0, pd.DataFrame(columns=['Joueur','Points'])

    p = periods[periods['owner'].astype(str).str.strip().eq(owner)].copy()
    if p.empty:
        return 0.0, pd.DataFrame(columns=['Joueur','Points'])

    rules = load_scoring_rules()

    # Closed deltas
    def _f(x):
        try:
            return float(x)
        except Exception:
            return 0.0

    closed = p[p['end_ts'].astype(str).str.strip().ne('')].copy()
    closed['earned'] = closed['points_delta'].apply(_f)

    # Open: current - start
    openp = p[p['end_ts'].astype(str).str.strip().eq('')].copy()
    cur_earned = []
    for _, r in openp.iterrows():
        pid = str(r.get('playerId','') or '').strip()
        pos = str(r.get('pos','') or '').strip()
        try:
            start = float(r.get('points_start') or 0)
        except Exception:
            start = 0.0
        cur = 0.0
        if pid:
            try:
                cur = _fantasy_points_for_player(pid, pos, season_lbl, rules)
            except Exception:
                cur = start
        cur_earned.append(float(cur - start))
    if len(openp):
        openp = openp.reset_index(drop=True)
        openp['earned'] = cur_earned

    allp = pd.concat([closed[['player','earned']], openp[['player','earned']]], ignore_index=True)
    out = allp.groupby('player', as_index=False)['earned'].sum()
    out = out.rename(columns={'player':'Joueur','earned':'Points'}).sort_values(by='Points', ascending=False)

    total = float(out['Points'].sum() if not out.empty else 0.0)
    return total, out.reset_index(drop=True)

def _ensure_local_csv_from_drive(local_path: str) -> bool:
    """If local_path is missing (Streamlit Cloud disk reset), try to restore it from Drive.

    Returns True if the file exists locally after this call.
    Never raises.
    """
    try:
        if local_path and os.path.exists(local_path):
            return True
        cfg = st.secrets.get("gdrive_oauth", {}) or {}
        folder_id = str(cfg.get("folder_id", "")).strip()
        if not folder_id:
            return False
        s = _drive()
        df = _drive_download_csv_df(s, folder_id, os.path.basename(local_path))
        if not isinstance(df, pd.DataFrame) or df.empty:
            return False
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        tmp = local_path + ".tmp"
        df.to_csv(tmp, index=False)
        os.replace(tmp, local_path)
        return True
    except Exception:
        return bool(local_path and os.path.exists(local_path))


# =====================================================
# HISTORY (normalized)
# =====================================================
def _history_expected_cols():
    return [
        "id", "timestamp", "season",
        "proprietaire", "joueur", "pos", "equipe",
        "from_statut", "from_slot", "to_statut", "to_slot",
        "action",
    ]

def _history_empty_df():
    return pd.DataFrame(columns=_history_expected_cols())

def load_history_file(path: str) -> pd.DataFrame:
    try:
        if path and os.path.exists(path):
            h = pd.read_csv(path)
            if isinstance(h, pd.DataFrame):
                for c in _history_expected_cols():
                    if c not in h.columns:
                        h[c] = ""
                return h[_history_expected_cols()].copy()
    except Exception:
        pass
    return _history_empty_df()

def next_hist_id(h: pd.DataFrame) -> int:
    try:
        if h is None or not isinstance(h, pd.DataFrame) or h.empty or "id" not in h.columns:
            return 1
        v = pd.to_numeric(h["id"], errors="coerce").fillna(0)
        return int(v.max()) + 1
    except Exception:
        return 1

def log_history_row(
    proprietaire: str,
    joueur: str,
    pos: str,
    equipe: str,
    from_statut: str,
    from_slot: str,
    to_statut: str,
    to_slot: str,
    action: str,
):
    h = st.session_state.get("history")
    h = h.copy() if isinstance(h, pd.DataFrame) else _history_empty_df()

    row_hist = {
        "id": next_hist_id(h),
        "timestamp": datetime.now(TZ_TOR).strftime("%Y-%m-%d %H:%M:%S"),
        "season": str(st.session_state.get("season", "") or ""),
        "proprietaire": str(proprietaire or ""),
        "joueur": str(joueur or ""),
        "pos": str(pos or ""),
        "equipe": str(equipe or ""),
        "from_statut": str(from_statut or ""),
        "from_slot": str(from_slot or ""),
        "to_statut": str(to_statut or ""),
        "to_slot": str(to_slot or ""),
        "action": str(action or ""),
    }

    h = pd.concat([h, pd.DataFrame([row_hist])], ignore_index=True)
    st.session_state["history"] = h
    persist_history(h, str(st.session_state.get("season", "")).strip())



# =====================================================
# MOVE + HISTORY (définition unique)
#   ✅ corrige NameError: apply_move_with_history
# =====================================================
def apply_move_with_history(owner: str, joueur: str, to_statut: str, to_slot: str, note: str = "") -> bool:
    """
    Applique un move (Statut/Slot) + écrit l'historique.
    - Simple et robuste: on modifie la ligne dans df.
    """
    df = st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS))
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        st.session_state["last_move_error"] = "Données manquantes."
        return False

    owner_s = str(owner or "").strip()
    joueur_s = str(joueur or "").strip()

    m = (
        df["Propriétaire"].astype(str).str.strip().eq(owner_s)
        & df["Joueur"].astype(str).str.strip().eq(joueur_s)
    )
    if not m.any():
        st.session_state["last_move_error"] = "Joueur introuvable."
        return False

    idx = df.index[m][0]
    from_statut = str(df.at[idx, "Statut"] if "Statut" in df.columns else "")
    from_slot = str(df.at[idx, "Slot"] if "Slot" in df.columns else "")

    # appliquer
    if "Statut" in df.columns:
        df.at[idx, "Statut"] = str(to_statut or "").strip()
    if "Slot" in df.columns:
        df.at[idx, "Slot"] = str(to_slot or "").strip()

    st.session_state["data"] = df
    persist_data(df, str(st.session_state.get("season") or ""))

    # log history (avec pos/equipe/saison)
    try:
        row = df.loc[idx]
        log_history_row(
            proprietaire=owner_s,
            joueur=joueur_s,
            pos=str(row.get("Pos", "")).strip(),
            equipe=str(row.get("Equipe", "")).strip(),
            from_statut=from_statut,
            from_slot=from_slot,
            to_statut=str(to_statut or "").strip(),
            to_slot=str(to_slot or "").strip(),
            action=str(note or ""),
        )
    except Exception:
        pass

    return True


# =====================================================
# PICKS (repêchage) — 8 rondes / 8 choix par équipe
# =====================================================
def _picks_path(season_lbl: str) -> str:
    season_lbl = str(season_lbl or "").strip() or "season"
    return os.path.join(DATA_DIR, f"picks_{season_lbl}.json")

def load_picks(season_lbl: str, teams: list[str]) -> dict:
    path = _picks_path(season_lbl)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            # normaliser
            for t in teams:
                data.setdefault(t, {})
                for rnd in range(1, 9):
                    data[t].setdefault(str(rnd), t)
            return data
        except Exception:
            pass
    # init: chaque équipe possède ses 8 choix
    data = {t: {str(r): t for r in range(1, 9)} for t in teams}
    save_picks(season_lbl, data)
    return data

def save_picks(season_lbl: str, data: dict) -> None:
    path = _picks_path(season_lbl)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data or {}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# =====================================================
# BUYOUTS — pénalité 50% salaire (affichée dans la masse)
# =====================================================
def _buyouts_path(season_lbl: str) -> str:
    season_lbl = str(season_lbl or "").strip() or "season"
    return os.path.join(DATA_DIR, f"buyouts_{season_lbl}.csv")

def load_buyouts(season_lbl: str) -> pd.DataFrame:
    path = _buyouts_path(season_lbl)
    cols = ["timestamp", "season", "proprietaire", "joueur", "salaire", "penalite", "bucket"]
    if os.path.exists(path):
        try:
            b = pd.read_csv(path)
            for c in cols:
                if c not in b.columns:
                    b[c] = ""
            return b[cols].copy()
        except Exception:
            return pd.DataFrame(columns=cols)
    return pd.DataFrame(columns=cols)

def save_buyouts(season_lbl: str, b: pd.DataFrame) -> None:
    path = _buyouts_path(season_lbl)
    try:
        b.to_csv(path, index=False)
    except Exception:
        pass

def buyout_penalty_sum(owner: str, bucket: str | None = None) -> int:
    """Somme des pénalités de rachat pour une équipe.
    bucket: 'GC' ou 'CE' (optionnel). Si None -> toutes les pénalités.
    """
    b = st.session_state.get("buyouts")
    if b is None or not isinstance(b, pd.DataFrame) or b.empty:
        return 0
    owner = str(owner or "").strip()

    tmp = b[b["proprietaire"].astype(str).str.strip().eq(owner)].copy()
    if tmp.empty:
        return 0

    if bucket:
        bucket = str(bucket).strip().upper()
        if "bucket" in tmp.columns:
            tmp = tmp[tmp["bucket"].astype(str).str.strip().str.upper().eq(bucket)].copy()
        else:
            # compat vieux fichiers: bucket manquant -> considérer GC par défaut
            if bucket != "GC":
                return 0

    pen = pd.to_numeric(tmp.get("penalite", 0), errors="coerce").fillna(0).astype(int)
    return int(pen.sum())



# =====================================================
# TRADE MARKET (joueurs disponibles aux échanges)
#   - Purement informatif (tag 🔁), persistant par saison
# =====================================================
def _trade_market_path(season_lbl: str) -> str:
    season_lbl = str(season_lbl or "").strip() or "season"
    return os.path.join(DATA_DIR, f"trade_market_{season_lbl}.csv")

def _transactions_path(season_lbl: str) -> str:
    season_lbl = str(season_lbl or "").strip() or "season"
    return os.path.join(DATA_DIR, f"transactions_{season_lbl}.csv")

def load_transactions(season_lbl: str) -> pd.DataFrame:
    """Charge les transactions sauvegardées (proposées) pour une saison."""
    path = _transactions_path(season_lbl)
    cols = ["trade_id","uuid","timestamp","season","owner_a","owner_b","a_players","b_players","a_picks","b_picks","a_retained","b_retained","a_cash","b_cash","status","approved_a","approved_b","submitted_by","approved_at_a","approved_at_b","completed_at"]
    if not os.path.exists(path):
        return pd.DataFrame(columns=cols)
    try:
        t = pd.read_csv(path)
        for c in cols:
            if c not in t.columns:
                t[c] = ""
        return t[cols].copy()
    except Exception:
        return pd.DataFrame(columns=cols)

def save_transactions(season_lbl: str, t: pd.DataFrame) -> None:
    """Persist transactions to local CSV (Cloud-safe)."""
    path = _transactions_path(season_lbl)
    cols = ["trade_id","uuid","timestamp","season","owner_a","owner_b","a_players","b_players","a_picks","b_picks","a_retained","b_retained","a_cash","b_cash","status","approved_a","approved_b","submitted_by","approved_at_a","approved_at_b","completed_at"]
    try:
        if t is None or not isinstance(t, pd.DataFrame):
            t = pd.DataFrame(columns=cols)
        for c in cols:
            if c not in t.columns:
                t[c] = ""
        t = t[cols].copy()
        t.to_csv(path, index=False)
    except Exception:
        pass

def append_transaction(season_lbl: str, row: dict) -> None:
    t = load_transactions(season_lbl)
    t = pd.concat([t, pd.DataFrame([row])], ignore_index=True)
    save_transactions(season_lbl, t)



# =====================================================
# PENDING TRADES — 2-step approval (A submits, B approves)
#   - Stored in transactions_{season}.csv
#   - Visible in Home + GM
# =====================================================

def tx_list_pending(season_lbl: str):
    t = load_transactions(season_lbl)
    if t is None or not isinstance(t, pd.DataFrame) or t.empty:
        return pd.DataFrame(columns=[])
    # normalize status
    tmp = t.copy()
    tmp["status"] = tmp.get("status", "").astype(str)
    pending = tmp[tmp["status"].astype(str).str.strip().isin(["En attente", "Pending", "PENDING"])].copy()
    return pending


def _tx_now_iso():
    try:
        return datetime.now(TZ_TOR).isoformat(timespec="seconds")
    except Exception:
        return datetime.now().isoformat(timespec="seconds")


def tx_next_trade_id(season_lbl: str) -> str:
    """Return next incremental trade_id like TR-00000001 based on transactions_{season}.csv."""
    try:
        t = load_transactions(season_lbl)
        if t is None or (hasattr(t, 'empty') and t.empty) or 'trade_id' not in getattr(t, 'columns', []):
            return 'TR-00000001'
        # Extract numeric part after TR-
        s = t['trade_id'].astype(str).str.strip()
        # accept formats like TR-00000001 or TR-00000001-XXXX
        nums = s.str.extract(r'^TR-(\d{1,})', expand=False)
        nums = pd.to_numeric(nums, errors='coerce').fillna(0).astype(int)
        n = int(nums.max()) if len(nums) else 0
        nxt = n + 1
        return f'TR-{nxt:08d}'
    except Exception:
        return 'TR-00000001'


def tx_create_pending(season_lbl: str, row: dict) -> str:
    """Create a pending trade row and persist. Returns trade_id."""
    trade_id = str(row.get("trade_id") or "").strip() or tx_next_trade_id(season_lbl)
    row = dict(row)
    row["trade_id"] = trade_id
    row.setdefault("uuid", uuid.uuid4().hex)
    row.setdefault("season", season_lbl)
    row.setdefault("timestamp", _tx_now_iso())
    row.setdefault("status", "En attente")
    row.setdefault("approved_a", True)
    row.setdefault("approved_b", False)
    row.setdefault("submitted_by", str(get_selected_team() or "").strip())
    row.setdefault("approved_at_a", _tx_now_iso() if row.get("approved_a") else "")
    row.setdefault("approved_at_b", "")
    row.setdefault("completed_at", "")
    append_transaction(season_lbl, row)
    return trade_id


def _split_pipe(s: str) -> list[str]:
    s = str(s or "").strip()
    if not s:
        return []
    return [x.strip() for x in s.split("|") if x.strip()]


def _parse_pick_label(lbl: str):
    """Parse 'R1 — Canadiens' => (1,'Canadiens'). Returns (round:int, orig_team:str) or (None,None)."""
    lbl = str(lbl or "").strip()
    m = re.search(r"R\s*(\d+)\s*[—\-]\s*(.+)$", lbl)
    if not m:
        return None, None
    try:
        rd = int(m.group(1))
    except Exception:
        return None, None
    orig = str(m.group(2) or "").strip()
    return rd, orig


def tx_execute_trade(season_lbl: str, trade_row: dict) -> bool:
    """Apply players + picks ownership swap. Returns True if applied."""
    try:
        owner_a = str(trade_row.get("owner_a") or "").strip()
        owner_b = str(trade_row.get("owner_b") or "").strip()
        if not owner_a or not owner_b or owner_a == owner_b:
            return False

        df = st.session_state.get("data")
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return False

        a_players = _split_pipe(trade_row.get("a_players", ""))
        b_players = _split_pipe(trade_row.get("b_players", ""))
        a_picks = _split_pipe(trade_row.get("a_picks", ""))
        b_picks = _split_pipe(trade_row.get("b_picks", ""))

        df = clean_data(df.copy())

        # Move players A -> B
        for j in a_players:
            m = (df["Propriétaire"].astype(str).str.strip().eq(owner_a) & df["Joueur"].astype(str).str.strip().eq(str(j).strip()))
            if m.any():
                df.loc[m, "Propriétaire"] = owner_b
                # safe default placement
                if "Statut" in df.columns:
                    df.loc[m, "Statut"] = STATUT_GC
                if "Slot" in df.columns:
                    df.loc[m, "Slot"] = SLOT_BANC

        # Move players B -> A
        for j in b_players:
            m = (df["Propriétaire"].astype(str).str.strip().eq(owner_b) & df["Joueur"].astype(str).str.strip().eq(str(j).strip()))
            if m.any():
                df.loc[m, "Propriétaire"] = owner_a
                if "Statut" in df.columns:
                    df.loc[m, "Statut"] = STATUT_GC
                if "Slot" in df.columns:
                    df.loc[m, "Slot"] = SLOT_BANC

        st.session_state["data"] = df
        persist_data(df, season_lbl)
        st.session_state["plafonds"] = rebuild_plafonds(df)

        # Picks swap
        try:
            owners = sorted(df["Propriétaire"].dropna().astype(str).str.strip().unique().tolist())
            picks = load_picks(season_lbl, owners) if callable(globals().get("load_picks")) else {}
        except Exception:
            picks = {}

        if isinstance(picks, dict) and picks:
            # A sends picks to B
            for lbl in a_picks:
                rd, orig = _parse_pick_label(lbl)
                if rd and orig and str(orig) in picks and str(rd) in picks[str(orig)]:
                    picks[str(orig)][str(rd)] = owner_b
            # B sends picks to A
            for lbl in b_picks:
                rd, orig = _parse_pick_label(lbl)
                if rd and orig and str(orig) in picks and str(rd) in picks[str(orig)]:
                    picks[str(orig)][str(rd)] = owner_a
            save_picks(season_lbl, picks)

        # History log (best effort)
        try:
            tid = str(trade_row.get("trade_id") or "").strip()
            for j in a_players:
                log_history_row(owner_a, j, "", "", "", "", STATUT_GC, SLOT_BANC, action=f"TRADE->{owner_b} #{tid}")
            for j in b_players:
                log_history_row(owner_b, j, "", "", "", "", STATUT_GC, SLOT_BANC, action=f"TRADE->{owner_a} #{tid}")
        except Exception:
            pass

        return True
    except Exception:
        return False


def tx_approve(season_lbl: str, trade_id: str, approver: str) -> tuple[bool, str]:
    """Approve pending trade. Returns (completed, message)."""
    trade_id = str(trade_id or "").strip()
    approver = str(approver or "").strip()
    if not trade_id or not approver:
        return False, "trade_id/approver manquant"

    t = load_transactions(season_lbl)
    if t is None or not isinstance(t, pd.DataFrame) or t.empty:
        return False, "Aucune transaction"

    if "trade_id" not in t.columns:
        return False, "Fichier transactions incompatible"

    m = t["trade_id"].astype(str).str.strip().eq(trade_id)
    if not m.any():
        return False, "Transaction introuvable"

    idx = t.index[m][0]
    row = t.loc[idx].to_dict()
    owner_a = str(row.get("owner_a") or "").strip()
    owner_b = str(row.get("owner_b") or "").strip()

    # Only owners can approve
    if approver != owner_a and approver != owner_b:
        return False, "Seuls les 2 propriétaires peuvent approuver"

    # Set approval
    if approver == owner_a:
        t.at[idx, "approved_a"] = True
        t.at[idx, "approved_at_a"] = _tx_now_iso()
    if approver == owner_b:
        t.at[idx, "approved_b"] = True
        t.at[idx, "approved_at_b"] = _tx_now_iso()

    # Check completion
    a_ok = str(t.at[idx, "approved_a"]).strip().lower() in ["1","true","yes","y","oui"]
    b_ok = str(t.at[idx, "approved_b"]).strip().lower() in ["1","true","yes","y","oui"]

    completed = False
    if a_ok and b_ok:
        # Execute
        ok = tx_execute_trade(season_lbl, row)
        if ok:
            t.at[idx, "status"] = "Complétée"
            t.at[idx, "completed_at"] = _tx_now_iso()
            completed = True
        else:
            t.at[idx, "status"] = "Erreur"

    save_transactions(season_lbl, t)
    if completed:
        return True, "✅ Transaction complétée"
    return False, "✅ Approbation enregistrée"


def tx_render_pending_cards(season_lbl: str, context_owner: str | None = None, in_home: bool = False) -> None:
    """Render pending trades list. If context_owner set, show approve button only for that owner."""
    pend = tx_list_pending(season_lbl)
    if pend is None or not isinstance(pend, pd.DataFrame) or pend.empty:
        if in_home:
            st.caption("Aucune transaction en attente.")
        return

    context_owner = str(context_owner or "").strip()

    st.markdown("### ⏳ Transactions en attente")
    for _, r in pend.iterrows():
        row = r.to_dict()
        tid = str(row.get("trade_id") or "").strip()
        oa = str(row.get("owner_a") or "").strip()
        ob = str(row.get("owner_b") or "").strip()
        a_ok = str(row.get("approved_a", "")).strip().lower() in ["1","true","yes","y","oui"]
        b_ok = str(row.get("approved_b", "")).strip().lower() in ["1","true","yes","y","oui"]

        with st.container(border=True):
            st.markdown(f"**#{tid}** — **{oa} ↔ {ob}**")
            ap = _split_pipe(row.get("a_players", ""))
            bp = _split_pipe(row.get("b_players", ""))
            apk = _split_pipe(row.get("a_picks", ""))
            bpk = _split_pipe(row.get("b_picks", ""))
            st.caption(f"{oa} envoie: {len(ap)} joueur(s), {len(apk)} pick(s) | {ob} envoie: {len(bp)} joueur(s), {len(bpk)} pick(s)")
            st.write(f"Approbations: {oa}={'✅' if a_ok else '⏳'} · {ob}={'✅' if b_ok else '⏳'}")

            # Approve button only for involved owner
            can_approve = context_owner in [oa, ob] and ((context_owner == oa and not a_ok) or (context_owner == ob and not b_ok))
            if can_approve:
                if st.button(f"✅ Approuver ({context_owner})", key=f"approve_{tid}_{context_owner}_{season_lbl}"):
                    done, msg = tx_approve(season_lbl, tid, context_owner)
                    if done:
                        st.success(msg)
                    else:
                        st.info(msg)
                    do_rerun()
            else:
                if context_owner in [oa, ob]:
                    st.caption("Tu as déjà approuvé." if ((context_owner==oa and a_ok) or (context_owner==ob and b_ok)) else "En attente de l'autre propriétaire.")

def load_trade_market(season_lbl: str) -> pd.DataFrame:
    path = _trade_market_path(season_lbl)
    cols = ["season", "proprietaire", "joueur", "is_available", "updated_at"]
    if os.path.exists(path):
        try:
            t = pd.read_csv(path)
            for c in cols:
                if c not in t.columns:
                    t[c] = ""
            return t[cols].copy()
        except Exception:
            pass
    return pd.DataFrame(columns=cols)

def save_trade_market(season_lbl: str, t: pd.DataFrame) -> None:
    path = _trade_market_path(season_lbl)
    cols = ["season", "proprietaire", "joueur", "is_available", "updated_at"]
    try:
        if t is None or not isinstance(t, pd.DataFrame):
            t = pd.DataFrame(columns=cols)
        for c in cols:
            if c not in t.columns:
                t[c] = ""
        t = t[cols].copy()
        t.to_csv(path, index=False)
    except Exception:
        pass

def is_on_trade_market(t: pd.DataFrame, owner: str, joueur: str) -> bool:
    if t is None or not isinstance(t, pd.DataFrame) or t.empty:
        return False
    owner = str(owner or "").strip()
    joueur = str(joueur or "").strip()
    m = (
        t["proprietaire"].astype(str).str.strip().eq(owner)
        & t["joueur"].astype(str).str.strip().eq(joueur)
    )
    if not m.any():
        return False
    v = str(t.loc[m].iloc[-1].get("is_available", "")).strip().lower()
    return v in {"1", "true", "yes", "oui", "y"}

def set_owner_market(t: pd.DataFrame, season_lbl: str, owner: str, available_players: list[str]) -> pd.DataFrame:
    owner = str(owner or "").strip()
    available_set = {str(x).strip() for x in (available_players or []) if str(x).strip()}
    now = datetime.now(TZ_TOR).isoformat(timespec="seconds")

    base = t.copy() if isinstance(t, pd.DataFrame) else load_trade_market(season_lbl)
    # retire anciennes lignes pour owner puis réécrit l'état final
    if not base.empty:
        base = base[~base["proprietaire"].astype(str).str.strip().eq(owner)].copy()

    rows = []
    for j in sorted(available_set):
        rows.append({
            "season": str(season_lbl),
            "proprietaire": owner,
            "joueur": j,
            "is_available": True,
            "updated_at": now,
        })

    if rows:
        base = pd.concat([base, pd.DataFrame(rows)], ignore_index=True)
    return base

# =====================================================
# PLAYERS DB
# =====================================================
def _norm_name(s: str) -> str:
    """Normalize player names for matching.

    - Lowercase
    - Strip accents (Slafkovský == Slafkovsky)
    - Remove team suffixes in parentheses and common separators
    - Keep only alphanumerics and spaces
    """
    s = str(s or '').strip().lower()
    # remove parenthetical team e.g. "Name (COL)"
    s = re.sub(r"\([^)]*\)", " ", s)
    # unicode -> ascii (remove accents)
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    # replace punctuation with spaces
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

# ==============================
# COUNTRY FLAG HELPERS (must be defined before dialogs)
# ==============================
def _iso2_to_flag(iso2: str) -> str:
    try:
        iso2 = (iso2 or '').strip().upper()
        if len(iso2) != 2 or not iso2.isalpha():
            return ''
        return chr(0x1F1E6 + (ord(iso2[0]) - ord('A'))) + chr(0x1F1E6 + (ord(iso2[1]) - ord('A')))
    except Exception:
        return ''

_COUNTRY3_TO2 = {
    'CAN': 'CA', 'USA': 'US', 'SWE': 'SE', 'FIN': 'FI', 'RUS': 'RU', 'CZE': 'CZ', 'SVK': 'SK',
    'CHE': 'CH', 'GER': 'DE', 'DEU': 'DE', 'AUT': 'AT', 'DNK': 'DK', 'NOR': 'NO', 'LVA': 'LV',
    'SVN': 'SI', 'FRA': 'FR', 'GBR': 'GB', 'UKR': 'UA', 'KAZ': 'KZ',
}

_COUNTRYNAME_TO2 = {
    'canada': 'CA', 'united states': 'US', 'usa': 'US', 'sweden': 'SE', 'finland': 'FI',
    'russia': 'RU', 'czechia': 'CZ', 'czech republic': 'CZ', 'slovakia': 'SK', 'switzerland': 'CH',
    'germany': 'DE', 'austria': 'AT', 'denmark': 'DK', 'norway': 'NO', 'latvia': 'LV',
    'slovenia': 'SI', 'france': 'FR', 'great britain': 'GB', 'ukraine': 'UA', 'kazakhstan': 'KZ',
}

def _country_flag_from_landing(landing: dict) -> str:
    """Return a flag emoji from NHL landing payload.
    Tries nationality/birth country fields; supports ISO2, ISO3, and country names.
    """
    if not isinstance(landing, dict):
        return ""

    def _pick(*vals) -> str:
        for v in vals:
            if v is None:
                continue
            # sometimes values are dicts like {"default": "Canada"}
            if isinstance(v, dict):
                v = v.get("default") or v.get("en") or v.get("fr")
            if isinstance(v, (list, tuple)) and v:
                v = v[0]
            s = str(v).strip() if v is not None else ""
            if s and s.lower() not in {"nan", "none", "null", "0", "0.0", "-"}:
                return s
        return ""

    raw = _pick(
        landing.get("nationality"),
        landing.get("nationalityCode"),
        landing.get("birthCountryCode"),
        landing.get("birthCountry"),
    )
    if not raw:
        return ""

    raw = raw.strip()
    # ISO2
    if len(raw) == 2 and raw.isalpha():
        return _iso2_to_flag(raw)
    # ISO3
    if len(raw) == 3 and raw.isalpha():
        return _iso2_to_flag(_COUNTRY3_TO2.get(raw.upper(), ""))
    # Country name
    return _iso2_to_flag(_COUNTRYNAME_TO2.get(raw.lower(), ""))



# --- Fallback: statsapi nationality (some players missing in api-web landing)
@st.cache_data(show_spinner=False, ttl=24*3600)
def _statsapi_people_cached(player_id: int) -> dict:
    """Fetch player info from statsapi.web.nhl.com (best-effort)."""
    try:
        pid = int(player_id or 0)
    except Exception:
        pid = 0
    if pid <= 0:
        return {}
    try:
        url = f"https://statsapi.web.nhl.com/api/v1/people/{pid}"
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return {}
        return r.json() if isinstance(r.json(), dict) else {}
    except Exception:
        return {}


# --- Fallback: draft prospects nationality (for players not present in NHL stats tables yet)
# Note: this endpoint returns a large payload; we cache it and only touch it when needed.
@st.cache_data(show_spinner=False, ttl=7*24*3600)
def _draft_prospects_map_cached() -> dict:
    # Map normalized prospect fullName -> ISO3 nationality/birthCountry
    try:
        url = "https://statsapi.web.nhl.com/api/v1/draft/prospects"
        r = requests.get(url, timeout=20)
        if r.status_code != 200:
            return {}
        j = r.json() if hasattr(r, 'json') else {}
        if not isinstance(j, dict):
            return {}
        prospects = j.get('prospects') or []
        if not isinstance(prospects, list):
            return {}
        out = {}
        for p in prospects:
            if not isinstance(p, dict):
                continue
            name = str(p.get('fullName') or '').strip()
            if not name:
                continue
            raw = str(p.get('nationality') or p.get('birthCountry') or '').strip()
            if not raw:
                continue
            key = _norm_name(name)
            if key:
                out[key] = raw
        return out
    except Exception:
        return {}


def _flag_from_any_country_code(raw: str) -> str:
    raw = str(raw or '').strip()
    if not raw or raw.lower() in {'nan','none','null','0','0.0','-'}:
        return ''
    if len(raw) == 2 and raw.isalpha():
        return _iso2_to_flag(raw)
    if len(raw) == 3 and raw.isalpha():
        return _iso2_to_flag(_COUNTRY3_TO2.get(raw.upper(), ''))
    return _iso2_to_flag(_COUNTRYNAME_TO2.get(raw.lower(), ''))




def _country_override_flag_from_players_db(player_id: int, player_name: str | None = None) -> str:
    """Return a flag emoji from manual Country column in hockey.players.csv, if available.

    Accepts ISO2 (CA), ISO3 (CAN), or country name (Canada).
    """
    try:
        pid = int(player_id or 0)
    except Exception:
        pid = 0

    path = _first_existing(PLAYERS_DB_FALLBACKS) if 'PLAYERS_DB_FALLBACKS' in globals() else ''
    if not path:
        path = os.path.join(DATA_DIR, 'hockey.players.csv')
    if not path or not os.path.exists(path):
        return ''

    try:
        mtime = os.path.getmtime(path)
    except Exception:
        mtime = 0.0

    db = load_players_db(path, mtime) if 'load_players_db' in globals() else pd.DataFrame()
    if db is None or db.empty or 'Country' not in db.columns:
        return ''

    def _clean(v: object) -> str:
        s = str(v or '').strip()
        if not s or s.lower() in {'nan','none','null','0','0.0','-'}:
            return ''
        return s

    # Match by playerId first
    if pid > 0 and 'playerId' in db.columns:
        try:
            pid_series = pd.to_numeric(db['playerId'], errors='coerce').fillna(0).astype(int)
            m = pid_series.eq(pid)
            if bool(m.any()):
                raw = _clean(db.loc[m, 'Country'].iloc[0])
                f = _flag_from_any_country_code(raw)
                if f:
                    return f
        except Exception:
            pass

    # Fallback by name
    if player_name and 'Player' in db.columns:
        try:
            key = _norm_name(player_name)
            # also try 'Last, First' swap if present
            key2 = _norm_name(player_name.split(' ', 1)[-1] + ', ' + player_name.split(' ', 1)[0]) if ' ' in player_name else ''
            for nm, raw in zip(db['Player'].astype(str).fillna('').tolist(), db['Country'].tolist()):
                k = _norm_name(nm)
                if k and (k == key or (key2 and k == key2)):
                    raw = _clean(raw)
                    f = _flag_from_any_country_code(raw)
                    if f:
                        return f
        except Exception:
            pass

    return ''
def _player_flag(player_id: int, landing: dict | None = None, player_name: str | None = None) -> str:
    """Return flag emoji for a player.

    Priority:
      1) api-web landing payload (fast)
      2) statsapi people endpoint (nationality / birthCountry) fallback
    """
    try:
        pid = int(player_id or 0)
    except Exception:
        pid = 0
    # 0) manual Country override (players DB)
    f0 = _country_override_flag_from_players_db(pid, player_name)
    if f0:
        return f0

    # 1) landing
    if isinstance(landing, dict):
        f = _country_flag_from_landing(landing)
        if f:
            return f

    # 2) statsapi fallback
    if pid > 0:
        j = _statsapi_people_cached(pid)
        ppl = []
        try:
            ppl = j.get('people') or []
        except Exception:
            ppl = []
        if ppl and isinstance(ppl, list) and isinstance(ppl[0], dict):
            p0 = ppl[0]
            raw = str(p0.get('nationality') or p0.get('birthCountry') or '').strip()
            if raw and raw.lower() not in {'nan','none','null','0','0.0','-'}:
                if len(raw) == 2 and raw.isalpha():
                    return _iso2_to_flag(raw)
                if len(raw) == 3 and raw.isalpha():
                    return _iso2_to_flag(_COUNTRY3_TO2.get(raw.upper(), ''))
                return _iso2_to_flag(_COUNTRYNAME_TO2.get(raw.lower(), ''))

    # 3) draft prospects fallback (no NHL playerId yet)
    if player_name:
        try:
            mp = _draft_prospects_map_cached()
            raw = mp.get(_norm_name(player_name), '') if isinstance(mp, dict) else ''
            f = _flag_from_any_country_code(raw)
            if f:
                return f
        except Exception:
            pass


    return ''


# =====================================================
# Country auto-fill (Web): Wikipedia + Wikidata
#   - Used ONLY from Admin tools (manual apply step)
#   - Cached locally to avoid repeated network calls
# =====================================================

def _country_cache_path() -> str:
    return os.path.join(DATA_DIR, 'country_web_cache.json')


def _load_country_cache() -> dict:
    path = _country_cache_path()
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                j = json.load(f)
                return j if isinstance(j, dict) else {}
    except Exception:
        pass
    return {}


def _save_country_cache(cache: dict) -> None:
    path = _country_cache_path()
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(cache or {}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


_WIKIDATA_COUNTRYNAME_TO2 = {
    # Common hockey countries
    'canada': 'CA',
    'united states of america': 'US',
    'united states': 'US',
    'usa': 'US',
    'sweden': 'SE',
    'finland': 'FI',
    'slovakia': 'SK',
    'czech republic': 'CZ',
    'czechia': 'CZ',
    'russia': 'RU',
    'germany': 'DE',
    'switzerland': 'CH',
    'latvia': 'LV',
    'norway': 'NO',
    'denmark': 'DK',
    'austria': 'AT',
    'belarus': 'BY',
    'ukraine': 'UA',
    'slovenia': 'SI',
    'poland': 'PL',
    'kazakhstan': 'KZ',
    'france': 'FR',
    'italy': 'IT',
    'japan': 'JP',
    'china': 'CN',
    'south korea': 'KR',
    'korea, south': 'KR',
    'united kingdom': 'GB',
    'england': 'GB',
    'scotland': 'GB',
    'wales': 'GB',
}


def _country_from_wikidata_label(label: str) -> str:
    if not label:
        return ''
    low = str(label).strip().lower()
    return _WIKIDATA_COUNTRYNAME_TO2.get(low, '')


def _wikipedia_search_title(name: str) -> str:
    """Return best matching Wikipedia title for a player name."""
    try:
        import requests
        q = f"{name} ice hockey"
        url = 'https://en.wikipedia.org/w/api.php'
        params = {
            'action': 'query',
            'list': 'search',
            'srsearch': q,
            'srlimit': 1,
            'format': 'json',
        }
        r = requests.get(url, params=params, timeout=10, headers={'User-Agent': 'PoolHockeyApp/1.0'})
        if r.status_code != 200:
            return ''
        j = r.json() if r.content else {}
        hits = ((j.get('query') or {}).get('search') or [])
        if hits and isinstance(hits, list) and isinstance(hits[0], dict):
            return str(hits[0].get('title') or '').strip()
    except Exception:
        pass
    return ''


def _wikibase_item_from_title(title: str) -> str:
    """Get Wikidata Q-id from a Wikipedia title."""
    if not title:
        return ''
    try:
        import requests
        url = 'https://en.wikipedia.org/w/api.php'
        params = {
            'action': 'query',
            'prop': 'pageprops',
            'titles': title,
            'format': 'json',
        }
        r = requests.get(url, params=params, timeout=10, headers={'User-Agent': 'PoolHockeyApp/1.0'})
        if r.status_code != 200:
            return ''
        j = r.json() if r.content else {}
        pages = ((j.get('query') or {}).get('pages') or {})
        if isinstance(pages, dict):
            for _, v in pages.items():
                if isinstance(v, dict):
                    pp = v.get('pageprops') or {}
                    qid = str(pp.get('wikibase_item') or '').strip()
                    if qid.startswith('Q'):
                        return qid
    except Exception:
        pass
    return ''


def _country_from_wikidata_entity(qid: str) -> str:
    """Fetch country from Wikidata entity (citizenship/place of birth -> country)."""
    if not qid:
        return ''
    try:
        import requests
        url = 'https://www.wikidata.org/w/api.php'
        params = {
            'action': 'wbgetentities',
            'ids': qid,
            'props': 'claims',
            'format': 'json',
        }
        r = requests.get(url, params=params, timeout=10, headers={'User-Agent': 'PoolHockeyApp/1.0'})
        if r.status_code != 200:
            return ''
        j = r.json() if r.content else {}
        ent = ((j.get('entities') or {}).get(qid) or {})
        claims = ent.get('claims') or {}

        # Try P27 (country of citizenship) first
        def _extract_qids(prop: str) -> list:
            out = []
            arr = claims.get(prop) or []
            if not isinstance(arr, list):
                return out
            for it in arr:
                try:
                    dv = (((it.get('mainsnak') or {}).get('datavalue') or {}).get('value') or {})
                    q = str(dv.get('id') or '').strip()
                    if q.startswith('Q'):
                        out.append(q)
                except Exception:
                    continue
            return out

        country_qids = _extract_qids('P27')

        # Fallback P19 place of birth -> P17 country
        pob_qids = _extract_qids('P19') if not country_qids else []

        def _labels_for(qids: list) -> list:
            if not qids:
                return []
            try:
                url2 = 'https://www.wikidata.org/w/api.php'
                params2 = {
                    'action': 'wbgetentities',
                    'ids': '|'.join(qids[:5]),
                    'props': 'labels',
                    'languages': 'en',
                    'format': 'json',
                }
                r2 = requests.get(url2, params=params2, timeout=10, headers={'User-Agent': 'PoolHockeyApp/1.0'})
                if r2.status_code != 200:
                    return []
                j2 = r2.json() if r2.content else {}
                ents = j2.get('entities') or {}
                labs = []
                if isinstance(ents, dict):
                    for _, ev in ents.items():
                        lab = (((ev or {}).get('labels') or {}).get('en') or {}).get('value')
                        if lab:
                            labs.append(str(lab))
                return labs
            except Exception:
                return []

        # Country of citizenship labels
        for lab in _labels_for(country_qids):
            iso2 = _country_from_wikidata_label(lab)
            if iso2:
                return iso2

        # Place of birth -> country (P17)
        if pob_qids:
            # Get P17 from each place entity
            for place_qid in pob_qids[:3]:
                try:
                    params_p = {
                        'action': 'wbgetentities',
                        'ids': place_qid,
                        'props': 'claims',
                        'format': 'json',
                    }
                    rp = requests.get(url, params=params_p, timeout=10, headers={'User-Agent': 'PoolHockeyApp/1.0'})
                    if rp.status_code != 200:
                        continue
                    jp = rp.json() if rp.content else {}
                    entp = ((jp.get('entities') or {}).get(place_qid) or {})
                    claimsp = entp.get('claims') or {}
                    arr = claimsp.get('P17') or []
                    qids = []
                    if isinstance(arr, list):
                        for it in arr:
                            dv = (((it.get('mainsnak') or {}).get('datavalue') or {}).get('value') or {})
                            q = str(dv.get('id') or '').strip()
                            if q.startswith('Q'):
                                qids.append(q)
                    for lab in _labels_for(qids):
                        iso2 = _country_from_wikidata_label(lab)
                        if iso2:
                            return iso2
                except Exception:
                    continue
    except Exception:
        pass
    return ''


def suggest_country_web(player_name: str) -> tuple[str, str, float]:
    """Suggest ISO2 country via Wikipedia + Wikidata.

    Returns: (country_iso2, source, confidence)
    """
    name = str(player_name or '').strip()
    if not name:
        return ('', '', 0.0)

    key = _norm_name(name)
    cache = _load_country_cache()
    if key in cache:
        v = cache.get(key) or {}
        iso2 = str(v.get('iso2') or '').strip()
        src = str(v.get('src') or '').strip()
        conf = float(v.get('conf') or 0.0)
        return (iso2, src, conf)

    title = _wikipedia_search_title(name)
    if not title:
        return ('', '', 0.0)
    qid = _wikibase_item_from_title(title)
    if not qid:
        return ('', '', 0.0)

    iso2 = _country_from_wikidata_entity(qid)
    if not iso2:
        return ('', '', 0.0)

    # Confidence heuristic: exact name match in title -> higher
    conf = 0.85
    if _norm_name(title) == key:
        conf = 0.95

    cache[key] = {'iso2': iso2, 'src': 'Wikipedia+Wikidata', 'conf': conf}
    _save_country_cache(cache)
    return (iso2, 'Wikipedia+Wikidata', conf)


@st.cache_data(show_spinner=False)
def load_puckpedia_contracts(path: str, mtime: float = 0.0) -> pd.DataFrame:
    """Charge puckpedia.contracts.csv (si présent) et prépare une clé de jointure.

    Supporte plusieurs formats:
      A) Colonnes explicites: first_name/last_name + contract_end + contract_level
      B) Colonnes 'Player'/'Name'/'Joueur' + contract_end + contract_level
      C) Format sans en-têtes fiable (comme ton screenshot): prenoms/nom en colonnes 0/1,
         contract_end en avant-dernière colonne, contract_level en dernière colonne.

    Retourne un DF avec:
      - _name_key (clé normalisée du nom complet)
      - contract_level (ELC/STD ou "")
      - contract_end (texte)
      - contract_end_year (Int or NA)
    """
    if not path or not os.path.exists(path):
        return pd.DataFrame(columns=["_name_key","contract_level","contract_end","contract_end_year"])

    try:
        dfc = pd.read_csv(path)
    except Exception:
        try:
            dfc = pd.read_csv(path, sep='\t')
        except Exception:
            return pd.DataFrame(columns=["_name_key","contract_level","contract_end","contract_end_year"])

    if dfc is None or dfc.empty:
        return pd.DataFrame(columns=["_name_key","contract_level","contract_end","contract_end_year"])

    cols_lower = {str(c).strip().lower(): c for c in dfc.columns}

    # --- 1) Construire le nom complet
    name_series = None

    # A) first/last explicit
    first_col = None
    last_col = None
    for k in ["first", "firstname", "first_name", "prenom", "prénom", "given", "given_name"]:
        if k in cols_lower:
            first_col = cols_lower[k]
            break
    for k in ["last", "lastname", "last_name", "nom", "surname", "family", "family_name"]:
        if k in cols_lower:
            last_col = cols_lower[k]
            break

    if first_col and last_col:
        name_series = dfc[first_col].astype(str).str.strip() + " " + dfc[last_col].astype(str).str.strip()
    else:
        # B) single player name column
        name_col = None
        for k in ["player", "name", "joueur", "full name", "fullname"]:
            if k in cols_lower:
                name_col = cols_lower[k]
                break
        if name_col:
            name_series = dfc[name_col].astype(str).str.strip()
        else:
            # C) fallback: assume first two columns are first/last
            try:
                name_series = dfc.iloc[:, 0].astype(str).str.strip() + " " + dfc.iloc[:, 1].astype(str).str.strip()
            except Exception:
                name_series = dfc.iloc[:, 0].astype(str).str.strip()

    # --- 2) contract_level + contract_end detection
    lvl_col = None
    end_col = None

    for k in ["contract_level", "level", "contractlevel"]:
        if k in cols_lower:
            lvl_col = cols_lower[k]
            break
    for k in ["contract_end", "end", "expiry", "expires", "expiration"]:
        if k in cols_lower:
            end_col = cols_lower[k]
            break

    # fallback to last columns if not found
    if lvl_col is None:
        try:
            lvl_col = dfc.columns[-1]
        except Exception:
            lvl_col = None
    if end_col is None:
        try:
            end_col = dfc.columns[-2]
        except Exception:
            end_col = None

    out = pd.DataFrame()
    out["_name_key"] = name_series.map(_norm_name)

    raw_lvl = dfc[lvl_col].astype(str).str.strip() if lvl_col is not None else ""
    raw_end = dfc[end_col].astype(str).str.strip() if end_col is not None else ""

    # normaliser contract_level -> ELC/STD
    def _norm_lvl(v: str) -> str:
        v = str(v or "").strip().lower()
        if "entry" in v or v in ["elc", "entry_level"]:
            return "ELC"
        if "standard" in v or v in ["std", "standard_level"]:
            return "STD"
        return ""

    out["contract_level"] = raw_lvl.map(_norm_lvl)
    out["contract_end"] = raw_end

    # extraire l'année de fin (ex: 2025-2026 -> 2026)
    out["contract_end_year"] = (
        out["contract_end"].astype(str).str.extract(r"(20\d{2})\s*$")[0]
    )
    out["contract_end_year"] = pd.to_numeric(out["contract_end_year"], errors="coerce").astype("Int64")

    out = out.dropna(subset=["_name_key"])
    out = out[out["_name_key"].astype(str).str.strip() != ""]
    out = out.drop_duplicates(subset=["_name_key"], keep="first").copy()

    return out


@st.cache_data(show_spinner=False)
def load_players_db_enriched(pdb_path: str, mtime_pdb: float = 0.0, mtime_contracts: float = 0.0) -> pd.DataFrame:
    """Lit hockey.players.csv et applique automatiquement:
      - merge puckpedia.contracts.csv (override Level + Expiry Year quand dispo)
      - colonnes Flags (FlagISO2 + Flag) depuis Country
    """
    if not pdb_path or not os.path.exists(pdb_path):
        return pd.DataFrame()

    try:
        dfp = pd.read_csv(pdb_path)
    except Exception:
        return pd.DataFrame()

    if dfp is None or dfp.empty:
        return pd.DataFrame()

    # key join
    if "Player" in dfp.columns:
        dfp["_name_key"] = dfp["Player"].astype(str).map(lambda s: _norm_name(_to_first_last(s)))
    elif "Joueur" in dfp.columns:
        dfp["_name_key"] = dfp["Joueur"].astype(str).map(lambda s: _norm_name(_to_first_last(s)))
    else:
        dfp["_name_key"] = ""

    # merge contracts if present
    contracts_path = os.path.join(os.path.dirname(pdb_path), "puckpedia.contracts.csv")
    if os.path.exists(contracts_path):
        try:
            dfc = load_puckpedia_contracts(contracts_path, mtime=mtime_contracts)
        except Exception:
            dfc = pd.DataFrame()
        if isinstance(dfc, pd.DataFrame) and not dfc.empty and "_name_key" in dfc.columns:
            # ensure cols
            for col in ["contract_level","contract_end","Level","Expiry Year"]:
                if col not in dfp.columns:
                    dfp[col] = ""

            dfp = dfp.merge(
                dfc[["_name_key","contract_level","contract_end","contract_end_year"]],
                on="_name_key",
                how="left",
                suffixes=("","_puck"),
            )

            # Always fill raw contract columns from puck when available
            dfp["contract_level"] = dfp.get("contract_level","" ).astype(str)
            dfp["contract_level"] = dfp["contract_level"].where(
                dfp["contract_level"].str.strip() != "",
                dfp.get("contract_level_puck", "").fillna("").astype(str)
            )

            dfp["contract_end"] = dfp.get("contract_end","" ).astype(str)
            dfp["contract_end"] = dfp["contract_end"].where(
                dfp["contract_end"].str.strip() != "",
                dfp.get("contract_end_puck", "").fillna("").astype(str)
            )

            # ✅ IMPORTANT: override Level from puck when puck has ELC/STD
            puck_lvl = dfp.get("contract_level_puck", "").fillna("").astype(str).str.strip().str.upper()
            dfp["Level"] = dfp.get("Level", "").fillna("").astype(str).str.strip().str.upper()
            dfp.loc[puck_lvl.isin(["ELC","STD"]), "Level"] = puck_lvl[puck_lvl.isin(["ELC","STD"])]

            # Expiry Year from puck end year when present
            puck_endy = dfp.get("contract_end_year_puck")
            if puck_endy is not None:
                dfp["Expiry Year"] = dfp.get("Expiry Year", "").fillna("").astype(str).str.strip()
                dfp.loc[pd.notna(puck_endy), "Expiry Year"] = puck_endy[pd.notna(puck_endy)].astype(str)

            # cleanup
            for c in ["contract_level_puck","contract_end_puck","contract_end_year_puck"]:
                if c in dfp.columns:
                    dfp.drop(columns=[c], inplace=True)

    # Flags from Country
    if "FlagISO2" not in dfp.columns:
        dfp["FlagISO2"] = ""
    if "Flag" not in dfp.columns:
        dfp["Flag"] = ""
    if "Country" not in dfp.columns:
        dfp["Country"] = ""

    try:
        iso = dfp["FlagISO2"].astype(str).str.strip()
        need_iso = iso.eq("") & dfp["Country"].astype(str).str.strip().ne("")
        if need_iso.any():
            dfp.loc[need_iso, "FlagISO2"] = dfp.loc[need_iso, "Country"].astype(str).map(_country_to_iso2)
    except Exception:
        pass

    try:
        fl = dfp["Flag"].astype(str).str.strip()
        need_fl = fl.eq("") & dfp["FlagISO2"].astype(str).str.strip().ne("")
        if need_fl.any():
            dfp.loc[need_fl, "Flag"] = dfp.loc[need_fl, "FlagISO2"].astype(str).map(_iso2_to_flag_emoji)
    except Exception:
        pass

    # normalize Level display: only ELC/STD, else blank
    try:
        dfp["Level"] = dfp.get("Level", "").astype(str).str.strip().str.upper()
        dfp.loc[~dfp["Level"].isin(["ELC","STD"]), "Level"] = ""
    except Exception:
        pass

    return dfp


def ensure_players_db_loaded() -> pd.DataFrame:
    """Charge et enrichit players_db une fois; stocke dans st.session_state['players_db']."""
    try:
        pdb_path = os.path.join(DATA_DIR, "hockey.players.csv") if "DATA_DIR" in globals() else "data/hockey.players.csv"
        mtime_pdb = os.path.getmtime(pdb_path) if os.path.exists(pdb_path) else 0.0
        contracts_path = os.path.join(os.path.dirname(pdb_path), "puckpedia.contracts.csv")
        mtime_c = os.path.getmtime(contracts_path) if os.path.exists(contracts_path) else 0.0
        pdb = load_players_db_enriched(pdb_path, mtime_pdb=mtime_pdb, mtime_contracts=mtime_c)
        if isinstance(pdb, pd.DataFrame) and not pdb.empty:
            st.session_state["players_db"] = pdb
        return pdb
    except Exception:
        return st.session_state.get("players_db", pd.DataFrame())


def ensure_owner_column(df: pd.DataFrame, fallback_owner: str) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame):
        return df
    out = df.copy()
    candidates = [
        "Propriétaire", "Proprietaire",
        "Owner", "owner", "Owners", "owners",
        "Team", "team",
        "Équipe", "Equipe", "équipe", "equipe",
        "Franchise", "franchise",
        "Club", "club",
    ]
    existing = next((c for c in candidates if c in out.columns), None)
    if existing and existing != "Propriétaire":
        out["Propriétaire"] = out[existing]
    if "Propriétaire" not in out.columns:
        out["Propriétaire"] = str(fallback_owner or "").strip()

    s = out["Propriétaire"].astype(str).str.strip()
    s = s.replace({"nan": "", "None": ""})
    s = s.mask(s.eq(""), str(fallback_owner or "").strip())
    out["Propriétaire"] = s
    return out


# =====================================================
# MOVE DIALOG — auto-remplacement IR + étiquette exacte
# =====================================================

# =====================================================
# PENDING MOVES (déplacements programmés)
# =====================================================
def _init_pending_moves():
    if "pending_moves" not in st.session_state or st.session_state["pending_moves"] is None:
        st.session_state["pending_moves"] = []

def process_pending_moves():
    """
    Applique les moves programmés dont la date d'effet est atteinte.
    Stockage: st.session_state["pending_moves"] = list[dict]
    """
    _init_pending_moves()
    moves = st.session_state.get("pending_moves") or []
    if not isinstance(moves, list) or not moves:
        return

    now = datetime.now(TZ_TOR)
    keep = []
    applied = 0

    for mv in moves:
        try:
            eff = pd.to_datetime(mv.get("effective_at"), errors="coerce")
            eff = eff.to_pydatetime() if not pd.isna(eff) else None
        except Exception:
            eff = None

        if eff is None or eff > now:
            keep.append(mv)
            continue

        owner = str(mv.get("owner","")).strip()
        joueur = str(mv.get("joueur","")).strip()
        to_statut = str(mv.get("to_statut","")).strip()
        to_slot = str(mv.get("to_slot","")).strip()
        note = str(mv.get("note","")).strip() or "Move programmé"

        ok = False
        if "apply_move_with_history" in globals() and callable(globals()["apply_move_with_history"]):
            ok = bool(globals()["apply_move_with_history"](owner, joueur, to_statut, to_slot, note))
        else:
            # fallback minimal
            df = st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS))
            m = (
                df["Propriétaire"].astype(str).str.strip().eq(owner)
                & df["Joueur"].astype(str).str.strip().eq(joueur)
            )
            if m.any():
                idx = df.index[m][0]
                df.at[idx, "Statut"] = to_statut
                df.at[idx, "Slot"] = to_slot
                st.session_state["data"] = df
                ok = True

        if ok:
            applied += 1
        else:
            keep.append(mv)

    st.session_state["pending_moves"] = keep
    if applied:
        try:
            persist_data(st.session_state.get("data"), st.session_state.get("season"))
        except Exception:
            pass

def open_move_dialog():
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
    if df_all is None or not isinstance(df_all, pd.DataFrame) or df_all.empty:
        st.error("Aucune donnée chargée.")
        clear_move_ctx()
        return

    df_all = clean_data(df_all)

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

    # -------------------------------------------------
    # RÈGLES D’EFFET (TES RÈGLES)
    # -------------------------------------------------
    def _effective_date(reason: str, from_statut: str, from_slot: str,
                        to_statut: str, to_slot: str) -> datetime:
        """
        Règles finales:
        - Changement demi-mois → IMMÉDIAT (toujours)
        - Blessure :
            - GC → CE (mineur) → IMMÉDIAT
            - CE → Actif (GC Actif) → +3 jours
            - autres → IMMÉDIAT
        """
        now = datetime.now(TZ_TOR)

        reason_low = str(reason or "").lower().strip()
        from_statut = str(from_statut or "").strip()
        from_slot = str(from_slot or "").strip()
        to_statut = str(to_statut or "").strip()
        to_slot = str(to_slot or "").strip()

        # Demi-mois = immédiat
        if reason_low.startswith("changement"):
            return now

        # Blessure
        if reason_low.startswith("bless"):
            # GC -> CE immédiat
            if from_statut == STATUT_GC and to_statut == STATUT_CE:
                return now
            # CE -> Actif (+3 jours)
            if from_statut == STATUT_CE and to_statut == STATUT_GC and to_slot == SLOT_ACTIF:
                return now + timedelta(days=3)
            return now

        return now

    # -------------------------------------------------
    # AUTO-REMPLACEMENT (GC Actif -> IR)
    # -------------------------------------------------
    def _auto_replace_injured(owner_: str, injured_pos_: str) -> bool:
        dfx = st.session_state.get("data")
        if dfx is None or not isinstance(dfx, pd.DataFrame) or dfx.empty:
            return False

        dfx = clean_data(dfx)
        owner_ = str(owner_ or "").strip()
        injured_pos_ = normalize_pos(injured_pos_)

        dprop = dfx[dfx["Propriétaire"].astype(str).str.strip().eq(owner_)].copy()
        if dprop.empty:
            return False

        # Exclure IR
        dprop_ok = dprop[dprop.get("Slot", "") != SLOT_IR].copy()

        # Exclure les lignes de cap mort des listes (Actifs/Banc/Mineur), mais garder pour le calcul du cap ailleurs
        dprop_ok = dprop_ok[dprop_ok.get("Slot","").astype(str).str.strip().ne(SLOT_RACHAT)].copy()

        # Banc GC
        banc = dprop_ok[
            (dprop_ok["Statut"] == STATUT_GC)
            & (dprop_ok.get("Slot", "").astype(str).str.strip() == SLOT_BANC)
        ].copy()

        # CE
        ce = dprop_ok[
            (dprop_ok["Statut"] == STATUT_CE)
        ].copy()

        def _pick(df_cand: pd.DataFrame) -> str | None:
            if df_cand is None or df_cand.empty:
                return None

            tmp = df_cand.copy()
            tmp["Pos"] = tmp.get("Pos", "F").apply(normalize_pos)
            tmp["Salaire"] = pd.to_numeric(tmp.get("Salaire", 0), errors="coerce").fillna(0).astype(int)

            same = tmp[tmp["Pos"] == injured_pos_].copy()
            pool = same if not same.empty else tmp

            pool["_posk"] = pool["Pos"].apply(pos_sort_key)
            pool = pool.sort_values(
                by=["_posk", "Salaire", "Joueur"],
                ascending=[True, False, True],
                kind="mergesort",
            )

            j = str(pool.iloc[0].get("Joueur", "")).strip()
            return j if j else None

        # 1) Banc -> Actif (immédiat)
        pick = _pick(banc)
        if pick:
            ok = _apply_f(
                owner_,
                pick,
                STATUT_GC,
                SLOT_ACTIF,
                "AUTO REMPLACEMENT — Banc → Actif (blessure)",
            )
            return bool(ok)

        # 2) CE -> Actif (immédiat dans le remplacement auto)
        pick = _pick(ce)
        if pick:
            ok = _apply_f(
                owner_,
                pick,
                STATUT_GC,
                SLOT_ACTIF,
                "AUTO REMPLACEMENT — CE → Actif (blessure)",
            )
            return bool(ok)

        return False
    @st.dialog(f"Déplacement — {joueur}", width="small")
    def _dlg():
        st.markdown(
            f"<div class='dlg-title'>{html.escape(owner)} • {html.escape(joueur)}</div>"
            f"<div class='dlg-sub'>{html.escape(cur_statut)}"
            f"{(' / ' + html.escape(cur_slot)) if cur_slot else ''}"
            f" • {html.escape(cur_pos)} • {html.escape(cur_team)} • {money(cur_sal)}</div>",
            unsafe_allow_html=True,
        )
        st.divider()

        # season label (safe for dialog scope)
        season_lbl = str(st.session_state.get("season") or st.session_state.get("season_lbl") or "season").strip() or "season"

        # -------------------------------------------------
        # ℹ️ Infos joueur (NHL API) — best effort
        # -------------------------------------------------

        try:
            cur_pid = int(row.get("playerId", 0) or 0)
        except Exception:
            cur_pid = 0

        # fallback: try Players DB mapping by name
        if cur_pid <= 0:
            try:
                pdb_path = _first_existing(PLAYERS_DB_FALLBACKS) if "PLAYERS_DB_FALLBACKS" in globals() else ""
                if not pdb_path:
                    pdb_path = os.path.join(DATA_DIR, "hockey.players.csv")
                mtime = os.path.getmtime(pdb_path) if (pdb_path and os.path.exists(pdb_path)) else 0.0
                pdb = load_players_db(pdb_path, mtime)
                if pdb is not None and not pdb.empty and "playerId" in pdb.columns and "Player" in pdb.columns:
                    # Utilise une normalisation disponible AVANT ce dialog (évite NameError)
                    nm = _norm_name(joueur)
                    pdb2 = pdb.copy()
                    pdb2["_k"] = pdb2["Player"].astype(str).map(_norm_name)
                    hit = pdb2[pdb2["_k"] == nm]
                    if not hit.empty:
                        cur_pid = int(hit.iloc[0].get("playerId", 0) or 0)
            except Exception:
                pass

        # -------------------------------------------------
        # Option B (auto): tentative automatique (1x) de trouver un playerId par nom
        #   - scan rosters via statsapi (caché 24h)
        #   - si trouvé: upsert identity dans hockey.players.csv (sans écraser Level/Cap Hit)
        # -------------------------------------------------
        if cur_pid <= 0:
            auto_key = f"auto_pid_try__{season_lbl}__{_norm_name(joueur)}"
            if not st.session_state.get(auto_key, False):
                st.session_state[auto_key] = True
                try:
                    guess = nhl_find_playerid_by_name_cached(joueur, season_lbl=season_lbl)
                    if int(guess or 0) > 0:
                        _upsert_player_identity_to_players_db(int(guess))
                        cur_pid = int(guess)
                except Exception:
                    pass

        # Pré-fetch landing (si possible) pour afficher la photo dès l'ouverture du dialog
        landing = None
        headshot = ""
        if cur_pid > 0:
            try:
                landing = nhl_player_landing_cached(cur_pid)
                if isinstance(landing, dict):
                    headshot = str(landing.get("headshot") or _landing_field(landing, ["headshot", "default"], "") or "").strip()
            except Exception:
                landing = None

        # Photo du joueur (affichée tout de suite quand on clique son nom)
        if headshot:
            try:
                st.image(headshot, width=140)
            except Exception:
                st.caption(headshot)

        # Infos NHL (toujours expanded)
        with st.expander("ℹ️ Infos NHL (api-web.nhle.com)", expanded=True):
            if cur_pid > 0:
                if isinstance(landing, dict) and landing:
                    first = str(_landing_field(landing, ["firstName", "default"], "") or _landing_field(landing, ["firstName"], "") or "").strip()
                    last  = str(_landing_field(landing, ["lastName", "default"], "") or _landing_field(landing, ["lastName"], "") or "").strip()
                    full  = (first + " " + last).strip() or str(landing.get("fullName") or "").strip()
                    pos   = str(landing.get("position") or landing.get("positionCode") or "").strip()
                    shoots= str(landing.get("shootsCatches") or "").strip()

                    team_abbrev = ""
                    team = landing.get("currentTeam")
                    if isinstance(team, dict):
                        team_abbrev = str(team.get("abbrev") or team.get("triCode") or "").strip()
                    if not team_abbrev:
                        team_abbrev = str(landing.get("currentTeamAbbrev") or "").strip()

                    height = landing.get("heightInInches") or landing.get("height")
                    weight = landing.get("weightInPounds") or landing.get("weight")
                    bdate  = str(landing.get("birthDate") or "").strip()

                    flag = _player_flag(cur_pid, landing, joueur)
                    title = f"{flag} {full or joueur}".strip() if flag else (full or joueur)
                    st.markdown(f"**{html.escape(title)}**")
                    if st.button("👤 Profil complet", key=f"btn_profile__{cur_pid}__{nonce}"):
                        st.session_state["profile_player_id"] = int(cur_pid)
                        st.session_state["profile_player_name"] = str(full or joueur)
                        st.session_state["move_ctx"] = None
                        st.session_state["active_tab"] = "👤 Profil Joueurs NHL"
                        do_rerun()

                    cols = st.columns(3)
                    cols[0].caption(f"playerId: {cur_pid}")
                    cols[1].caption(f"Pos: {pos or cur_pos}")
                    cols[2].caption(f"Team: {team_abbrev or cur_team}")

                    cols2 = st.columns(3)
                    cols2[0].caption(f"Shoots: {shoots or '—'}")
                    cols2[1].caption(f"Height: {height or '—'}")
                    cols2[2].caption(f"Weight: {weight or '—'}")
                    if bdate:
                        st.caption(f"Born: {bdate}")
                else:
                    st.info("Aucune donnée retournée pour ce playerId (API indisponible ou joueur introuvable).")
            else:
                st.info("playerId introuvable pour ce joueur.")

                # Option A: bouton pour mettre à jour CE joueur (best effort)
                if st.button("🔄 Mettre à jour ce joueur via API", key=f"btn_upd_one__{owner}__{joueur}__{nonce}"):
                    with st.spinner("Recherche du playerId et mise à jour Players DB..."):
                        try:
                            guess = nhl_find_playerid_by_name_cached(joueur, season_lbl=season_lbl)
                            if int(guess or 0) > 0:
                                _upsert_player_identity_to_players_db(int(guess))
                                st.success(f"playerId trouvé: {int(guess)}. Réessaie d'ouvrir ce joueur.")
                            else:
                                st.warning("Impossible de trouver ce joueur via les stats NHL (API). Utilise Admin → Mise à jour Players DB.")
                        except Exception as e:
                            st.warning(f"API indisponible: {e}")


        # 1) Type
        reason = st.radio(
            "Type de changement",
            ["Changement demi-mois", "Blessure"],
            horizontal=True,
            key=f"mv_reason_{owner}_{joueur}_{nonce}",
        )

        st.divider()

        # 2) Destination (mapping AVEC TES constantes)
        # RÈGLE: si le joueur provient du CE et que "Blessure" est sélectionné,
        #        le seul choix permis est "🟢 Actif" (rappel pour remplacer).
        if reason == "Blessure" and cur_statut == STATUT_CE:
            destinations = [("🟢 Actif", (STATUT_GC, SLOT_ACTIF))]
        else:
            destinations = [
                ("🟢 Actif", (STATUT_GC, SLOT_ACTIF)),
                ("🟡 Banc", (STATUT_GC, SLOT_BANC)),
                ("🔵 Mineur", (STATUT_CE, "")),
                ("🩹 Blessé (IR)", (cur_statut, SLOT_IR)),
            ]

        current = (cur_statut, cur_slot or "")
        destinations = [d for d in destinations if d[1] != current]

        labels = [d[0] for d in destinations]
        mapping = {d[0]: d[1] for d in destinations}

        choice = st.radio(
            "Destination",
            labels,
            label_visibility="collapsed",
            key=f"dest_{owner}_{joueur}_{nonce}",
        )
        to_statut, to_slot = mapping[choice]

        # 3) Effet exact (DATE + HEURE locale)
        now = datetime.now(TZ_TOR)
        eff_dt = _effective_date(reason, cur_statut, cur_slot, to_statut, to_slot)

        # Sécurité : si à quelques ms près ça doit être immédiat, on le traite immédiat
        immediate = (eff_dt <= (now + timedelta(seconds=1)))

        if immediate:
            hint = "immédiat"
        else:
            hint = eff_dt.strftime("effectif le %Y-%m-%d %H:%M")

        st.markdown(f"<span class='pill'>⏱️ {hint}</span>", unsafe_allow_html=True)
        st.divider()

        # ✅ Sécurité: apply_move_with_history doit exister
        _apply_f = globals().get("apply_move_with_history")
        if not callable(_apply_f):
            def _apply_f(owner_x: str, joueur_x: str, to_statut_x: str, to_slot_x: str, note_x: str = "") -> bool:
                df_x = st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS))
                if df_x is None or df_x.empty:
                    st.session_state["last_move_error"] = "Données manquantes."
                    return False
                m2 = (
                    df_x["Propriétaire"].astype(str).str.strip().eq(str(owner_x).strip())
                    & df_x["Joueur"].astype(str).str.strip().eq(str(joueur_x).strip())
                )
                if not m2.any():
                    st.session_state["last_move_error"] = "Joueur introuvable."
                    return False
                idx2 = df_x.index[m2][0]
                from_statut2 = str(df_x.at[idx2, "Statut"]) if "Statut" in df_x.columns else ""
                from_slot2 = str(df_x.at[idx2, "Slot"]) if "Slot" in df_x.columns else ""
                df_x.at[idx2, "Statut"] = to_statut_x
                df_x.at[idx2, "Slot"] = to_slot_x
                st.session_state["data"] = clean_data(df_x)
                st.session_state["data"] = enrich_level_from_players_db(st.session_state["data"])
                persist_data(st.session_state["data"], str(st.session_state.get("season") or season))
                # log minimal
                try:
                    log_history_row(str(owner_x), str(joueur_x), "", "", from_statut2, from_slot2, str(to_statut_x), str(to_slot_x), str(note_x))
                except Exception:
                    pass
                return True

        def _schedule_move(note: str):
            _init_pending_moves()
            st.session_state["pending_moves"].append({
                "owner": owner,
                "joueur": joueur,
                "to_statut": to_statut,
                "to_slot": to_slot,
                "reason": reason,
                "note": note,
                "effective_at": eff_dt.isoformat(timespec="seconds"),
                "created_at": now.isoformat(timespec="seconds"),
            })

        c1, c2 = st.columns(2)

        if c1.button("✅ Confirmer", type="primary", use_container_width=True, key=f"ok_{owner}_{joueur}_{nonce}"):

            note = f"{reason} — {cur_statut}/{cur_slot or '-'} → {to_statut}/{to_slot or '-'}"

            # IMMÉDIAT
            if immediate:
                ok = _apply_f(owner, joueur, to_statut, to_slot, note)
                if ok:
                    # ✅ Auto-remplacement retiré (comme demandé)

                    st.toast("✅ Déplacement effectué", icon="✅")
                    _close()
                    do_rerun()
                else:
                    st.error(st.session_state.get("last_move_error") or "Déplacement refusé.")

            # PROGRAMMÉ
            else:
                _schedule_move(note)
                st.toast(f"🕒 Déplacement programmé ({hint})", icon="🕒")
                _close()
                do_rerun()

        if c2.button("✖️ Annuler", use_container_width=True, key=f"cancel_{owner}_{joueur}_{nonce}"):
            _close()
            do_rerun()

    _dlg()






# =====================================================
# DIALOG — Preview Alignement Grand Club (GC)
# =====================================================
def open_gc_preview_dialog():
    if not st.session_state.get("gc_preview_open"):
        return

    owner = str(get_selected_team() or "").strip()

    df0 = st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS))
    df0 = clean_data(df0) if isinstance(df0, pd.DataFrame) else pd.DataFrame(columns=REQUIRED_COLS)

    dprop = df0[df0.get("Propriétaire", "").astype(str).str.strip().eq(owner)].copy() if (not df0.empty and owner) else pd.DataFrame()

    # Enlève IR pour le preview GC (tu peux enlever ce filtre si tu veux inclure IR)
    if not dprop.empty and "Slot" in dprop.columns:
        dprop = dprop[dprop.get("Slot", "") != SLOT_IR].copy()

    gc_all = dprop[dprop.get("Statut", "") == STATUT_GC].copy() if not dprop.empty else pd.DataFrame()

    cap_gc = int(st.session_state.get("PLAFOND_GC", 95_500_000) or 0)
    used_gc = int(gc_all["Salaire"].sum()) if (not gc_all.empty and "Salaire" in gc_all.columns) else 0
    remain_gc = cap_gc - used_gc

    @st.dialog(f"👀 Alignement GC — {owner or 'Équipe'}", width="large")
    def _dlg():
        st.caption("Prévisualisation rapide du Grand Club (GC).")

        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Total GC", money(used_gc))
        with c2:
            st.metric("Plafond GC", money(cap_gc))
        with c3:
            if used_gc > cap_gc:
                st.error(f"Non conforme — dépassement: {money(used_gc - cap_gc)}")
            else:
                st.success(f"Conforme — reste: {money(remain_gc)}")

        if gc_all.empty:
            st.info("Aucun joueur GC pour cette équipe.")
        else:
            # ✅ Pos complètement à gauche
            show_cols = [c for c in ["Pos", "Joueur", "Equipe", "Slot", "Salaire"] if c in gc_all.columns]
            df_show = gc_all[show_cols].copy()

            if "Salaire" in df_show.columns:
                df_show["Salaire"] = df_show["Salaire"].apply(lambda x: money(int(x) if str(x).strip() else 0))

            st.dataframe(df_show, use_container_width=True, hide_index=True)

        if st.button("OK", use_container_width=True, key="gc_preview_ok"):
            st.session_state["gc_preview_open"] = False
            do_rerun()

    _dlg()



# =====================================================
# PLAFONDS builder + Tableau UI
# =====================================================
def rebuild_plafonds(df: pd.DataFrame) -> pd.DataFrame:
    cap_gc = int(st.session_state.get("PLAFOND_GC", 95_500_000) or 0)
    cap_ce = int(st.session_state.get("PLAFOND_CE", 47_750_000) or 0)

    teams_all = sorted(list(LOGOS.keys()))
    resume = []
    for team in teams_all:
        d = df[df["Propriétaire"].astype(str).str.strip().eq(team)].copy()
        if d.empty:
            total_gc = 0
            total_ce = 0
        else:
            total_gc = d[(d["Statut"] == STATUT_GC) & (d["Slot"] != SLOT_IR)]["Salaire"].sum()
            total_ce = d[(d["Statut"] == STATUT_CE) & (d["Slot"] != SLOT_IR)]["Salaire"].sum()

            # + pénalités de rachat (50%) (peuvent être appliquées GC ou CE)
            total_gc = int(total_gc) + int(buyout_penalty_sum(team, "GC"))
            total_ce = int(total_ce) + int(buyout_penalty_sum(team, "CE"))

        resume.append(
            {
                "Propriétaire": team,
                "Logo": team_logo_path(team),
                "Total Grand Club": int(total_gc),
                "Montant Disponible GC": int(cap_gc - int(total_gc)),
                "Total Club École": int(total_ce),
                "Montant Disponible CE": int(cap_ce - int(total_ce)),
            }
        )
    return pd.DataFrame(resume)

def build_tableau_ui(plafonds: pd.DataFrame):
    """
    Tableau des masses salariales (cliquable):
      - clic sur le nom d'équipe => sélectionne l'équipe (comme l'ancien selectbox sidebar)
      - aucun dédoublement: on affiche une seule fois les valeurs
    """
    selected = str(get_selected_team() or "").strip()

    if plafonds is None or not isinstance(plafonds, pd.DataFrame) or plafonds.empty:
        st.info("Aucune équipe configurée.")
        return

    view = plafonds.copy()

    # Colonnes attendues (fallback)
    for c in ["Propriétaire", "Total Grand Club", "Montant Disponible GC", "Total Club École", "Montant Disponible CE"]:
        if c not in view.columns:
            view[c] = 0 if ("Total" in c or "Montant" in c) else ""

    # Format money
    def _fmt_money(x):
        try:
            return money(int(float(x)))
        except Exception:
            return money(0)

    view["_TotalGC"] = view["Total Grand Club"].apply(_fmt_money)
    view["_ResteGC"] = view["Montant Disponible GC"].apply(_fmt_money)
    view["_TotalCE"] = view["Total Club École"].apply(_fmt_money)
    view["_ResteCE"] = view["Montant Disponible CE"].apply(_fmt_money)

    st.markdown("#### Cliquez sur une équipe pour la sélectionner")
    h = st.columns([2.6, 1.5, 1.5, 1.5, 1.5], vertical_alignment="center")
    h[0].markdown("**Équipe**")
    h[1].markdown("**Total GC**")
    h[2].markdown("**Reste GC**")
    h[3].markdown("**Total CE**")
    h[4].markdown("**Reste CE**")

    for _, r in view.iterrows():
        owner = str(r.get("Propriétaire", "")).strip()
        is_sel = bool(owner) and owner == selected

        c = st.columns([2.6, 1.5, 1.5, 1.5, 1.5], vertical_alignment="center")

        label = f"✅ {owner}" if is_sel else owner
        if c[0].button(label, key=f"tbl_pick_{owner}", use_container_width=True):
            pick_team(owner)

        c[1].markdown(r["_TotalGC"])
        c[2].markdown(r["_ResteGC"])
        c[3].markdown(r["_TotalCE"])
        c[4].markdown(r["_ResteCE"])



# =====================================================
# 🏆 CLASSEMENT — Points via NHL APIs (combo nhle.com + statsapi)
#   - Règles de pointage éditables (CSV local + miroir Drive)
#   - API calls cachés (TTL) pour navigation rapide
# =====================================================

SCORING_RULES_FILE = os.path.join(DATA_DIR, "scoring_rules.csv")

def _default_scoring_rules_df() -> "pd.DataFrame":
    # Règles demandées:
    # F: G=1, A=1 | D: G=1, A=1 | G: W=2, OTL=1
    return pd.DataFrame([
        {"position_group": "Skater", "positions": "F,D", "stat_key": "goals",     "api_fields": "goals",          "points": 1, "description": "But (avants et défenseurs)"},
        {"position_group": "Skater", "positions": "F,D", "stat_key": "assists",   "api_fields": "assists",        "points": 1, "description": "Passe (avants et défenseurs)"},
        {"position_group": "Goalie", "positions": "G",   "stat_key": "wins",      "api_fields": "wins",           "points": 2, "description": "Victoire gardien"},
        {"position_group": "Goalie", "positions": "G",   "stat_key": "otLosses",  "api_fields": "otLosses,ot",    "points": 1, "description": "Défaite en prolongation (OTL)"},
    ])

@st.cache_data(show_spinner=False)
def _load_scoring_rules_cached(path: str, mtime: float) -> "pd.DataFrame":
    try:
        df = pd.read_csv(path)
        return df
    except Exception:
        return _default_scoring_rules_df()

def load_scoring_rules() -> "pd.DataFrame":
    # Local first
    try:
        if os.path.exists(SCORING_RULES_FILE):
            mtime = os.path.getmtime(SCORING_RULES_FILE)
            df = _load_scoring_rules_cached(SCORING_RULES_FILE, mtime)
        else:
            df = _default_scoring_rules_df()
        # sanitize
        for c in ["position_group","positions","stat_key","api_fields","description"]:
            if c not in df.columns:
                df[c] = ""
        if "points" not in df.columns:
            df["points"] = 0
        df["points"] = pd.to_numeric(df["points"], errors="coerce").fillna(0)
        return df
    except Exception:
        return _default_scoring_rules_df()

def save_scoring_rules(df: "pd.DataFrame") -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = SCORING_RULES_FILE + ".tmp"
        df.to_csv(tmp, index=False)
        os.replace(tmp, SCORING_RULES_FILE)
    except Exception:
        pass
    # mirror to Drive if configured
    try:
        cfg = st.secrets.get("gdrive_oauth", {}) or {}
        folder_id = str(cfg.get("folder_id", "")).strip()
        if folder_id:
            s = _drive()
            _drive_upsert_csv_bytes(
                s,
                folder_id,
                os.path.basename(SCORING_RULES_FILE),
                df.to_csv(index=False).encode("utf-8"),
            )
    except Exception:
        pass


def season_lbl_to_nhl(season_lbl: str) -> str:
    s = str(season_lbl or "").strip()
    # already like 20252026
    if len(s) == 8 and s.isdigit():
        return s
    # like 2025-2026
    if "-" in s:
        a, b = s.split("-", 1)
        a = "".join([ch for ch in a if ch.isdigit()])
        b = "".join([ch for ch in b if ch.isdigit()])
        if len(a) == 4 and len(b) == 4:
            return a + b
    # fallback: try keep digits
    d = "".join([ch for ch in s if ch.isdigit()])
    if len(d) >= 8:
        return d[:8]
    return d

@st.cache_data(show_spinner=False, ttl=3600)
def _statsapi_single_season_cached(player_id: int, season_code: str) -> dict:
    # NHL statsapi (stable fallback)
    try:
        url = f"https://statsapi.web.nhl.com/api/v1/people/{int(player_id)}/stats"
        params = {"stats": "statsSingleSeason", "season": season_code}
        r = requests.get(url, params=params, timeout=12)
        r.raise_for_status()
        j = r.json()
        splits = (((j.get("stats") or [{}])[0]).get("splits") or [])
        if splits and isinstance(splits, list) and isinstance(splits[0], dict):
            return splits[0].get("stat") or {}
    except Exception:
        return {}
    return {}

@st.cache_data(show_spinner=False, ttl=3600)
def _nhle_landing_cached(player_id: int) -> dict:
    # api-web.nhle.com landing (souvent plus riche)
    try:
        url = f"https://api-web.nhle.com/v1/player/{int(player_id)}/landing"
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        return r.json() if isinstance(r.json(), dict) else {}
    except Exception:
        return {}

def _extract_from_nhle_landing(j: dict) -> dict:
    out = {}
    if not isinstance(j, dict) or not j:
        return out
    # Try common nested paths for regular season totals
    # Different payloads exist; we try several.
    candidates = []
    fs = j.get("featuredStats")
    if isinstance(fs, dict):
        rs = fs.get("regularSeason")
        if isinstance(rs, dict):
            candidates.append(rs.get("subSeason"))
            candidates.append(rs.get("career"))
            candidates.append(rs.get("season"))
            candidates.append(rs)
    candidates.append(j.get("seasonTotals"))
    candidates.append(j.get("careerTotals"))
    candidates.append(j.get("playerStats"))
    # Find a dict that has goals/assists or wins/otLosses
    stat_dict = None
    for c in candidates:
        if isinstance(c, dict) and any(k in c for k in ["goals","assists","wins","otLosses","ot","overtimeLosses"]):
            stat_dict = c
            break
        if isinstance(c, list) and c:
            # take first with those keys
            for it in c:
                if isinstance(it, dict) and any(k in it for k in ["goals","assists","wins","otLosses","ot","overtimeLosses"]):
                    stat_dict = it
                    break
            if stat_dict:
                break
    if isinstance(stat_dict, dict):
        # normalize keys we care about
        for k in ["goals","assists","wins","otLosses","ot","overtimeLosses"]:
            if k in stat_dict:
                out[k] = stat_dict.get(k)
    return out

def nhl_player_stats_combo(player_id_raw: str, season_lbl: str) -> dict:
    """
    Combine 2 sources:
      1) api-web.nhle.com (landing) — primary
      2) statsapi.web.nhl.com (statsSingleSeason) — fallback / fill
    Returns normalized keys: goals, assists, wins, otLosses
    """
    try:
        pid = int(float(str(player_id_raw).strip()))
    except Exception:
        pid = 0
    season_code = season_lbl_to_nhl(season_lbl)

    out = {"goals": 0, "assists": 0, "wins": 0, "otLosses": 0}
    if pid <= 0:
        return out

    # 1) nhle landing (no season param — best effort)
    j1 = _nhle_landing_cached(pid)
    d1 = _extract_from_nhle_landing(j1)
    # 2) statsapi single season (has season)
    d2 = _statsapi_single_season_cached(pid, season_code)

    def _get_num(d, keys):
        for k in keys:
            if k in d:
                try:
                    v = float(d.get(k) or 0)
                    if v != v:
                        v = 0
                    return v
                except Exception:
                    return 0
        return 0

    out["goals"] = _get_num(d1, ["goals"]) or _get_num(d2, ["goals"])
    out["assists"] = _get_num(d1, ["assists"]) or _get_num(d2, ["assists"])
    out["wins"] = _get_num(d1, ["wins"]) or _get_num(d2, ["wins"])
    out["otLosses"] = _get_num(d1, ["otLosses","ot","overtimeLosses"]) or _get_num(d2, ["ot","otLosses","overtimeLosses"])
    # Ensure ints for display
    for k in out:
        try:
            out[k] = int(round(float(out[k] or 0)))
        except Exception:
            out[k] = 0
    return out

@st.cache_data(show_spinner=False, ttl=6*3600)
def nhle_player_game_log_cached(player_id: int, season_lbl: str) -> list:
    """Game log régulier via api-web.nhle.com.

    Retourne une liste de dicts (un par match) avec au minimum:
      - gameDate (YYYY-MM-DD)
      - goals, assists (patineurs)
      - decision (G) : 'W', 'L', 'OTL', 'SOL', etc.

    Note: les payloads peuvent varier; on garde le parsing tolérant.
    """
    try:
        pid = int(player_id)
    except Exception:
        return []
    if pid <= 0:
        return []

    season_code = season_lbl_to_nhl(season_lbl)
    try:
        # /2 = regular season
        url = f"https://api-web.nhle.com/v1/player/{pid}/game-log/{season_code}/2"
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        j = r.json()
        if not isinstance(j, dict):
            return []
        gl = j.get('gameLog') or j.get('games') or j.get('gameLogs')
        if isinstance(gl, list):
            out = []
            for it in gl:
                if not isinstance(it, dict):
                    continue
                out.append(it)
            return out
    except Exception:
        return []
    return []


def fantasy_points_timeseries(player_id_raw: str, position_raw: str, season_lbl: str, rules_df: "pd.DataFrame") -> "pd.DataFrame":
    """Points par match (date) pour un joueur, calculés via game log.

    Retourne DataFrame avec colonnes: date, points.
    """
    try:
        pid = int(float(str(player_id_raw).strip()))
    except Exception:
        pid = 0
    if pid <= 0:
        import pandas as _pd
        return _pd.DataFrame(columns=['date','points'])

    gl = nhle_player_game_log_cached(pid, season_lbl)
    rows = []

    pos = str(position_raw or '').upper().strip()
    is_goalie = (pos == 'G') or ('GOAL' in pos) or ('GK' in pos)

    # build rule maps
    if not isinstance(rules_df, pd.DataFrame) or rules_df.empty:
        rules_df = _default_scoring_rules_df()

    # for skaters: goals/assists
    pts_goal = 0.0
    pts_ast = 0.0
    pts_win = 0.0
    pts_otl = 0.0
    for _, r in rules_df.iterrows():
        if str(r.get('position_group','')).strip() == 'Skater':
            if str(r.get('stat_key','')).strip() == 'goals':
                pts_goal = float(r.get('points',0) or 0)
            if str(r.get('stat_key','')).strip() == 'assists':
                pts_ast = float(r.get('points',0) or 0)
        if str(r.get('position_group','')).strip() == 'Goalie':
            if str(r.get('stat_key','')).strip() == 'wins':
                pts_win = float(r.get('points',0) or 0)
            if str(r.get('stat_key','')).strip() in ('otLosses','ot','overtimeLosses'):
                pts_otl = float(r.get('points',0) or 0)

    import pandas as _pd

    for it in gl:
        if not isinstance(it, dict):
            continue
        d = str(it.get('gameDate') or it.get('date') or '').strip()
        if not d:
            continue
        # normalize date
        dt = _pd.to_datetime(d, errors='coerce')
        if _pd.isna(dt):
            continue
        dt = dt.date()

        if not is_goalie:
            g = it.get('goals', 0) or 0
            a = it.get('assists', 0) or 0
            try:
                g = float(g)
            except Exception:
                g = 0
            try:
                a = float(a)
            except Exception:
                a = 0
            pts = g*pts_goal + a*pts_ast
        else:
            # goalie decision: W, L, OTL, SOL
            dec = str(it.get('decision') or it.get('goalieDecision') or '').upper().strip()
            w = 1 if dec == 'W' else 0
            otl = 1 if dec in ('OTL','SOL','OT','SO') else 0
            # some payloads use 'overtimeLosses' or 'otLosses'
            if not otl:
                try:
                    otl = int(float(it.get('otLosses') or it.get('overtimeLosses') or it.get('ot') or 0))
                    otl = 1 if otl > 0 else 0
                except Exception:
                    otl = 0
            pts = w*pts_win + otl*pts_otl

        rows.append({'date': dt, 'points': float(pts or 0)})

    df = _pd.DataFrame(rows)
    if df.empty:
        return _pd.DataFrame(columns=['date','points'])
    df = df.groupby('date', as_index=False)['points'].sum().sort_values(by='date')
    return df

def compute_points_from_rules(position_raw: str, stats: dict, rules_df: "pd.DataFrame") -> float:
    pos = str(position_raw or "").upper().strip()
    is_goalie = ("G" == pos) or ("GOAL" in pos) or ("GK" == pos)
    group = "Goalie" if is_goalie else "Skater"
    total = 0.0
    if not isinstance(rules_df, pd.DataFrame) or rules_df.empty:
        rules_df = _default_scoring_rules_df()

    for _, r in rules_df.iterrows():
        if str(r.get("position_group","")).strip() != group:
            continue
        stat_key = str(r.get("stat_key","")).strip()
        pts = float(r.get("points",0) or 0)
        try:
            v = float(stats.get(stat_key, 0) or 0)
        except Exception:
            v = 0.0
        total += v * pts
    return float(total)

def render_tab_classement():
    st.subheader("🏆 Classement")
    st.caption("Points calculés via NHL APIs (api-web.nhle.com + statsapi.web.nhl.com), selon tes règles de pointage.")

    df = st.session_state.get("data", pd.DataFrame())
    if not isinstance(df, pd.DataFrame) or df.empty:
        st.info("Aucune donnée chargée. Va dans 🛠️ Gestion Admin → Import Fantrax.")
        return

    season_lbl = str(st.session_state.get("season") or "").strip() or saison_auto()
    rules = load_scoring_rules()

    # Detect columns
    col_player = "Joueur" if "Joueur" in df.columns else None
    col_owner = "Propriétaire" if "Propriétaire" in df.columns else None
    col_pos = None
    for c in ["Position","Pos","POS","position","Slot"]:
        if c in df.columns:
            col_pos = c
            break
    col_status = None
    for c in ["Statut","Status","Slot"]:
        if c in df.columns:
            col_status = c
            break

    col_pid = None
    for c in ["playerId","PlayerId","player_id","id_player"]:
        if c in df.columns:
            col_pid = c
            break

    if not (col_player and col_owner):
        st.warning("Colonnes manquantes: il faut 'Joueur' et 'Propriétaire' pour faire le classement.")
        return
    if not col_pid:
        st.warning("Il manque la colonne playerId dans ton roster. (On peut la mapper depuis Players DB si besoin.)")
        return

    d = df.copy()
    d[col_player] = d[col_player].astype(str).str.strip()
    d[col_owner] = d[col_owner].astype(str).str.strip()
    d[col_pid] = d[col_pid].astype(str).str.strip()

    # Filter actifs (best effort)
    actifs = d
    if col_status:
        s = d[col_status].astype(str).str.lower()
        filt = s.str.contains("actif|active|lineup|starter", regex=True, na=False)
        if filt.any():
            actifs = d[filt].copy()

    # Unique players per owner
    actifs = actifs[actifs[col_player].astype(str).str.len() > 0].copy()
    actifs = actifs.drop_duplicates(subset=[col_owner, col_player], keep="last").copy()

    # Cache key
    dv = str(st.session_state.get("data_version","0"))
    cache_key = f"{season_lbl}__{dv}"
    if "classement_cache" not in st.session_state:
        st.session_state["classement_cache"] = {}
    force_refresh = bool(st.session_state.pop('classement_force_refresh', False))


    if (cache_key in st.session_state["classement_cache"]) and (not force_refresh):
        cached = st.session_state["classement_cache"][cache_key]
        st.success("✅ Résultats en cache (rapide). Clique Recalculer si tu veux rafraîchir.")
        team_rank = cached.get("team_rank", pd.DataFrame())
        top_players = cached.get("top_players", pd.DataFrame())
        missing_pid = cached.get("missing_pid", [])
    else:
        with st.spinner("Calcul des points via API…"):
            rows = []
            missing_pid = []
            prog = st.progress(0)
            n = len(actifs)
            for i, r in enumerate(actifs.to_dict(orient="records")):
                name = str(r.get(col_player,"")).strip()
                owner = str(r.get(col_owner,"")).strip()
                pid = str(r.get(col_pid,"")).strip()
                pos_raw = str(r.get(col_pos,"") if col_pos else "").strip()
                if not pid or pid.lower() in {"nan","none","null","0","0.0","-"}:
                    missing_pid.append(name)
                    stats = {"goals":0,"assists":0,"wins":0,"otLosses":0}
                else:
                    stats = nhl_player_stats_combo(pid, season_lbl)
                pts = compute_points_from_rules(pos_raw, stats, rules)
                rows.append({
                    "Équipe": owner,
                    "Joueur": name,
                    "Position": pos_raw,
                    "playerId": pid,
                    "G": stats.get("goals",0),
                    "A": stats.get("assists",0),
                    "W": stats.get("wins",0),
                    "OTL": stats.get("otLosses",0),
                    "Points": pts,
                })
                try:
                    prog.progress(min(1.0, (i+1)/max(1,n)))
                except Exception:
                    pass
            try:
                prog.empty()
            except Exception:
                pass

            out = pd.DataFrame(rows)
            if out.empty:
                st.info("Aucun joueur actif à calculer.")
                return

            team_rank = (
                out.groupby("Équipe", as_index=False)["Points"]
                .sum()
                .sort_values(by="Points", ascending=False, kind="mergesort")
                .reset_index(drop=True)
            )
            team_rank.insert(0, "Rang", range(1, len(team_rank)+1))

            top_players = out.sort_values(by="Points", ascending=False, kind="mergesort").head(50).reset_index(drop=True)
            top_players.insert(0, "Rang", range(1, len(top_players)+1))

            st.session_state["classement_cache"][cache_key] = {
                "team_rank": team_rank,
                "top_players": top_players,
                "missing_pid": missing_pid[:200],
            }

    st.markdown("### 🏅 Classement des équipes (joueurs actifs)")
    st.dataframe(team_rank, use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("### 📅 Vue par jour / semaine / mois")
    st.caption("Les points proviennent du **game log** NHL (api-web.nhle.com). Les joueurs comptent selon ton roster **Actif** actuel.")

    gran = st.radio("Granularité", ["Jour", "Semaine", "Mois"], horizontal=True, key="classement_gran")
    vue = st.radio("Vue", ["Équipes", "Joueurs"], horizontal=True, key="classement_vue")

    # Fenêtre: par défaut 30 jours
    from datetime import date as _date
    cR1, cR2 = st.columns(2)
    with cR1:
        d1 = st.date_input("Du", value=_date.today() - timedelta(days=30), key="classement_d1")
    with cR2:
        d2 = st.date_input("Au", value=_date.today(), key="classement_d2")

    rules = load_scoring_rules()
    season_lbl = season_pick

    # Active roster uniquement
    df_all = st.session_state.get('data', pd.DataFrame())
    df_all = clean_data(df_all) if isinstance(df_all, pd.DataFrame) else pd.DataFrame()
    if df_all.empty or 'Joueur' not in df_all.columns:
        st.info('Aucun roster chargé.')
    else:
        act = df_all[df_all.get('Slot','').astype(str).str.strip().eq('Actif')].copy()
        if act.empty:
            st.info('Aucun joueur Actif dans le roster.')
        else:
            # map player -> id (players_db)
            pdb = st.session_state.get('players_db')
            if not isinstance(pdb, pd.DataFrame) or pdb.empty or 'Player' not in pdb.columns:
                pdb_path = os.path.join(DATA_DIR, 'hockey.players.csv')
                try:
                    mtime = os.path.getmtime(pdb_path) if os.path.exists(pdb_path) else 0.0
                except Exception:
                    mtime = 0.0
                pdb = load_players_db(pdb_path, mtime) if mtime else pd.DataFrame()

            pid_map = {}
            if isinstance(pdb, pd.DataFrame) and (not pdb.empty) and ('playerId' in pdb.columns) and ('Player' in pdb.columns):
                tmp = pdb.copy()
                tmp['_k'] = tmp['Player'].astype(str).apply(_norm_name)
                pid_map = dict(zip(tmp['_k'], tmp['playerId'].astype(str)))

            act['_k'] = act['Joueur'].astype(str).apply(_norm_name)
            act['playerId'] = act['_k'].map(pid_map).fillna('')

            # build per-game points rows
            rows = []
            for _, r in act.iterrows():
                pid = str(r.get('playerId','') or '').strip()
                if not pid:
                    continue
                pos = str(r.get('Pos','') or '').strip()
                try:
                    ts = fantasy_points_timeseries(pid, pos, season_lbl, rules)
                except Exception:
                    continue
                if ts is None or ts.empty:
                    continue
                ts2 = ts.copy()
                ts2['owner'] = str(r.get('Propriétaire','') or '').strip()
                ts2['player'] = str(r.get('Joueur','') or '').strip()
                rows.append(ts2)

            if not rows:
                st.info('Aucune donnée API disponible pour la période.')
            else:
                import pandas as _pd
                allp = _pd.concat(rows, ignore_index=True)
                allp['date'] = _pd.to_datetime(allp['date'], errors='coerce')
                allp = allp.dropna(subset=['date'])
                allp = allp[(allp['date'].dt.date >= d1) & (allp['date'].dt.date <= d2)].copy()

                if allp.empty:
                    st.info('Aucune partie dans cette fenêtre.')
                else:
                    if gran == 'Jour':
                        allp['bucket'] = allp['date'].dt.date.astype(str)
                    elif gran == 'Semaine':
                        iso = allp['date'].dt.isocalendar()
                        allp['bucket'] = (iso['year'].astype(str) + '-W' + iso['week'].astype(str).str.zfill(2))
                    else:
                        allp['bucket'] = allp['date'].dt.to_period('M').astype(str)

                    if vue == 'Équipes':
                        out = allp.groupby(['bucket','owner'], as_index=False)['points'].sum()
                        out = out.rename(columns={'bucket':'Période','owner':'Équipe','points':'Points'})
                        out = out.sort_values(by=['Période','Points'], ascending=[False, False])
                    else:
                        out = allp.groupby(['bucket','player','owner'], as_index=False)['points'].sum()
                        out = out.rename(columns={'bucket':'Période','player':'Joueur','owner':'Équipe','points':'Points'})
                        out = out.sort_values(by=['Période','Points'], ascending=[False, False])

                    st.dataframe(out.head(500), use_container_width=True, hide_index=True)


    st.markdown("### ⭐ Top joueurs actifs")
    st.dataframe(top_players, use_container_width=True, hide_index=True)

    if missing_pid:
        with st.expander(f"⚠️ playerId manquant ({len(missing_pid)})", expanded=False):
            st.write(missing_pid)



# =====================================================
# BOOTSTRAP GLOBAL (ordre propre)
#   0) players_db
#   1) data (load → clean → enrich Level)
#   2) history
#   3) pending moves
#   4) plafonds
# =====================================================

# --- Saison (fallback sécurisé)
season = str(st.session_state.get("season") or "").strip()
if not season:
    season = saison_auto()
    st.session_state["season"] = season

# --- Paths
DATA_FILE = os.path.join(DATA_DIR, f"equipes_joueurs_{season}.csv")
HISTORY_FILE = os.path.join(DATA_DIR, f"history_{season}.csv")
st.session_state["DATA_FILE"] = DATA_FILE
st.session_state["HISTORY_FILE"] = HISTORY_FILE

# -----------------------------------------------------
# 0) PLAYERS DATABASE (AVANT enrich)
# -----------------------------------------------------
pdb_path = _first_existing(PLAYERS_DB_FALLBACKS) if "PLAYERS_DB_FALLBACKS" in globals() else ""
pdb_mtime = 0.0
if pdb_path and os.path.exists(pdb_path):
    try:
        pdb_mtime = float(os.path.getmtime(pdb_path))
    except Exception:
        pdb_mtime = 0.0

players_db = load_players_db(pdb_path, pdb_mtime) if pdb_path else pd.DataFrame()
st.session_state["players_db"] = players_db

# -----------------------------------------------------
# 1) LOAD DATA (CSV → session_state) puis enrich Level
# -----------------------------------------------------
if "data_season" not in st.session_state or st.session_state["data_season"] != season:
    # Streamlit Cloud can reset local disk: restore roster file from Drive if missing.
    _ensure_local_csv_from_drive(DATA_FILE)
    if os.path.exists(DATA_FILE):
        try:
            df_loaded = pd.read_csv(DATA_FILE)
        except Exception:
            df_loaded = pd.DataFrame(columns=REQUIRED_COLS)
    else:
        df_loaded = pd.DataFrame(columns=REQUIRED_COLS)
        try:
            df_loaded.to_csv(DATA_FILE, index=False)
        except Exception:
            pass

    df_loaded = clean_data(df_loaded)
    df_loaded = enrich_level_from_players_db(df_loaded)  # ✅ players_db est déjà prêt
    st.session_state["data"] = df_loaded
    st.session_state["data_season"] = season
else:
    # perf: avoid re-clean/re-enrich on every widget change
    d0 = st.session_state.get('data')
    d0 = d0 if isinstance(d0, pd.DataFrame) else pd.DataFrame(columns=REQUIRED_COLS)

    # re-enrich only if players_db changed since last enrich
    last_pdb_mtime = float(st.session_state.get('_last_pdb_mtime', 0.0) or 0.0)
    cur_pdb_mtime = float(pdb_mtime or 0.0)
    if cur_pdb_mtime != last_pdb_mtime:
        try:
            d0 = clean_data(d0)
            d0 = enrich_level_from_players_db(d0)
        except Exception:
            pass
        st.session_state['_last_pdb_mtime'] = cur_pdb_mtime

    st.session_state['data'] = d0

# -----------------------------------------------------
# 2) LOAD HISTORY (CSV → session_state)
# -----------------------------------------------------
if "history_season" not in st.session_state or st.session_state["history_season"] != season:
    _ensure_local_csv_from_drive(HISTORY_FILE)
    st.session_state["history"] = load_history_file(HISTORY_FILE)
    st.session_state["history_season"] = season
else:
    h0 = st.session_state.get("history")
    st.session_state["history"] = h0 if isinstance(h0, pd.DataFrame) else _history_empty_df()

# -----------------------------------------------------
# 3) PROCESS PENDING MOVES (APRÈS data + history)
# -----------------------------------------------------
if "process_pending_moves" in globals() and callable(globals()["process_pending_moves"]):
    try:
        process_pending_moves()
    except Exception as e:
        st.warning(f"⚠️ process_pending_moves() a échoué: {type(e).__name__}: {e}")

# -----------------------------------------------------
# 4) BUILD PLAFONDS (fast)
#   ✅ Only rebuild when roster/caps changed (data_version)
# -----------------------------------------------------

# init version if missing
if 'data_version' not in st.session_state:
    st.session_state['data_version'] = 1

ensure_plafonds_uptodate(force=False)


# Init onglet actif (safe)
if "active_tab" not in st.session_state:
    st.session_state["active_tab"] = "🏠 Home"

# =====================================================
# SIDEBAR — Saison + Équipe + Plafonds + Mobile
# =====================================================
st.sidebar.checkbox("📱 Mode mobile", key="mobile_view")
_set_mobile_class(bool(st.session_state.get("mobile_view", False)))
st.sidebar.divider()

st.sidebar.header("📅 Saison")
saisons = ["2024-2025", "2025-2026", "2026-2027"]
auto = saison_auto()
if auto not in saisons:
    saisons.append(auto)
    saisons.sort()

season_pick = st.sidebar.selectbox("Saison", saisons, index=saisons.index(auto), key="sb_season_select")
st.session_state["season"] = season_pick
st.session_state["LOCKED"] = saison_verrouillee(season_pick)


def _tx_pending_from_state() -> bool:
    """Detecte une transaction en cours (sélections joueurs/picks/cash) via session_state."""
    ss = st.session_state
    for k, v in ss.items():
        if k.startswith(("tx_players_", "tx_picks_")):
            if isinstance(v, (list, tuple, set)) and len(v) > 0:
                return True
        if k.startswith(("tx_cash_", "tx_ret_")):
            try:
                if int(v or 0) > 0:
                    return True
            except Exception:
                pass
    return False

def _nav_label(tab_id: str) -> str:
    # Badge transaction en attente (affichage seulement; tab_id reste stable)
    if tab_id == "⚖️ Transactions" and _tx_pending_from_state():
        return "🔴 " + tab_id
    # Emoji ICE à côté de GM (affichage seulement; tab_id reste stable)
    if tab_id == "🧊 GM":
        return "🧊 GM"
    return tab_id


st.sidebar.markdown("### Navigation")

# -----------------------------------------------------
# SIDEBAR NAV (radio) — sans logo, GM = 🧊
#   ✅ Définit NAV_TABS + `active_tab` (source de vérité)
# -----------------------------------------------------

is_admin = _is_admin_whalers()

NAV_TABS = [
    "🏠 Home",
    "🏆 Classement",
    "🧾 Alignement",
    "👤 Profil Joueurs NHL",
    "🧊 GM",
    "👤 Joueurs autonomes",
    "🕘 Historique",
    "⚖️ Transactions",
]
if is_admin:
    NAV_TABS.append("🛠️ Gestion Admin")
NAV_TABS.append("🧠 Recommandations")

# init + fallback (safe)
if "active_tab" not in st.session_state:
    st.session_state["active_tab"] = NAV_TABS[0]
if st.session_state["active_tab"] not in NAV_TABS:
    st.session_state["active_tab"] = NAV_TABS[0]

# Widget (labels = tabs, pas de mapping fragile)
_cur = st.session_state.get("active_tab", NAV_TABS[0])
_cur_idx = NAV_TABS.index(_cur) if _cur in NAV_TABS else 0

_picked_tab = st.sidebar.radio(
    "Navigation",
    NAV_TABS,
    index=_cur_idx,
    key="sb_nav_radio",
)

if _picked_tab != st.session_state.get("active_tab"):
    st.session_state["active_tab"] = _picked_tab

# ✅ Variable utilisée par le routing plus bas
active_tab = st.session_state.get("active_tab", NAV_TABS[0])

st.sidebar.divider()
st.sidebar.markdown("### 🏒 Équipes")

teams = sorted(list(LOGOS.keys())) if "LOGOS" in globals() else []
if not teams:
    teams = ["Whalers"]

cur_team = get_selected_team().strip() or teams[0]
if cur_team not in teams:
    cur_team = teams[0]

chosen_team = st.sidebar.selectbox(
    "Choisir une équipe",
    teams,
    index=teams.index(cur_team),
    key="sb_team_select",
)

if chosen_team and chosen_team != cur_team:
    pick_team(chosen_team)

logo_path = team_logo_path(get_selected_team())
if logo_path:
    st.sidebar.image(logo_path, use_container_width=True)


if st.sidebar.button("👀 Prévisualiser l’alignement GC", use_container_width=True, key="sb_preview_gc"):
    st.session_state["gc_preview_open"] = True
    st.session_state["active_tab"] = "🧾 Alignement"
    do_rerun()

st.sidebar.divider()
st.sidebar.header("💰 Plafonds")
st.sidebar.metric("🏒 Plafond Grand Club", money(st.session_state.get("PLAFOND_GC", 95_500_000)))
st.sidebar.metric("🏫 Plafond Club École", money(st.session_state.get("PLAFOND_CE", 47_750_000)))

st.divider()


# =====================================================
# MOVE CONTEXT (safe)
#   - set_move_ctx() : ouvre le dialog
#   - clear_move_ctx(): ferme le dialog
# =====================================================
def set_move_ctx(owner: str, joueur: str, source_key: str):
    owner = str(owner or "").strip()
    joueur = str(joueur or "").strip()
    source_key = str(source_key or "").strip()

    # 🔒 reset toast flag à l'ouverture d'un nouveau move
    st.session_state["just_moved"] = False

    st.session_state["move_nonce"] = int(st.session_state.get("move_nonce", 0)) + 1
    st.session_state["move_source"] = source_key
    st.session_state["move_ctx"] = {
        "owner": owner,
        "joueur": joueur,
        "nonce": st.session_state["move_nonce"],
    }

def clear_move_ctx():
    st.session_state["move_ctx"] = None
    st.session_state["move_source"] = ""



# =====================================================
# Global scheduled moves + dialogs (APPELS SAFE)
#   ✅ 1 seule fois
#   ✅ seulement si data/history existent
#   ✅ jamais de NameError
# =====================================================
_has_data = isinstance(st.session_state.get("data"), pd.DataFrame)
_has_hist = isinstance(st.session_state.get("history"), pd.DataFrame)

if _has_data and _has_hist:

    # 1) Appliquer les déplacements programmés
    if "process_pending_moves" in globals() and callable(globals()["process_pending_moves"]):
        try:
            process_pending_moves()
        except Exception as e:
            st.warning(f"⚠️ process_pending_moves() a échoué: {type(e).__name__}: {e}")

    # 2) Dialog preview GC (si présent)
    if "open_gc_preview_dialog" in globals() and callable(globals()["open_gc_preview_dialog"]):
        try:
            open_gc_preview_dialog()
        except Exception as e:
            st.warning(f"⚠️ open_gc_preview_dialog() a échoué: {type(e).__name__}: {e}")

    # 3) Dialog MOVE (si présent)  ✅ IMPORTANT
    if "open_move_dialog" in globals() and callable(globals()["open_move_dialog"]):
        try:
            open_move_dialog()
        except Exception as e:
            st.warning(f"⚠️ open_move_dialog() a échoué: {type(e).__name__}: {e}")




# =====================================================
# UI — roster click list (compact list)
#   ⚠️ DOIT être défini AVANT Alignement (car appelé dans _render_gc_block)
# =====================================================

# =====================================================
# Contract helpers (pills / bars) — used in Alignement lists
# =====================================================

def _season_end_year() -> int:
    """Best-effort end year for current season. Defaults to current year."""
    s = str(st.session_state.get("season") or st.session_state.get("season_lbl") or "").strip()
    # accepts '2025-2026' or '20252026'
    m = re.search(r"(20\d{2})\s*[-/]\s*(20\d{2})", s)
    if m:
        return int(m.group(2))
    m2 = re.search(r"(20\d{2})(20\d{2})", s)
    if m2:
        return int(m2.group(2))
    return datetime.now().year


def _to_int_safe(x, default=None):
    try:
        if x is None:
            return default
        s = str(x).strip()
        if s == "" or s.lower() in {"nan","none","null"}:
            return default
        return int(float(s))
    except Exception:
        return default


def _expiry_pill_html(expiry_year: int | None, end_year: int) -> str:
    if not expiry_year:
        return "<span class='expiryPill'>—</span>"
    remain = max(0, int(expiry_year) - int(end_year))
    cls = "expiryOk"
    if remain <= 0:
        cls = "expirySoon"
    elif remain == 1:
        cls = "expiryMid"
    return f"<span class='expiryPill {cls}'>Exp {expiry_year}</span>"


def _contract_bar_html(level: str, expiry_year: int | None, end_year: int) -> tuple[str,str]:
    """Returns (bar_html, remain_text). For ELC shows remaining years."""
    lvl_u = str(level or "").strip().upper()
    if not expiry_year:
        return "<div class='contractBar'></div>", ""
    remain = max(0, int(expiry_year) - int(end_year))
    # Scale bar: ELC usually 0-3, STD up to ~8
    cap = 3 if lvl_u == "ELC" else 8
    pct = 0
    try:
        pct = int(round(min(remain, cap) / cap * 100))
    except Exception:
        pct = 0
    fill_cls = "contractFillELC" if lvl_u == "ELC" else "contractFill"
    bar = f"<div class='contractBar'><div class='contractFill {fill_cls}' style='width:{pct}%'></div></div>"
    txt = f"{remain}y" if (lvl_u == "ELC" and remain is not None) else ""
    return bar, txt



def _contract_alert_html(level: str, expiry_year: int | None, end_year: int) -> str:
    """Small warning icon with tooltip for expiring contracts."""
    lvl = str(level or "").strip().upper()
    if not expiry_year:
        return ""
    remain = max(0, int(expiry_year) - int(end_year))

    # Rules:
    # - Expired/this year: red warning
    # - Next year: yellow warning
    # - For ELC: if remaining years <= 1, highlight
    if remain <= 0:
        return "<span class='ctWarn ctRed' title='Contrat à renouveler (expire cette saison)'>⚠️</span>"
    if remain == 1:
        tip = "Contrat expire l'an prochain"
        if lvl == "ELC":
            tip = "ELC expire l'an prochain"
        return f"<span class='ctWarn ctYel' title='{html.escape(tip)}'>⚠️</span>"
    if lvl == "ELC" and remain == 2:
        return "<span class='ctWarn ctDim' title='ELC: 2 ans restants'>ℹ️</span>"
    return ""


def roster_click_list(df_src: pd.DataFrame, owner: str, source_key: str) -> str | None:
    # v38: force Level (STD/ELC) via Hockey.Players.csv before rendering
    try:
        df_src = apply_players_level(df_src)
    except Exception:
        pass
    if df_src is None or not isinstance(df_src, pd.DataFrame) or df_src.empty:
        st.info("Aucun joueur.")
        return None

    # CSS injecté 1x
    t = df_src.copy()

    # --- Alignement filters (UI polish)
    q = str(st.session_state.get('align_filter_q','') or '').strip().lower()
    only_elc = bool(st.session_state.get('align_filter_only_elc', False))
    only_std = bool(st.session_state.get('align_filter_only_std', False))

    # colonnes minimales
    for c, d in {"Joueur": "", "Pos": "F", "Equipe": "", "Salaire": 0, "Level": "", }.items():
        if c not in t.columns:
            t[c] = d

    t["Joueur"] = t["Joueur"].astype(str).fillna("").map(lambda x: re.sub(r"\s+", " ", x).strip())
    t["Equipe"] = t["Equipe"].astype(str).fillna("").map(lambda x: re.sub(r"\s+", " ", x).strip())
    t["Level"]  = t["Level"].astype(str).fillna("").map(lambda x: re.sub(r"\s+", " ", x).strip())
    t["Level"] = t["Level"].replace({"0": "", "0.0": ""})
    t["Salaire"] = pd.to_numeric(t["Salaire"], errors="coerce").fillna(0).astype(int)

    bad = {"", "none", "nan", "null"}
    t = t[~t["Joueur"].str.lower().isin(bad)].copy()

    # Apply filters
    if q:
        t = t[t['Joueur'].astype(str).str.lower().str.contains(q, na=False)].copy()
    if only_elc and not only_std:
        t = t[t['Level'].astype(str).str.upper().eq('ELC')].copy()
    if only_std and not only_elc:
        t = t[t['Level'].astype(str).str.upper().eq('STD')].copy()

    if t.empty:
        st.info("Aucun joueur (filtres).")
        return None

    # tri
    t["Pos"] = t["Pos"].apply(normalize_pos)
    t["_pos"] = t["Pos"].apply(pos_sort_key)
    t["_initial"] = t["Joueur"].str.upper().str[0].fillna("?")

    t = (
        t.sort_values(
            by=["_pos", "Salaire", "_initial", "Joueur"],
            ascending=[True, False, True, True],
            kind="mergesort",
        )
    )

    disabled = str(source_key or "").endswith("_disabled")
    pid_map = _players_name_to_pid_map()

    # players_db lookups (flags + Level) — no external API calls here
    pdb = st.session_state.get("players_db", pd.DataFrame())
    level_map: dict[str, str] = {}
    flag_map: dict[str, str] = {}
    if isinstance(pdb, pd.DataFrame) and not pdb.empty:
        name_col = "Player" if "Player" in pdb.columns else ("Joueur" if "Joueur" in pdb.columns else None)
        if name_col:
            tmpdb = pdb[[name_col] + [c for c in ["Level","Flag","FlagISO2","Country"] if c in pdb.columns]].copy()
            tmpdb["_k"] = tmpdb[name_col].astype(str).map(_norm_name)
            if "Level" in tmpdb.columns:
                level_map = {k: str(v).strip().upper() for k, v in zip(tmpdb["_k"], tmpdb["Level"]) if str(k).strip()}
            if "Flag" in tmpdb.columns:
                flag_map = {k: str(v).strip() for k, v in zip(tmpdb["_k"], tmpdb["Flag"]) if str(k).strip()}
            # fallback: compute flag from iso2 if emoji missing
            if (not flag_map) and ("FlagISO2" in tmpdb.columns):
                flag_map = {k: _iso2_to_flag_emoji(str(v).strip()) for k, v in zip(tmpdb["_k"], tmpdb["FlagISO2"]) if str(k).strip() and str(v).strip()}

    # header
    # Ratios: garder tout sur une seule ligne (bouton moins "gourmand")
    h = st.columns([0.8, 1.1, 4.8, 0.9, 1.7])
    h[0].markdown("**Pos**")
    h[1].markdown("**Équipe**")
    h[2].markdown("**Joueur**")
    h[3].markdown("**Level**")
    h[4].markdown("**Salaire**")

    clicked = None
    for _, r in t.iterrows():
        joueur = str(r.get("Joueur", "")).strip()
        if not joueur:
            continue

        pos = r.get("Pos", "F")
        team = str(r.get("Equipe", "")).strip()
        lvl = str(r.get("Level", "")).strip()
        salaire = int(r.get("Salaire", 0) or 0)

        # --- Flag + Level via Players DB (robuste: "Last, First" vs "First Last")
        key1 = _norm_name(joueur)
        key2 = _norm_name(_to_last_comma_first(joueur))
        key3 = _norm_name(_to_first_last(joueur))

        lvl_db = ""
        for k in (key1, key2, key3):
            if not lvl_db:
                lvl_db = str(level_map.get(k, "") or "").strip().upper()

        if lvl_db in ("ELC", "STD"):
            lvl = lvl_db
        else:
            lvl = str(lvl or "").strip().upper()
            if lvl not in ("ELC", "STD"):
                lvl = "—"

        fv = ""
        for k in (key1, key2, key3):
            if not fv:
                fv = flag_map.get(k, "")

        flag = "" if (fv is None or (isinstance(fv, float) and pd.isna(fv)) or str(fv).strip().lower() == "nan") else str(fv).strip()
        flag_url = flag if str(flag).lower().startswith("http") else ""
        flag_emoji = "" if flag_url else flag
        display_name = f"{flag_emoji} {joueur}".strip() if flag_emoji else joueur

        row_sig = f"{joueur}|{pos}|{team}|{lvl}|{salaire}"
        row_key = re.sub(r"[^a-zA-Z0-9_|\-]", "_", row_sig)[:120]

        c = st.columns([0.8, 1.1, 0.6, 4.2, 0.9, 1.7])
        c[0].markdown(pos_badge_html(pos), unsafe_allow_html=True)
        c[1].markdown(team if team and team.lower() not in bad else "—")

        # Flag + bouton joueur (no nested columns)
        if flag_url and str(flag_url).startswith("http"):
            try:
                c[2].image(flag_url, width=22)
            except Exception:
                pass
        else:
            c[2].markdown("")

        if c[3].button(
            display_name,
            key=f"{source_key}_{owner}_{row_key}",
            # IMPORTANT: ne pas étirer le bouton (sinon ça "mange" la ligne)
            disabled=disabled,
        ):
            clicked = joueur


        lvl_u = str(lvl or "").strip().upper()
        lvl_cls = "lvlELC" if lvl_u == "ELC" else ("lvlSTD" if lvl_u == "STD" else "")
        c[4].markdown(
            f"<span class='levelCell {lvl_cls}'>{html.escape(lvl) if lvl and lvl.lower() not in bad else '—'}</span>",
            unsafe_allow_html=True,
        )

        c[5].markdown(f"<span class='salaryCell'>{money(salaire)}</span>", unsafe_allow_html=True)

    return clicked



def render_player_profile_page():
    st.subheader("👤 Profil Joueurs NHL")

    # =====================================================
    # ### 🔎 Liste & filtres — tous les joueurs (points/salaire/level + appartenance)
    # =====================================================
    season_lbl = str(st.session_state.get("season") or st.session_state.get("season_lbl") or "").strip() or "2025-2026"
    df_roster = st.session_state.get("data", pd.DataFrame())
    df_roster = clean_data(df_roster) if isinstance(df_roster, pd.DataFrame) else pd.DataFrame()

    # Players DB (pour playerId)
    pdb = st.session_state.get("players_db")
    if not isinstance(pdb, pd.DataFrame) or pdb.empty:
        try:
            pdb_path = _first_existing(PLAYERS_DB_FALLBACKS) if "PLAYERS_DB_FALLBACKS" in globals() else ""
            if not pdb_path:
                pdb_path = os.path.join(DATA_DIR, "hockey.players.csv")
            mtime = os.path.getmtime(pdb_path) if (pdb_path and os.path.exists(pdb_path)) else 0.0
            pdb = load_players_db(pdb_path, mtime) if mtime else pd.DataFrame()
        except Exception:
            pdb = pd.DataFrame()

    name_to_pid = {}
    if isinstance(pdb, pd.DataFrame) and (not pdb.empty) and ("Player" in pdb.columns):
        tmp = pdb.copy()
        tmp["_k"] = tmp["Player"].astype(str).apply(_norm_name)
        pid_col = "playerId" if "playerId" in tmp.columns else ("PlayerId" if "PlayerId" in tmp.columns else None)
        if pid_col:
            name_to_pid = dict(zip(tmp["_k"], tmp[pid_col].astype(str)))

    # Build universe: roster + players_db names (optional)
    rows = []
    if not df_roster.empty and "Joueur" in df_roster.columns:
        d = df_roster.copy()
        d["Joueur"] = d["Joueur"].astype(str).str.strip()
        d = d[d["Joueur"].astype(str).str.len() > 0]
        # take last occurrence per player to get latest owner/level/salary
        d = d.drop_duplicates(subset=["Joueur"], keep="last")
        for _, r in d.iterrows():
            name = str(r.get("Joueur", "") or "").strip()
            if not name:
                continue
            k = _norm_name(name)
            owner = str(r.get("Propriétaire", "") or "").strip()
            pos = str(r.get("Pos", r.get("Position", "")) or "").strip()
            lvl = str(r.get("Level", "") or "").strip()
            sal = r.get("Salaire", r.get("Cap Hit", r.get("CapHit", "")))
            try:
                sal_i = int(float(sal)) if str(sal).strip() else 0
            except Exception:
                sal_i = 0
            pid = str(r.get("playerId", "") or "").strip() or str(name_to_pid.get(k, "") or "").strip()
            rows.append({
                "Joueur": name,
                "Propriétaire": owner,
                "Pos": pos,
                "Level": lvl,
                "Salaire": sal_i,
                "playerId": pid,
            })

    dfu = pd.DataFrame(rows)
    if dfu.empty:
        st.info("Aucun roster chargé — importe via 🛠️ Gestion Admin → Import Fantrax.")
    else:
        # Filters
        owners = sorted([o for o in dfu["Propriétaire"].dropna().astype(str).str.strip().unique().tolist() if o])
        owner_opts = ["Tous", "Joueurs autonomes"] + owners

        cF1, cF2, cF3 = st.columns([1.2, 1.2, 1.6])
        with cF1:
            owner_pick = st.selectbox("Filtre équipe", owner_opts, index=0, key="prof_owner_filter")
        with cF2:
            q = st.text_input("Recherche", value="", placeholder="Nom du joueur…", key="prof_search")
        with cF3:
            st.caption("Astuce: clique un joueur ci-dessous pour ouvrir son profil.")

        dfv = dfu.copy()
        if owner_pick == "Joueurs autonomes":
            dfv = dfv[dfv["Propriétaire"].astype(str).str.strip().eq("")]
        elif owner_pick != "Tous":
            dfv = dfv[dfv["Propriétaire"].astype(str).str.strip().eq(owner_pick)]

        if q.strip():
            qq = q.strip().lower()
            dfv = dfv[dfv["Joueur"].astype(str).str.lower().str.contains(qq, na=False)]

        dfv = dfv.sort_values(by=["Propriétaire", "Joueur"], kind="mergesort", na_position="last").reset_index(drop=True)

        # Points (API) — cache session pour accélérer
        rules = load_scoring_rules()
        pts_cache_key = f"profile_pts_cache__{season_lbl}"
        if pts_cache_key not in st.session_state:
            st.session_state[pts_cache_key] = {}
        pts_cache = st.session_state[pts_cache_key]

        # calcul pour les 200 premiers (évite surcharge)
        max_calc = 200
        pts = []
        for i, r in dfv.head(max_calc).iterrows():
            pid = str(r.get("playerId", "") or "").strip()
            pos = str(r.get("Pos", "") or "").strip()
            key = f"{pid}|{pos}"
            if pid and key in pts_cache:
                pts.append(float(pts_cache[key] or 0))
                continue
            if pid:
                try:
                    val = float(_fantasy_points_for_player(pid, pos, season_lbl, rules) or 0)
                except Exception:
                    val = 0.0
                pts_cache[key] = val
                pts.append(val)
            else:
                pts.append(0.0)
        # pad rest
        if len(pts) < len(dfv):
            pts += [0.0] * (len(dfv) - len(pts))

        dfv["Points"] = pts

        # Table
        show = dfv[[c for c in ["Joueur", "Propriétaire", "Pos", "Level", "Salaire", "Points"] if c in dfv.columns]].copy()
        show["Salaire"] = show["Salaire"].apply(lambda x: money(x) if isinstance(x, (int, float)) else str(x))
        show["Points"] = show["Points"].apply(lambda x: f"{float(x):.0f}")
        st.dataframe(show.head(500), use_container_width=True, hide_index=True)

        # Pick a player
        pick_names = dfv["Joueur"].head(500).tolist()
        pick = st.selectbox("Ouvrir le profil de…", [""] + pick_names, index=0, key="prof_pick_player")
        if pick:
            k = _norm_name(pick)
            pid = str(name_to_pid.get(k, "") or "").strip()
            # fallback from dfv
            if not pid:
                try:
                    pid = str(dfv[dfv["Joueur"].eq(pick)].iloc[0].get("playerId", "") or "").strip()
                except Exception:
                    pid = ""
            if pid:
                st.session_state["profile_player_id"] = pid
                st.session_state["profile_player_name"] = pick
                do_rerun()
            else:
                st.warning("playerId introuvable pour ce joueur (Players DB).")




    # -----------------------------------------------------
    # 🔎 Répertoire joueurs (avec filtres)
    #   - Points: via APIs (game logs / stats)
    #   - Salaire/Level: via roster (data)
    #   - Filtre: Tous / Appartient à une équipe / Joueur autonome / Équipe X
    # -----------------------------------------------------
    st.markdown("### 🔎 Répertoire — joueurs NHL")

    season_lbl = str(st.session_state.get('season') or st.session_state.get('season_lbl') or '').strip() or saison_auto()
    rules = load_scoring_rules()

    df_roster = st.session_state.get('data', pd.DataFrame())
    if not isinstance(df_roster, pd.DataFrame):
        df_roster = pd.DataFrame()
    df_roster = clean_data(df_roster) if not df_roster.empty else df_roster

    pdb = st.session_state.get('players_db')
    if not isinstance(pdb, pd.DataFrame) or pdb.empty:
        # best effort: load from disk
        try:
            pdb_path = _first_existing(PLAYERS_DB_FALLBACKS) if 'PLAYERS_DB_FALLBACKS' in globals() else ''
            if not pdb_path:
                pdb_path = os.path.join(DATA_DIR, 'hockey.players.csv')
            mtime = os.path.getmtime(pdb_path) if (pdb_path and os.path.exists(pdb_path)) else 0.0
            pdb = load_players_db(pdb_path, mtime) if mtime else pd.DataFrame()
        except Exception:
            pdb = pd.DataFrame()

    # Build name -> playerId map from Players DB
    name_to_pid = {}
    if isinstance(pdb, pd.DataFrame) and (not pdb.empty) and ('Player' in pdb.columns):
        p2 = pdb.copy()
        if 'playerId' not in p2.columns:
            p2['playerId'] = ''
        p2['_k'] = p2['Player'].astype(str).apply(_norm_name)
        name_to_pid = dict(zip(p2['_k'], p2['playerId'].astype(str)))

    # Owners list
    owners = []
    if not df_roster.empty and 'Propriétaire' in df_roster.columns:
        owners = sorted(df_roster['Propriétaire'].dropna().astype(str).str.strip().unique().tolist())
        owners = [o for o in owners if o]

    # Filters
    cF1, cF2, cF3 = st.columns([1.2, 1.2, 2.0], vertical_alignment='center')
    with cF1:
        scope = st.selectbox(
            'Filtre',
            ['Tous', 'Appartient à une équipe', 'Joueur autonome'] + owners,
            index=0,
            key='nhl_profile_scope'
        )
    with cF2:
        q = st.text_input('Recherche', value='', placeholder='Nom du joueur…', key='nhl_profile_q')
    with cF3:
        st.caption('Les points proviennent des APIs (cache). Salaire/Level viennent du roster de la saison.')

    # Build base list: roster players + Players DB players
    rows = []

    # From roster (preferred for owner/salary/level)
    if not df_roster.empty and 'Joueur' in df_roster.columns:
        cols_keep = [c for c in ['Joueur','Propriétaire','Pos','Equipe','Statut','Slot','Salaire','Cap Hit','Level'] if c in df_roster.columns]
        base = df_roster[cols_keep].copy()
        base['Joueur'] = base['Joueur'].astype(str).str.strip()
        base = base[base['Joueur'].astype(str).str.len() > 0]
        base['_k'] = base['Joueur'].astype(str).apply(_norm_name)
        base['playerId'] = base['_k'].map(name_to_pid).fillna('')

        # normalize salary
        if 'Salaire' not in base.columns:
            base['Salaire'] = base.get('Cap Hit', '')
        # keep one row per player (latest)
        base = base.drop_duplicates(subset=['_k'], keep='last')

        for _, r in base.iterrows():
            rows.append({
                'Joueur': str(r.get('Joueur','')).strip(),
                'Propriétaire': str(r.get('Propriétaire','')).strip(),
                'Pos': str(r.get('Pos','')).strip(),
                'Salaire': r.get('Salaire',''),
                'Level': str(r.get('Level','')).strip(),
                'playerId': str(r.get('playerId','')).strip(),
            })

    # If roster empty, fall back to Players DB list
    if not rows and isinstance(pdb, pd.DataFrame) and (not pdb.empty) and ('Player' in pdb.columns):
        p2 = pdb.copy()
        if 'playerId' not in p2.columns:
            p2['playerId'] = ''
        p2['Player'] = p2['Player'].astype(str).str.strip()
        p2 = p2[p2['Player'].astype(str).str.len() > 0]
        p2 = p2.drop_duplicates(subset=['Player'], keep='first')
        for _, r in p2.iterrows():
            rows.append({
                'Joueur': str(r.get('Player','')).strip(),
                'Propriétaire': '',
                'Pos': str(r.get('pos','') or r.get('Position','') or '').strip(),
                'Salaire': '',
                'Level': '',
                'playerId': str(r.get('playerId','')).strip(),
            })

    df_list = pd.DataFrame(rows)
    if not df_list.empty:
        df_list['_owner'] = df_list['Propriétaire'].astype(str).str.strip()

        # ownership classification
        def _is_autonome(owner: str) -> bool:
            o = (owner or '').strip().lower()
            return (not o) or (o in {'free agent','joueur autonome','autonome','fa'})

        if scope == 'Appartient à une équipe':
            df_list = df_list[~df_list['_owner'].apply(_is_autonome)].copy()
        elif scope == 'Joueur autonome':
            df_list = df_list[df_list['_owner'].apply(_is_autonome)].copy()
        elif scope not in ('Tous', 'Appartient à une équipe', 'Joueur autonome'):
            df_list = df_list[df_list['_owner'].eq(scope)].copy()

        if q.strip():
            qq = q.strip().lower()
            df_list = df_list[df_list['Joueur'].astype(str).str.lower().str.contains(qq)].copy()

    # Compute points (cached per season)
    pts_cache_key = f"nhl_points_cache__{season_lbl}"
    if pts_cache_key not in st.session_state:
        st.session_state[pts_cache_key] = {}
    pts_cache = st.session_state.get(pts_cache_key, {}) or {}

    def _to_float(x):
        try:
            return float(x)
        except Exception:
            return 0.0

    if df_list.empty:
        st.info('Aucun joueur trouvé avec ces filtres.')
    else:
        # limit to keep UI fast
        df_show = df_list.copy().head(300)

        pts_vals = []
        for _, r in df_show.iterrows():
            pid = str(r.get('playerId','') or '').strip()
            pos = str(r.get('Pos','') or '').strip()
            if pid and pid in pts_cache:
                pts_vals.append(_to_float(pts_cache.get(pid)))
                continue
            if not pid:
                pts_vals.append(0.0)
                continue
            try:
                pts = _fantasy_points_for_player(pid, pos, season_lbl, rules)
                pts_cache[pid] = float(pts or 0)
                pts_vals.append(float(pts or 0))
            except Exception:
                pts_vals.append(0.0)

        st.session_state[pts_cache_key] = pts_cache
        df_show = df_show.reset_index(drop=True)
        df_show['Points'] = pts_vals

        # Display list
        df_disp = df_show[['Joueur','Propriétaire','Pos','Points','Salaire','Level','playerId']].copy()
        st.dataframe(df_disp.drop(columns=['playerId'], errors='ignore'), use_container_width=True, hide_index=True)

        # Picker
        opts = [f"{r['Joueur']}" for _, r in df_disp.iterrows()]
        if opts:
            pick = st.selectbox('Ouvrir le profil', opts, key='nhl_profile_pick')
            if pick:
                row = df_disp[df_disp['Joueur'].eq(pick)].head(1)
                if not row.empty:
                    pid = str(row.iloc[0].get('playerId','') or '').strip()
                    if pid:
                        st.session_state['profile_player_id'] = pid
                        st.session_state['profile_player_name'] = pick
                        do_rerun()

    st.divider()


    # --- Sélecteur + liste (points / salaire / Level) ---
    df_roster_all = st.session_state.get("data", pd.DataFrame())
    df_roster_all = clean_data(df_roster_all) if isinstance(df_roster_all, pd.DataFrame) else pd.DataFrame()

    # Construire une liste de tous les joueurs connus (roster + players_db)
    owners = []
    if not df_roster_all.empty and "Propriétaire" in df_roster_all.columns:
        owners = sorted(df_roster_all["Propriétaire"].dropna().astype(str).str.strip().unique().tolist())

    with st.expander("🔎 Liste joueurs (points / salaire / Level)", expanded=True):
        cF1, cF2, cF3 = st.columns([1, 1, 2])
        with cF1:
            owner_filter = st.selectbox(
                "Filtre équipe",
                ["Toutes"] + (["Joueur autonome"] + owners if owners else ["Joueur autonome"]),
                key="profile_owner_filter",
            )
        with cF2:
            txt = st.text_input("Recherche", value="", key="profile_search_txt")
        with cF3:
            st.caption("💡 Les points viennent des APIs (cachés en cache). Si tu as beaucoup de joueurs, la première fois peut être plus lente.")

        view = df_roster_all.copy()
        if not view.empty:
            # filtre owner
            if owner_filter == "Joueur autonome":
                # owner vide ou libellés connus
                own = view.get("Propriétaire", "").astype(str).str.strip().str.lower()
                view = view[(own.eq("") | own.eq("free agent") | own.eq("joueur autonome") | own.eq("autonome"))].copy()
            elif owner_filter != "Toutes":
                view = view[view.get("Propriétaire", "").astype(str).str.strip().eq(owner_filter)].copy()

            if txt.strip():
                t = txt.strip().lower()
                view = view[view.get("Joueur", "").astype(str).str.lower().str.contains(t, na=False)].copy()

            # Colonnes clés
            for col in ["Joueur","Propriétaire","Pos","Equipe","Salaire","Level","Slot"]:
                if col not in view.columns:
                    view[col] = ""

            # Calcul points (saison) via API + rules
            season_lbl = str(st.session_state.get("season") or st.session_state.get("season_lbl") or '').strip() or saison_auto()
            rules = load_scoring_rules()

            # obtenir playerId via players_db
            pdb = st.session_state.get("players_db")
            if not isinstance(pdb, pd.DataFrame) or pdb.empty or "Player" not in pdb.columns:
                pdb_path = os.path.join(DATA_DIR, "hockey.players.csv")
                try:
                    mtime = os.path.getmtime(pdb_path) if os.path.exists(pdb_path) else 0.0
                except Exception:
                    mtime = 0.0
                pdb = load_players_db(pdb_path, mtime) if mtime else pd.DataFrame()
            pid_map = {}
            if isinstance(pdb, pd.DataFrame) and (not pdb.empty) and ("playerId" in pdb.columns) and ("Player" in pdb.columns):
                tmp = pdb.copy()
                tmp["_k"] = tmp["Player"].astype(str).apply(_norm_name)
                pid_map = dict(zip(tmp["_k"], tmp["playerId"].astype(str)))

            view["_k"] = view["Joueur"].astype(str).apply(_norm_name)
            view["playerId"] = view["_k"].map(pid_map).fillna("")

            def _pts_row(r):
                pid = str(r.get('playerId','') or '').strip()
                pos = str(r.get('Pos','') or '').strip()
                if not pid:
                    return 0
                try:
                    return int(round(_fantasy_points_for_player(pid, pos, season_lbl, rules)))
                except Exception:
                    return 0

            # limiter le calcul pour la table (évite freeze) — top 250
            vshow = view.head(250).copy()
            vshow["Points"] = vshow.apply(_pts_row, axis=1)

            show_cols = ["Joueur","Propriétaire","Pos","Equipe","Salaire","Level","Slot","Points"]
            vshow = vshow[show_cols].copy()
            vshow = vshow.sort_values(by=["Points"], ascending=False).reset_index(drop=True)

            st.dataframe(vshow, use_container_width=True, hide_index=True)

            # choix joueur
            names = vshow["Joueur"].astype(str).tolist()
            pick = st.selectbox("Ouvrir le profil", ["—"] + names, key="profile_pick_from_list")
            if pick and pick != "—":
                st.session_state["profile_player_name"] = pick
                # set id if we have it
                try:
                    pid = str(view.loc[view["Joueur"].astype(str).eq(pick), "playerId"].iloc[0])
                except Exception:
                    pid = ""
                if pid:
                    try:
                        st.session_state["profile_player_id"] = int(float(pid))
                    except Exception:
                        pass
                do_rerun()
        else:
            st.info("Aucune donnée roster chargée.")
    pid = int(st.session_state.get("profile_player_id", 0) or 0)
    pname = str(st.session_state.get("profile_player_name", "") or "").strip()
    if pid <= 0:
        st.info("Clique sur un joueur dans Alignement puis sur ‘👤 Profil complet’. ")
        return

    landing = nhl_player_landing_cached(pid)
    if not landing:
        st.warning("Aucune donnée NHL pour ce joueur (API indisponible).")
        return

    flag = _player_flag(pid, landing, joueur)
    first = str(_landing_field(landing, ["firstName","default"], "") or _landing_field(landing, ["firstName"], "") or "").strip()
    last  = str(_landing_field(landing, ["lastName","default"], "") or _landing_field(landing, ["lastName"], "") or "").strip()
    full  = (first + " " + last).strip() or str(landing.get("fullName") or pname or "").strip()
    pos   = str(landing.get("position") or landing.get("positionCode") or "").strip()
    shoots= str(landing.get("shootsCatches") or "").strip()
    team_abbrev = ""
    team = landing.get("currentTeam")
    if isinstance(team, dict):
        team_abbrev = str(team.get("abbrev") or team.get("triCode") or "").strip()
    if not team_abbrev:
        team_abbrev = str(landing.get("currentTeamAbbrev") or "").strip()

    headshot = str(landing.get("headshot") or _landing_field(landing, ["headshot","default"], "") or "").strip()
    cols = st.columns([1, 2], vertical_alignment="top")
    with cols[0]:
        if headshot:
            try:
                st.image(headshot, width=200)
            except Exception:
                pass
    with cols[1]:
        title = (flag + " " + full).strip() if flag else full
        st.markdown(f"## {html.escape(title)}", unsafe_allow_html=True)
        st.markdown(f"**{html.escape(pos or '—')}** · **{html.escape(team_abbrev or '—')}**")
        meta = []
        if shoots: meta.append(f"Shoots/Catches: {shoots}")
        h = landing.get("heightInInches") or landing.get("height")
        w = landing.get("weightInPounds") or landing.get("weight")
        bdate = str(landing.get("birthDate") or "").strip()
        if h: meta.append(f"Height: {h}")
        if w: meta.append(f"Weight: {w}")
        if bdate: meta.append(f"Born: {bdate}")
        if meta:
            st.caption(" · ".join(meta))
        st.caption(f"playerId: {pid}")

    st.divider()
    st.caption("Données: api-web.nhle.com (landing) — cache 24h")

    if st.button("↩️ Retour à Alignement", key=f"profile_back__{pid}"):
        st.session_state["active_tab"] = "🧾 Alignement"
        do_rerun()




def render_tab_gm():
    owner = str(get_selected_team() or "").strip()
    if not owner:
        st.info("Sélectionne une équipe.")
        return

    df = clean_data(st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS)))
    dprop = df[df["Propriétaire"].astype(str).str.strip().eq(owner)].copy()

    # =========================
    # HEADER GM — logo + masses
    # =========================
    colL, colR = st.columns([1.2, 3], vertical_alignment="center")

    with colL:
        # GM logo (priorité) puis logo d'équipe
        gm_logo = "gm_logo.png"
        if os.path.exists(gm_logo):
            st.image(gm_logo, width=110)
        else:
            logo = team_logo_path(owner)
            if logo:
                st.image(logo, width=110)

        st.markdown(
            f"<div style='font-size:22px;font-weight:900;margin-top:6px;'>🧊 GM — {html.escape(owner)}</div>",
            unsafe_allow_html=True,
        )

    with colR:
        cap_gc = int(st.session_state.get("PLAFOND_GC", 95_500_000))
        cap_ce = int(st.session_state.get("PLAFOND_CE", 47_750_000))

        used_gc = int(dprop[dprop["Statut"] == STATUT_GC]["Salaire"].sum()) if not dprop.empty else 0
        used_ce = int(dprop[dprop["Statut"] == STATUT_CE]["Salaire"].sum()) if not dprop.empty else 0

        r_gc = cap_gc - used_gc
        r_ce = cap_ce - used_ce

        c1, c2 = st.columns(2)
        with c1:
            st.markdown(
                f"""
                <div style="padding:14px;border-radius:14px;background:rgba(255,255,255,.05)">
                  <div style="font-size:13px;opacity:.8">Masse Grand Club</div>
                  <div style="font-size:26px;font-weight:900;margin:4px 0">{money(used_gc)}</div>
                  <div style="font-size:13px;opacity:.75">Plafond {money(cap_gc)}</div>
                  <div style="font-size:14px;font-weight:700;color:{'#ef4444' if r_gc < 0 else '#22c55e'}">
                    Reste {money(r_gc)}
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(
                f"""
                <div style="padding:14px;border-radius:14px;background:rgba(255,255,255,.05)">
                  <div style="font-size:13px;opacity:.8">Masse Club École</div>
                  <div style="font-size:26px;font-weight:900;margin:4px 0">{money(used_ce)}</div>
                  <div style="font-size:13px;opacity:.75">Plafond {money(cap_ce)}</div>
                  <div style="font-size:14px;font-weight:700;color:{'#ef4444' if r_ce < 0 else '#22c55e'}">
                    Reste {money(r_ce)}
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # =========================
    # 🏆 Points (cumul ACTIFS seulement)
    #   - Les points s'accumulent uniquement quand le joueur est ACTIF.
    #   - Quand il passe banc/mineur/IR, il conserve les points acquis.
    # =========================
    try:
        season_lbl = str(st.session_state.get('season') or '').strip() or saison_auto()
        pts_total, pts_break = team_points_snapshot(owner, season_lbl)
    except Exception:
        pts_total, pts_break = 0.0, pd.DataFrame(columns=['Joueur','Points'])

    with colR:
        st.markdown(
            f"""
            <div style=\"padding:14px;border-radius:14px;background:rgba(255,255,255,.05);margin-top:10px\">
              <div style=\"font-size:13px;opacity:.8\">🏆 Points (cumul Actifs)</div>
              <div style=\"font-size:26px;font-weight:900;margin:4px 0\">{pts_total:.0f}</div>
              <div style=\"font-size:12px;opacity:.75\">Seuls les points gagnés pendant les périodes ACTIF comptent.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if not pts_break.empty:
            with st.expander("📊 Détail points (joueurs)", expanded=False):
                st.dataframe(pts_break.head(50), use_container_width=True, hide_index=True)


        # (Auto-update déplacé dans Gestion Admin → Backups & Restore → Alerts)

    st.divider()

    # =========================
    # ⏳ Transactions en attente (approbation)
    # =========================
    try:
        tx_render_pending_cards(str(st.session_state.get("season") or ""), context_owner=owner, in_home=False)
    except Exception:
        pass


    
    # =====================================================
    # 🎛️ Filtres Alignement (rapide) — déplacés ici (GM)
    #   - contrôle l'affichage dans Alignement (roster_click_list)
    # =====================================================
    with st.expander('🎛️ Filtres Alignement (rapide)', expanded=False):
        f1, f2, f3 = st.columns([2.2, 1, 1])
        with f1:
            st.text_input(
                'Recherche joueur',
                value=str(st.session_state.get('align_filter_q','') or ''),
                key='align_filter_q',
                placeholder='ex: Suzuki'
            )
        with f2:
            st.checkbox('ELC', value=bool(st.session_state.get('align_filter_only_elc', False)), key='align_filter_only_elc')
        with f3:
            st.checkbox('STD', value=bool(st.session_state.get('align_filter_only_std', False)), key='align_filter_only_std')

    st.write("")
# =========================
    # 📄 Contrats — tous les joueurs de l'équipe (source: hockey.players.csv + puckpedia.contracts.csv)
    #   - Ici (GM), on affiche les infos contrat; on les retire de l'Alignement.
    # =========================
    try:
        pdb = st.session_state.get('players_db', pd.DataFrame())
        if not isinstance(pdb, pd.DataFrame) or pdb.empty:
            pdb_path = os.path.join(DATA_DIR, 'hockey.players.csv') if 'DATA_DIR' in globals() else 'data/hockey.players.csv'
            if os.path.exists(pdb_path):
                pdb = pd.read_csv(pdb_path)
                st.session_state['players_db'] = pdb

        show = dprop.copy() if isinstance(dprop, pd.DataFrame) else pd.DataFrame()
        if not show.empty:
            # Normalize roster columns
            for col, default in {'Joueur':'','Pos':'','Equipe':'','Salaire':0,'Level':'','Expiry Year':''}.items():
                if col not in show.columns:
                    show[col] = default

            # Map roster -> players_db for contract fields
            if isinstance(pdb, pd.DataFrame) and (not pdb.empty) and ('Player' in pdb.columns):
                p = pdb.copy()
                p['_k'] = p['Player'].astype(str).apply(_norm_name)
                p_cols = [c for c in ['Country','Flag','FlagISO2','Level','Expiry Year','contract_end','contract_level','Cap Hit','nhl_id'] if c in p.columns]
                p = p[['_k'] + p_cols].drop_duplicates('_k')

                show['_k'] = show['Joueur'].astype(str).apply(_norm_name)
                show = show.merge(p, on='_k', how='left', suffixes=('','_pdb'))

                # Prefer roster Level if present, else players_db
                show['Level'] = show['Level'].astype(str).str.strip()
                show['Level'] = show['Level'].where(show['Level'].str.strip()!='', show.get('Level_pdb',''))

                # Ensure expiry
                if 'Expiry Year_pdb' in show.columns:
                    show['Expiry Year'] = show['Expiry Year'].astype(str).str.strip()
                    show['Expiry Year'] = show['Expiry Year'].where(show['Expiry Year'].str.strip()!='', show['Expiry Year_pdb'].astype(str))

            # Render
            st.markdown('### 📄 Contrats (équipe complète)')
            st.caption('Tous les joueurs de ton équipe avec **Level (ELC/STD)** et infos de contrat. (Alignement = flags + lineups seulement.)')

            # Compute ELC remaining years (same logic)
            end_year = _season_end_year()
            def _elc_rem(level, exp):
                lvl = str(level or '').upper().strip()
                if lvl != 'ELC':
                    return ''
                y = _to_int_safe(exp, default=None)
                return '' if y is None else f"{max(0, int(y)-int(end_year))}y"

            show['ELC reste'] = show.apply(lambda r: _elc_rem(r.get('Level',''), r.get('Expiry Year','')), axis=1)

            cols = []
            # Flag + player name
            if 'Flag' in show.columns:
                show['Joueur'] = show.apply(lambda r: (str(r.get('Flag') or '').strip()+" "+str(r.get('Joueur') or '').strip()).strip(), axis=1)
            cols = [c for c in ['Joueur','Pos','Equipe','Level','ELC reste','contract_level','contract_end','Expiry Year','Cap Hit','Salaire'] if c in show.columns]

            # Format money fields
            if 'Cap Hit' in show.columns:
                show['Cap Hit'] = pd.to_numeric(show['Cap Hit'], errors='coerce').fillna(0).astype(int).map(money)
            if 'Salaire' in show.columns:
                show['Salaire'] = pd.to_numeric(show['Salaire'], errors='coerce').fillna(0).astype(int).map(money)

            st.dataframe(show[cols].sort_values(['Level','Joueur']), use_container_width=True, hide_index=True)
        else:
            st.info('Aucun joueur importé pour cette équipe (Admin → Import).')
    except Exception as e:
        st.warning(f"Contrats GM indisponibles: {e}")


    # GM — picks & buyouts
    # =========================
    render_tab_gm_picks_buyout(owner, dprop)


def render_tab_gm_picks_buyout(owner: str, dprop: "pd.DataFrame") -> None:
    """
    GM: Choix de repêchage + Rachat de contrat
    - Collapses complets (pas de nested expander)
    - HTML avec styles INLINE (donc rendu pro même si le CSS est cassé / non injecté)
    """
    owner = str(owner or "").strip()
    teams = sorted(list(LOGOS.keys())) if "LOGOS" in globals() else []
    season = str(st.session_state.get("season", "") or "").strip()

    # -------------------------
    # 🎯 PICKS
    # -------------------------
    with st.expander("🎯 Choix de repêchage", expanded=True):
        st.caption("Possession des rondes 1 à 8, par année")

        # base year = fin de saison (ex "2025-2026" => 2026)
        nums = re.findall(r"\d{4}", season)
        base_year = None
        if len(nums) >= 2:
            try:
                base_year = int(nums[-1])
            except Exception:
                base_year = None
        elif len(nums) == 1:
            try:
                base_year = int(nums[0])
            except Exception:
                base_year = None

        years = [str(base_year + i) for i in range(0, 3)] if base_year else ([season] if season else [])

        # cache picks
        cache = st.session_state.get("_picks_cache")
        if not isinstance(cache, dict):
            cache = {}
            st.session_state["_picks_cache"] = cache

        # styles inline (fallback robuste)
        row_style = (
            "display:flex;gap:10px;flex-wrap:nowrap;overflow-x:auto;overflow-y:hidden;"
            "white-space:nowrap;padding:6px 0 10px 0;-webkit-overflow-scrolling:touch;"
        )
        pill_mine = (
            "display:inline-flex;align-items:center;justify-content:center;"
            "padding:7px 10px;border-radius:999px;font-weight:700;font-size:13px;"
            "border:1px solid rgba(34,197,94,.55);background:rgba(34,197,94,.10);"
        )
        pill_other = (
            "display:inline-flex;align-items:center;justify-content:center;"
            "padding:7px 10px;border-radius:999px;font-weight:700;font-size:13px;"
            "border:1px solid rgba(255,255,255,.14);background:rgba(255,255,255,.06);"
            "opacity:.92;"
        )
        year_badge = (
            "display:inline-flex;align-items:center;justify-content:center;"
            "padding:8px 10px;border-radius:999px;font-weight:900;font-size:13px;"
            "border:1px solid rgba(34,197,94,.55);background:rgba(34,197,94,.10);"
            "width:70px;"
        )

        for ylbl in years:
            if ylbl not in cache:
                try:
                    cache[ylbl] = load_picks(ylbl, teams)
                except Exception:
                    cache[ylbl] = {}
                st.session_state["_picks_cache"] = cache

            p_all = cache.get(ylbl, {}) or {}
            my_p = p_all.get(owner, {}) if isinstance(p_all, dict) else {}

            nb = 0
            for rr in range(1, 9):
                who = str(my_p.get(str(rr), owner) or "").strip() or owner
                if who == owner:
                    nb += 1

            # line container (grid-like using columns)
            cY, cR = st.columns([1, 8], vertical_alignment="top")
            with cY:
                st.markdown(
                    f"<div style='{year_badge}'>{html.escape(str(ylbl))}</div>"
                    f"<div style='font-size:12px;opacity:.75;padding-left:6px;margin-top:6px;'>{nb} choix</div>",
                    unsafe_allow_html=True,
                )
            with cR:
                pills = [f"<div style='{row_style}'>"]
                for rr in range(1, 9):
                    who = str(my_p.get(str(rr), owner) or "").strip() or owner
                    style = pill_mine if who == owner else pill_other
                    label = f"R{rr} • {html.escape(who)}"
                    pills.append(f"<span style='{style}' title='{html.escape(who)}'>{label}</span>")
                pills.append("</div>")
                st.markdown("".join(pills), unsafe_allow_html=True)

        show_detail = st.checkbox("Voir le détail en tableau", value=False, key=f"gm_picks_detail_{owner}")
        if show_detail:
            rows = []
            for ylbl in years:
                p_all = st.session_state.get("_picks_cache", {}).get(ylbl, {}) or {}
                my_p = p_all.get(owner, {}) if isinstance(p_all, dict) else {}
                for rr in range(1, 9):
                    who = str(my_p.get(str(rr), owner) or "").strip() or owner
                    rows.append({
                        "Année": str(ylbl),
                        "Ronde": int(rr),
                        "Appartenant à": who,
                        "Reçu le": "—",
                    })
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.info("Aucun choix trouvé pour cette équipe.")

    st.divider()

    # -------------------------
    # 🧾 RACHAT
    # -------------------------
    with st.expander("🧾 Rachat de contrat", expanded=False):
        st.caption("Pénalité automatique : 50% du salaire • Le joueur devient Autonome")

        candidates = dprop.copy()
        if "Joueur" in candidates.columns:
            candidates = candidates[~candidates["Joueur"].astype(str).str.startswith("RACHAT —", na=False)].copy()
        if "Salaire" in candidates.columns:
            candidates = candidates[candidates["Salaire"].fillna(0).astype(float) > 0].copy()

        name_col = "Joueur" if "Joueur" in candidates.columns else ("Player" if "Player" in candidates.columns else None)
        if not name_col or candidates.empty:
            st.info("Aucun joueur éligible au rachat.")
            return

        display = []
        disp_salary = {}
        disp_name = {}
        for _, r in candidates.iterrows():
            nm = str(r.get(name_col, "")).strip()
            if not nm:
                continue
            sal_raw = float(r.get("Salaire", 0) or 0)
            sal = money(int(sal_raw))
            pos = str(r.get("Position", r.get("Pos", "")) or "").strip()
            team = str(r.get("Team", r.get("Équipe", "")) or "").strip()
            disp = f"{nm}  —  {pos}  {team}  —  {sal}"
            display.append(disp)
            disp_salary[disp] = sal_raw
            disp_name[disp] = nm

        picked_rows = st.selectbox("Joueur à racheter", [""] + display, index=0, key="gm_buyout_pick")
        sel_salary = float(disp_salary.get(picked_rows, 0) or 0)
        penalite = int(round(sel_salary * 0.50)) if sel_salary > 0 else 0
        can_apply = bool(str(picked_rows).strip())

        c1, c2, c3 = st.columns([1, 1, 2], vertical_alignment="center")
        with c1:
            bucket = st.radio("Appliqué à", ["GC", "CE"], horizontal=True, key="gm_buyout_bucket")
        with c2:
            st.metric("Pénalité (50%)", money(int(penalite)) if can_apply else "—")
        with c3:
            note = st.text_input("Note (optionnel)", key="gm_buyout_note")

        if st.button("✅ Confirmer le rachat", type="primary", disabled=not can_apply, use_container_width=True, key="gm_buyout_confirm"):
            df_all = st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS))
            df_new, player_name, penalite_calc, removed = apply_buyout(df_all, owner, picked_rows, bucket)

            st.session_state["data"] = df_new

            # Sauvegarde data
            try:
                data_file = str(st.session_state.get("DATA_FILE", "") or "").strip()
                if data_file:
                    df_new.to_csv(data_file, index=False)
            except Exception:
                pass

            # Rebuild plafonds
            try:
                st.session_state["plafonds"] = rebuild_plafonds(df_new)
            except Exception:
                pass

            # Marché: joueur devient autonome
            try:
                season_lbl = str(st.session_state.get("season","") or "").strip()
                push_buyout_to_market(season_lbl, player_name)
            except Exception:
                pass

            # Historique
            try:
                h = st.session_state.get("history", pd.DataFrame())
                if not isinstance(h, pd.DataFrame):
                    h = pd.DataFrame()
                row = {
                    "timestamp": datetime.now(ZoneInfo("America/Toronto")).isoformat(timespec="seconds"),
                    "action": "RACHAT",
                    "proprietaire": owner,
                    "joueur": player_name,
                    "detail": f"{bucket} — pénalité {money(int(penalite_calc or 0))}",
                    "note": str(note or ""),
                }
                h = pd.concat([h, pd.DataFrame([row])], ignore_index=True)
                st.session_state["history"] = h
                hf = str(st.session_state.get("HISTORY_FILE","") or "").strip()
                if hf:
                    h.to_csv(hf, index=False)
            except Exception:
                pass

            st.success(f"Rachat appliqué ✅ — {player_name} devient **Autonome** (pénalité {money(int(penalite_calc or 0))} sur {bucket})")
            do_rerun()






def push_buyout_to_market(season_lbl: str, player_name: str) -> None:
    if not ("load_trade_market" in globals() and callable(globals()["load_trade_market"]) and
            "save_trade_market" in globals() and callable(globals()["save_trade_market"])):
        return

    season_lbl = str(season_lbl or "").strip()
    joueur_key = str(player_name or "").strip()
    if not season_lbl or not joueur_key:
        return

    try:
        tm = load_trade_market(season_lbl)
    except Exception:
        tm = pd.DataFrame()

    if not isinstance(tm, pd.DataFrame):
        tm = pd.DataFrame()

    for c in ["season", "proprietaire", "joueur", "is_available", "updated_at"]:
        if c not in tm.columns:
            tm[c] = ""

    now_s = datetime.now(ZoneInfo("America/Toronto")).strftime("%Y-%m-%d %H:%M:%S")
    mask = tm["joueur"].astype(str).str.strip().eq(joueur_key)

    if mask.any():
        tm.loc[mask, "season"] = season_lbl
        tm.loc[mask, "proprietaire"] = "Autonome"
        tm.loc[mask, "is_available"] = True
        tm.loc[mask, "updated_at"] = now_s
    else:
        tm = pd.concat([tm, pd.DataFrame([{
            "season": season_lbl,
            "proprietaire": "Autonome",
            "joueur": joueur_key,
            "is_available": True,
            "updated_at": now_s,
        }])], ignore_index=True)

    try:
        save_trade_market(season_lbl, tm)
    except Exception:
        pass



def render_tab_autonomes(show_header: bool = True, lock_dest_to_owner: bool = False):
    """Onglet Joueurs autonomes / Ajout joueurs (Admin).

    Règles:
    - Un joueur est jouable IFF (NHL GP >= 84) ET (Level != ELC)
    - La sélection (max 5) est persistée par propriétaire + saison et ne disparaît pas quand on change la recherche.
    """

    # --- Contexte
    try:
        owner = str(get_selected_team() or "").strip() if "get_selected_team" in globals() else ""
    except Exception:
        owner = ""

    season_lbl = str(st.session_state.get("season", "") or "").strip()
    scope = "auto" if lock_dest_to_owner else "admin"
    pick_state_key = f"fa_pick__{season_lbl}__{owner or 'x'}__{scope}"
    sel_players = [str(x).strip() for x in (st.session_state.get(pick_state_key) or []) if str(x).strip()]

    if show_header:
        st.subheader("👤 Joueurs autonomes")
        st.caption("Recherche → sélection (max 5) → confirmer. La sélection reste même si tu changes la recherche.")

    players_db = st.session_state.get("players_db")
    if players_db is None or (not isinstance(players_db, pd.DataFrame)) or players_db.empty:
        st.error("Impossible de charger la base joueurs (players_db).")
        st.stop()

    df_db = players_db.copy()

    # --- Helpers
    def _cap_to_int(v) -> int:
        try:
            s = str(v).strip()
            if not s or s.lower() in ("nan", "none"):
                return 0
            s = s.replace("$", "").replace("€", "").replace("£", "")
            s = s.replace(",", " ").replace(" ", " ")
            s = re.sub(r"[^0-9.]", "", s)
            return int(round(float(s))) if s else 0
        except Exception:
            return 0

    def _as_int(v) -> int:
        try:
            return int(float(v))
        except Exception:
            return 0

    def _reason(nhl_gp: int, lvl_u: str) -> str:
        reasons = []
        if nhl_gp < 84:
            reasons.append("NHL GP < 84")
        if (lvl_u or "").strip().upper() == "ELC":
            reasons.append("Level = ELC")
        return " + ".join(reasons) if reasons else "—"

    # --- Normalisation colonnes (best effort)
    if "Player" not in df_db.columns:
        for cand in ["Joueur", "Name", "Full Name", "fullname", "player"]:
            if cand in df_db.columns:
                df_db = df_db.rename(columns={cand: "Player"})
                break
    if "Team" not in df_db.columns:
        for cand in ["Équipe", "Equipe", "NHL Team", "team", "Club"]:
            if cand in df_db.columns:
                df_db = df_db.rename(columns={cand: "Team"})
                break
    if "Position" not in df_db.columns:
        for cand in ["Pos", "POS", "position"]:
            if cand in df_db.columns:
                df_db = df_db.rename(columns={cand: "Position"})
                break

    level_col = "Level" if "Level" in df_db.columns else None
    if not level_col:
        for cand in ["Contrat", "Contract", "Type", "level"]:
            if cand in df_db.columns:
                df_db = df_db.rename(columns={cand: "Level"})
                level_col = "Level"
                break

    cap_col = None
    for cand in ["Cap Hit", "CapHit", "Cap", "Salary", "Salaire", "AAV"]:
        if cand in df_db.columns:
            cap_col = cand
            break

    nhl_gp_col = None
    for cand in ["NHL GP", "NHL_GP", "NHLGP", "NHL Games", "NHLGames", "GP", "NHL_Games"]:
        if cand in df_db.columns:
            nhl_gp_col = cand
            break

    # --- Mapping "appartient déjà à" (à partir de la ligue)
    df_league = st.session_state.get("data")
    owner_map = {}
    def _norm_player_key(name: str) -> str:
        """Normalise un nom joueur pour matcher 'Leo Carlsson' et 'Carlsson, Leo'."""
        s = str(name or "").strip().lower()
        if "," in s:
            # 'nom, prenom' -> 'prenom nom'
            parts = [p.strip() for p in s.split(",", 1)]
            if len(parts) == 2 and parts[1] and parts[0]:
                s = f"{parts[1]} {parts[0]}".strip()
        # compacter espaces
        s = " ".join(s.split())
        return s


# =====================================================
# NHL — Country flag helpers (emoji)
# =====================================================

def _iso2_to_flag(iso2: str) -> str:
    try:
        iso2 = (iso2 or '').strip().upper()
        if len(iso2) != 2 or not iso2.isalpha():
            return ''
        return chr(0x1F1E6 + (ord(iso2[0]) - ord('A'))) + chr(0x1F1E6 + (ord(iso2[1]) - ord('A')))
    except Exception:
        return ''

_COUNTRY3_TO2 = {
    'CAN': 'CA', 'USA': 'US', 'SWE': 'SE', 'FIN': 'FI', 'RUS': 'RU', 'CZE': 'CZ', 'SVK': 'SK',
    'CHE': 'CH', 'GER': 'DE', 'DEU': 'DE', 'AUT': 'AT', 'DNK': 'DK', 'NOR': 'NO', 'LVA': 'LV',
    'SVN': 'SI', 'FRA': 'FR', 'GBR': 'GB', 'UKR': 'UA', 'KAZ': 'KZ',
}

_COUNTRYNAME_TO2 = {
    'canada': 'CA', 'united states': 'US', 'usa': 'US', 'sweden': 'SE', 'finland': 'FI',
    'russia': 'RU', 'czechia': 'CZ', 'czech republic': 'CZ', 'slovakia': 'SK', 'switzerland': 'CH',
    'germany': 'DE', 'austria': 'AT', 'denmark': 'DK', 'norway': 'NO', 'latvia': 'LV',
    'slovenia': 'SI', 'france': 'FR', 'great britain': 'GB', 'ukraine': 'UA', 'kazakhstan': 'KZ',
}


def _players_name_to_pid_map() -> dict:
    """Build {normalized_name: playerId} from st.session_state['players_db']."""
    db = st.session_state.get('players_db')
    if db is None or (not isinstance(db, pd.DataFrame)) or db.empty:
        return {}
    if 'Player' not in db.columns or 'playerId' not in db.columns:
        return {}
    m = {}
    try:
        s_names = db['Player'].astype(str).map(_norm_name)
        s_pid = pd.to_numeric(db['playerId'], errors='coerce').fillna(0).astype(int)
        for k, pid in zip(s_names.tolist(), s_pid.tolist()):
            if k and pid > 0 and k not in m:
                m[k] = pid
    except Exception:
        return {}
    return m

    if isinstance(df_league, pd.DataFrame) and not df_league.empty and "Joueur" in df_league.columns and "Propriétaire" in df_league.columns:
        tmp = df_league[["Joueur", "Propriétaire"]].copy()
        tmp["_k"] = tmp["Joueur"].astype(str).map(_norm_player_key)
        for _, rr in tmp.iterrows():
            owner_map[str(rr.get("_k", ""))] = str(rr.get("Propriétaire", "") or "").strip()

    def owned_to(player: str) -> str:
        return owner_map.get(_norm_player_key(player), "")

    # --- UI filtres
    f1, f2, f3 = st.columns([5, 3, 3], vertical_alignment="center")
    with f1:
        q_name = st.text_input("Nom / Prénom", value="", key=f"fa_q_name__{season_lbl}__{owner or 'x'}").strip()
    with f2:
        teams = ["Toutes"]
        if "Team" in df_db.columns:
            teams += sorted(df_db["Team"].dropna().astype(str).str.strip().unique().tolist())
        team_pick = st.selectbox("Équipe", teams, index=0, key=f"fa_team_pick__{season_lbl}__{owner or 'x'}")
    with f3:
        levels = ["Tous"]
        if level_col:
            levels += sorted(df_db["Level"].dropna().astype(str).str.strip().unique().tolist())
        lvl_pick = st.selectbox("Level (Contrat)", levels, index=0, key=f"fa_lvl_pick__{season_lbl}__{owner or 'x'}")

    # Rien ne doit apparaître tant que rien n'est saisi (sauf si sélection déjà en cours)
    if not q_name and not sel_players:
        st.info("Commence à taper un nom (ou début de nom) dans **Nom / Prénom** pour afficher des résultats.")
        st.stop()

    st.divider()

    st.markdown("### 💰 Recherche par Salaire (Cap Hit)")
    cap_on = st.checkbox("Activer le filtre Cap Hit", value=False, key=f"fa_cap_on__{season_lbl}__{owner or 'x'}")

    cap_min, cap_max = (0, 30_000_000)
    if cap_col and cap_col in df_db.columns:
        try:
            vals = df_db[cap_col].apply(_cap_to_int)
            if vals.notna().any():
                cap_min = int(vals.min())
                cap_max = int(vals.max())
        except Exception:
            pass
    cap_min = max(0, int(cap_min or 0))
    cap_max = max(int(cap_max or 1), 1)

    cap_rng = (0, cap_max)
    if cap_on:
        cap_rng = st.slider(
            "Plage Cap Hit",
            min_value=0,
            max_value=int(cap_max),
            value=(0, int(cap_max)),
            step=50_000,
            key=f"fa_cap_rng__{season_lbl}__{owner or 'x'}",
        )

    st.divider()

    only_jouable = st.checkbox(
        "🚫 Exclure les joueurs selon les critères (NHL GP < 84 ou Level = ELC)",
        value=True,
        key=f"fa_only_jouable__{season_lbl}__{owner or 'x'}",
    )

    # --- Filtrage
    dff = df_db.copy()
    if q_name:
        dff = dff[dff["Player"].astype(str).str.lower().str.contains(q_name.lower(), na=False)].copy()
    if team_pick != "Toutes" and "Team" in dff.columns:
        dff = dff[dff["Team"].astype(str).str.strip().eq(str(team_pick).strip())].copy()
    if lvl_pick != "Tous" and level_col:
        dff = dff[dff["Level"].astype(str).str.strip().eq(str(lvl_pick).strip())].copy()
    if cap_on and cap_col and cap_col in dff.columns:
        cap_vals = dff[cap_col].apply(_cap_to_int)
        dff = dff[(cap_vals >= int(cap_rng[0])) & (cap_vals <= int(cap_rng[1]))].copy()

    if dff.empty:
        st.warning("Aucun joueur trouvé.")
        return

    # --- Calcul jouable + raison
    dff["_nhl_gp"] = dff[nhl_gp_col].apply(_as_int) if nhl_gp_col and nhl_gp_col in dff.columns else 0
    dff["_lvl_u"] = dff["Level"].astype(str).str.strip().str.upper() if level_col else ""
    dff["✅ Jouable"] = (dff["_nhl_gp"] >= 84) & (dff["_lvl_u"] != "ELC")
    dff["Raison"] = [
        _reason(int(gp or 0), str(lv or ""))
        for gp, lv in zip(dff["_nhl_gp"].tolist(), dff["_lvl_u"].tolist())
    ]
    if only_jouable:
        dff = dff[dff["✅ Jouable"]].copy()
        if dff.empty:
            st.warning("Aucun joueur jouable avec ces filtres.")
            return

    dff = dff.head(300).reset_index(drop=True)

    # --- Présentation Fantrax
    show_cols = ["Player", "Position", "Team"]
    show_cols = [c for c in show_cols if c in dff.columns]
    df_show = dff[show_cols].copy()
    if cap_col and cap_col in dff.columns:
        df_show["Cap Hit"] = dff[cap_col].apply(lambda x: money(_cap_to_int(x)))
    df_show["NHL GP"] = dff["_nhl_gp"].astype(int)
    if level_col:
        df_show["Level"] = dff["Level"].astype(str).str.strip()
    df_show["✅"] = dff["✅ Jouable"].apply(lambda v: "✅" if bool(v) else "—")
    df_show["🔴"] = df_show["Player"].apply(lambda p: "🔴" if owned_to(p) else "")
    df_show["Appartenant à"] = df_show["Player"].apply(owned_to)
    df_show["Raison"] = dff["Raison"].astype(str)

    # Tri: sélectionnés en haut
    df_show["_sel"] = df_show["Player"].astype(str).str.strip().isin(sel_players)
    df_show = df_show.sort_values(by=["_sel", "Player"], ascending=[False, True], na_position="last").drop(columns=["_sel"]).reset_index(drop=True)

    # Légende colonnes
    st.markdown(
        "**Colonnes :** ✅ = jouable (NHL GP ≥ 84 et Level ≠ ELC) • 🔴 = déjà dans une équipe • Appartenant à = propriétaire actuel (si 🔴) • Raison = pourquoi NON jouable."
    )

    st.dataframe(df_show, use_container_width=True, hide_index=True)

    # --- Sélection persistante (max 5)
    n_sel = len(sel_players)
    st.markdown(f"### ✅ Sélection ({n_sel} / 5)")

    if n_sel == 0:
        st.caption("Aucun joueur sélectionné. Utilise les résultats ci-dessous puis ajoute.")
    else:
        # Construire l'affichage de la sélection depuis la base complète (pas seulement df_show)
        # Ainsi, tous les joueurs sélectionnés apparaissent même si filtres/head(300) changent.
        sel_full_disp = df_db[df_db["Player"].astype(str).str.strip().isin(sel_players)].copy()
        if sel_full_disp.empty:
            st.info("Sélection introuvable dans la base (réessaie la recherche).")
        else:
            # Recréer les mêmes colonnes que dans les résultats
            show_cols2 = ["Player", "Position", "Team"]
            show_cols2 = [c for c in show_cols2 if c in sel_full_disp.columns]
            sel_df = sel_full_disp[show_cols2].copy()
            if cap_col and cap_col in sel_full_disp.columns:
                sel_df["Cap Hit"] = sel_full_disp[cap_col].apply(lambda x: money(_cap_to_int(x)))
            sel_df["NHL GP"] = (
                sel_full_disp[nhl_gp_col].apply(_as_int).astype(int)
                if nhl_gp_col and nhl_gp_col in sel_full_disp.columns
                else 0
            )
            if level_col and "Level" in sel_full_disp.columns:
                sel_df["Level"] = sel_full_disp["Level"].astype(str).str.strip()

            # Calcul jouable + raison (comme plus haut)
            _gp = sel_full_disp[nhl_gp_col].apply(_as_int) if nhl_gp_col and nhl_gp_col in sel_full_disp.columns else 0
            _lv = sel_full_disp["Level"].astype(str).str.strip().str.upper() if level_col and "Level" in sel_full_disp.columns else ""
            _jouable = (_gp >= 84) & (_lv != "ELC")
            sel_df["✅"] = _jouable.apply(lambda v: "✅" if bool(v) else "—")
            sel_df["🔴"] = sel_df["Player"].apply(lambda p: "🔴" if owned_to(p) else "")
            sel_df["Appartenant à"] = sel_df["Player"].apply(owned_to)
            sel_df["Raison"] = [
                _reason(int(gp or 0), str(lv or ""))
                for gp, lv in zip(
                    list(_gp) if hasattr(_gp, '__iter__') else [0]*len(sel_df),
                    list(_lv) if hasattr(_lv, '__iter__') else [""]*len(sel_df),
                )
            ]

            # highlight non-jouables / déjà possédé
            try:
                def _style_row(row):
                    nonj = str(row.get("Raison", "—")) != "—"
                    owned = str(row.get("Appartenant à", "") or "").strip() != ""
                    if nonj:
                        return ["background: rgba(239,68,68,0.12); font-weight:700;"] * len(row)
                    if owned:
                        return ["border: 2px solid rgba(239,68,68,0.95);"] * len(row)
                    return [""] * len(row)
                st.dataframe(sel_df.style.apply(_style_row, axis=1), use_container_width=True, hide_index=True)
            except Exception:
                st.dataframe(sel_df, use_container_width=True, hide_index=True)

        # Retirer un joueur
        remove_opts = sel_players
        to_remove = st.multiselect(
            "Retirer de la sélection",
            options=remove_opts,
            default=[],
            key=f"fa_remove__{season_lbl}__{owner or 'x'}__{scope}",
            disabled=(n_sel == 0),
        )
        if to_remove and st.button(
            "🗑️ Retirer",
            use_container_width=True,
            key=f"fa_remove_btn__{season_lbl}__{owner or 'x'}__{scope}",
        ):
            st.session_state[pick_state_key] = [p for p in sel_players if p not in set(to_remove)]
            do_rerun()


    # Ajouter depuis résultats
    st.write("")
    can_add_more = len(sel_players) < 5
    add_choices = [p for p in df_show["Player"].astype(str).str.strip().tolist() if p]
    # --- Ajouter depuis les résultats (multi-ajout stable) ---
    add_widget_key = f"fa_pending_add__{season_lbl}__{owner or 'x'}__{scope}"
    add_btn_key = f"fa_add_btn__{season_lbl}__{owner or 'x'}__{scope}"

    def _fa_add_to_selection(_wkey=add_widget_key, _pick_key=pick_state_key):
        pending = st.session_state.get(_wkey, []) or []
        cur = st.session_state.get(_pick_key, []) or []
        new_list = [str(x).strip() for x in cur if str(x).strip()]

        for p in pending:
            p = str(p).strip()
            if p and p not in new_list:
                new_list.append(p)

        st.session_state[_pick_key] = new_list[:5]
        # ✅ on peut vider un widget key seulement via callback
        st.session_state[_wkey] = []

    # --- init widget state (évite warning Streamlit: default + session_state) ---
    if add_widget_key not in st.session_state:
        st.session_state[add_widget_key] = []

    pending_add = st.multiselect(
        "Ajouter depuis les résultats (max 5 total)",
        options=add_choices,
        key=add_widget_key,
        disabled=(not can_add_more),
    )

    if pending_add:
        st.caption("À ajouter à la sélection : " + ", ".join([str(x) for x in pending_add[:5]]))

    st.button(
        "➕ Ajouter à la sélection",
        type="primary",
        use_container_width=True,
        key=add_btn_key,
        disabled=(not pending_add or not can_add_more),
        on_click=_fa_add_to_selection,
    )

    if len(sel_players) >= 5:
        st.info("Sélection complète (5/5) — retire un joueur pour en ajouter un autre.")

    st.divider()

    # --- Validation pour confirmation
    picked_now = [str(x).strip() for x in (st.session_state.get(pick_state_key) or []) if str(x).strip()]
    if not picked_now:
        st.caption("Sélectionne jusqu'à 5 joueurs avant de confirmer.")
        return

    # On reconstruit un df pour les joueurs sélectionnés (afin d'avoir NHL GP/Level même si filtres)
    sel_full = df_db[df_db["Player"].astype(str).str.strip().isin(picked_now)].copy()
    if sel_full.empty:
        st.warning("Sélection introuvable dans la base (réessaie la recherche).")
        return

    sel_full["_nhl_gp"] = sel_full[nhl_gp_col].apply(_as_int) if nhl_gp_col and nhl_gp_col in sel_full.columns else 0
    sel_full["_lvl_u"] = sel_full["Level"].astype(str).str.strip().str.upper() if level_col else ""
    sel_full["_jouable"] = (sel_full["_nhl_gp"] >= 84) & (sel_full["_lvl_u"] != "ELC")
    non_jouables = sel_full[~sel_full["_jouable"]]
    owned = [p for p in picked_now if owned_to(p)]

    has_non_jouable = not non_jouables.empty
    has_owned = len(owned) > 0

    if has_non_jouable:
        st.error("❌ Embauche impossible: au moins un joueur sélectionné est NON JOUABLE (NHL GP < 84 ou Level = ELC). Retire-le de la sélection.")
    if has_owned:
        st.error("❌ Embauche impossible: au moins un joueur sélectionné appartient déjà à une équipe. Retire-le de la sélection.")

    # --- Destination + affectation
    owners = []
    if isinstance(df_league, pd.DataFrame) and not df_league.empty and "Propriétaire" in df_league.columns:
        owners = sorted(df_league["Propriétaire"].dropna().astype(str).str.strip().unique().tolist())
    if not owners and "LOGOS" in globals():
        owners = sorted(list(LOGOS.keys()))
    if not owners:
        owners = [owner] if owner else []

    cA, cB = st.columns([2, 2], vertical_alignment="center")
    with cA:
        dest_default = owner if owner in owners else (owners[0] if owners else "")
        dest_options = [dest_default] if (lock_dest_to_owner and dest_default) else owners
        dest_owner = st.selectbox(
            "Équipe destination",
            options=dest_options,
            index=0,
            key=f"fa_dest_owner__{season_lbl}__{owner or 'x'}__{scope}",
            disabled=bool(lock_dest_to_owner),
        )
    with cB:
        assign_state_key = f"fa_assign__{season_lbl}__{owner or 'x'}__{scope}"
        assign = st.radio("Affectation", ["GC", "Banc", "CE"], horizontal=True, key=assign_state_key)

    # --- Confirmer
    if st.button(
        "✅ Confirmer l’embauche",
        type="primary",
        use_container_width=True,
        key=f"fa_confirm__{season_lbl}__{owner or 'x'}__{scope}",
        disabled=(has_non_jouable or has_owned or (not bool(dest_owner))),
    ):
        df_all = st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS))
        if not isinstance(df_all, pd.DataFrame):
            df_all = pd.DataFrame(columns=REQUIRED_COLS)

        added = 0
        skipped = []
        for pname in picked_now:
            if not pname:
                continue
            if owned_to(pname):
                skipped.append(f"{pname} (déjà à {owned_to(pname)})")
                continue

            sub = df_db[df_db["Player"].astype(str).str.strip().eq(pname)].head(1)
            if sub.empty:
                skipped.append(f"{pname} (introuvable)")
                continue
            r0 = sub.iloc[0].to_dict()

            gp = _as_int(r0.get(nhl_gp_col, 0)) if nhl_gp_col else 0
            lv = str(r0.get("Level", "") or "").strip().upper() if level_col else ""
            if (gp < 84) or (lv == "ELC"):
                skipped.append(f"{pname} (NON JOUABLE)")
                continue

            pos = str(r0.get("Position", r0.get("Pos", "")) or "").strip()
            team = str(r0.get("Team", "") or "").strip()
            sal = _cap_to_int(r0.get(cap_col, 0)) if cap_col else 0
            lvl = str(r0.get("Level", "") or "").strip() if level_col else ""

            if assign == "GC":
                statut_val, slot_val = STATUT_GC, SLOT_ACTIF
            elif assign == "Banc":
                statut_val, slot_val = STATUT_GC, SLOT_BANC
            else:
                statut_val, slot_val = STATUT_CE, SLOT_MINEUR

            new_row = {
                "Propriétaire": str(dest_owner),
                "Joueur": pname,
                "Équipe": team,
                "Pos": pos,
                "Salaire": int(sal or 0),
                "Statut": statut_val,
                "Slot": slot_val,
                "Level": lvl,
            }
            for c in REQUIRED_COLS:
                if c not in new_row:
                    new_row[c] = ""

            df_all = pd.concat([df_all, pd.DataFrame([new_row])], ignore_index=True)
            added += 1

        st.session_state["data"] = df_all
        try:
            st.session_state["plafonds"] = rebuild_plafonds(df_all)
        except Exception:
            pass

        # Reset sélection seulement après confirmation
        st.session_state[pick_state_key] = []

        if skipped:
            st.warning("Ignorés: " + "; ".join(skipped[:10]))
        st.success(f"Embauche complétée ✅ — {added} joueur(s) ajoutés à {dest_owner}.")
        do_rerun()


# =====================================================

# --- Auto-load Players DB (flags + contracts + level) once per run
try:
    ensure_players_db_loaded()
except Exception:
    pass

# ROUTING PRINCIPAL — ONE SINGLE CHAIN
# =====================================================
if active_tab == "🏠 Home":
    st.subheader("🏠 Home — Masses salariales (toutes les équipes)")

    # Sous-titre discret (UI)
    st.markdown(
        '<div class="muted">Vue d’ensemble des équipes pour la saison active</div>',
        unsafe_allow_html=True
    )

    st.write("")  # spacing léger

    # =====================================================
    # 🔔 Transactions en cours (Marché) — aperçu rapide
    #   Affiche un encart s'il y a des joueurs "disponibles" sur le marché.
    # =====================================================
    if "load_trade_market" in globals() and callable(globals()["load_trade_market"]):
        try:
            market = load_trade_market(season)

        except Exception:
            market = pd.DataFrame()

        if isinstance(market, pd.DataFrame) and not market.empty:
            mkt = market.copy()
            # normalise la colonne is_available
            if "is_available" in mkt.columns:
                mkt["is_available_str"] = mkt["is_available"].astype(str).str.strip().str.lower()
                on = mkt[mkt["is_available_str"].isin(["1", "true", "yes", "y", "oui"])]
            else:
                on = pd.DataFrame()

            if not on.empty:
                # Dernière MAJ (best effort)
                last_upd = ""
                if "updated_at" in on.columns:
                    try:
                        dt = pd.to_datetime(on["updated_at"], errors="coerce")
                        if dt.notna().any():
                            last_upd = dt.max().strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        pass

                by_owner = on["proprietaire"].astype(str).str.strip().value_counts().to_dict() if "proprietaire" in on.columns else {}
                total = int(len(on))
                owners_txt = ", ".join([f"{k} ({v})" for k, v in list(by_owner.items())[:6]])
                msg = f"📣 **Transactions / marché actif** : **{total}** joueur(s) disponible(s)"
                if owners_txt:
                    msg += f" — {owners_txt}"
                if last_upd:
                    msg += f" _(MAJ: {last_upd})_"

                c1, c2 = st.columns([4, 1], vertical_alignment="center")
                with c1:
                    st.info(msg)
                with c2:
                    if st.button("Voir", use_container_width=True, key="home_go_tx"):
                        st.session_state["active_tab"] = "⚖️ Transactions"
                        do_rerun()
            else:
                st.caption("🔕 Aucune transaction affichée pour l’instant.")
        else:
            st.caption("🔕 Aucune transaction affichée pour l’instant.")
    # =====================================================
    # ⏳ Transactions en attente — visibilité + approbation
    #   - Visible pour tous
    #   - Bouton Approuver seulement pour les équipes impliquées
    # =====================================================
    try:
        tx_render_pending_cards(season, context_owner=str(get_selected_team() or "").strip(), in_home=True)
    except Exception:
        pass

    # ⚠️ Le tableau principal reste inchangé
    build_tableau_ui(st.session_state.get("plafonds"))

    st.write("")
    st.markdown("### 🕒 Derniers changements (moves / rachats / échanges)")

    def _recent_changes_df(limit: int = 15) -> pd.DataFrame:
        rows = []

        # Moves / actions via history
        h = st.session_state.get("history")
        if isinstance(h, pd.DataFrame) and not h.empty:
            hh = h.copy()
            # normaliser colonnes
            if "timestamp" in hh.columns:
                hh["_dt"] = hh["timestamp"].apply(to_dt_local)
            else:
                hh["_dt"] = pd.NaT
            for _, r in hh.iterrows():
                rows.append({
                    "Date": format_date_fr(r.get("timestamp")),
                    "_dt": r.get("_dt", pd.NaT),
                    "Type": str(r.get("action", "") or "MOVE"),
                    "Équipe": str(r.get("proprietaire", "") or ""),
                    "Détail": f"{str(r.get('joueur','') or '')} — {str(r.get('from_statut','') or '')}/{str(r.get('from_slot','') or '')} → {str(r.get('to_statut','') or '')}/{str(r.get('to_slot','') or '')}".strip(),
                })

        # Rachats
        b = st.session_state.get("buyouts")
        if isinstance(b, pd.DataFrame) and not b.empty:
            bb = b.copy()
            bb["_dt"] = bb["timestamp"].apply(to_dt_local) if "timestamp" in bb.columns else pd.NaT
            for _, r in bb.iterrows():
                bucket = str(r.get("bucket", "GC") or "GC").strip().upper()
                rows.append({
                    "Date": format_date_fr(r.get("timestamp")),
                    "_dt": r.get("_dt", pd.NaT),
                    "Type": f"RACHAT {bucket}",
                    "Équipe": str(r.get("proprietaire", "") or ""),
                    "Détail": f"{str(r.get('joueur','') or '')} — pénalité {money(int(float(r.get('penalite',0) or 0)))}",
                })
        elif isinstance(b, list) and len(b) > 0:
            for r in b:
                try:
                    bucket = str(r.get("bucket", "GC") or "GC").strip().upper()
                    rows.append({
                        "Date": format_date_fr(r.get("timestamp")),
                        "_dt": to_dt_local(r.get("timestamp")),
                        "Type": f"RACHAT {bucket}",
                        "Équipe": str(r.get("proprietaire", "") or ""),
                        "Détail": f"{str(r.get('joueur','') or '')} — pénalité {money(int(float(r.get('penalite',0) or 0)))}",
                    })
                except Exception:
                    pass

        # (placeholder) Échanges: si tu ajoutes un log plus tard, on l’intègre ici
        out = pd.DataFrame(rows)
        if out.empty:
            return out

        out = out.sort_values(by="_dt", ascending=False, na_position="last").drop(columns=["_dt"])
        return out.head(int(limit))

    recent = _recent_changes_df(20)
    if recent.empty:
        st.caption("Aucun changement enregistré pour l’instant.")
    else:
        st.dataframe(recent, use_container_width=True, hide_index=True)



elif active_tab == "🏆 Classement":
    render_tab_classement()


elif active_tab == "🧾 Alignement":
    st.subheader("🧾 Alignement")

    df = clean_data(st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS)))
    st.session_state["data"] = df

    proprietaire = str(get_selected_team() or "").strip()
    if not proprietaire:
        st.info("Sélectionne une équipe dans le menu à gauche.")
        st.stop()

    dprop = df[df["Propriétaire"].astype(str).str.strip().eq(proprietaire)].copy()

    # v35: Level autoritaire + indicateur "trouvé"
    try:
        dprop = apply_players_level(dprop)
    except Exception:
        pass

    # v35: alert joueurs non trouvés dans Hockey.Players.csv
    try:
        if "Level_found" in dprop.columns:
            missing = dprop[~dprop["Level_found"]].copy()
            if not missing.empty:
                st.warning(f"⚠️ {len(missing)} joueur(s) sans match dans Hockey.Players.csv (Level peut être incomplet).")
                with st.expander("Voir les joueurs non trouvés"):
                    st.dataframe(missing[["Joueur","Équipe","Pos","Level"]].head(200), use_container_width=True)
    except Exception:
        pass

    # v29: enrich Level depuis data/hockey.players.csv (players DB)
    try:
        players_db = st.session_state.get("players_db", pd.DataFrame())
        if 'fill_level_and_expiry_from_players_db' in globals() and callable(globals()['fill_level_and_expiry_from_players_db']):
            dprop = fill_level_and_expiry_from_players_db(dprop, players_db)
    except Exception:
        pass

    cap_gc = int(st.session_state.get("PLAFOND_GC", 95_500_000) or 0)
    cap_ce = int(st.session_state.get("PLAFOND_CE", 47_750_000) or 0)

    if dprop.empty:
        st.warning(f"Aucun alignement importé pour **{proprietaire}** (Admin → Import).")
        j1, j2 = st.columns(2)
        with j1:
            st.markdown(cap_bar_html(0, cap_gc, f"📊 Plafond GC — {proprietaire}"), unsafe_allow_html=True)
        with j2:
            st.markdown(cap_bar_html(0, cap_ce, f"📊 Plafond CE — {proprietaire}"), unsafe_allow_html=True)
        clear_move_ctx()
        st.stop()

    # --- Split IR vs non-IR (DOIT être avant les totaux)
    injured_all = dprop[dprop.get("Slot", "") == SLOT_IR].copy()
    dprop_ok = dprop[dprop.get("Slot", "") != SLOT_IR].copy()

    # Exclure les lignes de cap mort des listes (Actifs/Banc/Mineur), mais garder pour le calcul du cap ailleurs
    dprop_ok = dprop_ok[dprop_ok.get("Slot","").astype(str).str.strip().ne(SLOT_RACHAT)].copy()

    dprop_cap = dprop[dprop.get("Slot","") != SLOT_IR].copy()  # inclut RACHAT pour le cap

    # Listes d'affichage: exclure le cap mort (RACHAT) et IR
    gc_all = dprop_ok[dprop_ok["Statut"] == STATUT_GC].copy()
    ce_all = dprop_ok[dprop_ok["Statut"] == STATUT_CE].copy()

    gc_actif = gc_all[gc_all.get("Slot", "") == SLOT_ACTIF].copy()
    gc_banc = gc_all[gc_all.get("Slot", "") == SLOT_BANC].copy()

    tmp = gc_actif.copy()
    tmp["Pos"] = tmp.get("Pos", "F").apply(normalize_pos)
    nb_F = int((tmp["Pos"] == "F").sum())
    nb_D = int((tmp["Pos"] == "D").sum())
    nb_G = int((tmp["Pos"] == "G").sum())

    used_gc = int(gc_all["Salaire"].sum()) if "Salaire" in gc_all.columns else 0
    used_ce = int(ce_all["Salaire"].sum()) if "Salaire" in ce_all.columns else 0
    remain_gc = cap_gc - used_gc
    remain_ce = cap_ce - used_ce

    # --- Barres plafond (tes barres restent)
    j1, j2 = st.columns(2)
    with j1:
        st.markdown(cap_bar_html(used_gc, cap_gc, f"📊 Plafond GC — {proprietaire}"), unsafe_allow_html=True)
    with j2:
        st.markdown(cap_bar_html(used_ce, cap_ce, f"📊 Plafond CE — {proprietaire}"), unsafe_allow_html=True)

    st.write("")

    # =====================================================
    # 📅 Projections cap — année suivante (Salary cap intelligence)
    # =====================================================
    end_year = _season_end_year()
    next_end = end_year + 1

    def _cap_next_year(df_cap: pd.DataFrame) -> int:
        if df_cap is None or df_cap.empty:
            return 0
        tmp = df_cap.copy()
        if 'Salaire' not in tmp.columns:
            return 0
        tmp['Salaire'] = pd.to_numeric(tmp['Salaire'], errors='coerce').fillna(0).astype(int)
        tmp['_exp'] = tmp.get('Expiry Year','').apply(lambda x: _to_int_safe(x, default=None))
        # Keep players whose contract runs through next season end.
        tmp['_keep'] = tmp['_exp'].apply(lambda y: True if (y is None or pd.isna(y)) else int(y) >= int(next_end))
        return int(tmp.loc[tmp['_keep'], 'Salaire'].sum())

    cap_next_gc = _cap_next_year(gc_all)
    cap_next_ce = _cap_next_year(ce_all)

    p1, p2, p3, p4 = st.columns(4)
    with p1:
        st.metric('💰 Cap GC (maint.)', money(int(used_gc)))
    with p2:
        st.metric('📅 Cap GC (an prochain)', money(int(cap_next_gc)))
    with p3:
        st.metric('💰 Cap CE (maint.)', money(int(used_ce)))
    with p4:
        st.metric('📅 Cap CE (an prochain)', money(int(cap_next_ce)))

    st.write("")

    st.markdown(
        f"**Actifs** — F {_count_badge(nb_F, 12)} • D {_count_badge(nb_D, 6)} • G {_count_badge(nb_G, 2)}",
        unsafe_allow_html=True,
    )

    st.divider()

    popup_open = st.session_state.get("move_ctx") is not None
    if popup_open:
        st.caption("🔒 Sélection désactivée: un déplacement est en cours.")

    mobile_view = bool(st.session_state.get("mobile_view", False))

    def _render_gc_block():
        with st.container(border=True):
            st.markdown("### 🟢 Actifs (Grand Club)")
            if gc_actif.empty:
                st.info("Aucun joueur.")
            else:
                if not popup_open:
                    p = roster_click_list(gc_actif, proprietaire, "actifs")
                    if p:
                        set_move_ctx(proprietaire, p, "actifs"); do_rerun()
                else:
                    roster_click_list(gc_actif, proprietaire, "actifs_disabled")

    def _render_ce_block():
        with st.container(border=True):
            st.markdown("### 🔵 Mineur (Club École)")
            if ce_all.empty:
                st.info("Aucun joueur.")
            else:
                if not popup_open:
                    p = roster_click_list(ce_all, proprietaire, "min")
                    if p:
                        set_move_ctx(proprietaire, p, "min"); do_rerun()
                else:
                    roster_click_list(ce_all, proprietaire, "min_disabled")

    if mobile_view:
        _render_gc_block()
        st.divider()
        _render_ce_block()
    else:
        colA, colB = st.columns(2, gap="small")
        with colA: _render_gc_block()
        with colB: _render_ce_block()

    st.divider()

    with st.expander("🟡 Banc", expanded=True):
        if gc_banc.empty:
            st.info("Aucun joueur.")
        else:
            if not popup_open:
                p = roster_click_list(gc_banc, proprietaire, "banc")
                if p:
                    set_move_ctx(proprietaire, p, "banc"); do_rerun()
            else:
                roster_click_list(gc_banc, proprietaire, "banc_disabled")

    with st.expander("🩹 Joueurs Blessés (IR)", expanded=True):
        if injured_all.empty:
            st.info("Aucun joueur blessé.")
        else:
            if not popup_open:
                p_ir = roster_click_list(injured_all, proprietaire, "ir")
                if p_ir:
                    set_move_ctx(proprietaire, p_ir, "ir"); do_rerun()
            else:
                roster_click_list(injured_all, proprietaire, "ir_disabled")

    # open_move_dialog() est appelé globalement (une seule fois) — éviter le double rendu ici

    if st.session_state.pop("just_moved", False):
        show_status_alerts(
            total_gc=int(used_gc),
            cap_gc=int(cap_gc),
            total_ce=int(used_ce),
            cap_ce=int(cap_ce),
            ir_count=int(len(injured_all)),
            toast=True,
            context="Move appliqué",
        )



elif active_tab == "👤 Profil Joueurs NHL":
    render_player_profile_page()

elif active_tab == "🧊 GM":
    render_tab_gm()

elif active_tab == "👤 Joueurs autonomes":
    render_tab_autonomes(lock_dest_to_owner=True)

elif active_tab == "🕘 Historique":
    st.subheader("🕘 Historique des changements d’alignement")

    h = st.session_state.get("history")
    h = h.copy() if isinstance(h, pd.DataFrame) else _history_empty_df()

    if h.empty:
        st.info("Aucune entrée d’historique pour cette saison.")
        st.stop()

    h["timestamp_dt"] = h["timestamp"].apply(to_dt_local)
    h = h.sort_values("timestamp_dt", ascending=False, na_position="last")

    owners = ["Tous"] + sorted(h["proprietaire"].dropna().astype(str).str.strip().unique().tolist())
    owner_filter = st.selectbox("Filtrer par propriétaire", owners, key="hist_owner_filter")
    if owner_filter != "Tous":
        h = h[h["proprietaire"].astype(str).str.strip().eq(str(owner_filter).strip())]

    if h.empty:
        st.info("Aucune entrée pour ce propriétaire.")
        st.stop()

    h_show = h.copy()
    h_show["timestamp"] = h_show["timestamp_dt"].apply(format_date_fr)
    h_show = h_show.drop(columns=["timestamp_dt"])

    st.dataframe(h_show.head(500), use_container_width=True, hide_index=True)

elif active_tab == "⚖️ Transactions":
    st.subheader("⚖️ Transactions")
    st.caption("Construis une transaction (joueurs + choix + salaire retenu) et vois l’impact sur les masses salariales.")

    plafonds = st.session_state.get("plafonds")
    df = st.session_state.get("data")
    if df is None or df.empty or plafonds is None or plafonds.empty:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
        st.stop()

    owners = sorted(plafonds["Propriétaire"].dropna().astype(str).str.strip().unique().tolist())
    if len(owners) < 2:
        st.info("Il faut au moins 2 équipes pour bâtir une transaction.")
        st.stop()

    # ✅ Picks (choix repêchage) — signature: load_picks(season_lbl, teams)
    try:
        picks = load_picks(season, owners) if "load_picks" in globals() else {}
    except TypeError:
        # fallback si ancienne signature
        picks = load_picks(season, owners) if "load_picks" in globals() else {}
    market = load_trade_market(season) if "load_trade_market" in globals() else pd.DataFrame(columns=["season","proprietaire","joueur","is_available","updated_at"])
    def _roster(owner: str) -> pd.DataFrame:
        d = df[df["Propriétaire"].astype(str).str.strip().eq(str(owner).strip())].copy()
        d = clean_data(d)
        # on exclut IR du marché par défaut
        if "Slot" in d.columns:
            d = d[d["Slot"].astype(str).str.strip() != SLOT_IR].copy()
        return d

    def _player_label(r) -> str:
        j = str(r.get("Joueur","")).strip()
        pos = str(r.get("Pos","")).strip()
        team = str(r.get("Equipe","")).strip()
        lvl = str(r.get("Level","")).strip()
        sal = int(pd.to_numeric(r.get("Salaire",0), errors="coerce") or 0)
        flag = "🔁 " if is_on_trade_market(market, str(r.get("Propriétaire","")), j) else ""
        exp = str(r.get('Expiry Year','')).strip()
        exp_txt = exp if exp else '—'
        return f"{flag}{j} · {pos} · {team} · {lvl or '—'} · Exp {exp_txt} · {money(sal)}"

    def _owner_picks(owner: str):
        """Retourne les choix détenus par owner sous forme 'R{round} — {orig}' (rondes 1-7 seulement)."""
        out = []
        if isinstance(picks, dict) and picks:
            for orig_team, rounds in (picks or {}).items():
                if not isinstance(rounds, dict):
                    continue
                for rd, holder in rounds.items():
                    try:
                        rdi = int(rd)
                    except Exception:
                        continue
                    if rdi >= 8:  # 8e ronde non échangeable
                        continue
                    if str(holder).strip() == str(owner).strip():
                        out.append(f"R{rdi} — {orig_team}")
        return sorted(out, key=lambda x: (int(re.search(r'R(\d+)', x).group(1)), x))

    # --- Choix des 2 propriétaires côte à côte
    cA, cB = st.columns(2, vertical_alignment="top")
    with cA:
        owner_a = st.selectbox("Propriétaire A", owners, index=0, key="tx_owner_a")
    with cB:
        owner_b = st.selectbox("Propriétaire B", owners, index=1 if len(owners)>1 else 0, key="tx_owner_b")

    if owner_a == owner_b:
        st.warning("Choisis deux propriétaires différents.")
        st.stop()

    st.divider()

    # --- Options marché
    mc1, mc2 = st.columns([1, 2], vertical_alignment="center")
    with mc1:
        market_only = st.checkbox("Afficher seulement joueurs sur le marché", value=False, key="tx_market_only")
    with mc2:
        st.caption("🔁 = joueur annoncé disponible sur le marché des échanges.")

    dfa = _roster(owner_a)
    dfb = _roster(owner_b)

    # --- Sélection multi joueurs + picks
    left, right = st.columns(2, vertical_alignment="top")

    def _multiselect_players(owner: str, dfo: pd.DataFrame, side_key: str):
        if dfo.empty:
            st.info("Aucun joueur.")
            return [], {}

        # options
        rows = dfo.to_dict("records")
        opts = []
        map_lbl_to_name = {}
        for r in rows:
            j = str(r.get("Joueur","")).strip()
            if not j:
                continue
            if market_only and (not is_on_trade_market(market, owner, j)):
                continue
            lbl = _player_label(r)
            opts.append(lbl)
            map_lbl_to_name[lbl] = j

        picked_lbl = st.multiselect("Joueurs inclus", opts, key=f"tx_players_{side_key}")
        picked_names = [map_lbl_to_name[x] for x in picked_lbl if x in map_lbl_to_name]

        # retenue salaire (par joueur)
        retained = {}
        if picked_names:
            st.markdown("**Salaire retenu (optionnel)**")
            for j in picked_names:
                sal = int(pd.to_numeric(dfo.loc[dfo["Joueur"].astype(str).str.strip().eq(j), "Salaire"].iloc[0], errors="coerce") or 0)
                retained[j] = st.number_input(
                    f"Retenu sur {j}",
                    min_value=0,
                    max_value=int(sal),
                    step=50_000,
                    value=0,
                    key=f"tx_ret_{side_key}_{re.sub(r'[^a-zA-Z0-9_]', '_', j)[:40]}",
                )

        # picks
        owner_picks = _owner_picks(owner)
        picked_picks = st.multiselect("Choix de repêchage (R1–R7)", owner_picks, key=f"tx_picks_{side_key}")

        # montants retenus global (cash) — optionnel
        cash = st.number_input("Montant retenu (cash) — optionnel", min_value=0, step=50_000, value=0, key=f"tx_cash_{side_key}")

        return picked_names, {"retained": retained, "picks": picked_picks, "cash": int(cash)}

    with left:
        st.markdown(f"### {owner_a} ➜ envoie")
        a_players, a_meta = _multiselect_players(owner_a, dfa, "A")

    with right:
        st.markdown(f"### {owner_b} ➜ envoie")
        b_players, b_meta = _multiselect_players(owner_b, dfb, "B")

    st.divider()

    # --- Affichage détails (salaire, pos, level, années restantes si dispo)
    def _detail_df(owner: str, dfo: pd.DataFrame, picked_rows: list[str]) -> pd.DataFrame:
        if not picked_rows:
            return pd.DataFrame(columns=["Joueur","Pos","Equipe","Salaire","Level","Expiry Year","Marché"])
        tmp = dfo[dfo["Joueur"].astype(str).str.strip().isin([str(x).strip() for x in picked_rows])].copy()
        tmp["Salaire"] = tmp["Salaire"].apply(lambda x: money(int(pd.to_numeric(x, errors="coerce") or 0)))
        tmp["Marché"] = tmp["Joueur"].apply(lambda j: "Oui" if is_on_trade_market(market, owner, str(j)) else "Non")


        # Expiry Year (si dispo)
        if "Expiry Year" not in tmp.columns:
            tmp["Expiry Year"] = ""
        else:
            tmp["Expiry Year"] = tmp["Expiry Year"].astype(str).str.strip()

        keep = [c for c in ["Joueur","Pos","Equipe","Salaire","Level","Expiry Year","Marché"] if c in tmp.columns]
        return tmp[keep].reset_index(drop=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"#### Détails — {owner_a} envoie")
        st.dataframe(_detail_df(owner_a, dfa, a_players), use_container_width=True, hide_index=True)
    with c2:
        st.markdown(f"#### Détails — {owner_b} envoie")
        st.dataframe(_detail_df(owner_b, dfb, b_players), use_container_width=True, hide_index=True)

    # --- Résumé + Impact (approximation simple)
    def _sum_salary(dfo: pd.DataFrame, picked_rows: list[str]) -> int:
        if not picked_rows or dfo.empty:
            return 0
        m = dfo["Joueur"].astype(str).str.strip().isin([str(x).strip() for x in picked_rows])
        return int(pd.to_numeric(dfo.loc[m, "Salaire"], errors="coerce").fillna(0).sum())

    sal_a = _sum_salary(dfa, a_players)
    sal_b = _sum_salary(dfb, b_players)

    ret_a = int(sum((a_meta.get("retained") or {}).values()))
    ret_b = int(sum((b_meta.get("retained") or {}).values()))

    # Impact net (simplifié): l'équipe qui envoie garde la retenue (elle paie), l'équipe qui reçoit ajoute salaire - retenue
    # A reçoit: sal_b - ret_b ; A enlève: sal_a ; A paie: ret_a ; +cash optionnel
    # Net cap A = (sal_b - ret_b) - sal_a + ret_a + cash_A (si tu utilises cash comme pénalité)
    net_a = (sal_b - ret_b) - sal_a + ret_a + int(a_meta.get("cash",0))
    net_b = (sal_a - ret_a) - sal_b + ret_b + int(b_meta.get("cash",0))

    st.markdown("### Résumé")
    s1, s2 = st.columns(2)
    with s1:
        st.markdown(f"**{owner_a}** reçoit: {len(b_players)} joueur(s), {len(b_meta.get('picks',[]))} pick(s)")
        st.caption(f"Variation cap (approx): {money(net_a)} (positif = augmente)")
    with s2:
        st.markdown(f"**{owner_b}** reçoit: {len(a_players)} joueur(s), {len(a_meta.get('picks',[]))} pick(s)")
        st.caption(f"Variation cap (approx): {money(net_b)} (positif = augmente)")

    st.divider()

    # --- Marquer des joueurs "sur le marché" directement ici (optionnel)

    # -----------------------------
    # ✅ Soumission / Confirmation (proposition)
    #   Ajoute un bouton de confirmation lorsque des joueurs/picks sont sélectionnés
    # -----------------------------
    has_trade = bool(a_players or b_players or (a_meta.get("picks") or []) or (b_meta.get("picks") or []) or int(a_meta.get("cash",0) or 0) or int(b_meta.get("cash",0) or 0) or ret_a or ret_b)
    if has_trade:
        st.markdown("### ✅ Confirmer la transaction")
        st.caption("La transaction sera enregistrée comme **proposition** (aucun alignement n'est modifié ici).")
        confirm_tx = st.checkbox("✅ Je confirme vouloir soumettre cette transaction", value=False, key=f"tx_confirm_submit__{season}")
        cbtn1, cbtn2 = st.columns([1,1])
        with cbtn1:
            if st.button("📨 Soumettre la transaction", use_container_width=True, disabled=(not confirm_tx), key=f"tx_submit_btn__{season}"):
                if not (callable(globals().get("append_transaction"))):
                    st.error("Fonction append_transaction() manquante — impossible d'enregistrer la transaction.")
                else:
                    ts = datetime.now(TZ_TOR).strftime("%Y-%m-%d %H:%M:%S") if TZ_TOR else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    row = {
                        "trade_id": tx_next_trade_id(season),
                        "uuid": uuid.uuid4().hex,
                        "timestamp": ts,
                        "season": season,
                        "owner_a": owner_a,
                        "owner_b": owner_b,
                        "a_players": " | ".join([str(x).strip() for x in (a_players or [])]),
                        "b_players": " | ".join([str(x).strip() for x in (b_players or [])]),
                        "a_picks": " | ".join([str(x).strip() for x in (a_meta.get("picks") or [])]),
                        "b_picks": " | ".join([str(x).strip() for x in (b_meta.get("picks") or [])]),
                        "a_retained": json.dumps(a_meta.get("retained") or {}, ensure_ascii=False),
                        "b_retained": json.dumps(b_meta.get("retained") or {}, ensure_ascii=False),
                        "a_cash": int(a_meta.get("cash",0) or 0),
                        "b_cash": int(b_meta.get("cash",0) or 0),
                        "status": "En attente",
                        "approved_a": True,
                        "approved_b": False,
                        "submitted_by": str(get_selected_team() or "").strip(),
                        "approved_at_a": ts,
                        "approved_at_b": "",
                        "completed_at": "",
                    }
                    append_transaction(season, row)
                    st.toast("✅ Transaction soumise", icon="✅")
        with cbtn2:
            if st.button("🧹 Vider la sélection", use_container_width=True, key=f"tx_clear_btn__{season}"):
                # reset des widgets de sélection
                # reset des widgets de sélection (toutes variantes, incluant suffix saison)
                prefixes = ["tx_players_A","tx_players_B","tx_picks_A","tx_picks_B","tx_cash_A","tx_cash_B","tx_confirm_submit__"]
                for kk in list(st.session_state.keys()):
                    if any(str(kk).startswith(pref) for pref in prefixes):
                        try:
                            del st.session_state[kk]
                        except Exception:
                            pass
                # retenues
                for k in list(st.session_state.keys()):
                    if k.startswith("tx_ret_A_") or k.startswith("tx_ret_B_"):
                        try:
                            del st.session_state[k]
                        except Exception:
                            pass
                st.toast("🧹 Sélection vidée", icon="🧹")
                do_rerun()
        st.divider()
    st.markdown("### Marché des échanges (optionnel)")
    st.caption("Coche/décoche un joueur comme disponible. C’est purement informatif (n’applique pas la transaction).")

    mm1, mm2 = st.columns(2)
    with mm1:
        if not dfa.empty:
            opts = sorted(dfa["Joueur"].dropna().astype(str).str.strip().unique().tolist())
            cur_on = [j for j in opts if is_on_trade_market(market, owner_a, j)]
            mkey_a = f"tx_market_a__{season}"
            if mkey_a not in st.session_state:
                st.session_state[mkey_a] = cur_on
            new_on = st.multiselect(f"{owner_a} — joueurs disponibles", opts, key=mkey_a)
            # sync safe (sans default)
            market = set_owner_market(market, season, owner_a, new_on)
    with mm2:
        if not dfb.empty:
            opts = sorted(dfb["Joueur"].dropna().astype(str).str.strip().unique().tolist())
            cur_on = [j for j in opts if is_on_trade_market(market, owner_b, j)]
            mkey_b = f"tx_market_b__{season}"
            if mkey_b not in st.session_state:
                st.session_state[mkey_b] = cur_on
            new_on = st.multiselect(f"{owner_b} — joueurs disponibles", opts, key=mkey_b)
            # sync safe (sans default)
            market = set_owner_market(market, season, owner_b, new_on)

    if st.button("💾 Sauvegarder le marché", use_container_width=True, key=f"tx_market_save__{season}"):
        save_trade_market(season, market)
        st.toast("✅ Marché sauvegardé", icon="✅")
        do_rerun()





if active_tab == "🛠️ Gestion Admin":
    if not is_admin:
        st.warning("Accès admin requis.")
        st.stop()

    st.subheader("🛠️ Gestion Admin")

    # --- Drive readiness (required before Backups expander)
    cfg_drive = st.secrets.get("gdrive_oauth", {}) or {}
    folder_id = str(cfg_drive.get("folder_id", "") or "").strip()
    try:
        creds = drive_creds_from_secrets(show_error=False) if 'drive_creds_from_secrets' in globals() else None
    except Exception:
        creds = None
    drive_ok = bool(creds)

    # =====================================================
    # 🧷 Backups & Restore (Drive) — TOUT dans un seul expander
    # =====================================================
    if drive_ok and folder_id:
        with st.expander("🧷 Backups & Restore (Drive)", expanded=False):
            st.caption(
                "Ces actions travaillent **directement dans le dossier Drive** "
                "(backup rapide si l’app tombe)."
            )

            # Season label
            season_lbl = (
                str(st.session_state.get("season")
                    or st.session_state.get("season_lbl")
                    or "").strip()
                or "2025-2026"
            )

            # Fichiers critiques (inclut historique + log des backups)
            CRITICAL_FILES = [
                f"equipes_joueurs_{season_lbl}.csv",
                "hockey.players.csv",
                f"transactions_{season_lbl}.csv",
                "historique_fantrax_v2.csv",
                "rachats_v2.csv",
                "backup_history.csv",
            ]


            # Drive service (OAuth)
            drive_backups_disabled = False
            try:
                s = _drive()
            except Exception as e:
                st.error(f"❌ Impossible d'initialiser Drive — {type(e).__name__}: {e}")
                st.info("Backups indisponibles pour le moment. Réessaie plus tard.")
                s = None
                drive_backups_disabled = True


            if s is not None:
                tabs = st.tabs(["🛡️ Backup ALL", "📄 Fichiers", "🕘 Historique", "🌙 Nightly", "🔔 Alerts"])
            else:
                tabs = [st.container() for _ in range(5)]
                drive_backups_disabled = True



            # ------------------
            # 🛡️ Backup ALL
            # ------------------
            with tabs[0]:
                st.markdown("### 🛡️ Backup global")
                if st.button(
                    "🛡️ Backup ALL (vNNN + timestamp pour chaque fichier)",
                    use_container_width=True,
                    key="backup_all_global"
                ):
                    ok = 0
                    fail = 0
                    for fn in CRITICAL_FILES:
                        existing = _drive_safe_find_file(s, folder_id, fn)
                        if not existing:
                            log_backup_event(s, folder_id, {
                                "action": "backup_all",
                                "file": fn,
                                "result": "SKIP (missing)",
                                "note": "fichier absent sur Drive",
                                "by": str(get_selected_team() or "admin"),
                            })
                            continue
                        try:
                            res = _backup_copy_both(s, folder_id, fn)
                            ok += 1
                            log_backup_event(s, folder_id, {
                                "action": "backup_all",
                                "file": fn,
                                "result": "OK",
                                "v_name": res.get("v_name", ""),
                                "ts_name": res.get("ts_name", ""),
                                "by": str(get_selected_team() or "admin"),
                            })
                        except Exception as e:
                            fail += 1
                            log_backup_event(s, folder_id, {
                                "action": "backup_all",
                                "file": fn,
                                "result": f"FAIL ({type(e).__name__})",
                                "note": str(e),
                                "by": str(get_selected_team() or "admin"),
                            })

                    if fail:
                        st.warning(f"⚠️ Backup ALL terminé avec erreurs — OK: {ok} | FAIL: {fail}")
                    else:
                        st.success(f"✅ Backup ALL terminé — OK: {ok}")

            # ------------------
            # 📄 Fichiers
            # ------------------
            with tabs[1]:
                st.markdown("### 📄 Backups & Restore — fichiers")
                chosen = st.selectbox("Fichier", CRITICAL_FILES, key="backup_file_pick")
                fn = str(chosen)

                existing = _drive_safe_find_file(s, folder_id, fn)
                if existing:
                    st.caption(f"Drive: ✅ présent — id={existing.get('id','')}")
                else:
                    st.warning("Drive: ⚠️ fichier absent (tu peux l’uploader au besoin).")

                a1, a2, a3 = st.columns([1,1,2], vertical_alignment="center")
                with a1:
                    if st.button("🛡️ Backup now", key=f"bk_one__{fn}", use_container_width=True, disabled=(not existing)):
                        try:
                            res = _backup_copy_both(s, folder_id, fn)
                            st.success(f"✅ Backups créés: {res['v_name']} + {res['ts_name']}")
                            log_backup_event(s, folder_id, {
                                "action": "backup_now",
                                "file": fn,
                                "result": "OK",
                                "v_name": res.get("v_name",""),
                                "ts_name": res.get("ts_name",""),
                                "by": str(get_selected_team() or "admin"),
                            })
                        except Exception as e:
                            st.error(f"❌ Backup KO — {type(e).__name__}: {e}")

                with a2:
                    backups = _drive_list_backups(s, folder_id, fn)
                    latest = backups[0] if backups else None
                    if st.button("⏪ Restore latest", key=f"rst_latest__{fn}", use_container_width=True, disabled=(not existing or not latest)):
                        try:
                            _restore_from_backup(s, fn, latest["id"], folder_id=folder_id)
                            st.success(f"✅ Restored depuis: {latest['name']}")
                            log_backup_event(s, folder_id, {
                                "action": "restore_latest",
                                "file": fn,
                                "result": "OK",
                                "note": latest.get("name",""),
                                "by": str(get_selected_team() or "admin"),
                            })
                        except Exception as e:
                            st.error(f"❌ Restore KO — {type(e).__name__}: {e}")

                with a3:
                    st.caption("Liste/Restore spécifique et maintenance ci-dessous.")

                st.divider()
                st.markdown("#### 📚 Liste des backups")
                backups = _drive_list_backups(s, folder_id, fn)
                if not backups:
                    st.info("Aucun backup trouvé pour ce fichier.")
                else:
                    rows = []
                    for b in backups[:200]:
                        rows.append({
                            "name": b.get("name", ""),
                            "modifiedTime": b.get("modifiedTime", ""),
                            "size": b.get("size", ""),
                            "id": b.get("id", ""),
                        })
                    dfb = pd.DataFrame(rows)
                    st.dataframe(dfb.drop(columns=["id"]), use_container_width=True, hide_index=True)

                    options = {f"{r['name']}  —  {r['modifiedTime']}": r["id"] for r in rows}
                    choice = st.selectbox("Restaurer un backup spécifique", list(options.keys()), key=f"pick_one__{fn}")
                    if st.button("✅ Restore selected", key=f"rst_sel_one__{fn}", use_container_width=True):
                        try:
                            _restore_from_backup(s, fn, options[choice], folder_id=folder_id)
                            st.success(f"✅ Restored depuis: {choice.split('  —  ')[0]}")
                            log_backup_event(s, folder_id, {
                                "action": "restore_selected",
                                "file": fn,
                                "result": "OK",
                                "note": choice.split('  —  ')[0],
                                "by": str(get_selected_team() or "admin"),
                            })
                        except Exception as e:
                            st.error(f"❌ Restore KO — {type(e).__name__}: {e}")

                st.divider()
                st.markdown("#### 🧹 Maintenance backups")
                k1, k2 = st.columns(2)
                with k1:
                    keep_v = st.number_input("Garder (vNNN)", min_value=0, max_value=500, value=20, step=5, key=f"keepv_one__{fn}")
                with k2:
                    keep_ts = st.number_input("Garder (timestamp)", min_value=0, max_value=500, value=20, step=5, key=f"keepts_one__{fn}")

                confirm = st.checkbox("✅ Je confirme supprimer les anciens backups", key=f"confirm_clean_one__{fn}")
                if st.button("🧹 Nettoyer maintenant", key=f"clean_one__{fn}", use_container_width=True, disabled=(not confirm)):
                    try:
                        res = _drive_cleanup_backups(s, folder_id, fn, keep_v=int(keep_v), keep_ts=int(keep_ts))
                        st.success(
                            f"✅ Nettoyage terminé — supprimés: {res['deleted']} | restants: {res['remaining']} "
                            f"(kept v: {res['kept_v']}, kept ts: {res['kept_ts']})"
                        )
                        if res.get("delete_errors"):
                            st.warning("Certaines suppressions ont échoué:")
                            st.write("• " + "\n• ".join(res["delete_errors"]))
                    except Exception as e:
                        st.error(f"❌ Nettoyage KO — {type(e).__name__}: {e}")

            # ------------------
            # 🕘 Historique
            # ------------------
            with tabs[2]:
                st.markdown("### 🕘 Historique des backups")
                try:
                    hist = _drive_download_csv_df(s, folder_id, "backup_history.csv")
                except Exception:
                    hist = pd.DataFrame()
                if hist is None or hist.empty:
                    st.info("Aucun log encore. Fais un Backup now / Backup ALL.")
                else:
                    st.dataframe(hist.tail(500).iloc[::-1], use_container_width=True, hide_index=True)

            # ------------------
            # 🌙 Nightly
            # ------------------
            with tabs[3]:
                st.markdown("### 🌙 Nightly backup (once/day)")
                alerts_cfg = st.secrets.get("alerts", {}) or {}
                hour_mtl = int(alerts_cfg.get("nightly_hour_mtl", 3) or 3)
                st.caption(f"Exécute au plus une fois par jour après {hour_mtl}:00 (America/Montreal) via un marker Drive.")

                if st.button("🌙 Lancer maintenant (si éligible)", use_container_width=True, key="nightly_run_now"):
                    try:
                        res = nightly_backup_once_per_day(s, folder_id, CRITICAL_FILES, hour_mtl=hour_mtl)
                        st.write(res)
                        if res.get("ran") and int(res.get("fail", 0) or 0) > 0:
                            msg = f"Nightly backup: FAIL={res.get('fail')} OK={res.get('ok')} (marker {res.get('marker')})"
                            send_slack_alert(msg)
                            send_email_alert("PMS Nightly backup errors", msg)
                    except Exception as e:
                        st.error(f"❌ Nightly KO — {type(e).__name__}: {e}")

                st.info(
                    "Astuce: pour un vrai cron même si personne n’ouvre l’app, utilise GitHub Actions pour ping ton URL Streamlit chaque nuit."
                )

            # ------------------
            # 🔔 Alerts
            # ------------------
            with tabs[4]:
                # =====================================================
                # ⚙️ AUTOUPDATE_ADMIN — Auto-update (Admin) + Pinger externe
                # =====================================================
                st.markdown("#### ⚙️ Auto-update (Admin)")
                st.caption("Active/désactive une mise à jour périodique des points (cache) et envoie un ping externe optionnel.")

                # Settings in session (persist simple in Drive marker CSV)
                if 'admin_autoupdate_enabled' not in st.session_state:
                    st.session_state['admin_autoupdate_enabled'] = False
                if 'admin_autoupdate_minutes' not in st.session_state:
                    st.session_state['admin_autoupdate_minutes'] = 15

                cA1, cA2, cA3 = st.columns([1,1,1.2])
                with cA1:
                    st.session_state['admin_autoupdate_enabled'] = st.toggle("Auto-update ON/OFF", value=bool(st.session_state['admin_autoupdate_enabled']), key='admin_autoupdate_toggle')
                with cA2:
                    st.session_state['admin_autoupdate_minutes'] = st.number_input("Intervalle (minutes)", min_value=5, max_value=180, value=int(st.session_state['admin_autoupdate_minutes']), step=5, key='admin_autoupdate_minutes_in')
                with cA3:
                    if st.button("▶️ Exécuter maintenant", use_container_width=True, key='admin_autoupdate_run_now'):
                        try:
                            # met à jour points cache pour tous les owners présents
                            rules = load_scoring_rules()
                            # owners from roster data
                            df_roster = st.session_state.get('data')
                            owners = []
                            if hasattr(df_roster, 'columns') and 'Propriétaire' in df_roster.columns:
                                owners = sorted(df_roster['Propriétaire'].astype(str).str.strip().unique().tolist())
                            season_lbl = str(st.session_state.get('season') or '').strip() or saison_auto()
                            ok_ct = 0
                            for ow in owners:
                                try:
                                    # build team total points cache (actifs)
                                    _ = compute_team_points_active_only(df_roster, ow, season_lbl, rules)
                                    ok_ct += 1
                                except Exception:
                                    pass
                            st.success(f"✅ Auto-update exécuté — équipes mises à jour: {ok_ct}")
                        except Exception as e:
                            st.error(f"❌ Auto-update KO — {type(e).__name__}: {e}")

                # Run periodically within app sessions (best-effort, not a real cron)
                try:
                    if st.session_state.get('admin_autoupdate_enabled'):
                        import time
                        last = float(st.session_state.get('_admin_autoupdate_last_ts', 0.0) or 0.0)
                        interval = int(st.session_state.get('admin_autoupdate_minutes', 15) or 15) * 60
                        now = time.time()
                        if (now - last) >= interval:
                            st.session_state['_admin_autoupdate_last_ts'] = now
                            # lightweight: just refresh creds / ping external if configured
                            # (team points recalculated on-demand elsewhere)
                            try:
                                _ = drive_creds_from_secrets(show_error=False)
                            except Exception:
                                pass
                            # optional external ping
                            try:
                                pinger = st.secrets.get('pinger', {}) or {}
                                ping_url = str(pinger.get('url','') or '').strip()
                                if ping_url:
                                    import requests
                                    requests.get(ping_url, timeout=5)
                            except Exception:
                                pass
                except Exception:
                    pass

                st.markdown("#### 🩺 Pinger externe")
                st.caption("Pour garder l'app ""alive"" et recevoir un signal, configure un moniteur (UptimeRobot/BetterUptime/Healthchecks).")
                try:
                    token_need = str((st.secrets.get('pinger', {}) or {}).get('token','') or '').strip()
                except Exception:
                    token_need = ''
                base_url = ''
                try:
                    base_url = str(st.secrets.get('app_url','') or '').strip()
                except Exception:
                    base_url = ''
                if not base_url:
                    st.info("Astuce: ajoute `app_url` dans Secrets (ex: https://ton-app.streamlit.app) pour afficher l'URL de ping.")
                else:
                    ping = f"{base_url}/?ping=1" + (f"&token={token_need}" if token_need else '')
                    st.code(ping)
                st.caption("Optionnel: secrets [pinger].url = URL à pinger (healthchecks.io) et [pinger].token = protection du endpoint /?ping=1.")
                st.divider()

                st.markdown("### 🔔 Alerts (Slack / Email)")
                st.caption("Configurables via [alerts] dans Secrets.")
                cA, cB = st.columns(2)
                with cA:
                    if st.button("🔔 Test Slack", use_container_width=True, key="test_slack"):
                        ok = send_slack_alert("✅ Test Slack — PMS backups")
                        st.success("Slack OK") if ok else st.error("Slack KO")
                with cB:
                    if st.button("✉️ Test Email", use_container_width=True, key="test_email"):
                        ok = send_email_alert("PMS backups test", "✅ Test email — PMS backups")
                        st.success("Email OK") if ok else st.error("Email KO")




            # -----------------------------

    else:
        st.info("Backups Drive désactivés (Drive non prêt ou folder_id manquant).")



    # -----------------------------
    # 🗃️ Players DB (hockey.players.csv) — Admin
    #   - sert de source pour Country (drapeaux) et parfois Level/Expiry
    # -----------------------------
    with st.expander("🗃️ Players DB (hockey.players.csv)", expanded=False):
        st.caption("Source de vérité pour **Country** (drapeaux), et souvent **Level/Expiry** selon ta config.")

        # Local path (fallback)
        pdb_path = ""
        try:
            if "PLAYERS_DB_FALLBACKS" in globals() and isinstance(PLAYERS_DB_FALLBACKS, (list, tuple)):
                pdb_path = _first_existing(PLAYERS_DB_FALLBACKS)
        except Exception:
            pdb_path = ""
        if not pdb_path:
            pdb_path = os.path.join(DATA_DIR, "hockey.players.csv")

        st.caption(f"Chemin utilisé : `{pdb_path}`")

        cA, cB, cC = st.columns([1, 1, 2], vertical_alignment="center")

        with cA:
            if st.button("🔄 Recharger Players DB", use_container_width=True, key="admin_reload_players_db"):
                try:
                    mtime = os.path.getmtime(pdb_path) if os.path.exists(pdb_path) else 0.0
                    if "load_players_db" in globals() and callable(globals()["load_players_db"]) and mtime:
                        st.session_state["players_db"] = load_players_db(pdb_path, mtime)
                    else:
                        st.session_state["players_db"] = pd.read_csv(pdb_path) if os.path.exists(pdb_path) else pd.DataFrame()
                    st.success("✅ Players DB rechargée.")
                except Exception as e:
                    st.error(f"❌ Rechargement KO — {type(e).__name__}: {e}")

        with cB:
            if st.button("⬆️ Mettre à jour Players DB", use_container_width=True, key="admin_update_players_db"):
                try:
                    # Si ton app a une fonction dédiée, on la déclenche. Sinon, on garde juste le bouton.
                    if "update_players_db" in globals() and callable(globals()["update_players_db"]):
                        try:
                            update_players_db(pdb_path)
                        except TypeError:
                            update_players_db()
                        st.success("✅ Mise à jour lancée.")
                    else:
                        st.info("Aucune fonction `update_players_db()` détectée dans ton app (bouton disponible quand même).")
                except Exception as e:
                    st.error(f"❌ Update KO — {type(e).__name__}: {e}")

        with cC:
            st.caption("Astuce: pour forcer les drapeaux, remplis **Country** (CA/US/SE/FI…) dans hockey.players.csv.")


        # Aperçu rapide (PAS d'expander dans un expander -> Streamlit interdit)
        pdb = st.session_state.get("players_db")
        if isinstance(pdb, pd.DataFrame) and not pdb.empty:
            cols_show = [c for c in ["Player", "Country", "playerId"] if c in pdb.columns]
            show_preview = st.checkbox(
                "👀 Afficher un aperçu (20 lignes)",
                value=False,
                key="admin_playersdb_preview",
            )
            if show_preview:
                st.dataframe(
                    pdb[cols_show].head(20) if cols_show else pdb.head(20),
                    use_container_width=True,
                    hide_index=True,
                )
        else:
            st.warning("Players DB non chargée. Clique **Recharger Players DB**.")
        # 🧩 Outil — Joueurs sans drapeau (Country manquant)
        #   Liste les joueurs présents dans le roster actif dont le flag
        #   ne peut pas être affiché sans une valeur Country.
        #   ⚠️ Aucun appel API obligatoire ici (diagnostic + édition). Si certaines
        #      fonctions de suggestion Web/API existent dans ton app, elles seront utilisées.
        # -----------------------------
        try:
            st.markdown("### 🧩 Joueurs sans drapeau (Country manquant)")
            st.caption(
                "Affiche les joueurs du roster actif (saison sélectionnée) dont la colonne **Country** est vide dans hockey.players.csv. "
                "Remplis **Country** avec CA/US/SE/FI... pour forcer le drapeau."
            )

            if st.checkbox("🔎 Trouver les joueurs sans drapeau", value=False, key="admin_find_missing_flags"):
                try:
                    # petit fallback si _norm_name n'existe pas
                    def _nm(x: str) -> str:
                        try:
                            if "_norm_name" in globals() and callable(globals()["_norm_name"]):
                                return globals()["_norm_name"](x)
                        except Exception:
                            pass
                        s = str(x or "").strip().lower()
                        s = re.sub(r"\s+", " ", s)
                        return s

                    # 1) roster actuel
                    df_roster = st.session_state.get("data", pd.DataFrame())
                    df_roster = clean_data(df_roster) if isinstance(df_roster, pd.DataFrame) else pd.DataFrame()
                    if df_roster.empty or "Joueur" not in df_roster.columns:
                        st.info("Aucun roster chargé pour cette saison. Va dans Admin → Import Fantrax.")
                    else:
                        roster_players = (
                            df_roster[[c for c in ["Joueur", "Equipe", "Propriétaire", "Statut", "Slot"] if c in df_roster.columns]]
                            .dropna(subset=["Joueur"])
                            .copy()
                        )
                        roster_players["Joueur"] = roster_players["Joueur"].astype(str).str.strip()
                        roster_players = roster_players[roster_players["Joueur"].astype(str).str.len() > 0]
                        uniq = roster_players.drop_duplicates(subset=["Joueur"]).copy()

                        # 2) players DB
                        pdb = st.session_state.get("players_db")
                        if not isinstance(pdb, pd.DataFrame) or pdb.empty:
                            pdb_path = _first_existing(PLAYERS_DB_FALLBACKS) if "PLAYERS_DB_FALLBACKS" in globals() else ""
                            if not pdb_path:
                                pdb_path = os.path.join(DATA_DIR, "hockey.players.csv")
                            mtime = os.path.getmtime(pdb_path) if (pdb_path and os.path.exists(pdb_path)) else 0.0
                            pdb = load_players_db(pdb_path, mtime) if mtime else pd.DataFrame()

                        if pdb.empty or "Player" not in pdb.columns:
                            st.warning("Players DB introuvable ou invalide. Lance d'abord Admin → Mettre à jour Players DB.")
                        else:
                            pdb2 = pdb.copy()
                            if "Country" not in pdb2.columns:
                                pdb2["Country"] = ""
                            pdb2["_k"] = pdb2["Player"].astype(str).apply(_nm)
                            name_to_country = dict(zip(pdb2["_k"], pdb2["Country"].astype(str)))
                            name_to_pid = dict(zip(pdb2["_k"], pdb2.get("playerId", pd.Series(dtype=object)).astype(str)))

                            uniq["_k"] = uniq["Joueur"].astype(str).apply(_nm)
                            uniq["Country"] = uniq["_k"].map(name_to_country).fillna("")
                            uniq["playerId"] = uniq["_k"].map(name_to_pid).fillna("")
                            missing = uniq[uniq["Country"].astype(str).str.strip().eq("")].copy()

                            cols = [c for c in ["Joueur", "Equipe", "Propriétaire", "Statut", "Slot", "playerId"] if c in missing.columns]
                            missing_show = missing[cols].copy()
                            if "Joueur" in missing_show.columns:
                                missing_show = missing_show.sort_values(by=["Joueur"]).reset_index(drop=True)

                            if missing_show.empty:
                                st.success("✅ Aucun joueur du roster actif n'a Country manquant (drapeaux OK).")
                            else:
                                st.warning(
                                    f"⚠️ {len(missing_show)} joueur(s) du roster actif n'ont pas Country. "
                                    "Tu peux le remplir ici (inline) ou dans hockey.players.csv."
                                )

                                # Suggestions optionnelles (si tes helpers existent)
                                use_suggest = bool("suggest_country_web" in globals() and callable(globals()["suggest_country_web"]))
                                if use_suggest:
                                    st.caption("Bouton optionnel: suggestions via Web/API (selon les helpers présents dans l’app).")

                                editor = missing_show.copy()
                                editor["Country"] = ""

                                st.caption("✏️ Édite la colonne **Country** (ex: CA, US, SE, FI).")
                                editor_view = st.data_editor(
                                    editor,
                                    use_container_width=True,
                                    hide_index=True,
                                    num_rows="fixed",
                                    column_config={
                                        "Country": st.column_config.TextColumn(
                                            "Country",
                                            help="ISO2 (CA/US/SE/FI) ou ISO3 (CAN/USA/SWE) ou nom du pays.",
                                            max_chars=24,
                                        )
                                    },
                                    disabled=[c for c in editor.columns if c != "Country"],
                                    key=f"admin_missing_flags_editor__{season_pick}",
                                )

                                c_apply, c_export = st.columns([1, 1])
                                with c_apply:
                                    if st.button("💾 Appliquer Country", use_container_width=True, key=f"admin_apply_country__{season_pick}"):
                                        try:
                                            pdb_path = _first_existing(PLAYERS_DB_FALLBACKS) if "PLAYERS_DB_FALLBACKS" in globals() else ""
                                            if not pdb_path:
                                                pdb_path = os.path.join(DATA_DIR, "hockey.players.csv")

                                            pdb_df = pd.read_csv(pdb_path) if os.path.exists(pdb_path) else pd.DataFrame()
                                            if pdb_df.empty:
                                                pdb_df = pd.DataFrame(columns=["Player", "Country", "playerId"])

                                            if "Player" not in pdb_df.columns:
                                                pdb_df["Player"] = ""
                                            if "Country" not in pdb_df.columns:
                                                pdb_df["Country"] = ""

                                            pdb_df["_k"] = pdb_df["Player"].astype(str).apply(_nm)
                                            idx_by_k = {k: i for i, k in enumerate(pdb_df["_k"].tolist())}

                                            applied = 0
                                            for row in editor_view.to_dict(orient="records"):
                                                name = str(row.get("Joueur", "") or "").strip()
                                                ctry = str(row.get("Country", "") or "").strip()
                                                if not name or not ctry:
                                                    continue
                                                k = _nm(name)
                                                if k in idx_by_k:
                                                    i2 = idx_by_k[k]
                                                    cur = str(pdb_df.at[i2, "Country"] or "").strip()
                                                    if not cur:
                                                        pdb_df.at[i2, "Country"] = ctry
                                                        applied += 1
                                                else:
                                                    pdb_df = pd.concat([
                                                        pdb_df,
                                                        pd.DataFrame([{ "Player": name, "Country": ctry }])
                                                    ], ignore_index=True)
                                                    applied += 1

                                            pdb_df = pdb_df.drop(columns=["_k"], errors="ignore")
                                            pdb_df.to_csv(pdb_path, index=False)

                                            # refresh cached players_db
                                            try:
                                                try:
                                                    st.cache_data.clear()
                                                except Exception:
                                                    pass
                                                mtime = os.path.getmtime(pdb_path) if os.path.exists(pdb_path) else 0.0
                                                st.session_state["players_db"] = load_players_db(pdb_path, mtime)
                                            except Exception:
                                                pass

                                            st.success(f"✅ Country appliqué pour {applied} joueur(s).")
                                            do_rerun()
                                        except Exception as _e:
                                            st.error(f"Erreur écriture hockey.players.csv: {type(_e).__name__}: {_e}")

                                with c_export:
                                    try:
                                        csv_bytes = editor_view.to_csv(index=False).encode("utf-8")
                                        st.download_button(
                                            "📤 Export CSV",
                                            data=csv_bytes,
                                            file_name=f"joueurs_sans_drapeau_{season_pick}.csv",
                                            mime="text/csv",
                                            use_container_width=True,
                                            key=f"admin_export_missing_flags__{season_pick}",
                                        )
                                    except Exception:
                                        pass

                                st.caption("Astuce: tu peux aussi éditer directement hockey.players.csv. Valeurs acceptées: CA/US/SE/FI…")
                except Exception as e:
                    st.error(f"Erreur diagnostic drapeaux: {type(e).__name__}: {e}")

            st.divider()
        except Exception as e:
            st.error(f"Erreur outil drapeaux: {type(e).__name__}: {e}")


    # -----------------------------
    # 📥 Importation CSV Fantrax (Admin)
    # -----------------------------
    manifest = load_init_manifest() or {}
    if "fantrax_by_team" not in manifest:
        manifest["fantrax_by_team"] = {}

    teams = sorted(list(LOGOS.keys())) or ["Whalers"]
    default_owner = str(get_selected_team() or "").strip() or teams[0]
    if default_owner not in teams:
        default_owner = teams[0]

    chosen_owner = st.selectbox(
        "Importer l'alignement dans quelle équipe ?",
        teams,
        index=teams.index(default_owner),
        key="admin_import_team_pick",
    )

    clear_team_before = st.checkbox(
        f"Vider l’alignement de {chosen_owner} avant import",
        value=True,
        help="Recommandé si tu réimportes la même équipe.",
        key="admin_clear_team_before",
    )

    u_nonce = int(st.session_state.get("uploader_nonce", 0))
    c_init1, c_init2 = st.columns(2)
    with c_init1:
        init_align = st.file_uploader(
            "CSV — Alignement (Fantrax)",
            type=["csv", "txt"],
            key=f"admin_import_align__{season_pick}__{chosen_owner}__{u_nonce}",
        )
    with c_init2:
        init_hist = st.file_uploader(
            "CSV — Historique (optionnel)",
            type=["csv", "txt"],
            key=f"admin_import_hist__{season_pick}__{chosen_owner}__{u_nonce}",
        )

    c_btn1, c_btn2 = st.columns([1, 1])

    with c_btn1:
        if st.button("👀 Prévisualiser", use_container_width=True, key="admin_preview_import"):
            if init_align is None:
                st.warning("Choisis un fichier CSV alignement avant de prévisualiser.")
            else:
                try:
                    buf = io.BytesIO(init_align.getbuffer())
                    buf.name = getattr(init_align, "name", "alignement.csv")
                    df_import = parse_fantrax(buf)
                    df_import = ensure_owner_column(df_import, fallback_owner=chosen_owner)
                    df_import["Propriétaire"] = str(chosen_owner).strip()
                    df_import = clean_data(df_import)
                    df_import = force_level_from_players(df_import)  # ✅ remplit Level (STD/ELC)

                    st.session_state["init_preview_df"] = df_import
                    st.session_state["init_preview_owner"] = str(chosen_owner).strip()
                    st.session_state["init_preview_filename"] = getattr(init_align, "name", "")
                    st.success(f"✅ Preview prête — {len(df_import)} joueur(s) pour **{chosen_owner}**.")
                except Exception as e:
                    st.error(f"❌ Preview échouée : {type(e).__name__}: {e}")

    preview_df = st.session_state.get("init_preview_df")
    if isinstance(preview_df, pd.DataFrame) and not preview_df.empty:
        with st.expander("🔎 Aperçu (20 premières lignes)", expanded=True):
            st.dataframe(preview_df.head(20), use_container_width=True)

    with c_btn2:
        disabled_confirm = not (isinstance(preview_df, pd.DataFrame) and not preview_df.empty)
        if st.button("✅ Confirmer l'import", use_container_width=True, disabled=disabled_confirm, key="admin_confirm_import"):
            df_team = st.session_state.get("init_preview_df")
            owner_final = str(st.session_state.get("init_preview_owner", chosen_owner) or "").strip()
            filename_final = st.session_state.get("init_preview_filename", "") or (getattr(init_align, "name", "") if init_align else "")

            df_cur = clean_data(st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS)))

            df_team = clean_data(df_team.copy())
            df_team["Propriétaire"] = owner_final
            df_team = clean_data(df_team)

            if clear_team_before:
                keep = df_cur[df_cur["Propriétaire"].astype(str).str.strip() != owner_final].copy()
                df_new = pd.concat([keep, df_team], ignore_index=True)
            else:
                df_new = pd.concat([df_cur, df_team], ignore_index=True)

            if {"Propriétaire", "Joueur"}.issubset(df_new.columns):
                df_new["Propriétaire"] = df_new["Propriétaire"].astype(str).str.strip()
                df_new["Joueur"] = df_new["Joueur"].astype(str).str.strip()
                df_new = df_new.drop_duplicates(subset=["Propriétaire", "Joueur"], keep="last")

            df_new = clean_data(df_new)
            st.session_state["data"] = df_new
            persist_data(df_new, season_pick)

            st.session_state["plafonds"] = rebuild_plafonds(df_new)

            st.session_state["selected_team"] = owner_final
            st.session_state["align_owner"] = owner_final
            clear_move_ctx()

            manifest["fantrax_by_team"][owner_final] = {
                "uploaded_name": filename_final,
                "season": season_pick,
                "saved_at": datetime.now(TZ_TOR).isoformat(timespec="seconds"),
                "team": owner_final,
            }
            save_init_manifest(manifest)

            if init_hist is not None:
                try:
                    h0 = pd.read_csv(io.BytesIO(init_hist.getbuffer()))
                    if "Propriétaire" in h0.columns and "proprietaire" not in h0.columns:
                        h0["proprietaire"] = h0["Propriétaire"]
                    if "Joueur" in h0.columns and "joueur" not in h0.columns:
                        h0["joueur"] = h0["Joueur"]
                    for c in _history_expected_cols():
                        if c not in h0.columns:
                            h0[c] = ""
                    h0 = h0[_history_expected_cols()].copy()
                    st.session_state["history"] = h0
                    persist_history(h0, season_pick)
                except Exception as e:
                    st.warning(f"⚠️ Historique initial non chargé : {type(e).__name__}: {e}")

            st.session_state["uploader_nonce"] = int(st.session_state.get("uploader_nonce", 0)) + 1
            st.session_state.pop("init_preview_df", None)
            st.session_state.pop("init_preview_owner", None)
            st.session_state.pop("init_preview_filename", None)

            st.success(f"✅ Import OK — seule l’équipe **{owner_final}** a été mise à jour.")
            do_rerun()

    st.divider()
    st.markdown("### 📌 Derniers imports par équipe")

    by_team = manifest.get("fantrax_by_team", {}) or {}
    if not by_team:
        st.caption("— Aucun import enregistré —")
    else:
        if "admin_imports_desc" not in st.session_state:
            st.session_state["admin_imports_desc"] = True

        c1, c2, _ = st.columns([0.12, 1, 3], vertical_alignment="center")
        with c1:
            icon = "⬇️" if st.session_state["admin_imports_desc"] else "⬆️"
            if st.button(icon, key="admin_imports_sort_btn", help="Changer l'ordre de tri"):
                st.session_state["admin_imports_desc"] = not st.session_state["admin_imports_desc"]
                do_rerun()
        with c2:
            st.caption("Tri par date")

        rows = []
        for team, info in by_team.items():
            rows.append({
                "Équipe": str(team).strip(),
                "Fichier": str(info.get("uploaded_name", "") or "").strip(),
                "Date": str(info.get("saved_at", "") or "").strip(),
            })

        df_imports = pd.DataFrame(rows)
        df_imports["_dt"] = df_imports["Date"].apply(to_dt_local)

        df_imports = df_imports.sort_values(
            by="_dt",
            ascending=(not st.session_state["admin_imports_desc"]),
            na_position="last",
        )

        df_imports["Date"] = df_imports["_dt"].apply(format_date_fr)
        df_imports = df_imports.drop(columns=["_dt"]).reset_index(drop=True)

        st.dataframe(df_imports, use_container_width=True, hide_index=True)

    # -----------------------------
    # 💰 Plafonds (édition admin)
    # -----------------------------
    with st.expander("💰 Plafonds (Admin)", expanded=False):
        locked = bool(st.session_state.get("LOCKED", False))
        if locked:
            st.warning("🔒 Saison verrouillée : les plafonds sont bloqués pour cette saison.")

        st.caption("Modifie les plafonds de masse salariale. Les changements s’appliquent immédiatement.")
        st.session_state["PLAFOND_GC"] = st.number_input(
            "Plafond Grand Club",
            value=int(st.session_state.get("PLAFOND_GC", 95_500_000) or 0),
            step=500_000,
            key="admin_plafond_gc",
            disabled=locked,
        )
        st.session_state["PLAFOND_CE"] = st.number_input(
            "Plafond Club École",
            value=int(st.session_state.get("PLAFOND_CE", 47_750_000) or 0),
            step=250_000,
            key="admin_plafond_ce",
            disabled=locked,
        )

    # -----------------------------
    # ➕ Ajout de joueurs (Admin)
    #   - liste déroulante Équipe (destination)
    #   - puis même UI que Joueurs autonomes
    # -----------------------------
    with st.expander("➕ Ajout de joueurs (Admin)", expanded=False):
        teams_add = sorted(list(LOGOS.keys())) if 'LOGOS' in globals() else []
        if not teams_add:
            teams_add = [str(get_selected_team() or 'Whalers').strip() or 'Whalers']
        cur_sel = str(get_selected_team() or '').strip() or teams_add[0]
        if cur_sel not in teams_add:
            cur_sel = teams_add[0]

        dest_team = st.selectbox("Équipe (destination)", teams_add, index=teams_add.index(cur_sel), key='admin_addplayer_team')
        # On force le contexte d'équipe pour que l'ajout s'applique au bon owner
        if dest_team and dest_team != str(get_selected_team() or '').strip():
            try:
                pick_team(dest_team)
            except Exception:
                st.session_state['selected_team'] = dest_team
                st.session_state['align_owner'] = dest_team

        # -----------------------------------------------------
        # ✅ Ajout rapide (Admin) — rechercher un joueur et l'ajouter à l'équipe choisie
        #   (simple & idiotproof: 1 recherche -> 1 joueur -> confirmer)
        # -----------------------------------------------------
        st.markdown("#### ➕ Ajouter un joueur à une équipe")

        # Source: Players DB (hockey.players.csv)
        pdb = st.session_state.get("players_db")
        if not isinstance(pdb, pd.DataFrame) or pdb.empty:
            try:
                pdb_path = _first_existing(PLAYERS_DB_FALLBACKS) if "PLAYERS_DB_FALLBACKS" in globals() else ""
                if not pdb_path:
                    pdb_path = os.path.join(DATA_DIR, "hockey.players.csv")
                mtime = os.path.getmtime(pdb_path) if os.path.exists(pdb_path) else 0.0
                pdb = load_players_db(pdb_path, mtime) if mtime else pd.DataFrame()
                st.session_state["players_db"] = pdb
            except Exception:
                pdb = pd.DataFrame()

        if pdb is None or pdb.empty or ("Player" not in pdb.columns and "Joueur" not in pdb.columns):
            st.info("Players DB indisponible. Va dans **Players DB** → **Mettre à jour Players DB**.")
        else:
            col_name = "Player" if "Player" in pdb.columns else "Joueur"
            q = st.text_input("Rechercher un joueur", value="", key="admin_addplayer_search")
            qn = _norm_name(q) if "_norm_name" in globals() else str(q or "").strip().lower()

            # candidates
            cand_df = pdb.copy()
            cand_df[col_name] = cand_df[col_name].astype(str)
            if qn:
                cand_df = cand_df[cand_df[col_name].str.lower().str.contains(str(q).strip().lower(), na=False)]
            cand = cand_df[col_name].dropna().astype(str).str.strip().unique().tolist()
            cand = [x for x in cand if x]
            cand = cand[:50]

            if not cand:
                st.caption("Aucun joueur trouvé (essaie un autre nom).")
            else:
                pick = st.selectbox("Joueur", cand, key="admin_addplayer_pick")
                cA, cB, cC = st.columns([1, 1, 1])
                with cA:
                    statut = st.selectbox("Statut", ["Actif", "Banc", "Mineur", "Blessé (IR)"], index=0, key="admin_addplayer_statut")
                with cB:
                    note = st.text_input("Note (optionnel)", value="", key="admin_addplayer_note")
                with cC:
                    confirm = st.button("✅ Confirmer l'ajout", use_container_width=True, key="admin_addplayer_confirm")

                if confirm:
                    try:
                        # roster current
                        df_cur = st.session_state.get("data", pd.DataFrame())
                        df_cur = clean_data(df_cur) if isinstance(df_cur, pd.DataFrame) else pd.DataFrame(columns=REQUIRED_COLS)
                        for c in REQUIRED_COLS:
                            if c not in df_cur.columns:
                                df_cur[c] = ""

                        # enrich from Players DB
                        rowp = cand_df[cand_df[col_name].astype(str).str.strip().eq(str(pick).strip())].head(1)
                        team_abbr = ""
                        pos = ""
                        cap = ""
                        lvl = ""
                        pid = ""
                        if not rowp.empty:
                            r0 = rowp.iloc[0].to_dict()
                            team_abbr = str(r0.get("Team") or r0.get("Team Abbr") or r0.get("NHL Team") or "").strip()
                            pos = str(r0.get("Pos") or r0.get("Position") or r0.get("position") or "").strip()
                            cap = str(r0.get("Cap Hit") or r0.get("CapHit") or r0.get("cap_hit") or r0.get("Salary") or "").strip()
                            lvl = str(r0.get("Level") or "").strip()
                            pid = str(r0.get("playerId") or r0.get("player_id") or "").strip()

                        # map statut -> Slot/Statut app
                        statut_norm = statut
                        if "bless" in statut.lower():
                            slot = "IR"
                        elif "mine" in statut.lower():
                            slot = "Mineur"
                        elif "banc" in statut.lower():
                            slot = "Banc"
                        else:
                            slot = "Actif"

                        new_row = {c: "" for c in REQUIRED_COLS}
                        new_row.update({
                            "Propriétaire": str(dest_team).strip(),
                            "Joueur": str(pick).strip(),
                            "Equipe": team_abbr,
                            "Statut": statut_norm,
                            "Slot": slot,
                        })
                        if "Position" in new_row:
                            new_row["Position"] = pos
                        if "Pos" in df_cur.columns:
                            new_row["Pos"] = pos
                        if "Cap Hit" in df_cur.columns:
                            new_row["Cap Hit"] = cap
                        if "Level" in df_cur.columns and lvl:
                            new_row["Level"] = lvl
                        if "playerId" in df_cur.columns and pid:
                            new_row["playerId"] = pid
                        if "Note" in df_cur.columns and note:
                            new_row["Note"] = note

                        df_new = pd.concat([df_cur, pd.DataFrame([new_row])], ignore_index=True)
                        df_new["Propriétaire"] = df_new["Propriétaire"].astype(str).str.strip()
                        df_new["Joueur"] = df_new["Joueur"].astype(str).str.strip()
                        df_new = df_new.drop_duplicates(subset=["Propriétaire", "Joueur"], keep="last")
                        df_new = clean_data(df_new)

                        st.session_state["data"] = df_new
                        season_pick = str(st.session_state.get("season") or st.session_state.get("season_lbl") or saison_auto()).strip() or "2025-2026"
                        persist_data(df_new, season_pick)
                        st.session_state["plafonds"] = rebuild_plafonds(df_new)

                        st.success(f"✅ {pick} ajouté à {dest_team} ({statut}).")
                        do_rerun()
                    except Exception as e:
                        st.error(f"❌ Ajout KO — {type(e).__name__}: {e}")

        st.divider()

        # -----------------------------------------------------
        # UI complète (joueurs autonomes / logique existante)
        # -----------------------------------------------------
        render_tab_autonomes(show_header=False)


    # -----------------------------------------------------
    # ♻️ Classement — forcer recalcul API
    # -----------------------------------------------------
    st.markdown("### ♻️ Classement — Recalcul points API")
    st.caption("Vide les caches du classement / points API (utile si tu veux forcer un refresh manuel).")
    if st.button("♻️ Rafraîchir points API (Classement)", use_container_width=True, key="admin_refresh_points_api"):
        try:
            st.session_state["classement_cache"] = {}
        except Exception:
            pass
        try:
            st.cache_data.clear()
        except Exception:
            pass
        st.session_state["classement_force_refresh"] = True
        st.toast("✅ Caches vidés — le classement va recalculer", icon="✅")
        do_rerun()

    # =====================================================

    # =====================================================
    # 🌐 NHL (API gratuite) — Auto-mapping IDs joueurs
    #   ✅ Remplace complètement API payante
    # =====================================================
    with st.expander("🌐 NHL (API gratuite) — Auto-mapping IDs joueurs", expanded=False):
        st.caption(
            "Récupère les rosters via l’API publique NHL (sans clé) et auto-map des IDs dans data/hockey.players.csv. "
            "Pratique pour enrichir ton Players DB sans clé payante."
        )

        import re
        import unicodedata
        from difflib import SequenceMatcher

        NHL_BASE = "https://api-web.nhle.com"

        def _strip_accents(s: str) -> str:
            return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))

        def _norm_name(s: str) -> str:
            s = _strip_accents(str(s or "")).lower().strip()
            s = s.replace(".", " ")
            s = re.sub(r"[^a-z\s\-\']", " ", s)
            s = re.sub(r"\s+", " ", s).strip()
            return s

        def _ratio(a: str, b: str) -> float:
            if not a or not b:
                return 0.0
            return SequenceMatcher(None, a, b).ratio()

        @st.cache_data(show_spinner=False, ttl=24 * 3600)
        def nhl_get_teams():
            """Retourne la liste des équipes NHL (triCode + noms) via l’API publique.

            ⚠️ /v1/teams retourne parfois 404. On utilise donc /v1/standings/now (fiable)
            pour obtenir les équipes actives.
            """
            teams: list[dict] = []

            # 1) Source principale: standings/now
            try:
                url = f"{NHL_BASE}/v1/standings/now"
                r = requests.get(url, timeout=20)
                r.raise_for_status()
                j = r.json()

                # Structure typique: {"standings": [ {"teamAbbrev": {"default": "TOR"}, "teamName": {"default": "Maple Leafs"}, ...}, ... ]}
                rows = None
                if isinstance(j, dict):
                    rows = j.get("standings")
                if isinstance(rows, list):
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        ab = row.get("teamAbbrev")
                        name = row.get("teamName")

                        tri = ""
                        if isinstance(ab, dict):
                            tri = str(ab.get("default") or ab.get("fr") or "").strip()
                        else:
                            tri = str(ab or "").strip()

                        nm = ""
                        if isinstance(name, dict):
                            nm = str(name.get("default") or name.get("fr") or "").strip()
                        else:
                            nm = str(name or "").strip()

                        if tri:
                            teams.append({"triCode": tri.upper(), "name": nm or tri.upper()})
            except Exception:
                teams = []

            # 2) Fallback: liste hardcodée (au cas où NHL change la réponse)
            if not teams:
                fallback_tris = [
                    "ANA","BOS","BUF","CGY","CAR","CHI","COL","CBJ","DAL","DET","EDM","FLA","LAK","MIN","MTL","NJD",
                    "NSH","NYI","NYR","OTT","PHI","PIT","SEA","SJS","STL","TBL","TOR","UTA","VAN","VGK","WSH","WPG",
                ]
                teams = [{"triCode": t, "name": t} for t in fallback_tris]

            # dédupe
            seen = set()
            uniq = []
            for t in teams:
                tri = str(t.get("triCode") or "").strip().upper()
                if not tri or tri in seen:
                    continue
                seen.add(tri)
                uniq.append({"triCode": tri, "name": str(t.get("name") or tri).strip() or tri})
            return uniq

        def _nhl_get_json_with_retry(url: str, *, session: requests.Session | None = None, timeout: int = 20,
                                     max_tries: int = 6, base_sleep: float = 0.6):
            """GET JSON avec retry/backoff (gère 429 Too Many Requests).

            NHL api-web peut rate-limit (429), surtout sur Streamlit Cloud (IP partagée).
            On respecte Retry-After si présent, sinon backoff exponentiel.
            """
            import time
            s = session or requests.Session()
            last_exc = None
            for attempt in range(1, max_tries + 1):
                try:
                    r = s.get(url, timeout=timeout)
                    if r.status_code == 429:
                        ra = r.headers.get("Retry-After")
                        try:
                            wait = float(ra) if ra else 0.0
                        except Exception:
                            wait = 0.0
                        if wait <= 0:
                            wait = base_sleep * (2 ** (attempt - 1))
                        time.sleep(min(wait, 20.0))
                        continue
                    r.raise_for_status()
                    return r.json()
                except Exception as e:
                    last_exc = e
                    # Backoff léger sur erreurs transitoires
                    time.sleep(min(base_sleep * (2 ** (attempt - 1)), 10.0))
            raise last_exc or RuntimeError("NHL API request failed")

        def nhl_get_roster(tri_code: str, season: str, *, session: requests.Session | None = None):
            """Roster d’une équipe pour une saison: /v1/roster/{TEAM}/{SEASON}.

            ⚠️ Pas en cache ici: on veut gérer correctement le rate limit (429)
            et pouvoir throttler l’exécution.
            """
            tri_code = str(tri_code or "").strip().upper()
            season = str(season or "").strip()
            url = f"{NHL_BASE}/v1/roster/{tri_code}/{season}"
            return _nhl_get_json_with_retry(url, session=session)

        def extract_players_from_roster(roster_json: dict, tri_code: str):
            out = []
            if not isinstance(roster_json, dict):
                return out

            # Sections typiques
            for group_key in ["forwards", "defensemen", "goalies"]:
                grp = roster_json.get(group_key)
                if not isinstance(grp, list):
                    continue
                for p in grp:
                    if not isinstance(p, dict):
                        continue
                    pid = p.get("id")
                    first = p.get("firstName")
                    last = p.get("lastName")
                    # parfois firstName/lastName sont dicts multi-lang
                    if isinstance(first, dict):
                        first = first.get("default") or first.get("fr") or next(iter(first.values()), "")
                    if isinstance(last, dict):
                        last = last.get("default") or last.get("fr") or next(iter(last.values()), "")
                    full = " ".join([str(first or "").strip(), str(last or "").strip()]).strip()
                    if pid and full:
                        out.append({
                            "nhl_player_id": int(pid),
                            "player_name": full,
                            "team": tri_code,
                        })
            return out

        # --- UI
        today = datetime.now(MTL_TZ).date() if "MTL_TZ" in globals() else date.today()
        default_season = f"{today.year}{today.year+1}" if today.month >= 7 else f"{today.year-1}{today.year}"

        season = st.text_input(
            "Saison (format NHL: 20252026)",
            value=default_season,
            help="Format attendu par l’API NHL: 8 chiffres, ex: 20252026",
            key="nhl_free_season",
        )

        colA, colB, colC = st.columns([1, 1, 1])
        with colA:
            fetch_btn = st.button("📥 Charger rosters NHL", use_container_width=True, key="nhl_free_fetch")
        with colB:
            cutoff = st.slider("Seuil fuzzy (plus haut = plus strict)", 0.80, 0.99, 0.92, 0.01, key="nhl_free_cutoff")
        with colC:
            max_teams = st.slider("Max équipes par run", 5, 32, 12, 1, key="nhl_free_max_teams",
                                  help="Évite les 429 (rate limit). Re-clique pour compléter si besoin.")

        roster_df = st.session_state.get("nhl_free_roster_df")

        if fetch_btn:
            try:
                teams = nhl_get_teams()
                if not teams:
                    st.error("Aucune équipe trouvée via /v1/teams.")
                else:
                    all_players = []
                    # limiter le volume de requêtes pour éviter 429
                    teams_run = teams[: int(max_teams or 12)]
                    import time
                    sess = requests.Session()
                    prog = st.progress(0)
                    for i, t in enumerate(teams_run, start=1):
                        tri = t["triCode"]
                        # throttle + retry/backoff inside nhl_get_roster
                        j = nhl_get_roster(tri, season, session=sess)
                        all_players.extend(extract_players_from_roster(j, tri))
                        prog.progress(int(i / max(1, len(teams_run)) * 100))
                        time.sleep(0.45)  # throttle doux (IP partagée Streamlit Cloud)
                    prog.empty()

                    roster_df = pd.DataFrame(all_players)
                    if roster_df.empty:
                        st.warning("Rosters chargés, mais 0 joueur trouvé. Vérifie le format de saison.")
                    else:
                        roster_df = roster_df.drop_duplicates(subset=["nhl_player_id"])
                        st.session_state["nhl_free_roster_df"] = roster_df
                        st.success(
                            f"✅ Rosters: {roster_df['team'].nunique()} équipes | {len(roster_df)} joueurs uniques "
                            f"(run: {len(teams_run)}/{len(teams)} équipes — re-clique pour compléter)"
                        )
            except Exception as e:
                st.error(f"❌ NHL API KO — {type(e).__name__}: {e}")

        if isinstance(roster_df, pd.DataFrame) and not roster_df.empty:
            st.dataframe(roster_df.head(200), use_container_width=True, hide_index=True)

            # -----------------------------
            # Auto-mapping -> hockey.players.csv
            # -----------------------------
            st.markdown("### 🔗 Auto-mapping vers data/hockey.players.csv")

            def _detect_name_col(df: pd.DataFrame) -> str:
                for c in ["Player", "Joueur", "Nom", "Name", "player_name"]:
                    if c in df.columns:
                        return c
                return ""

            data_dir = globals().get("DATA_DIR") or "data"
            players_path = os.path.join(str(data_dir), "hockey.players.csv")

            st.caption(f"Fichier cible: {players_path}")

            if st.button("🧠 Auto-mapper NHL IDs dans hockey.players.csv", use_container_width=True, key="nhl_free_map"):
                try:
                    if not os.path.exists(players_path):
                        st.error("hockey.players.csv introuvable.")
                    else:
                        pdb = pd.read_csv(players_path)
                        nmcol = _detect_name_col(pdb)
                        if not nmcol:
                            st.error("Aucune colonne nom joueur trouvée (Player/Joueur/Nom/Name).")
                        else:
                            if "nhl_player_id" not in pdb.columns:
                                pdb["nhl_player_id"] = ""

                            # index rosters
                            roster_df2 = roster_df.copy()
                            roster_df2["_k"] = roster_df2["player_name"].map(_norm_name)
                            key_to_id = dict(zip(roster_df2["_k"], roster_df2["nhl_player_id"]))
                            roster_keys = list(key_to_id.keys())

                            filled_exact = 0
                            filled_fuzzy = 0
                            misses = 0

                            for i, row in pdb.iterrows():
                                cur = str(row.get("nhl_player_id", "")).strip()
                                if cur:
                                    continue
                                raw = str(row.get(nmcol, "")).strip()
                                if not raw:
                                    continue
                                k = _norm_name(raw)
                                if not k:
                                    continue

                                # exact
                                if k in key_to_id:
                                    pdb.at[i, "nhl_player_id"] = int(key_to_id[k])
                                    filled_exact += 1
                                    continue

                                # fuzzy
                                best_k = ""
                                best_s = 0.0
                                for rk in roster_keys:
                                    s = _ratio(k, rk)
                                    if s > best_s:
                                        best_s = s
                                        best_k = rk
                                if best_k and best_s >= float(cutoff):
                                    pdb.at[i, "nhl_player_id"] = int(key_to_id[best_k])
                                    filled_fuzzy += 1
                                else:
                                    misses += 1

                            pdb.to_csv(players_path, index=False)
                            st.success(
                                f"✅ Auto-mapping terminé — Exact: {filled_exact} | Fuzzy: {filled_fuzzy} | Non trouvés: {misses}"
                            )
                            try:
                                st.cache_data.clear()
                            except Exception:
                                pass

                            st.download_button(
                                "⬇️ Télécharger hockey.players.csv (mis à jour)",
                                data=pdb.to_csv(index=False).encode("utf-8"),
                                file_name="hockey.players.csv",
                                mime="text/csv",
                                use_container_width=True,
                                key="nhl_free_dl",
                            )

                except Exception as e:
                    st.error(f"❌ Auto-mapping KO — {type(e).__name__}: {e}")

    with st.expander("📦 Transactions (Admin)", expanded=False):
        st.caption("Sauvegarde une proposition de transaction (ne modifie pas les alignements).")

        owner_a = str(st.session_state.get("tx_owner_a", "") or "").strip()
        owner_b = str(st.session_state.get("tx_owner_b", "") or "").strip()

        a_players = st.session_state.get("tx_players_A", []) or []
        b_players = st.session_state.get("tx_players_B", []) or []
        a_picks = st.session_state.get("tx_picks_A", []) or []
        b_picks = st.session_state.get("tx_picks_B", []) or []
        a_cash = int(st.session_state.get("tx_cash_A", 0) or 0)
        b_cash = int(st.session_state.get("tx_cash_B", 0) or 0)

        def _collect_ret(side: str) -> dict:
            out = {}
            for k, v in st.session_state.items():
                if k.startswith(f"tx_ret_{side}_"):
                    try:
                        amt = int(v or 0)
                    except Exception:
                        amt = 0
                    if amt > 0:
                        out[k] = amt
            return out

        a_retained = _collect_ret("A")
        b_retained = _collect_ret("B")

        has_any = bool(a_players or b_players or a_picks or b_picks or a_cash or b_cash)
        if not has_any:
            st.info("Aucune transaction en cours. Va dans ⚖️ Transactions pour en construire une.")
        else:
            df_all = st.session_state.get("data", pd.DataFrame()).copy()

            missing = []
            for side, owner, plist in [("A", owner_a, a_players), ("B", owner_b, b_players)]:
                for j in plist:
                    if "Joueur" not in df_all.columns:
                        missing.append(f"{owner or side} — {j} (colonnes roster manquantes)")
                        continue
                    d = df_all[df_all["Joueur"].astype(str).str.strip().eq(str(j).strip())].copy()
                    if d.empty:
                        missing.append(f"{owner or side} — {j} (introuvable)")
                        continue
                    lvl = str(d.iloc[0].get("Level", "")).strip()
                    exp = str(d.iloc[0].get("Expiry Year", "")).strip()
                    if not lvl or lvl.upper() not in ("STD", "ELC"):
                        missing.append(f"{owner or side} — {j} (Level manquant)")
                    if not exp:
                        missing.append(f"{owner or side} — {j} (Expiry Year manquant)")

            if missing:
                st.error("Impossible de sauvegarder : il manque Level (STD/ELC) et/ou Expiry Year pour certains joueurs.")
                st.write("• " + "\n• ".join(missing[:12]))
                if len(missing) > 12:
                    st.caption(f"+ {len(missing)-12} autres…")
                can_save = False
            else:
                can_save = True

            st.markdown("**Résumé**")
            st.write(f"**{owner_a or 'Équipe A'}** : {len(a_players)} joueur(s), {len(a_picks)} pick(s), cash {money(a_cash)}")
            st.write(f"**{owner_b or 'Équipe B'}** : {len(b_players)} joueur(s), {len(b_picks)} pick(s), cash {money(b_cash)}")

            col_s1, col_s2 = st.columns(2)
            with col_s1:
                if st.button("💾 Sauvegarder la transaction", use_container_width=True, disabled=(not can_save), key="admin_tx_save"):
                    ts = datetime.now(ZoneInfo("America/Montreal")).strftime("%Y-%m-%d %H:%M:%S")
                    row = {
                        "timestamp": ts,
                        "owner_a": owner_a,
                        "owner_b": owner_b,
                        "a_players": " | ".join([str(x).strip() for x in a_players]),
                        "b_players": " | ".join([str(x).strip() for x in b_players]),
                        "a_picks": " | ".join([str(x).strip() for x in a_picks]),
                        "b_picks": " | ".join([str(x).strip() for x in b_picks]),
                        "a_retained": json.dumps(a_retained, ensure_ascii=False),
                        "b_retained": json.dumps(b_retained, ensure_ascii=False),
                        "a_cash": int(a_cash or 0),
                        "b_cash": int(b_cash or 0),
                        "status": "En attente",
                        "approved_a": True,
                        "approved_b": False,
                        "submitted_by": str(get_selected_team() or "").strip(),
                        "approved_at_a": ts,
                        "approved_at_b": "",
                        "completed_at": "",
                    }
                    append_transaction(season_pick, row)
                    st.toast("✅ Transaction sauvegardée", icon="✅")

            with col_s2:
                if st.button("🗑️ Réinitialiser la transaction", use_container_width=True, key="admin_tx_reset"):
                    for k in list(st.session_state.keys()):
                        if k.startswith(("tx_players_", "tx_picks_", "tx_cash_", "tx_ret_")) or k in ("tx_owner_a", "tx_owner_b"):
                            try:
                                del st.session_state[k]
                            except Exception:
                                pass
                    st.toast("🧹 Transaction réinitialisée", icon="🧹")
                    do_rerun()

elif active_tab == "🧠 Recommandations":
    st.subheader("🧠 Recommandations")
    st.caption("Une recommandation unique par équipe (résumé).")

    plafonds0 = st.session_state.get("plafonds")
    df0 = st.session_state.get("data")
    if df0 is None or df0.empty or plafonds0 is None or plafonds0.empty:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
        st.stop()

    rows = []
    for _, r in plafonds0.iterrows():
        owner = str(r.get("Propriétaire", "")).strip()
        dispo_gc = int(r.get("Montant Disponible GC", 0) or 0)
        dispo_ce = int(r.get("Montant Disponible CE", 0) or 0)

        if dispo_gc < 2_000_000:
            reco = "Rétrogradation recommandée (manque de marge GC)"
        elif dispo_ce > 10_000_000:
            reco = "Rappel possible (marge CE élevée)"
        else:
            reco = "Aucune action urgente"

        rows.append({
            "Équipe": owner,
            "Marge GC": money(dispo_gc),
            "Marge CE": money(dispo_ce),
            "Recommandation": reco,
        })

    out = pd.DataFrame(rows).sort_values(by=["Équipe"], kind="mergesort").reset_index(drop=True)
    st.dataframe(out, use_container_width=True, hide_index=True)
import streamlit as st
import pandas as pd
import requests
import os
import json
import re
import unicodedata
from datetime import datetime

# =========================================================
# CONFIG
# =========================================================
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

PLAYERS_DB_PATH_DEFAULT = os.path.join(DATA_DIR, "hockey.players.csv")
NHL_COUNTRY_CACHE_DEFAULT = os.path.join(DATA_DIR, "nhl_country_cache.json")
NHL_COUNTRY_CHECKPOINT_DEFAULT = os.path.join(DATA_DIR, "nhl_country_checkpoint.json")
CLUB_COUNTRY_CACHE_DEFAULT = os.path.join(DATA_DIR, "club_country_cache.json")

# =========================================================
# JSON helpers (atomic)
# =========================================================
def _read_json(path: str) -> dict:
    try:
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
                return d if isinstance(d, dict) else {}
    except Exception:
        pass
    return {}

def _write_json(path: str, data: dict) -> None:
    if not path:
        return
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data or {}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

# =========================================================
# Checkpoint badge
# =========================================================
def checkpoint_status(path: str = NHL_COUNTRY_CHECKPOINT_DEFAULT):
    if path and os.path.exists(path):
        try:
            ts = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            ts = "?"
        return True, path, ts
    return False, path, ""

# =========================================================
# NHL API helpers (free)
# =========================================================
def _http_get_json(url: str, params=None, timeout: int = 12):
    r = requests.get(url, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()

def _nhl_search_playerid(player_name: str):
    if not player_name:
        return None
    q = str(player_name).strip()
    if not q:
        return None
    try:
        data = _http_get_json(
            "https://search.d3.nhle.com/api/v1/search/player",
            params={"q": q, "limit": 10},
            timeout=12,
        )
    except Exception:
        return None

    items = data.get("items") or []
    name_norm = q.lower().strip()
    last = name_norm.split()[-1] if name_norm.split() else name_norm

    for it in items:
        try:
            pid_i = int(it.get("playerId") or it.get("id"))
        except Exception:
            continue
        nm = str(it.get("name") or it.get("playerName") or it.get("fullName") or "").lower().strip()
        if not nm:
            continue
        if nm == name_norm or (last and last in nm):
            return pid_i
    return None

def _nhl_landing_country(player_id: int):
    try:
        data = _http_get_json(f"https://api-web.nhle.com/v1/player/{int(player_id)}/landing", timeout=12)
    except Exception:
        return ""
    for k in ["birthCountryCode", "nationality", "countryCode"]:
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            cc = v.strip().upper()
            if len(cc) == 2:
                return cc
            if len(cc) == 3 and cc.isalpha():
                return cc[:2]
    return ""

# =========================================================
# Fallbacks (League + Club)
# =========================================================
FALLBACK_LEAGUE_TO_COUNTRY = {
    "NCAA": "US",
    "USHL": "US",
    "OHL": "CA",
    "WHL": "CA",
    "QMJHL": "CA",
    "CHL": "CA",
    "SHL": "SE",
    "ALLSVENSKAN": "SE",
    "LIIGA": "FI",
    "MESTIS": "FI",
    "KHL": "RU",
    "NL": "CH",
    "NLA": "CH",
    "DEL": "DE",
    "DEL2": "DE",
    "LIGUE MAGNUS": "FR",
}

SEED_CLUB_TOKENS = {
    "FROLUNDA": "SE",
    "FÄRJESTAD": "SE",
    "DJURGARDEN": "SE",
    "KARPAT": "FI",
    "HIFK": "FI",
    "DAVOS": "CH",
    "LUGANO": "CH",
}

def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

def _club_slug(s: str) -> str:
    s = _strip_accents((s or "").upper())
    s = re.sub(r"[\-/_,\.\(\)]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for w in ["HC", "IF", "IK", "SK", "HOCKEY", "CLUB", "TEAM"]:
        s = s.replace(f" {w}", "")
    return s.strip()

def _infer_from_league(row: dict) -> str:
    for col in ["League", "League Name", "Competition"]:
        v = row.get(col)
        if isinstance(v, str) and v.strip():
            up = v.upper()
            for k, cc in FALLBACK_LEAGUE_TO_COUNTRY.items():
                if k in up:
                    return cc
    return ""

def _infer_from_club(row: dict, club_cache: dict) -> str:
    for col in ["Club", "Team", "Current Team", "Junior Team"]:
        v = row.get(col)
        if isinstance(v, str) and v.strip():
            slug = _club_slug(v)
            if slug in club_cache:
                return club_cache.get(slug, "")
            for tok, cc in SEED_CLUB_TOKENS.items():
                if tok in slug:
                    return cc
    return ""

def _learn_club(row: dict, cc: str, club_cache: dict):
    for col in ["Club", "Team", "Current Team", "Junior Team"]:
        v = row.get(col)
        if isinstance(v, str) and v.strip():
            slug = _club_slug(v)
            if slug and slug not in club_cache:
                club_cache[slug] = cc

# =========================================================
# Update Players DB (with fallback)
# =========================================================
def update_players_db(path: str, *, max_calls=300, save_every=500, resume_only=True):
    if not os.path.exists(path):
        return {"ok": False, "error": "File not found"}

    df = pd.read_csv(path)
    if "Country" not in df.columns:
        df["Country"] = ""
    if "playerId" not in df.columns:
        df["playerId"] = ""

    cache = _read_json(NHL_COUNTRY_CACHE_DEFAULT)
    club_cache = _read_json(CLUB_COUNTRY_CACHE_DEFAULT)
    ckpt = _read_json(NHL_COUNTRY_CHECKPOINT_DEFAULT)

    start = int(ckpt.get("cursor", 0)) if resume_only else 0
    cand = [i for i, r in df.iterrows() if not str(r.get("Country") or "").strip()]
    total = len(cand)
    end = min(start + max_calls, total)

    updated = processed = errors = 0

    for pos in range(start, end):
        i = cand[pos]
        row = df.loc[i]
        rowd = row.to_dict()

        nm = str(row.get("Player") or "").strip()
        pid = None
        if row.get("playerId"):
            try:
                pid = int(row.get("playerId"))
            except Exception:
                pid = None
        if pid is None and nm:
            pid = _nhl_search_playerid(nm)

        cc = ""
        if pid:
            cc = _nhl_landing_country(pid)
            if cc:
                df.at[i, "Country"] = cc
                df.at[i, "playerId"] = pid
                cache[str(pid)] = {"ok": True, "country": cc}
                _learn_club(rowd, cc, club_cache)
                updated += 1
            else:
                cache[str(pid)] = {"ok": False}
        else:
            cc = _infer_from_league(rowd) or _infer_from_club(rowd, club_cache)
            if cc:
                df.at[i, "Country"] = cc
                _learn_club(rowd, cc, club_cache)
                updated += 1
            else:
                errors += 1

        processed += 1
        if save_every and processed % save_every == 0:
            df.to_csv(path, index=False)
            _write_json(NHL_COUNTRY_CACHE_DEFAULT, cache)
            _write_json(CLUB_COUNTRY_CACHE_DEFAULT, club_cache)
            _write_json(NHL_COUNTRY_CHECKPOINT_DEFAULT, {"cursor": pos + 1})

    df.to_csv(path, index=False)
    _write_json(NHL_COUNTRY_CACHE_DEFAULT, cache)
    _write_json(CLUB_COUNTRY_CACHE_DEFAULT, club_cache)
    _write_json(NHL_COUNTRY_CHECKPOINT_DEFAULT, {"cursor": end})

    return {"ok": True, "updated": updated, "processed": processed, "errors": errors, "total": total}

# =========================================================
# UI
# =========================================================
st.set_page_config(page_title="Pool Hockey", layout="wide")
tab = st.radio("Navigation", ["🏠 Home", "🛠️ Gestion Admin"], horizontal=True)

if tab == "🏠 Home":
    st.title("🏠 Home")
    st.info("Home clean.")

else:
    st.title("🛠️ Gestion Admin")
    has_ckpt, ckpt_file, ckpt_ts = checkpoint_status()
    if has_ckpt:
        st.warning(f"Checkpoint detected — {ckpt_ts}")
    st.subheader("Players DB — Country fill (NHL → League → Club)")
    path = st.text_input("Players DB path", PLAYERS_DB_PATH_DEFAULT)
    max_calls = st.number_input("Max calls", 50, 2000, 300, 50)
    save_every = st.number_input("Save every", 50, 5000, 500, 50)
    resume = st.checkbox("Resume only", True)

    if st.button("▶ Run"):
        res = update_players_db(path, max_calls=int(max_calls), save_every=int(save_every), resume_only=resume)
        st.json(res)

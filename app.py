import streamlit as st
import pandas as pd
import requests
import os
import json
import re
from datetime import datetime

# =========================================================
# CONFIG
# =========================================================
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

PLAYERS_DB_PATH_DEFAULT = os.path.join(DATA_DIR, "hockey.players.csv")
NHL_COUNTRY_CACHE_DEFAULT = os.path.join(DATA_DIR, "nhl_country_cache.json")
NHL_COUNTRY_CHECKPOINT_DEFAULT = os.path.join(DATA_DIR, "nhl_country_checkpoint.json")


# =========================================================
# JSON helpers (atomic)
# =========================================================
def _pdb_read_json(path: str) -> dict:
    try:
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
                return d if isinstance(d, dict) else {}
    except Exception:
        pass
    return {}


def _pdb_write_json(path: str, data: dict) -> None:
    if not path:
        return
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data or {}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# =========================================================
# Checkpoint badge helpers
# =========================================================
def checkpoint_status(path: str = NHL_COUNTRY_CHECKPOINT_DEFAULT):
    if not path:
        return False, "", ""
    if os.path.exists(path):
        try:
            ts = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            ts = "?"
        return True, path, ts
    return False, path, ""


# =========================================================
# NHL API helpers (free)
# =========================================================
def _http_get_json(url: str, params: dict | None = None, timeout: int = 12):
    r = requests.get(url, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _nhl_search_playerid(player_name: str):
    """Best-effort NHL playerId from name using NHL search endpoint."""
    if not player_name:
        return None
    q = str(player_name).strip()
    if not q:
        return None

    try:
        url = "https://search.d3.nhle.com/api/v1/search/player"
        params = {"q": q, "limit": 10}
        data = _http_get_json(url, params=params, timeout=12)
    except Exception:
        return None

    items = data.get("items") or []
    if not isinstance(items, list):
        return None

    name_norm = q.lower().strip()
    last = name_norm.split()[-1] if name_norm.split() else name_norm

    for it in items:
        try:
            pid = it.get("playerId") or it.get("id")
            pid_i = int(pid)
        except Exception:
            continue

        nm = str(it.get("name") or it.get("playerName") or it.get("fullName") or "").strip().lower()
        if not nm:
            continue

        if nm == name_norm:
            return pid_i
        # tolerant: last name match
        if last and last in nm:
            return pid_i

    return None


def _nhl_landing_country(player_id: int):
    """Fetch country code from NHL player landing endpoint (best-effort)."""
    try:
        url = f"https://api-web.nhle.com/v1/player/{int(player_id)}/landing"
        data = _http_get_json(url, params=None, timeout=12)
    except Exception:
        return ""

    # Common fields seen: birthCountry, birthCountryCode, nationality, countryCode
    for k in ["birthCountryCode", "birthCountry", "nationality", "countryCode"]:
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            cc = v.strip().upper()
            # normalize common full country strings if needed
            if len(cc) == 2:
                return cc
            # sometimes "CAN" etc — keep first 2 only if looks like alpha
            if len(cc) == 3 and cc.isalpha():
                return cc[:2]
    return ""


# =========================================================
# Players DB update with Resume / Checkpoint / Cache
# =========================================================
def _norm_name_key(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def update_players_db(
    path: str,
    *,
    fill_country: bool = True,
    resume_only: bool = True,
    reset_progress: bool = False,
    failed_only: bool = False,
    max_calls: int = 300,
    save_every: int = 500,
    cache_path: str = NHL_COUNTRY_CACHE_DEFAULT,
    checkpoint_path: str = NHL_COUNTRY_CHECKPOINT_DEFAULT,
    progress_cb=None,
):
    """Update Players DB (Country fill) with cache + checkpoint.
    - cache: nhl_country_cache.json (pid->country or fail)
    - checkpoint: nhl_country_checkpoint.json (cursor)
    """
    if not path:
        return {"ok": False, "error": "No path provided"}
    if not os.path.exists(path):
        return {"ok": False, "error": f"File not found: {path}"}

    df = pd.read_csv(path)

    # Ensure columns
    if "Country" not in df.columns:
        df["Country"] = ""
    if "playerId" not in df.columns:
        df["playerId"] = ""

    # Load cache & checkpoint
    cache = _pdb_read_json(cache_path)
    if not isinstance(cache, dict):
        cache = {}

    ckpt = _pdb_read_json(checkpoint_path)
    if reset_progress:
        ckpt = {}
        try:
            _pdb_write_json(checkpoint_path, {})
        except Exception:
            pass

    start_at = 0
    if resume_only and isinstance(ckpt, dict):
        try:
            start_at = int(ckpt.get("cursor") or 0)
        except Exception:
            start_at = 0
    start_at = max(0, start_at)

    # Candidate rows: missing Country
    cand_idx = []
    for i, row in df.iterrows():
        ctry = str(row.get("Country") or "").strip()
        if ctry:
            continue

        nm = str(row.get("Player") or row.get("Joueur") or "").strip()
        pid = str(row.get("playerId") or "").strip()

        # failed_only: only retry those that previously failed (by pid or by name)
        if failed_only:
            name_key = "NAME::" + _norm_name_key(nm)
            pid_key = pid if pid else None
            failed = False
            if pid_key and isinstance(cache.get(pid_key), dict) and cache.get(pid_key, {}).get("ok") is False:
                failed = True
            if (not pid_key) and isinstance(cache.get(name_key), dict) and cache.get(name_key, {}).get("ok") is False:
                failed = True
            if not failed:
                continue

        cand_idx.append(i)

    total = len(cand_idx)
    end_at = min(start_at + int(max_calls or 300), total)

    processed = 0
    updated = 0
    skipped_cached = 0
    errors = 0
    cursor = start_at

    for pos in range(start_at, end_at):
        i = cand_idx[pos]
        row = df.loc[i]

        nm = str(row.get("Player") or row.get("Joueur") or "").strip()
        pid_raw = str(row.get("playerId") or "").strip()

        # resolve/parse pid
        pid_i = None
        if pid_raw:
            try:
                pid_i = int(pid_raw)
            except Exception:
                pid_i = None

        name_key = "NAME::" + _norm_name_key(nm)

        # If no pid, try name cache first
        if pid_i is None and nm:
            cached_name = cache.get(name_key)
            if isinstance(cached_name, dict) and cached_name.get("ok") is True and cached_name.get("country"):
                df.at[i, "Country"] = str(cached_name.get("country")).strip().upper()
                skipped_cached += 1
                processed += 1
                cursor = pos + 1
                continue

        # resolve pid if missing
        if pid_i is None and nm:
            pid_i = _nhl_search_playerid(nm)

        # If still no pid: mark failed by name
        if pid_i is None:
            cache[name_key] = {"ok": False, "reason": "no_pid"}
            errors += 1
            processed += 1
            cursor = pos + 1
            continue

        pid_key = str(pid_i)

        cached_pid = cache.get(pid_key)
        if isinstance(cached_pid, dict) and cached_pid.get("ok") is True and cached_pid.get("country"):
            df.at[i, "Country"] = str(cached_pid.get("country")).strip().upper()
            df.at[i, "playerId"] = pid_i
            skipped_cached += 1
            processed += 1
            cursor = pos + 1
        else:
            ctry = _nhl_landing_country(pid_i) if fill_country else ""
            if ctry:
                df.at[i, "Country"] = ctry
                df.at[i, "playerId"] = pid_i
                cache[pid_key] = {"ok": True, "country": ctry}
                # also store name cache for faster future hits
                if nm:
                    cache[name_key] = {"ok": True, "country": ctry, "source": "pid"}
                updated += 1
            else:
                cache[pid_key] = {"ok": False, "reason": "no_country"}
                if nm:
                    cache[name_key] = {"ok": False, "reason": "no_country"}
                errors += 1
            processed += 1
            cursor = pos + 1

        # progress callback
        if callable(progress_cb):
            try:
                progress_cb({"phase": "Country", "cursor": cursor, "total": total, "updated": updated, "processed": processed})
            except Exception:
                pass

        # periodic saves
        if save_every and processed % int(save_every) == 0:
            try:
                df.to_csv(path, index=False)
            except Exception:
                pass
            try:
                _pdb_write_json(cache_path, cache)
            except Exception:
                pass
            try:
                _pdb_write_json(checkpoint_path, {"phase": "Country", "cursor": cursor})
            except Exception:
                pass

    # final save + checkpoint
    done = (cursor >= total)
    try:
        df.to_csv(path, index=False)
    except Exception:
        pass
    try:
        _pdb_write_json(cache_path, cache)
    except Exception:
        pass
    try:
        _pdb_write_json(checkpoint_path, {"phase": "Country", "cursor": (total if done else cursor)})
    except Exception:
        pass

    return {
        "ok": True,
        "path": path,
        "phase": "Country",
        "cursor": (total if done else cursor),
        "total": total,
        "processed": processed,
        "updated": updated,
        "errors": errors,
        "cached": skipped_cached,
        "done": bool(done),
        "cache_path": cache_path,
        "checkpoint_path": checkpoint_path,
        "failed_only": bool(failed_only),
    }


# =========================================================
# UI
# =========================================================
st.set_page_config(page_title="Pool Hockey", layout="wide")

TABS = ["🏠 Home", "🛠️ Gestion Admin"]
active_tab = st.radio("Navigation", TABS, horizontal=True)

if active_tab == "🏠 Home":
    st.title("🏠 Home")
    st.info("Home tab clean. No Players DB here.")

elif active_tab == "🛠️ Gestion Admin":
    st.title("🛠️ Gestion Admin")

    # Checkpoint badge in sidebar-like top area
    has_ckpt, ckpt_file, ckpt_ts = checkpoint_status()
    if has_ckpt:
        st.warning(f"✅ **Checkpoint file detected** — {ckpt_ts}\n\n`{ckpt_file}`")
    else:
        st.caption("Aucun checkpoint détecté.")

    st.subheader("🗃️ Players DB — Country fill (Resume/Checkpoint)")

    players_path = st.text_input("Players DB path", value=PLAYERS_DB_PATH_DEFAULT)
    colA, colB, colC, colD = st.columns(4)
    with colA:
        max_calls = st.number_input("Max calls / run", min_value=50, max_value=2000, value=300, step=50)
    with colB:
        save_every = st.number_input("Save every N processed", min_value=50, max_value=5000, value=500, step=50)
    with colC:
        resume_only = st.checkbox("Resume only (use checkpoint)", value=True)
    with colD:
        failed_only = st.checkbox("Failed only", value=False)

    col1, col2, col3 = st.columns(3)
    with col1:
        run_btn = st.button("▶ Resume Country fill", type="primary")
    with col2:
        reset_btn = st.button("🔁 Reset progress")
    with col3:
        reset_failed_btn = st.button("♻️ Reset failed-only (clear cache fails)")

    if reset_failed_btn:
        cache = _pdb_read_json(NHL_COUNTRY_CACHE_DEFAULT)
        if isinstance(cache, dict):
            # keep only ok==True entries
            cache2 = {k: v for k, v in cache.items() if isinstance(v, dict) and v.get("ok") is True}
            _pdb_write_json(NHL_COUNTRY_CACHE_DEFAULT, cache2)
            st.success(f"Cache cleaned: kept {len(cache2)} ok entries.")
        else:
            st.info("No cache to clean.")

    if reset_btn:
        try:
            _pdb_write_json(NHL_COUNTRY_CHECKPOINT_DEFAULT, {})
            st.success("Checkpoint reset.")
        except Exception as e:
            st.error(f"Reset failed: {e}")

    if run_btn:
        status_box = st.empty()

        def _cb(stat):
            status_box.info(stat)

        stats = update_players_db(
            players_path,
            fill_country=True,
            resume_only=resume_only,
            reset_progress=False,
            failed_only=failed_only,
            max_calls=int(max_calls),
            save_every=int(save_every),
            cache_path=NHL_COUNTRY_CACHE_DEFAULT,
            checkpoint_path=NHL_COUNTRY_CHECKPOINT_DEFAULT,
            progress_cb=_cb,
        )
        st.success("Run completed.")
        st.json(stats)

    st.divider()
    st.caption("Files used:")
    st.code("\n".join([PLAYERS_DB_PATH_DEFAULT, NHL_COUNTRY_CACHE_DEFAULT, NHL_COUNTRY_CHECKPOINT_DEFAULT]))

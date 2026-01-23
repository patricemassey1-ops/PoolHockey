import streamlit as st
import pandas as pd
import requests
import os
import json
import re
import unicodedata
import time
import zipfile
from datetime import datetime
from typing import Optional

# =========================================================
# MUST BE FIRST STREAMLIT COMMAND
# =========================================================
st.set_page_config(page_title="Pool Hockey", layout="wide")

# =========================================================
# CONFIG
# =========================================================
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

PLAYERS_DB_PATH_DEFAULT = os.path.join(DATA_DIR, "hockey.players.csv")

NHL_COUNTRY_CACHE_DEFAULT = os.path.join(DATA_DIR, "nhl_country_cache.json")
NHL_COUNTRY_CHECKPOINT_DEFAULT = os.path.join(DATA_DIR, "nhl_country_checkpoint.json")
CLUB_COUNTRY_CACHE_DEFAULT = os.path.join(DATA_DIR, "club_country_cache.json")

BACKUP_DIR_DEFAULT = os.path.join(DATA_DIR, "backups")
os.makedirs(BACKUP_DIR_DEFAULT, exist_ok=True)

# Transactions
def _season_lbl_default() -> str:
    # simple season label: "2025-2026" based on today
    y = datetime.now().year
    m = datetime.now().month
    if m >= 8:
        return f"{y}-{y+1}"
    return f"{y-1}-{y}"

TRANSACTIONS_PATH_DEFAULT = os.path.join(DATA_DIR, f"transactions_{_season_lbl_default()}.csv")

# =========================================================
# ONE SINGLE CSS INJECTION (règles d’or)
# =========================================================
THEME_CSS = r"""
<style>
.nowrap { white-space: nowrap; }
.right { text-align: right; }
.muted { color: rgba(120,120,120,0.95); font-size: 0.90rem; }
.small { font-size: 0.92rem; }
.card { padding: 10px 12px; border: 1px solid rgba(120,120,120,0.25); border-radius: 14px; }
hr.soft { border: none; border-top: 1px solid rgba(120,120,120,0.25); margin: 0.7rem 0; }
div.stButton > button { padding: 0.35rem 0.6rem; border-radius: 10px; }
</style>
"""
st.markdown(THEME_CSS, unsafe_allow_html=True)

# =========================================================
# ROBUSTNESS HELPERS
# =========================================================
def _ss_init(key: str, default):
    if key not in st.session_state:
        st.session_state[key] = default

def _now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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

def checkpoint_status(path: str = NHL_COUNTRY_CHECKPOINT_DEFAULT):
    if path and os.path.exists(path):
        try:
            ts = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            ts = "?"
        return True, path, ts
    return False, path, ""

def _anti_double_run_guard(tag: str, min_seconds: float = 0.8) -> bool:
    """
    Returns True if allowed to run, False if blocked (too soon).
    Prevents double-click / double rerun issues for expensive actions.
    """
    k = f"_last_run__{tag}"
    t = time.time()
    last = float(st.session_state.get(k, 0.0) or 0.0)
    if t - last < min_seconds:
        return False
    st.session_state[k] = t
    return True

# =========================================================
# FLAG HELPERS
# =========================================================
def _country_to_flag_emoji(cc: str) -> str:
    cc = (cc or "").strip().upper()
    if len(cc) != 2 or not cc.isalpha():
        return ""
    return chr(127397 + ord(cc[0])) + chr(127397 + ord(cc[1]))

def _fmt_money(x) -> str:
    try:
        v = float(x)
    except Exception:
        return str(x or "").strip()
    return f"{int(round(v)):,}".replace(",", " ")

# =========================================================
# NHL API (free)
# =========================================================
def _http_get_json(url: str, params=None, timeout: int = 12):
    r = requests.get(url, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()

def _nhl_search_playerid(player_name: str) -> Optional[int]:
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

def _nhl_landing_country(player_id: int) -> str:
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
# FALLBACKS (League + Club)
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
    s = re.sub(r"[\-/_\,\.\(\)]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for w in [" HC", " IF", " IK", " SK", " HOCKEY", " CLUB", " TEAM", " U20", " J20", " U18", " J18"]:
        s = s.replace(w, "")
    return s.strip()

def _infer_from_league(row: dict) -> str:
    for col in ["League", "League Name", "Competition", "Junior League", "Jr League"]:
        v = row.get(col)
        if isinstance(v, str) and v.strip():
            up = v.upper()
            if "ICEHL" in up or "EBEL" in up:
                return ""
            for k, cc in FALLBACK_LEAGUE_TO_COUNTRY.items():
                if k in up:
                    return cc
    return ""

def _infer_from_club(row: dict, club_cache: dict) -> str:
    for col in ["Club", "Team", "Current Team", "Junior Team", "Jr Team"]:
        v = row.get(col)
        if isinstance(v, str) and v.strip():
            slug = _club_slug(v)
            if slug in club_cache:
                return str(club_cache.get(slug) or "").strip().upper()
            for tok, cc in SEED_CLUB_TOKENS.items():
                if tok in slug:
                    return cc
    return ""

def _learn_club(row: dict, cc: str, club_cache: dict):
    for col in ["Club", "Team", "Current Team", "Junior Team", "Jr Team"]:
        v = row.get(col)
        if isinstance(v, str) and v.strip():
            slug = _club_slug(v)
            if slug and slug not in club_cache:
                club_cache[slug] = cc

# =========================================================
# PLAYERS DB UPDATE (resume/checkpoint + fallback)
# =========================================================
def update_players_db(
    path: str,
    *,
    max_calls=300,
    save_every=500,
    resume_only=True,
    reset_progress=False,
    failed_only=False,
    progress_cb=None,
):
    if not os.path.exists(path):
        return {"ok": False, "error": f"File not found: {path}"}

    df = pd.read_csv(path)
    if "Country" not in df.columns:
        df["Country"] = ""
    if "playerId" not in df.columns:
        df["playerId"] = ""

    cache = _read_json(NHL_COUNTRY_CACHE_DEFAULT)
    club_cache = _read_json(CLUB_COUNTRY_CACHE_DEFAULT)
    ckpt = _read_json(NHL_COUNTRY_CHECKPOINT_DEFAULT)

    if reset_progress:
        ckpt = {}
        _write_json(NHL_COUNTRY_CHECKPOINT_DEFAULT, {})

    start = int(ckpt.get("cursor", 0)) if resume_only else 0

    cand = []
    for i, r in df.iterrows():
        if str(r.get("Country") or "").strip():
            continue
        if failed_only:
            pid = str(r.get("playerId") or "").strip()
            nm = str(r.get("Player") or r.get("Joueur") or "").strip()
            name_key = f"NAME::{nm.lower().strip()}"
            is_failed = False
            if pid and isinstance(cache.get(pid), dict) and cache.get(pid, {}).get("ok") is False:
                is_failed = True
            if (not pid) and isinstance(cache.get(name_key), dict) and cache.get(name_key, {}).get("ok") is False:
                is_failed = True
            if not is_failed:
                continue
        cand.append(i)

    total = len(cand)
    end = min(start + int(max_calls), total)

    updated = processed = errors = cached = 0

    for pos in range(start, end):
        i = cand[pos]
        row = df.loc[i]
        rowd = row.to_dict()

        nm = str(row.get("Player") or row.get("Joueur") or "").strip()
        pid = None
        pid_raw = str(row.get("playerId") or "").strip()
        if pid_raw:
            try:
                pid = int(pid_raw)
            except Exception:
                pid = None

        name_key = f"NAME::{nm.lower().strip()}" if nm else ""

        if pid is None and name_key:
            cached_name = cache.get(name_key)
            if isinstance(cached_name, dict) and cached_name.get("ok") is True and cached_name.get("country"):
                cc = str(cached_name.get("country")).strip().upper()
                df.at[i, "Country"] = cc
                cached += 1
                processed += 1
                _write_json(NHL_COUNTRY_CHECKPOINT_DEFAULT, {"cursor": pos + 1})
                continue

        if pid is None and nm:
            pid = _nhl_search_playerid(nm)

        if pid:
            pid_key = str(pid)
            cached_pid = cache.get(pid_key)
            if isinstance(cached_pid, dict) and cached_pid.get("ok") is True and cached_pid.get("country"):
                cc = str(cached_pid.get("country")).strip().upper()
                df.at[i, "Country"] = cc
                df.at[i, "playerId"] = pid
                cached += 1
            else:
                cc = _nhl_landing_country(pid)
                if cc:
                    df.at[i, "Country"] = cc
                    df.at[i, "playerId"] = pid
                    cache[pid_key] = {"ok": True, "country": cc}
                    if name_key:
                        cache[name_key] = {"ok": True, "country": cc, "source": "pid"}
                    _learn_club(rowd, cc, club_cache)
                    updated += 1
                else:
                    cc2 = _infer_from_league(rowd) or _infer_from_club(rowd, club_cache)
                    if cc2:
                        df.at[i, "Country"] = cc2
                        df.at[i, "playerId"] = pid
                        cache[pid_key] = {"ok": True, "country": cc2, "source": "fallback"}
                        if name_key:
                            cache[name_key] = {"ok": True, "country": cc2, "source": "fallback"}
                        _learn_club(rowd, cc2, club_cache)
                        updated += 1
                    else:
                        cache[pid_key] = {"ok": False, "reason": "no_country"}
                        if name_key:
                            cache[name_key] = {"ok": False, "reason": "no_country"}
                        errors += 1
        else:
            cc2 = _infer_from_league(rowd) or _infer_from_club(rowd, club_cache)
            if cc2:
                df.at[i, "Country"] = cc2
                _learn_club(rowd, cc2, club_cache)
                if name_key:
                    cache[name_key] = {"ok": True, "country": cc2, "source": "fallback"}
                updated += 1
            else:
                if name_key:
                    cache[name_key] = {"ok": False, "reason": "no_pid"}
                errors += 1

        processed += 1

        if callable(progress_cb):
            try:
                progress_cb({"cursor": pos + 1, "total": total, "updated": updated, "processed": processed, "cached": cached, "errors": errors})
            except Exception:
                pass

        if save_every and processed % int(save_every) == 0:
            df.to_csv(path, index=False)
            _write_json(NHL_COUNTRY_CACHE_DEFAULT, cache)
            _write_json(CLUB_COUNTRY_CACHE_DEFAULT, club_cache)
            _write_json(NHL_COUNTRY_CHECKPOINT_DEFAULT, {"cursor": pos + 1})

    df.to_csv(path, index=False)
    _write_json(NHL_COUNTRY_CACHE_DEFAULT, cache)
    _write_json(CLUB_COUNTRY_CACHE_DEFAULT, club_cache)
    _write_json(NHL_COUNTRY_CHECKPOINT_DEFAULT, {"cursor": end})

    return {"ok": True, "updated": updated, "processed": processed, "cached": cached, "errors": errors, "total": total, "cursor": end}

# =========================================================
# ALIGNEMENT UI (Flag in button + nowrap + swap Banc/IR)
# =========================================================
def _guess_cols(df: pd.DataFrame):
    col_player = "Player" if "Player" in df.columns else ("Joueur" if "Joueur" in df.columns else None)
    col_pos = "Pos" if "Pos" in df.columns else ("Position" if "Position" in df.columns else None)
    col_salary = "Salary" if "Salary" in df.columns else ("Salaire" if "Salaire" in df.columns else None)
    col_owner = "Propriétaire" if "Propriétaire" in df.columns else ("Owner" if "Owner" in df.columns else None)
    col_status = "Status" if "Status" in df.columns else ("Statut" if "Statut" in df.columns else None)
    return col_player, col_pos, col_salary, col_owner, col_status

def roster_click_list(df: pd.DataFrame, title: str):
    st.markdown(f"### {title}")
    if df is None or df.empty:
        st.caption("Aucun joueur.")
        return None

    col_player, col_pos, col_salary, _, _ = _guess_cols(df)

    h1, h2, h3 = st.columns([7, 2, 2])
    with h1:
        st.markdown('<div class="muted nowrap">Joueur</div>', unsafe_allow_html=True)
    with h2:
        st.markdown('<div class="muted nowrap">Pos</div>', unsafe_allow_html=True)
    with h3:
        st.markdown('<div class="muted nowrap right">Salaire</div>', unsafe_allow_html=True)

    chosen = None
    for idx, row in df.iterrows():
        name = str(row.get(col_player) or "").strip()
        pos = str(row.get(col_pos) or "").strip() if col_pos else ""
        sal = row.get(col_salary) if col_salary else ""
        cc = str(row.get("Country") or "").strip().upper()
        flag = _country_to_flag_emoji(cc)

        c1, c2, c3 = st.columns([7, 2, 2])
        with c1:
            if st.button(f"{flag}  {name}" if flag else name, key=f"{title}__p__{idx}"):
                chosen = idx
        with c2:
            st.markdown(f'<div class="nowrap small">{pos}</div>', unsafe_allow_html=True)
        with c3:
            st.markdown(f'<div class="nowrap right small">{_fmt_money(sal)}</div>', unsafe_allow_html=True)

    return chosen

# =========================================================
# TRANSACTIONS (clean + CSV persistence)
# =========================================================
TRANSACTION_COLS = [
    "trade_id","timestamp","season","owner_a","owner_b",
    "a_players","b_players","a_picks","b_picks","a_cash","b_cash",
    "status","notes"
]

def _tx_read(path: str) -> pd.DataFrame:
    if os.path.exists(path):
        try:
            df = pd.read_csv(path)
            for c in TRANSACTION_COLS:
                if c not in df.columns:
                    df[c] = ""
            return df[TRANSACTION_COLS].copy()
        except Exception:
            pass
    return pd.DataFrame(columns=TRANSACTION_COLS)

def _tx_write(path: str, df: pd.DataFrame) -> None:
    try:
        df.to_csv(path, index=False)
    except Exception:
        pass

def _make_trade_id() -> str:
    return "TR-" + datetime.now().strftime("%Y%m%d") + "-" + hex(int(time.time()*1000))[-6:].upper()

# =========================================================
# BACKUP/RESTORE (local + optional Drive placeholder)
# =========================================================
def _zip_backup(dest_dir: str, files: list[str]) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(dest_dir, f"backup_{ts}.zip")
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for fp in files:
            if fp and os.path.exists(fp):
                arc = os.path.relpath(fp, DATA_DIR) if fp.startswith(DATA_DIR + os.sep) else os.path.basename(fp)
                z.write(fp, arcname=arc)
    return out_path

def _restore_zip(zip_path: str, dest_dir: str) -> dict:
    if not os.path.exists(zip_path):
        return {"ok": False, "error": "zip not found"}
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(dest_dir)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _drive_available() -> bool:
    # Safe detection only. No hard deps that can crash.
    try:
        _ = st.secrets.get("gdrive_oauth", None)
    except Exception:
        return False
    try:
        import googleapiclient  # noqa: F401
        return True
    except Exception:
        return False

# =========================================================
# UI (NAV)
# =========================================================
TABS = ["🏠 Home", "🧾 Alignement", "⚖️ Transactions", "🛠️ Gestion Admin"]
active_tab = st.radio("Navigation", TABS, horizontal=True)

if active_tab == "🏠 Home":
    st.title("🏠 Home")
    st.info("Home clean. (No Players DB here.)")

elif active_tab == "🧾 Alignement":
    st.title("🧾 Alignement")

    if not os.path.exists(PLAYERS_DB_PATH_DEFAULT):
        st.error(f"Missing: {PLAYERS_DB_PATH_DEFAULT}")
        st.stop()

    df = pd.read_csv(PLAYERS_DB_PATH_DEFAULT)
    col_player, col_pos, col_salary, col_owner, col_status = _guess_cols(df)

    if col_owner:
        owners = sorted([x for x in df[col_owner].dropna().astype(str).unique() if x.strip()])
        owner = st.selectbox("Équipe", owners) if owners else ""
        view = df[df[col_owner].astype(str).eq(owner)].copy() if owner else df.copy()
    else:
        st.caption("Colonne Propriétaire absente — affichage global (démo).")
        view = df.copy()

    if col_status:
        actifs = view[view[col_status].astype(str).str.contains("Actif|Active", case=False, na=False)].copy()
        banc = view[view[col_status].astype(str).str.contains("Banc|Bench", case=False, na=False)].copy()
        ir = view[view[col_status].astype(str).str.contains("IR|Inj", case=False, na=False)].copy()
        mineur = view[view[col_status].astype(str).str.contains("Mineur|Minor|AHL", case=False, na=False)].copy()
    else:
        actifs, banc, ir, mineur = view.copy(), view.iloc[0:0].copy(), view.iloc[0:0].copy(), view.iloc[0:0].copy()

    left, center, right = st.columns([1.1, 1.1, 1.1])
    with left:
        roster_click_list(actifs, "⭐ Actifs")
    with center:
        roster_click_list(banc, "🪑 Banc")
        st.divider()
        roster_click_list(ir, "🩹 IR")
    with right:
        roster_click_list(mineur, "🧊 Mineur")

elif active_tab == "⚖️ Transactions":
    st.title("⚖️ Transactions")

    season = st.text_input("Saison", value=_season_lbl_default())
    tx_path = os.path.join(DATA_DIR, f"transactions_{season}.csv")

    df_tx = _tx_read(tx_path)

    st.markdown("#### ➕ Proposer une transaction")
    c1, c2 = st.columns(2)
    with c1:
        owner_a = st.text_input("Équipe A (propose)", key="tx_owner_a")
        a_players = st.text_area("Joueurs A (séparés par virgule)", key="tx_a_players")
        a_picks = st.text_input("Picks A (ex: 2026-1,2027-2)", key="tx_a_picks")
        a_cash = st.text_input("Cash A", key="tx_a_cash")
    with c2:
        owner_b = st.text_input("Équipe B", key="tx_owner_b")
        b_players = st.text_area("Joueurs B (séparés par virgule)", key="tx_b_players")
        b_picks = st.text_input("Picks B", key="tx_b_picks")
        b_cash = st.text_input("Cash B", key="tx_b_cash")

    notes = st.text_area("Notes", key="tx_notes")

    if st.button("✅ Enregistrer la proposition", type="primary"):
        if not _anti_double_run_guard("save_tx", 0.8):
            st.info("Patiente une seconde (anti double-click).")
        else:
            tid = _make_trade_id()
            new = {
                "trade_id": tid,
                "timestamp": _now_ts(),
                "season": season,
                "owner_a": owner_a,
                "owner_b": owner_b,
                "a_players": a_players,
                "b_players": b_players,
                "a_picks": a_picks,
                "b_picks": b_picks,
                "a_cash": a_cash,
                "b_cash": b_cash,
                "status": "PROPOSED",
                "notes": notes,
            }
            df_tx = pd.concat([df_tx, pd.DataFrame([new])], ignore_index=True)
            _tx_write(tx_path, df_tx)
            st.success(f"Transaction enregistrée: {tid}")

    st.divider()
    st.markdown("#### 📋 Transactions enregistrées")
    if df_tx.empty:
        st.caption("Aucune transaction.")
    else:
        st.dataframe(df_tx.sort_values("timestamp", ascending=False), use_container_width=True)

elif active_tab == "🛠️ Gestion Admin":
    st.title("🛠️ Gestion Admin")

    has_ckpt, ckpt_file, ckpt_ts = checkpoint_status()
    if has_ckpt:
    st.warning(f"✅ Checkpoint file detected — {ckpt_ts}")

    else:
        st.caption("Aucun checkpoint détecté.")

    st.markdown("### 🗃️ Players DB — Country fill (NHL → League → Club)")
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

    c_run, c_reset, c_cache = st.columns(3)
    with c_run:
        run_btn = st.button("▶ Resume Country fill", type="primary")
    with c_reset:
        reset_btn = st.button("🔁 Reset progress")
    with c_cache:
        reset_failed_btn = st.button("♻️ Reset failed-only (keep ok cache)")

    if reset_failed_btn:
        cache = _read_json(NHL_COUNTRY_CACHE_DEFAULT)
        if isinstance(cache, dict):
            cache2 = {k: v for k, v in cache.items() if isinstance(v, dict) and v.get("ok") is True}
            _write_json(NHL_COUNTRY_CACHE_DEFAULT, cache2)
            st.success(f"Cache cleaned: kept {len(cache2)} ok entries.")
        else:
            st.info("No cache to clean.")

    if reset_btn:
        _write_json(NHL_COUNTRY_CHECKPOINT_DEFAULT, {})
        st.success("Checkpoint reset.")

    if run_btn:
        if not _anti_double_run_guard("country_fill", 0.8):
            st.info("Patiente une seconde (anti double-click).")
        else:
            status_box = st.empty()

            def _cb(stat):
                status_box.info(stat)

            res = update_players_db(
                players_path,
                max_calls=int(max_calls),
                save_every=int(save_every),
                resume_only=bool(resume_only),
                reset_progress=False,
                failed_only=bool(failed_only),
                progress_cb=_cb,
            )
            st.success("Run completed.")
            st.json(res)

    st.divider()

    st.markdown("### 🧷 Backups & Restore (Local + Drive optionnel)")
    st.caption("Local backups sont toujours disponibles. Drive est optionnel (si secrets + libs).")

    backup_dir = st.text_input("Backup folder", value=BACKUP_DIR_DEFAULT)

    critical_files = [
        PLAYERS_DB_PATH_DEFAULT,
        NHL_COUNTRY_CACHE_DEFAULT,
        CLUB_COUNTRY_CACHE_DEFAULT,
        NHL_COUNTRY_CHECKPOINT_DEFAULT,
    ]

    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button("📦 Create local backup (zip)"):
            if not _anti_double_run_guard("backup_zip", 0.8):
                st.info("Patiente une seconde.")
            else:
                os.makedirs(backup_dir, exist_ok=True)
                zp = _zip_backup(backup_dir, critical_files)
                st.success(f"Backup created: {zp}")

    with b2:
        zips = []
        try:
            if os.path.exists(backup_dir):
                zips = sorted([f for f in os.listdir(backup_dir) if f.lower().endswith(".zip")], reverse=True)
        except Exception:
            zips = []
        pick = st.selectbox("Restore from zip", options=[""] + zips)
        if st.button("♻️ Restore selected zip"):
            if not pick:
                st.warning("Choisis un zip.")
            else:
                res = _restore_zip(os.path.join(backup_dir, pick), DATA_DIR)
                if res.get("ok"):
                    st.success("Restore completed. Relance l’app si nécessaire.")
                else:
                    st.error(res.get("error") or "Restore failed")

    with b3:
        st.markdown("**Drive**")
        if _drive_available():
            st.success("Drive: détecté (secrets + libs).")
            st.caption("Intégration Drive complète = prochaine itération (OAuth / folder_id / upload & list).")
        else:
            st.info("Drive: non configuré (normal).")
            st.caption("Pour l’activer: ajouter `gdrive_oauth` dans Secrets + installer googleapiclient.")

    st.divider()
    st.caption("Files used:")
    st.code("Files listed above")


# app.py — Fantrax Pool Hockey (COMPLET)
# ✅ Tooltip hover sur les noms (HTML/CSS)
# ✅ Bouton "Déplacer" (ouvre le pop-up via query params)
# ✅ IR net (1 seul tableau) + IR Date persistée
# ✅ Pop-up stable + historique + Undo
# ✅ Import Fantrax robuste
# ✅ Tab Joueurs (base data/Hockey.Players.csv) + filtres + comparaison

import streamlit as st
import pandas as pd
import io
import os
import re
import html as html_lib
import textwrap
from datetime import datetime
from urllib.parse import quote, unquote
import base64
from zoneinfo import ZoneInfo

# =====================================================
# CONFIG STREAMLIT
# =====================================================
st.set_page_config("Fantrax Pool Hockey", layout="wide")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# -----------------------------------------------------
# Fichiers
# -----------------------------------------------------
PLAYERS_DB_FILE = "data/Hockey.Players.csv"  # ton fichier est dans /data
LOGO_POOL_FILE = "Logo_Pool.png"

# -----------------------------------------------------
# Logos équipes (propriétaires)
# -----------------------------------------------------
LOGOS = {
    "Nordiques": "Nordiques_Logo.png",
    "Cracheurs": "Cracheurs_Logo.png",
    "Prédateurs": "Prédateurs_Logo.png",
    "Red Wings": "Red_Wings_Logo.png",
    "Whalers": "Whalers_Logo.png",
    "Canadiens": "Canadiens_Logo.png",
}
LOGO_SIZE = 55


# =====================================================
# UTILS
# =====================================================
def do_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


def money(v):
    try:
        return f"{int(v):,}".replace(",", " ") + " $"
    except Exception:
        return "0 $"


def saison_auto():
    now = datetime.now()
    return f"{now.year}-{now.year+1}" if now.month >= 9 else f"{now.year-1}-{now.year}"


def saison_verrouillee(season):
    return int(season[:4]) < int(saison_auto()[:4])


def normalize_pos(pos: str) -> str:
    p = str(pos or "").upper()
    if "G" in p:
        return "G"
    if "D" in p:
        return "D"
    return "F"


def pos_sort_key(pos: str) -> int:
    return {"F": 0, "D": 1, "G": 2}.get(str(pos).upper(), 99)


# =====================================================
# CLEAN DATA (robuste)
# =====================================================
REQUIRED_COLS = ["Propriétaire", "Joueur", "Salaire", "Statut", "Slot", "Pos", "Equipe", "IR Date"]


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame(columns=REQUIRED_COLS)

    df = df.copy()

    # s'assure colonnes
    for c in REQUIRED_COLS:
        if c not in df.columns:
            df[c] = ""

    # normalize textes
    for c in ["Propriétaire", "Joueur", "Statut", "Slot", "Pos", "Equipe", "IR Date"]:
        df[c] = df[c].astype(str).fillna("").map(lambda x: re.sub(r"\s+", " ", x).strip())

    # salaire
    def _to_int(x):
        s = str(x).strip().replace(",", "").replace(" ", "")
        s = re.sub(r"[^\d]", "", s)
        return int(s) if s.isdigit() else 0

    df["Salaire"] = df["Salaire"].apply(_to_int).astype(int)

    # statut standard
    df["Statut"] = df["Statut"].replace(
        {
            "GC": "Grand Club",
            "CE": "Club École",
            "Club Ecole": "Club École",
            "GrandClub": "Grand Club",
        }
    )

    # slot standard
    df["Slot"] = df["Slot"].replace(
        {
            "Active": "Actif",
            "Bench": "Banc",
            "IR": "Blessé",
            "Injured": "Blessé",
        }
    )

    # pos standard
    df["Pos"] = df["Pos"].apply(normalize_pos)

    # règles slot selon statut (sécurité)
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

    # drop duplicates (dernier gagne)
    df = df.drop_duplicates(subset=["Propriétaire", "Joueur"], keep="last").reset_index(drop=True)

    return df


# =====================================================
# PLAYERS DB + TOOLTIP HOVER
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

    if name_col is None:
        return dfp

    dfp["_name_key"] = dfp[name_col].astype(str).map(_norm_name)
    return dfp


def get_player_row(players_df: pd.DataFrame, player_name: str) -> dict | None:
    if players_df is None or players_df.empty:
        return None
    if "_name_key" not in players_df.columns:
        return None
    key = _norm_name(player_name)
    hit = players_df[players_df["_name_key"] == key]
    if hit.empty:
        return None
    return hit.iloc[0].to_dict()


def _pick(d: dict, candidates: list[str], default=""):
    for k in candidates:
        if k in d and pd.notna(d[k]) and str(d[k]).strip() != "":
            return str(d[k]).strip()
    return default


def player_tooltip_css():
    st.markdown(
        textwrap.dedent(
            """
        <style>
          .ph-wrap{position:relative;display:inline-block;}
          .ph-name{color:#4aa3ff;font-weight:900;text-decoration:underline;cursor:default;}
          .ph-tip{display:none;position:absolute;left:0;top:28px;width:520px;max-width:70vw;
                  background:rgba(10,14,18,.98);border:1px solid rgba(255,255,255,.10);
                  box-shadow:0 18px 50px rgba(0,0,0,.55);border-radius:18px;overflow:hidden;z-index:9999;}
          .ph-wrap:hover .ph-tip{display:block;}
          .ph-head{display:flex;gap:12px;align-items:center;padding:14px 14px 10px 14px;
                   background:linear-gradient(180deg, rgba(12,18,24,1), rgba(7,10,13,1));}
          .ph-avatar{width:54px;height:54px;border-radius:14px;background:rgba(255,255,255,.06);
                     object-fit:cover;flex:0 0 auto;border:1px solid rgba(255,255,255,.10);}
          .ph-title{font-size:20px;font-weight:1000;color:#4aa3ff;line-height:1.05;margin-bottom:4px;}
          .ph-sub{font-size:13px;color:rgba(255,255,255,.72);font-weight:700;}
          .ph-sub b{color:rgba(255,255,255,.92);}
          .ph-flag{display:inline-flex;gap:8px;align-items:center;margin-top:6px;font-size:13px;
                   color:rgba(255,255,255,.80);font-weight:800;}
          .ph-flag img{width:18px;height:12px;border-radius:2px;border:1px solid rgba(255,255,255,.25);object-fit:cover;}
          .ph-body{padding:12px 14px 14px 14px;}
          .ph-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px 14px;}
          .ph-kv{font-size:13px;color:rgba(255,255,255,.75);font-weight:800;padding:8px 10px;border-radius:12px;
                 background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.07);}
          .ph-kv span{color:rgba(255,255,255,.95);font-weight:1000;margin-left:6px;}
          @media (max-width: 700px){.ph-tip{width:92vw;}}
        </style>
        """
        ),
        unsafe_allow_html=True,
    )


def render_player_hover_name(players_df: pd.DataFrame, player_name: str) -> str:
    row = get_player_row(players_df, player_name) or {}
    name = player_name.strip()

    photo_url = _pick(row, ["Photo", "Headshot", "Image", "photo_url", "headshot_url"], default="")
    team = _pick(row, ["Team", "NHL Team", "Equipe", "Équipe"], default="")
    pos = _pick(row, ["Pos", "Position"], default="")
    jersey = _pick(row, ["Jersey #", "Jersey", "No", "#"], default="")
    shoots = _pick(row, ["Shoots", "Shot", "Tire"], default="")
    height = _pick(row, ["Hgt", "Height", "Taille"], default="")
    weight = _pick(row, ["W(lbs)", "Weight", "Poids"], default="")
    dob = _pick(row, ["DOB", "Birthdate", "Date of Birth", "Naissance"], default="")
    draft = _pick(row, ["Draft Year", "Draft", "Année Repêchage"], default="")
    ufa = _pick(row, ["UFA Year", "UFA", "Autonomie"], default="")
    caphit = _pick(row, ["Cap Hit", "CapHit", "AAV"], default="")
    country = _pick(row, ["Country", "Pays"], default="")
    flag_url = _pick(row, ["Flag", "Flag URL", "Flag_Image"], default="")

    if not photo_url:
        svg = """<svg xmlns='http://www.w3.org/2000/svg' width='54' height='54'>
        <rect width='54' height='54' rx='14' fill='rgba(255,255,255,0.06)'/>
        <circle cx='27' cy='22' r='9' fill='rgba(255,255,255,0.18)'/>
        <rect x='14' y='34' width='26' height='12' rx='6' fill='rgba(255,255,255,0.14)'/>
        </svg>"""
        photo_url = "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("utf-8")

    esc = html_lib.escape
    name_e = esc(name)

    sub_bits = []
    if team:
        sub_bits.append(esc(team))
    if pos:
        sub_bits.append(f"• <b>{esc(pos)}</b>")
    if jersey:
        sub_bits.append(f"• #{esc(jersey)}")
    sub_line = " ".join(sub_bits) if sub_bits else "<span style='opacity:.6'>Info indisponible</span>"

    kv = []

    def add_kv(label, value):
        if value and str(value).strip():
            kv.append((label, str(value).strip()))

    add_kv("Shoots", shoots)
    add_kv("Height", height)
    add_kv("Weight", weight)
    add_kv("DOB", dob)
    add_kv("Draft", draft)
    add_kv("UFA", ufa)
    add_kv("Cap Hit", caphit)

    kv_html = (
        "".join([f"<div class='ph-kv'>{esc(k)}:<span>{esc(v)}</span></div>" for k, v in kv])
        or "<div class='ph-kv'>No details<span>—</span></div>"
    )

    flag_html = ""
    if country or flag_url:
        img = f"<img src='{esc(flag_url)}' />" if flag_url else ""
        flag_html = f"<div class='ph-flag'>{img}<span>{esc(country) if country else ''}</span></div>"

    return f"""
      <span class="ph-wrap">
        <span class="ph-name">{name_e}</span>
        <div class="ph-tip">
          <div class="ph-head">
            <img class="ph-avatar" src="{esc(photo_url)}" />
            <div style="min-width:0;">
              <div class="ph-title">{name_e}</div>
              <div class="ph-sub">{sub_line}</div>
              {flag_html}
            </div>
          </div>
          <div class="ph-body">
            <div class="ph-grid">{kv_html}</div>
          </div>
        </div>
      </span>
    """


# =====================================================
# QUERY PARAMS (compat)
# =====================================================
def _get_qp(key: str):
    if hasattr(st, "query_params"):
        v = st.query_params.get(key)
        if isinstance(v, list):
            return v[0] if v else None
        return v
    qp = st.experimental_get_query_params()
    v = qp.get(key)
    return v[0] if v else None


def _clear_qp(key: str):
    if hasattr(st, "query_params"):
        try:
            st.query_params.pop(key, None)
        except Exception:
            st.query_params[key] = ""
    else:
        st.experimental_set_query_params()


# =====================================================
# SESSION DEFAULTS
# =====================================================
if "uploader_nonce" not in st.session_state:
    st.session_state["uploader_nonce"] = 0
if "PLAFOND_GC" not in st.session_state:
    st.session_state["PLAFOND_GC"] = 95_500_000
if "PLAFOND_CE" not in st.session_state:
    st.session_state["PLAFOND_CE"] = 47_750_000
if "move_ctx" not in st.session_state:
    st.session_state["move_ctx"] = None
if "move_nonce" not in st.session_state:
    st.session_state["move_nonce"] = 0


def set_move_ctx(owner: str, joueur: str):
    st.session_state["move_nonce"] = st.session_state.get("move_nonce", 0) + 1
    st.session_state["move_ctx"] = {"owner": owner, "joueur": joueur, "nonce": st.session_state["move_nonce"]}


def clear_move_ctx():
    st.session_state["move_ctx"] = None


# =====================================================
# HISTORY
# =====================================================
def load_history(history_file: str) -> pd.DataFrame:
    if os.path.exists(history_file):
        return pd.read_csv(history_file)
    return pd.DataFrame(
        columns=[
            "id",
            "timestamp",
            "season",
            "proprietaire",
            "joueur",
            "pos",
            "equipe",
            "from_statut",
            "from_slot",
            "to_statut",
            "to_slot",
            "action",
        ]
    )


def save_history(history_file: str, h: pd.DataFrame):
    h.to_csv(history_file, index=False)


def next_hist_id(h: pd.DataFrame) -> int:
    if h.empty or "id" not in h.columns:
        return 1
    return int(pd.to_numeric(h["id"], errors="coerce").fillna(0).max()) + 1


def log_history_row(proprietaire, joueur, pos, equipe, from_statut, from_slot, to_statut, to_slot, action):
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
# APPLY MOVE (avec IR Date persistée)
# =====================================================
def apply_move_with_history(proprietaire: str, joueur: str, to_statut: str, to_slot: str, action_label: str) -> bool:
    if st.session_state.get("LOCKED"):
        st.error("🔒 Saison verrouillée : modification impossible.")
        return False

    df0 = st.session_state.get("data")
    if df0 is None or df0.empty:
        st.error("Aucune donnée en mémoire.")
        return False

    if "IR Date" not in df0.columns:
        df0["IR Date"] = ""

    to_statut = str(to_statut).strip()
    to_slot = str(to_slot).strip()

    allowed_slots_gc = {"Actif", "Banc", "Blessé"}
    allowed_slots_ce = {"", "Blessé"}

    if to_statut == "Grand Club" and to_slot not in allowed_slots_gc:
        st.error(f"Slot invalide pour Grand Club: {to_slot}")
        return False
    if to_statut == "Club École" and to_slot not in allowed_slots_ce:
        st.error(f"Slot invalide pour Club École: {to_slot}")
        return False

    mask = (df0["Propriétaire"] == proprietaire) & (df0["Joueur"] == joueur)
    if df0[mask].empty:
        st.error("Joueur introuvable pour ce propriétaire.")
        return False

    before = df0[mask].iloc[0]
    from_statut = str(before.get("Statut", "")).strip()
    from_slot = str(before.get("Slot", "")).strip()
    pos0 = str(before.get("Pos", "F")).strip()
    equipe0 = str(before.get("Equipe", "")).strip()

    # Apply
    df0.loc[mask, "Statut"] = to_statut
    df0.loc[mask, "Slot"] = to_slot if to_slot else ""

    # IR Date
    entering_ir = (to_slot == "Blessé") and (from_slot != "Blessé")
    leaving_ir = (from_slot == "Blessé") and (to_slot != "Blessé")
    if entering_ir:
        now_tor = datetime.now(ZoneInfo("America/Toronto"))
        df0.loc[mask, "IR Date"] = now_tor.strftime("%Y-%m-%d %H:%M")
    elif leaving_ir:
        df0.loc[mask, "IR Date"] = ""

    df0 = clean_data(df0)
    st.session_state["data"] = df0

    try:
        df0.to_csv(st.session_state["DATA_FILE"], index=False)
    except Exception as e:
        st.error(f"Erreur sauvegarde CSV: {e}")
        return False

    try:
        log_history_row(
            proprietaire=proprietaire,
            joueur=joueur,
            pos=pos0,
            equipe=equipe0,
            from_statut=from_statut,
            from_slot=from_slot,
            to_statut=to_statut,
            to_slot=(to_slot if to_slot else ""),
            action=action_label,
        )
    except Exception as e:
        st.warning(f"⚠️ Déplacement OK, mais historique non écrit: {e}")

    return True


# =====================================================
# FANTRAX PARSER
# =====================================================
def parse_fantrax(upload):
    raw_lines = upload.read().decode("utf-8", errors="ignore").splitlines()
    raw_lines = [re.sub(r"[\x00-\x1f\x7f]", "", l) for l in raw_lines]  # nettoie chars invisibles

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

    # fantrax salary souvent en milliers => *1000
    sal = (
        df[salary_col]
        .astype(str)
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
# TABLE HTML (hover + bouton Déplacer)
# =====================================================
def render_table_with_hover(df_src: pd.DataFrame, qp_key: str, title: str, max_height: int = 360, show_ir_date: bool = False):
    if df_src is None or df_src.empty:
        st.info("Aucun joueur.")
        return

    d = df_src.copy()
    d["Pos"] = d["Pos"].apply(normalize_pos)
    d["_pos_order"] = d["Pos"].apply(pos_sort_key)
    d = d.sort_values(["_pos_order", "Joueur"]).drop(columns=["_pos_order"]).reset_index(drop=True)

    d["Salaire_fmt"] = d["Salaire"].apply(money) if "Salaire" in d.columns else ""
    if "IR Date" in d.columns:
        d["IR Date_fmt"] = d["IR Date"].astype(str).str.strip()
        d.loc[d["IR Date_fmt"].eq(""), "IR Date_fmt"] = "—"
    else:
        d["IR Date_fmt"] = "—"

    st.markdown(
        textwrap.dedent(
            f"""
        <style>
          .tbl-card{{background:#000;border:1px solid rgba(255,255,255,.10);border-radius:16px;overflow:hidden;}}
          .tbl-head{{padding:10px 14px;border-bottom:1px solid rgba(255,255,255,.10);font-weight:1000;}}
          .tbl-wrap{{max-height:{max_height}px;overflow:auto;}}
          table.tbl{{width:100%;border-collapse:separate;border-spacing:0;color:#f5f5f5;font-weight:800;font-size:14px;}}
          table.tbl th{{text-align:left;padding:10px 12px;position:sticky;top:0;background:rgba(8,8,8,.95);
                        border-bottom:1px solid rgba(255,255,255,.10);z-index:2;font-weight:1000;white-space:nowrap;}}
          table.tbl td{{padding:10px 12px;border-bottom:1px solid rgba(255,255,255,.06);white-space:nowrap;}}
          table.tbl tbody tr:hover td{{background:rgba(255,255,255,.04);}}
          .td-pos{{width:60px;text-align:center;opacity:.9;}}
          .td-team{{width:84px;text-align:center;opacity:.9;}}
          .td-sal{{text-align:right;}}
          .td-ir{{width:150px;opacity:.9;}}
          .btn-move{{display:inline-block;padding:6px 10px;border-radius:999px;border:1px solid rgba(255,255,255,.18);
                     text-decoration:none;color:#fff;font-weight:900;background:rgba(255,255,255,.06);}}
          .btn-move:hover{{background:rgba(255,255,255,.12);}}
        </style>
        """
        ),
        unsafe_allow_html=True,
    )

    rows_html = ""
    for _, rr in d.iterrows():
        raw_name = str(rr.get("Joueur", "")).strip()
        if not raw_name:
            continue

        name_hover_html = render_player_hover_name(players_db, raw_name)

        pos = html_lib.escape(str(rr.get("Pos", "")))
        team = html_lib.escape(str(rr.get("Equipe", "")))
        ir_date = html_lib.escape(str(rr.get("IR Date_fmt", "—")))
        sal = html_lib.escape(str(rr.get("Salaire_fmt", "")))

        q = quote(raw_name)
        action = f"<a class='btn-move' href='?{qp_key}={q}'>Déplacer</a>"

        if show_ir_date:
            rows_html += (
                "<tr>"
                f"<td>{name_hover_html}</td>"
                f"<td class='td-pos'>{pos}</td>"
                f"<td class='td-team'>{team}</td>"
                f"<td class='td-ir'>{ir_date}</td>"
                f"<td class='td-sal'>{sal}</td>"
                f"<td>{action}</td>"
                "</tr>"
            )
        else:
            rows_html += (
                "<tr>"
                f"<td>{name_hover_html}</td>"
                f"<td class='td-pos'>{pos}</td>"
                f"<td class='td-team'>{team}</td>"
                f"<td class='td-sal'>{sal}</td>"
                f"<td>{action}</td>"
                "</tr>"
            )

    if show_ir_date:
        thead = """
          <tr>
            <th>Joueur</th>
            <th class="td-pos">Pos</th>
            <th class="td-team">Équipe</th>
            <th class="td-ir">Date IR</th>
            <th class="td-sal">Salaire</th>
            <th>Action</th>
          </tr>
        """
    else:
        thead = """
          <tr>
            <th>Joueur</th>
            <th class="td-pos">Pos</th>
            <th class="td-team">Équipe</th>
            <th class="td-sal">Salaire</th>
            <th>Action</th>
          </tr>
        """

    html_block = textwrap.dedent(
        f"""
    <div class="tbl-card">
      <div class="tbl-head">{html_lib.escape(title)}</div>
      <div class="tbl-wrap">
        <table class="tbl">
          <thead>{thead}</thead>
          <tbody>{rows_html}</tbody>
        </table>
      </div>
    </div>
    """
    ).strip()

    st.markdown(html_block, unsafe_allow_html=True)


# =====================================================
# POP-UP (dialog)
# =====================================================
def open_move_dialog():
    ctx = st.session_state.get("move_ctx")
    if not ctx:
        return

    if st.session_state.get("LOCKED"):
        st.warning("🔒 Saison verrouillée : aucun changement permis.")
        clear_move_ctx()
        return

    owner = ctx["owner"]
    joueur = ctx["joueur"]
    nonce = ctx.get("nonce", 0)

    df_all = st.session_state["data"]
    mask = (df_all["Propriétaire"] == owner) & (df_all["Joueur"] == joueur)
    if df_all[mask].empty:
        st.error("Joueur introuvable.")
        clear_move_ctx()
        return

    row = df_all[mask].iloc[0]
    cur_statut = str(row["Statut"])
    cur_slot = str(row.get("Slot", "")).strip()
    cur_pos = normalize_pos(row.get("Pos", "F"))
    cur_equipe = str(row.get("Equipe", ""))
    cur_salaire = int(row.get("Salaire", 0))

    counts = st.session_state.get("align_counts", {"F": 0, "D": 0, "G": 0})
    f_count = int(counts.get("F", 0))
    d_count = int(counts.get("D", 0))
    g_count = int(counts.get("G", 0))

    def can_go_actif(pos: str):
        if pos == "F" and f_count >= 12:
            return False, "🚫 Déjà 12 F actifs."
        if pos == "D" and d_count >= 6:
            return False, "🚫 Déjà 6 D actifs."
        if pos == "G" and g_count >= 2:
            return False, "🚫 Déjà 2 G actifs."
        return True, ""

    @st.dialog(f"Déplacement — {joueur}", width="large")
    def _dlg():
        st.markdown(f"**{owner}** • **{joueur}** • **{cur_pos}** • **{cur_equipe}** • **{money(cur_salaire)}**")
        st.caption(f"Position actuelle : **{cur_statut}**" + (f" / **{cur_slot}**" if cur_slot else ""))
        st.divider()

        destinations = [
            ("🟢 Grand Club / Actif", ("Grand Club", "Actif")),
            ("🟡 Grand Club / Banc", ("Grand Club", "Banc")),
            ("🔵 Mineur", ("Club École", "")),
            ("🩹 Joueurs Blessés (IR)", (cur_statut, "Blessé")),
        ]

        current = (cur_statut, cur_slot if cur_slot else "")
        destinations = [d for d in destinations if d[1] != current]

        if cur_slot == "Blessé":
            destinations = [d for d in destinations if d[1][1] != "Blessé"]

        if not destinations:
            st.info("Aucune destination disponible pour ce joueur.")
            if st.button("✖️ Fermer", key=f"close_{owner}_{joueur}_{nonce}", use_container_width=True):
                clear_move_ctx()
                do_rerun()
            return

        choice = st.radio(
            "Choisir la destination :",
            [d[0] for d in destinations],
            index=0,
            key=f"dest_{owner}_{joueur}_{nonce}",
        )
        to_statut, to_slot = dict(destinations)[choice]

        st.divider()
        c1, c2 = st.columns(2)

        if c1.button(
            "✅ Confirmer le déplacement",
            key=f"confirm_{owner}_{joueur}_{nonce}",
            use_container_width=True,
            type="primary",
        ):
            if to_statut == "Grand Club" and to_slot == "Actif":
                ok, msg = can_go_actif(cur_pos)
                if not ok:
                    st.error(msg)
                    return

            ok2 = apply_move_with_history(
                proprietaire=owner,
                joueur=joueur,
                to_statut=to_statut,
                to_slot=to_slot,
                action_label=f"{cur_statut}/{cur_slot or '-'} → {to_statut}/{to_slot or '-'}",
            )

            if ok2:
                clear_move_ctx()

                if to_slot == "Blessé":
                    st.toast(f"🩹 {joueur} → Liste des blessés", icon="🩹")
                elif to_statut == "Grand Club" and to_slot == "Actif":
                    st.toast(f"🟢 {joueur} → Grand Club (Actif)", icon="🟢")
                elif to_statut == "Grand Club" and to_slot == "Banc":
                    st.toast(f"🟡 {joueur} → Banc", icon="🟡")
                elif to_statut == "Club École":
                    st.toast(f"🔵 {joueur} → Mineur", icon="🔵")
                else:
                    st.toast(f"✅ Déplacement enregistré pour {joueur}", icon="✅")

                do_rerun()

        if c2.button("❌ Annuler", key=f"cancel_{owner}_{joueur}_{nonce}", use_container_width=True):
            clear_move_ctx()
            do_rerun()

    _dlg()


# =====================================================
# SIDEBAR — Saison & plafonds
# =====================================================
st.sidebar.header("📅 Saison")
saisons = ["2024-2025", "2025-2026", "2026-2027"]
auto = saison_auto()
if auto not in saisons:
    saisons.append(auto)
    saisons.sort()

season = st.sidebar.selectbox("Saison", saisons, index=saisons.index(auto))
LOCKED = saison_verrouillee(season)

DATA_FILE = f"{DATA_DIR}/fantrax_{season}.csv"
HISTORY_FILE = f"{DATA_DIR}/history_{season}.csv"
st.session_state["DATA_FILE"] = DATA_FILE
st.session_state["HISTORY_FILE"] = HISTORY_FILE
st.session_state["LOCKED"] = LOCKED

st.sidebar.divider()
st.sidebar.header("💰 Plafonds")
if st.sidebar.button("✏️ Modifier les plafonds"):
    st.session_state["edit_plafond"] = True

if st.session_state.get("edit_plafond"):
    st.session_state["PLAFOND_GC"] = st.sidebar.number_input(
        "Plafond Grand Club", value=int(st.session_state["PLAFOND_GC"]), step=500_000
    )
    st.session_state["PLAFOND_CE"] = st.sidebar.number_input(
        "Plafond Club École", value=int(st.session_state["PLAFOND_CE"]), step=250_000
    )

st.sidebar.metric("🏒 Grand Club", money(st.session_state["PLAFOND_GC"]))
st.sidebar.metric("🏫 Club École", money(st.session_state["PLAFOND_CE"]))

# =====================================================
# LOAD DATA / HISTORY quand saison change
# =====================================================
if "season" not in st.session_state or st.session_state["season"] != season:
    if os.path.exists(DATA_FILE):
        st.session_state["data"] = pd.read_csv(DATA_FILE)
    else:
        st.session_state["data"] = pd.DataFrame(columns=REQUIRED_COLS)

    st.session_state["data"] = clean_data(st.session_state["data"])
    st.session_state["data"].to_csv(DATA_FILE, index=False)
    st.session_state["season"] = season

if "history_season" not in st.session_state or st.session_state["history_season"] != season:
    st.session_state["history"] = load_history(HISTORY_FILE)
    st.session_state["history_season"] = season

# =====================================================
# IMPORT FANTRAX
# =====================================================
st.sidebar.header("📥 Import Fantrax")
uploaded = st.sidebar.file_uploader(
    "CSV Fantrax",
    type=["csv", "txt"],
    help="Le fichier peut contenir Skaters et Goalies séparés par une ligne vide.",
    key=f"fantrax_uploader_{st.session_state['uploader_nonce']}",
)

if uploaded is not None:
    if LOCKED:
        st.sidebar.warning("🔒 Saison verrouillée : import désactivé.")
    else:
        try:
            df_import = parse_fantrax(uploaded)
            if df_import is None or df_import.empty:
                st.sidebar.error("❌ Import invalide : aucune donnée exploitable.")
            else:
                owner = os.path.splitext(uploaded.name)[0]
                df_import["Propriétaire"] = owner

                st.session_state["data"] = pd.concat([st.session_state["data"], df_import], ignore_index=True)
                st.session_state["data"] = clean_data(st.session_state["data"])
                st.session_state["data"].to_csv(DATA_FILE, index=False)
                st.sidebar.success("✅ Import réussi")

                st.session_state["uploader_nonce"] += 1
                do_rerun()
        except Exception as e:
            st.sidebar.error(f"❌ Import échoué : {e}")

# =====================================================
# HEADER
# =====================================================
if os.path.exists(LOGO_POOL_FILE):
    st.image(LOGO_POOL_FILE, use_container_width=True)

st.title("🏒 Fantrax – Gestion Salariale")

df = st.session_state["data"]
if df.empty:
    st.info("Aucune donnée")
    st.stop()

# =====================================================
# Load players DB + inject tooltip CSS (UNE FOIS)
# =====================================================
players_db = load_players_db(PLAYERS_DB_FILE)
player_tooltip_css()

# =====================================================
# CALCULS PLAFONDS (EXCLUT BLESSÉS)
# =====================================================
resume = []
for p in df["Propriétaire"].unique():
    d = df[df["Propriétaire"] == p]
    gc = d[(d["Statut"] == "Grand Club") & (d["Slot"] != "Blessé")]["Salaire"].sum()
    ce = d[(d["Statut"] == "Club École") & (d["Slot"] != "Blessé")]["Salaire"].sum()

    logo = ""
    for k, v in LOGOS.items():
        if k.lower() in str(p).lower():
            logo = v

    resume.append(
        {
            "Propriétaire": p,
            "Logo": logo,
            "GC": int(gc),
            "Restant GC": int(st.session_state["PLAFOND_GC"] - gc),
            "CE": int(ce),
            "Restant CE": int(st.session_state["PLAFOND_CE"] - ce),
        }
    )
plafonds = pd.DataFrame(resume)

# =====================================================
# TABS
# =====================================================
tab1, tabA, tabJ, tabH, tab2, tab3 = st.tabs(
    ["📊 Tableau", "🧾 Alignement", "👤 Joueurs", "🕘 Historique", "⚖️ Transactions", "🧠 Recommandations"]
)

# =====================================================
# TAB 1 — Tableau
# =====================================================
with tab1:
    headers = st.columns([4, 2, 2, 2, 2])
    headers[0].markdown("**Équipe**")
    headers[1].markdown("**Total GC**")
    headers[2].markdown("**Restant GC**")
    headers[3].markdown("**Total CE**")
    headers[4].markdown("**Restant CE**")

    for _, r in plafonds.iterrows():
        cols = st.columns([4, 2, 2, 2, 2])
        owner = str(r["Propriétaire"])
        logo_path = str(r["Logo"]).strip()

        with cols[0]:
            a, b = st.columns([1, 4])
            if logo_path and os.path.exists(logo_path):
                a.image(logo_path, width=LOGO_SIZE)
            else:
                a.markdown("—")
            b.markdown(f"**{owner}**")

        cols[1].markdown(money(r["GC"]))
        cols[2].markdown(money(r["Restant GC"]))
        cols[3].markdown(money(r["CE"]))
        cols[4].markdown(money(r["Restant CE"]))

# =====================================================
# TAB A — Alignement (hover + bouton Déplacer) + IR
# =====================================================
with tabA:
    st.subheader("🧾 Alignement")
    st.caption("Hover sur le nom = carte du joueur. Clique 'Déplacer' = ouvre le pop-up.")

    proprietaire = st.selectbox(
        "Propriétaire",
        sorted(st.session_state["data"]["Propriétaire"].unique()),
        key="align_owner",
    )

    # Click "Déplacer" via query param
    picked_qp = _get_qp("pick")
    if picked_qp:
        picked_qp = unquote(picked_qp).strip()
        if picked_qp:
            set_move_ctx(proprietaire, picked_qp)
        _clear_qp("pick")
        do_rerun()

    st.session_state["data"] = clean_data(st.session_state["data"])
    data_all = st.session_state["data"]
    dprop = data_all[data_all["Propriétaire"] == proprietaire].copy()

    injured_all = dprop[dprop.get("Slot", "") == "Blessé"].copy()
    dprop_not_inj = dprop[dprop.get("Slot", "") != "Blessé"].copy()

    gc_all = dprop_not_inj[dprop_not_inj["Statut"] == "Grand Club"].copy()
    ce_all = dprop_not_inj[dprop_not_inj["Statut"] == "Club École"].copy()

    gc_actif = gc_all[gc_all.get("Slot", "") == "Actif"].copy()
    gc_banc = gc_all[gc_all.get("Slot", "") == "Banc"].copy()

    # counts actifs
    tmp = gc_actif.copy()
    tmp["Pos"] = tmp["Pos"].apply(normalize_pos)
    nb_F = int((tmp["Pos"] == "F").sum())
    nb_D = int((tmp["Pos"] == "D").sum())
    nb_G = int((tmp["Pos"] == "G").sum())

    total_gc = int(gc_all["Salaire"].sum())
    total_ce = int(ce_all["Salaire"].sum())
    restant_gc = int(st.session_state["PLAFOND_GC"] - total_gc)
    restant_ce = int(st.session_state["PLAFOND_CE"] - total_ce)

    st.session_state["align_counts"] = {"F": nb_F, "D": nb_D, "G": nb_G}

    top = st.columns([1, 1, 1, 1, 1])
    top[0].metric("GC", money(total_gc))
    top[1].metric("R GC", money(restant_gc))
    top[2].metric("CE", money(total_ce))
    top[3].metric("R CE", money(restant_ce))
    top[4].metric("Blessés", f"{len(injured_all)}")

    st.caption(f"Actifs: F {nb_F}/12 • D {nb_D}/6 • G {nb_G}/2")
    st.divider()

    c1, c2, c3 = st.columns(3)
    with c1:
        render_table_with_hover(gc_actif, qp_key="pick", title="🟢 Actifs", max_height=320, show_ir_date=False)
    with c2:
        render_table_with_hover(gc_banc, qp_key="pick", title="🟡 Banc", max_height=320, show_ir_date=False)
    with c3:
        render_table_with_hover(ce_all, qp_key="pick", title="🔵 Mineur", max_height=320, show_ir_date=False)

    st.divider()
    render_table_with_hover(injured_all, qp_key="pick", title="🩹 Joueurs Blessés (IR) — Salaire non comptabilisé", max_height=380, show_ir_date=True)

    # IMPORTANT : appeler le pop-up à la fin
    open_move_dialog()

# =====================================================
# TAB J — Joueurs (Autonomes) + comparaison
# =====================================================
with tabJ:
    st.subheader("👤 Joueurs (Autonomes)")
    st.caption("Aucun résultat tant qu’aucun filtre n’est rempli (Nom/Prénom, Équipe, Level/Contrat ou Cap Hit).")

    df_db = players_db.copy()
    if df_db.empty:
        st.error(f"Impossible de charger la base joueurs: {PLAYERS_DB_FILE}")
        st.stop()

    if "Player" not in df_db.columns:
        # tentatives auto
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

    has_any_filter = bool(q_name.strip()) or (q_team != "Toutes") or (q_level != "Tous") or bool(cap_apply)

    if not has_any_filter:
        st.info("Entre au moins un filtre pour afficher les résultats.")
    else:
        dff = df_db.copy()

        if q_name.strip():
            dff = dff[dff["Player"].astype(str).str.contains(q_name, case=False, na=False)]
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
            st.divider()
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

    st.divider()
    st.markdown("### 📊 Comparer 2 joueurs")

    players_list = sorted(df_db["Player"].dropna().astype(str).unique().tolist())

    def _filter_names(q: str, names: list[str], limit: int = 40) -> list[str]:
        q = str(q or "").strip().lower()
        if not q:
            return names[:limit]
        out = [n for n in names if q in n.lower()]
        return out[:limit]

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
# TAB H — Historique + Undo + Delete
# =====================================================
with tabH:
    st.subheader("🕘 Historique des changements d’alignement")

    h = st.session_state["history"].copy()
    if h.empty:
        st.info("Aucune entrée d’historique pour cette saison.")
    else:
        owners = ["Tous"] + sorted(h["proprietaire"].dropna().astype(str).unique().tolist())
        owner_filter = st.selectbox("Filtrer par propriétaire", owners, key="hist_owner_filter")

        if owner_filter != "Tous":
            h = h[h["proprietaire"].astype(str) == owner_filter]

        if h.empty:
            st.info("Aucune entrée pour ce propriétaire.")
        else:
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
                rid = int(r["id"])
                cols = st.columns([1.5, 1.4, 2.4, 1.0, 1.6, 1.6, 2.0, 0.8, 0.7])

                cols[0].markdown(str(r["timestamp"]))
                cols[1].markdown(str(r["proprietaire"]))
                cols[2].markdown(str(r["joueur"]))
                cols[3].markdown(str(r["pos"]))

                de = f"{r['from_statut']}" + (f" ({r['from_slot']})" if str(r["from_slot"]).strip() else "")
                vers = f"{r['to_statut']}" + (f" ({r['to_slot']})" if str(r["to_slot"]).strip() else "")
                cols[4].markdown(de)
                cols[5].markdown(vers)
                cols[6].markdown(str(r.get("action", "")))

                if cols[7].button("↩️", key=f"undo_{rid}"):
                    if LOCKED:
                        st.error("🔒 Saison verrouillée : annulation impossible.")
                    else:
                        owner = str(r["proprietaire"])
                        joueur = str(r["joueur"])
                        mask = (st.session_state["data"]["Propriétaire"] == owner) & (st.session_state["data"]["Joueur"] == joueur)

                        if st.session_state["data"][mask].empty:
                            st.error("Impossible d'annuler : joueur introuvable.")
                        else:
                            before = st.session_state["data"][mask].iloc[0]
                            cur_statut = str(before.get("Statut", ""))
                            cur_slot = str(before.get("Slot", "")).strip()
                            pos0 = str(before.get("Pos", "F"))
                            equipe0 = str(before.get("Equipe", ""))

                            st.session_state["data"].loc[mask, "Statut"] = str(r["from_statut"])
                            st.session_state["data"].loc[mask, "Slot"] = str(r["from_slot"]) if str(r["from_slot"]).strip() else ""

                            st.session_state["data"] = clean_data(st.session_state["data"])
                            st.session_state["data"].to_csv(DATA_FILE, index=False)

                            log_history_row(
                                owner,
                                joueur,
                                pos0,
                                equipe0,
                                cur_statut,
                                cur_slot,
                                str(r["from_statut"]),
                                (str(r["from_slot"]) if str(r["from_slot"]).strip() else ""),
                                action=f"UNDO #{rid}",
                            )

                            st.toast("↩️ Changement annulé", icon="↩️")
                            do_rerun()

                if cols[8].button("❌", key=f"del_{rid}"):
                    h2 = st.session_state["history"].copy()
                    h2 = h2[h2["id"] != rid]
                    st.session_state["history"] = h2
                    save_history(HISTORY_FILE, h2)
                    st.toast("🗑️ Entrée supprimée", icon="🗑️")
                    do_rerun()

# =====================================================
# TAB 2 — Transactions (validation plafonds)
# =====================================================
with tab2:
    p = st.selectbox("Propriétaire", plafonds["Propriétaire"], key="tx_owner")
    salaire = st.number_input("Salaire du joueur", min_value=0, step=100000, key="tx_salary")
    statut = st.radio("Statut", ["Grand Club", "Club École"], key="tx_statut")

    ligne = plafonds[plafonds["Propriétaire"] == p].iloc[0]
    reste = ligne["Restant GC"] if statut == "Grand Club" else ligne["Restant CE"]

    if salaire > reste:
        st.error("🚨 Dépassement du plafond")
    else:
        st.success("✅ Transaction valide")

# =====================================================
# TAB 3 — Recommandations (simple)
# =====================================================
with tab3:
    for _, r in plafonds.iterrows():
        if r["Restant GC"] < 2_000_000:
            st.warning(f"{r['Propriétaire']} : rétrogradation recommandée")
        if r["Restant CE"] > 10_000_000:
            st.info(f"{r['Propriétaire']} : rappel possible")

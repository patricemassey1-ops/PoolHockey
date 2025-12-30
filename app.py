import streamlit as st
import pandas as pd
import io
import os
import re
from datetime import datetime

# =====================================================
# CONFIG
# =====================================================
st.set_page_config("Fantrax Pool Hockey", layout="wide")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# =====================================================
# PLAFONDS (MODIFIABLES)
# =====================================================
if "PLAFOND_GC" not in st.session_state:
    st.session_state["PLAFOND_GC"] = 95_500_000
if "PLAFOND_CE" not in st.session_state:
    st.session_state["PLAFOND_CE"] = 47_750_000

# =====================================================
# LOGOS
# =====================================================
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
# SAISON AUTO
# =====================================================
def saison_auto():
    now = datetime.now()
    return f"{now.year}-{now.year+1}" if now.month >= 9 else f"{now.year-1}-{now.year}"

def saison_verrouillee(season):
    return int(season[:4]) < int(saison_auto()[:4])

# =====================================================
# FORMAT $
# =====================================================
def money(v):
    try:
        return f"{int(v):,}".replace(",", " ") + " $"
    except Exception:
        return "0 $"

# =====================================================
# POSITIONS (F, D, G) + TRI
# =====================================================
def normalize_pos(pos: str) -> str:
    p = str(pos).upper()
    if "G" in p:
        return "G"
    if "D" in p:
        return "D"
    return "F"

def pos_sort_key(pos: str) -> int:
    return {"F": 0, "D": 1, "G": 2}.get(str(pos).upper(), 99)

# =====================================================
# NETTOYAGE GLOBAL
# - enlève None/Skaters/Goalies
# - aucun doublon (Propriétaire, Joueur)
# - support Slot = Blessé
# =====================================================
def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    for col in ["Propriétaire", "Joueur", "Salaire", "Statut", "Slot", "Pos", "Equipe"]:
        if col not in df.columns:
            df[col] = "" if col != "Salaire" else 0

    df["Propriétaire"] = df["Propriétaire"].astype(str).str.strip()
    df["Joueur"] = df["Joueur"].astype(str).str.strip()
    df["Equipe"] = df["Equipe"].astype(str).str.strip()
    df["Statut"] = df["Statut"].astype(str).str.strip()
    df["Slot"] = df["Slot"].astype(str).str.strip()
    df["Pos"] = df["Pos"].astype(str).str.strip()

    # Normalise slot blessé
    df["Slot"] = df["Slot"].replace(
        {"IR": "Blessé", "Blesse": "Blessé", "Blesses": "Blessé", "Injured": "Blessé", "INJ": "Blessé"}
    )

    # Salaire -> int (accepte "12 500 000 $" etc.)
    df["Salaire"] = (
        df["Salaire"]
        .astype(str)
        .str.replace("$", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace(",", "", regex=False)
        .replace(["None", "nan", "NaN", ""], "0")
    )
    df["Salaire"] = pd.to_numeric(df["Salaire"], errors="coerce").fillna(0).astype(int)

    # Positions
    df["Pos"] = df["Pos"].apply(normalize_pos)

    # Retire lignes parasites / titres de sections
    forbidden = {"none", "skaters", "goalies", "player", "null"}
    df = df[~df["Joueur"].str.lower().isin(forbidden)]
    df = df[df["Joueur"].str.len() > 2]

    # Retire ligne vide typique entre sections: salaire 0 + équipe vide/none
    df = df[
        ~(
            (df["Salaire"] <= 0)
            & (df["Equipe"].str.lower().isin(["none", "nan", "", "n/a"]))
        )
    ]

    # Slot par défaut : Grand Club => Actif si vide
    mask_gc_default = (df["Statut"] == "Grand Club") & (df["Slot"].fillna("").eq(""))
    df.loc[mask_gc_default, "Slot"] = "Actif"

    # Club École => slot vide (sauf Blessé)
    mask_ce = (df["Statut"] == "Club École") & (df["Slot"] != "Blessé")
    df.loc[mask_ce, "Slot"] = ""

    # Aucun doublon peu importe le propriétaire
    df = df.drop_duplicates(subset=["Propriétaire", "Joueur"], keep="last")

    return df.reset_index(drop=True)

# =====================================================
# PARSER FANTRAX (Skaters + Goalies séparés par ligne vide)
# - Ajoute Equipe (Team)
# - Salaire en milliers -> x1000
# =====================================================
def parse_fantrax(upload):
    raw_lines = upload.read().decode("utf-8", errors="ignore").splitlines()
    # Nettoie chars invisibles
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

    header_idxs = [
        i for i, l in enumerate(raw_lines)
        if ("player" in l.lower() and "salary" in l.lower() and sep in l)
    ]
    if not header_idxs:
        raise ValueError("Colonnes Fantrax non détectées (Player/Salary).")

    def read_section(start, end):
        lines = raw_lines[start:end]
        lines = [l for l in lines if l.strip() != ""]
        if len(lines) < 2:
            return None
        dfp = pd.read_csv(
            io.StringIO("\n".join(lines)),
            sep=sep,
            engine="python",
            on_bad_lines="skip",
        )
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
        df[salary_col]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.replace(" ", "", regex=False)
        .replace(["None", "nan", "NaN", ""], "0")
    )
    out["Salaire"] = pd.to_numeric(sal, errors="coerce").fillna(0).astype(int) * 1000

    if status_col:
        out["Statut"] = df[status_col].apply(
            lambda x: "Club École" if "min" in str(x).lower() else "Grand Club"
        )
    else:
        out["Statut"] = "Grand Club"

    out["Slot"] = out["Statut"].apply(lambda s: "Actif" if s == "Grand Club" else "")
    out = clean_data(out)
    return out

# =====================================================
# CAP HELPERS (Blessé = non compté)
# =====================================================
def counted_bucket(statut: str, slot: str):
    if str(slot).strip() == "Blessé":
        return None
    if statut == "Grand Club":
        return "GC"
    if statut == "Club École":
        return "CE"
    return None

# =====================================================
# SELECTION HELPERS
# =====================================================
def clear_df_selections():
    for k in ["sel_actifs", "sel_banc", "sel_min"]:
        if k in st.session_state and isinstance(st.session_state[k], dict):
            st.session_state[k]["selection"] = {"rows": []}

def set_move_ctx(owner: str, joueur: str):
    # nonce unique pour éviter conflits de keys dans le dialog
    st.session_state["move_nonce"] = st.session_state.get("move_nonce", 0) + 1
    st.session_state["move_ctx"] = {"owner": owner, "joueur": joueur, "nonce": st.session_state["move_nonce"]}

def clear_move_ctx():
    st.session_state["move_ctx"] = None

def pick_from_df(df_ui: pd.DataFrame, key_state: str) -> str:
    sel = st.session_state.get(key_state, {})
    rows = sel.get("selection", {}).get("rows", [])
    if rows:
        i = rows[0]
        if 0 <= i < len(df_ui):
            return str(df_ui.iloc[i]["Joueur"])
    return ""

# =====================================================
# HISTORY HELPERS
# =====================================================
def load_history(history_file: str) -> pd.DataFrame:
    if os.path.exists(history_file):
        h = pd.read_csv(history_file)
    else:
        h = pd.DataFrame(columns=[
            "id", "timestamp", "season",
            "proprietaire", "joueur", "pos", "equipe",
            "from_statut", "from_slot",
            "to_statut", "to_slot",
            "action"
        ])
    return h

def save_history(history_file: str, h: pd.DataFrame):
    h.to_csv(history_file, index=False)

def next_hist_id(h: pd.DataFrame) -> int:
    if h.empty or "id" not in h.columns:
        return 1
    return int(pd.to_numeric(h["id"], errors="coerce").fillna(0).max()) + 1

# =====================================================
# SIDEBAR - Saison + plafonds
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
# DATA LOAD
# =====================================================
if "season" not in st.session_state or st.session_state["season"] != season:
    if os.path.exists(DATA_FILE):
        st.session_state["data"] = pd.read_csv(DATA_FILE)
    else:
        st.session_state["data"] = pd.DataFrame(
            columns=["Propriétaire", "Joueur", "Salaire", "Statut", "Slot", "Pos", "Equipe"]
        )

    if "Slot" not in st.session_state["data"].columns:
        st.session_state["data"]["Slot"] = ""

    st.session_state["data"] = clean_data(st.session_state["data"])
    st.session_state["data"].to_csv(DATA_FILE, index=False)
    st.session_state["season"] = season

if "history_season" not in st.session_state or st.session_state["history_season"] != season:
    st.session_state["history"] = load_history(HISTORY_FILE)
    st.session_state["history_season"] = season

if "move_ctx" not in st.session_state:
    st.session_state["move_ctx"] = None

# =====================================================
# IMPORT FANTRAX
# =====================================================
st.sidebar.header("📥 Import Fantrax")
uploaded = st.sidebar.file_uploader(
    "CSV Fantrax",
    type=["csv", "txt"],
    help="Le fichier peut contenir Skaters et Goalies séparés par une ligne vide.",
)

if uploaded:
    if LOCKED:
        st.sidebar.warning("🔒 Saison verrouillée : import désactivé.")
    else:
        try:
            df_import = parse_fantrax(uploaded)
            if df_import.empty:
                st.sidebar.error("❌ Import invalide : aucune donnée exploitable.")
                st.stop()

            owner = os.path.splitext(uploaded.name)[0]
            df_import["Propriétaire"] = owner

            st.session_state["data"] = pd.concat([st.session_state["data"], df_import], ignore_index=True)
            st.session_state["data"] = clean_data(st.session_state["data"])
            st.session_state["data"].to_csv(DATA_FILE, index=False)

            st.sidebar.success("✅ Import réussi")
        except Exception as e:
            st.sidebar.error(f"❌ Import échoué : {e}")
            st.stop()

# =====================================================
# HEADER
# =====================================================
st.image("Logo_Pool.png", use_container_width=True)
st.title("🏒 Fantrax – Gestion Salariale")

df = st.session_state["data"]
if df.empty:
    st.info("Aucune donnée")
    st.stop()

# =====================================================
# MOVES + HISTORY
# =====================================================
def log_history_row(proprietaire, joueur, pos, equipe,
                    from_statut, from_slot,
                    to_statut, to_slot,
                    action):
    h = st.session_state["history"].copy()
    row = {
        "id": next_hist_id(h),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "season": season,
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
    h = pd.concat([h, pd.DataFrame([row])], ignore_index=True)
    st.session_state["history"] = h
    save_history(HISTORY_FILE, h)

def apply_move_with_history(proprietaire: str, joueur: str, to_statut: str, to_slot: str, action_label: str):
    mask = (
        (st.session_state["data"]["Propriétaire"] == proprietaire)
        & (st.session_state["data"]["Joueur"] == joueur)
    )
    if st.session_state["data"][mask].empty:
        st.error("Joueur introuvable.")
        return False

    before = st.session_state["data"][mask].iloc[0]
    from_statut = str(before["Statut"])
    from_slot = str(before.get("Slot", "")).strip()
    pos0 = str(before.get("Pos", "F"))
    equipe0 = str(before.get("Equipe", ""))

    st.session_state["data"].loc[mask, "Statut"] = to_statut
    st.session_state["data"].loc[mask, "Slot"] = to_slot if str(to_slot).strip() else ""
    st.session_state["data"] = clean_data(st.session_state["data"])
    st.session_state["data"].to_csv(DATA_FILE, index=False)

    log_history_row(
        proprietaire, joueur, pos0, equipe0,
        from_statut, from_slot,
        to_statut, (to_slot if str(to_slot).strip() else ""),
        action=action_label
    )
    return True

# =====================================================
# POP-UP SIMPLE + ROBUSTE
# =====================================================
def open_move_dialog():
    ctx = st.session_state.get("move_ctx")
    if not ctx:
        return

    if LOCKED:
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

    # Compteurs (pré-calculés dans Alignement)
    counts = st.session_state.get("align_counts", {"F": 0, "D": 0, "G": 0})
    f_count = int(counts.get("F", 0))
    d_count = int(counts.get("D", 0))
    g_count = int(counts.get("G", 0))

    def can_go_actif(pos: str) -> tuple[bool, str]:
        if pos == "F" and f_count >= 12:
            return False, "🚫 Déjà 12 F actifs."
        if pos == "D" and d_count >= 6:
            return False, "🚫 Déjà 6 D actifs."
        if pos == "G" and g_count >= 2:
            return False, "🚫 Déjà 2 G actifs."
        return True, ""

    @st.dialog(f"Déplacement — {joueur}")
    def _dlg():
        st.caption(f"**{owner}** • **{joueur}** • Pos **{cur_pos}** • **{cur_equipe}** • Salaire **{money(cur_salaire)}**")
        st.caption(f"Actuel : **{cur_statut}**" + (f" (**{cur_slot}**)" if cur_slot else ""))

        # Destinations possibles (simples)
        destinations = [
            ("🟢 Grand Club / Actif", ("Grand Club", "Actif")),
            ("🟡 Grand Club / Banc", ("Grand Club", "Banc")),
            ("🔵 Mineur", ("Club École", "")),
            ("🩹 Joueurs Blessés (IR)", (cur_statut, "Blessé")),  # garde le statut, slot=Blessé
        ]

        # 1) Enlève l'option correspondant à la position actuelle
        current = (cur_statut, cur_slot if cur_slot else "")
        destinations = [d for d in destinations if d[1] != current]

        # 2) Si déjà Blessé, on n’affiche pas l’option Blessé
        if cur_slot == "Blessé":
            destinations = [d for d in destinations if d[1][1] != "Blessé"]

        # 3) Si plus aucune option (cas rare), on sort
        if not destinations:
            st.info("Aucune destination disponible.")
            if st.button("Fermer", key=f"close_{nonce}", use_container_width=True):
                clear_move_ctx()
                st.rerun()
            return

        choice = st.radio(
            "Destination",
            [d[0] for d in destinations],
            index=0,
            key=f"dest_{owner}_{joueur}_{nonce}",  # ✅ key unique
        )
        to_statut, to_slot = dict(destinations)[choice]

        c1, c2 = st.columns(2)

        if c1.button("✅ Confirmer", key=f"confirm_{owner}_{joueur}_{nonce}", use_container_width=True):
            # Vérifie quotas si vers GC/Actif
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
                st.success("✅ Déplacement enregistré.")
                st.rerun()

        if c2.button("Annuler", key=f"cancel_{owner}_{joueur}_{nonce}", use_container_width=True):
            clear_move_ctx()
            st.rerun()

    _dlg()



# =====================================================
# CALCULS - plafonds par propriétaire (EXCLUT Blessé)
# =====================================================
resume = []
for p in df["Propriétaire"].unique():
    d = df[df["Propriétaire"] == p]
    gc_sum = d[(d["Statut"] == "Grand Club") & (d["Slot"] != "Blessé")]["Salaire"].sum()
    ce_sum = d[(d["Statut"] == "Club École") & (d["Slot"] != "Blessé")]["Salaire"].sum()

    logo = ""
    for k, v in LOGOS.items():
        if k.lower() in str(p).lower():
            logo = v

    resume.append(
        {
            "Propriétaire": p,
            "Logo": logo,
            "GC": int(gc_sum),
            "CE": int(ce_sum),
            "Restant GC": int(st.session_state["PLAFOND_GC"] - gc_sum),
            "Restant CE": int(st.session_state["PLAFOND_CE"] - ce_sum),
        }
    )
plafonds = pd.DataFrame(resume)

# =====================================================
# ONGLETs
# =====================================================
tab1, tabA, tabH, tab2, tab3 = st.tabs(
    ["📊 Tableau", "🧾 Alignement", "🕘 Historique", "⚖️ Transactions", "🧠 Recommandations"]
)

# =====================================================
# TABLEAU
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
# ALIGNEMENT
# - Actifs / Banc / Mineur
# =====================================================
# BLESSÉS : SECTION PLUS VISIBLE (NOIR + ROUGE + BOUTONS)
# =====================================================
st.markdown("## 🩹 Joueurs Blessés (IR)")
df_inj_ui = view_for_click(injured_all)

if df_inj_ui.empty:
    st.info("Aucun joueur blessé.")
else:
    # Carte plus visible + bordure rouge + ombre légère
    rows_html = ""
    for _, rr in df_inj_ui.iterrows():
        rows_html += f"""
        <tr>
          <td style="padding:10px 12px;border-bottom:1px solid #2a2a2a;font-weight:800;">{rr['Joueur']}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #2a2a2a;font-weight:800;">{rr['Pos']}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #2a2a2a;font-weight:800;">{rr['Equipe']}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #2a2a2a;text-align:right;font-weight:900;">{rr['Salaire']}</td>
        </tr>
        """

    st.markdown(
        f"""
        <div style="
            background:#000;
            border:2px solid #ff2d2d;
            border-radius:16px;
            overflow:hidden;
            box-shadow:0 6px 18px rgba(0,0,0,0.35);
            margin-top:6px;
        ">
          <div style="
              padding:12px 14px;
              color:#ff2d2d;
              font-weight:1000;
              border-bottom:1px solid #2a2a2a;
              letter-spacing:1px;
              text-transform:uppercase;
              display:flex;
              align-items:center;
              justify-content:space-between;
          ">
            <span>JOUEURS BLESSÉS</span>
            <span style="font-size:12px;opacity:0.85;">SALAIRE NON COMPTABILISÉ</span>
          </div>

          <table style="width:100%;border-collapse:collapse;color:#ff2d2d;">
            <thead>
              <tr style="border-bottom:1px solid #2a2a2a;">
                <th style="text-align:left;padding:10px 12px;font-weight:1000;">Joueur</th>
                <th style="text-align:left;padding:10px 12px;font-weight:1000;">Pos</th>
                <th style="text-align:left;padding:10px 12px;font-weight:1000;">Équipe</th>
                <th style="text-align:right;padding:10px 12px;font-weight:1000;">Salaire</th>
              </tr>
            </thead>
            <tbody>
              {rows_html}
            </tbody>
          </table>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Boutons plus visibles (gros + style "danger")
    st.markdown(
        """
        <div style="
            background:#0a0a0a;
            border:1px solid #2a2a2a;
            border-radius:16px;
            padding:12px 14px;
            margin-top:10px;
        ">
          <div style="color:#ff2d2d;font-weight:1000;letter-spacing:0.6px;margin-bottom:10px;">
            CLIQUE POUR DÉPLACER
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # CSS local pour rendre ces boutons rouges/noirs (sans affecter toute l'app)
    st.markdown(
        """
        <style>
          div[data-testid="stHorizontalBlock"] button[kind="secondary"]{
            border:1px solid #ff2d2d !important;
            background: #000000 !important;
            color:#ff2d2d !important;
            font-weight:800 !important;
          }
          div[data-testid="stHorizontalBlock"] button[kind="secondary"]:hover{
            background:#120000 !important;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )

    names = df_inj_ui["Joueur"].tolist()
    btn_cols = st.columns(3)
    for idx, name in enumerate(names):
        with btn_cols[idx % 3]:
            if st.button(f"🩹 {name}", use_container_width=True, key=f"inj_btn_{proprietaire}_{idx}"):
                set_move_ctx(proprietaire, name)
                st.rerun()


        # Boutons cliquables (ouvre pop-up direct)
        st.markdown(
            """
            <div style="background:#000;border:1px solid #222;border-radius:12px;padding:10px;margin-top:8px;">
              <div style="color:#ff2d2d;font-weight:900;margin-bottom:8px;">CLIQUE POUR DÉPLACER</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        names = df_inj_ui["Joueur"].tolist()
        btn_cols = st.columns(3)
        for idx, name in enumerate(names):
            with btn_cols[idx % 3]:
                if st.button(f"🩹 {name}", use_container_width=True, key=f"inj_btn_{proprietaire}_{idx}"):
                    set_move_ctx(proprietaire, name)
                    st.rerun()

    # Ouvrir pop-up si clic dans dataframe
    picked = ""
    picked = picked or pick_from_df(df_actifs_ui, "sel_actifs")
    picked = picked or pick_from_df(df_banc_ui, "sel_banc")
    picked = picked or pick_from_df(df_min_ui, "sel_min")

    if picked:
        set_move_ctx(proprietaire, picked)
        clear_df_selections()
        st.rerun()

    # Affiche le dialog si move_ctx existe
    open_move_dialog()

# =====================================================
# HISTORIQUE (filtre propriétaire + undo + delete)
# =====================================================
with tabH:
    st.subheader("🕘 Historique des changements d’alignement")

    h = st.session_state["history"].copy()
    if h.empty:
        st.info("Aucune entrée d’historique pour cette saison.")
        st.stop()

    owners = ["Tous"] + sorted(h["proprietaire"].dropna().astype(str).unique().tolist())
    owner_filter = st.selectbox("Filtrer par propriétaire", owners, key="hist_owner_filter")

    if owner_filter != "Tous":
        h = h[h["proprietaire"].astype(str) == owner_filter]

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
                st.stop()

            owner = str(r["proprietaire"])
            joueur = str(r["joueur"])

            mask = (
                (st.session_state["data"]["Propriétaire"] == owner)
                & (st.session_state["data"]["Joueur"] == joueur)
            )

            if st.session_state["data"][mask].empty:
                st.error("Impossible d'annuler : joueur introuvable.")
            else:
                before = st.session_state["data"][mask].iloc[0]
                cur_statut = str(before["Statut"])
                cur_slot = str(before.get("Slot", "")).strip()
                pos0 = str(before.get("Pos", "F"))
                equipe0 = str(before.get("Equipe", ""))

                st.session_state["data"].loc[mask, "Statut"] = str(r["from_statut"])
                st.session_state["data"].loc[mask, "Slot"] = str(r["from_slot"]) if str(r["from_slot"]).strip() else ""
                st.session_state["data"] = clean_data(st.session_state["data"])
                st.session_state["data"].to_csv(DATA_FILE, index=False)

                log_history_row(
                    owner, joueur, pos0, equipe0,
                    cur_statut, cur_slot,
                    str(r["from_statut"]),
                    (str(r["from_slot"]) if str(r["from_slot"]).strip() else ""),
                    action=f"UNDO #{rid}"
                )

                st.success("✅ Annulation effectuée.")
                st.rerun()

        if cols[8].button("❌", key=f"del_{rid}"):
            h2 = st.session_state["history"].copy()
            h2 = h2[h2["id"] != rid]
            st.session_state["history"] = h2
            save_history(HISTORY_FILE, h2)
            st.success("🗑️ Entrée supprimée.")
            st.rerun()

# =====================================================
# TRANSACTIONS
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
# RECOMMANDATIONS
# =====================================================
with tab3:
    for _, r in plafonds.iterrows():
        if r["Restant GC"] < 2_000_000:
            st.warning(f"{r['Propriétaire']} : rétrogradation recommandée")
        if r["Restant CE"] > 10_000_000:
            st.info(f"{r['Propriétaire']} : rappel possible")

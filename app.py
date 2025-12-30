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
    return f"{int(v):,}".replace(",", " ") + " $"

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
# NETTOYAGE GLOBAL (anti None/Goalies + aucun doublon)
# + support Slot="Blessé"
# =====================================================
def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    for col in ["Propriétaire", "Joueur", "Salaire", "Statut", "Slot", "Pos", "Equipe"]:
        if col not in df.columns:
            df[col] = "" if col != "Salaire" else 0

    df["Propriétaire"] = df["Propriétaire"].astype(str).str.strip()
    df["Joueur"] = df["Joueur"].astype(str).str.strip()
    df["Pos"] = df["Pos"].astype(str).str.strip()
    df["Equipe"] = df["Equipe"].astype(str).str.strip()
    df["Statut"] = df["Statut"].astype(str).str.strip()
    df["Slot"] = df["Slot"].astype(str).str.strip()

    # Normalise Slot (tolère plusieurs écritures)
    df["Slot"] = df["Slot"].replace(
        {"IR": "Blessé", "Blesse": "Blessé", "Blesses": "Blessé", "Injured": "Blessé"}
    )

    # Salaire => int (accepte "9 000 000 $" etc.)
    df["Salaire"] = (
        df["Salaire"]
        .astype(str)
        .str.replace("$", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace(",", "", regex=False)
        .replace(["None", "nan", "NaN", ""], "0")
    )
    df["Salaire"] = pd.to_numeric(df["Salaire"], errors="coerce").fillna(0).astype(int)

    # Positions => F/D/G
    df["Pos"] = df["Pos"].apply(normalize_pos)

    # Retire séparateurs Fantrax
    forbidden = {"none", "skaters", "goalies", "player", "null"}
    df = df[~df["Joueur"].str.lower().isin(forbidden)]
    df = df[df["Joueur"].str.len() > 2]

    # Retire ligne fantôme typique: salaire 0 + équipe vide/none
    df = df[
        ~(
            (df["Salaire"] <= 0)
            & (df["Equipe"].str.lower().isin(["none", "nan", "", "n/a"]))
        )
    ]

    # Slot par défaut si GC et slot vide
    mask_gc_default = (df["Statut"] == "Grand Club") & (df["Slot"].fillna("").eq(""))
    df.loc[mask_gc_default, "Slot"] = "Actif"

    # Si Club École => Slot vide, SAUF si Blessé
    mask_ce_not_inj = (df["Statut"] == "Club École") & (df["Slot"] != "Blessé")
    df.loc[mask_ce_not_inj, "Slot"] = ""

    # Aucun doublon par propriétaire
    df = df.drop_duplicates(subset=["Propriétaire", "Joueur"], keep="last")

    return df.reset_index(drop=True)

# =====================================================
# PARSER FANTRAX (Skaters + Goalies séparés par ligne vide)
# - Ajoute Equipe (Team)
# - Salaire en milliers -> x1000
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

    header_idxs = [
        i for i, l in enumerate(raw_lines)
        if ("player" in l.lower() and "salary" in l.lower() and sep in l)
    ]
    if not header_idxs:
        raise ValueError("Aucune section Fantrax valide détectée (Player / Salary).")

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
    return clean_data(out)

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
        "Plafond Grand Club", value=st.session_state["PLAFOND_GC"], step=500_000
    )
    st.session_state["PLAFOND_CE"] = st.sidebar.number_input(
        "Plafond Club École", value=st.session_state["PLAFOND_CE"], step=250_000
    )

st.sidebar.metric("🏒 Grand Club", money(st.session_state["PLAFOND_GC"]))
st.sidebar.metric("🏫 Club École", money(st.session_state["PLAFOND_CE"]))

# =====================================================
# HISTORIQUE - helpers
# =====================================================
def load_history() -> pd.DataFrame:
    if os.path.exists(HISTORY_FILE):
        h = pd.read_csv(HISTORY_FILE)
    else:
        h = pd.DataFrame(columns=[
            "id", "timestamp", "season",
            "proprietaire", "joueur", "pos", "equipe",
            "from_statut", "from_slot",
            "to_statut", "to_slot",
            "action"
        ])
    return h

def save_history(h: pd.DataFrame):
    h.to_csv(HISTORY_FILE, index=False)

def ensure_history_loaded():
    if "history_season" not in st.session_state or st.session_state["history_season"] != season:
        st.session_state["history"] = load_history()
        st.session_state["history_season"] = season

def next_hist_id(h: pd.DataFrame) -> int:
    if h.empty or "id" not in h.columns:
        return 1
    return int(pd.to_numeric(h["id"], errors="coerce").fillna(0).max()) + 1

def log_history(proprietaire, joueur, pos, equipe,
                from_statut, from_slot,
                to_statut, to_slot,
                action):
    ensure_history_loaded()
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
    save_history(h)

# =====================================================
# DATA - load season file
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

ensure_history_loaded()

# =====================================================
# IMPORT FANTRAX
# =====================================================
st.sidebar.header("📥 Import Fantrax")
uploaded = st.sidebar.file_uploader(
    "CSV Fantrax",
    type=["csv", "txt"],
    help="Import autorisé seulement pour la saison courante ou future",
)

if uploaded:
    if LOCKED:
        st.sidebar.warning("🔒 Saison verrouillée : import désactivé.")
    else:
        try:
            df_import = parse_fantrax(uploaded)
            if df_import.empty:
                st.sidebar.error("❌ Import invalide : aucune donnée Fantrax exploitable.")
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
# HELPERS - cap: blessé non compté
# =====================================================
def counted_bucket(statut: str, slot: str):
    if str(slot).strip() == "Blessé":
        return None
    if statut == "Grand Club":
        return "GC"
    if statut == "Club École":
        return "CE"
    return None

def is_counted_label(statut: str, slot: str) -> str:
    return "✅ Comptabilisé" if counted_bucket(statut, slot) in ("GC", "CE") else "🩹 Non comptabilisé (Blessé)"

def apply_move_with_history(proprietaire: str, joueur: str, to_statut: str, to_slot: str, action_label: str):
    mask = (
        (st.session_state["data"]["Propriétaire"] == proprietaire)
        & (st.session_state["data"]["Joueur"] == joueur)
    )
    if st.session_state["data"][mask].empty:
        st.error("Joueur introuvable.")
        return False

    before = st.session_state["data"][mask].iloc[0]
    from_statut, from_slot = str(before["Statut"]), str(before["Slot"])
    pos0, equipe0 = str(before["Pos"]), str(before["Equipe"])

    st.session_state["data"].loc[mask, "Statut"] = to_statut
    st.session_state["data"].loc[mask, "Slot"] = to_slot if str(to_slot).strip() else ""
    st.session_state["data"] = clean_data(st.session_state["data"])
    st.session_state["data"].to_csv(DATA_FILE, index=False)

    log_history(
        proprietaire, joueur, pos0, equipe0,
        from_statut, from_slot,
        to_statut, (to_slot if str(to_slot).strip() else ""),
        action=action_label
    )
    return True

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
    headers[1].markdown("**Grand Club**")
    headers[2].markdown("**Restant GC**")
    headers[3].markdown("**Club École**")
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
# ALIGNEMENT (clic -> popup compact)
# =====================================================
with tabA:
    st.subheader("🧾 Alignement")
    st.caption(
        "Clique sur un joueur (Actifs / Banc / Min / Blessés) pour le déplacer. "
        "Actifs : 12F / 6D / 2G. Banc : illimité. Blessés : salaire non comptabilisé."
    )

    proprietaire = st.selectbox(
        "Propriétaire",
        sorted(st.session_state["data"]["Propriétaire"].unique()),
        key="align_owner",
    )

    st.session_state["data"] = clean_data(st.session_state["data"])
    data_all = st.session_state["data"]
    dprop = data_all[data_all["Propriétaire"] == proprietaire].copy()

    injured_all = dprop[dprop["Slot"] == "Blessé"].copy()
    dprop_not_inj = dprop[dprop["Slot"] != "Blessé"].copy()

    gc_all = dprop_not_inj[dprop_not_inj["Statut"] == "Grand Club"].copy()
    ce_all = dprop_not_inj[dprop_not_inj["Statut"] == "Club École"].copy()
    gc_actif = gc_all[gc_all["Slot"] == "Actif"].copy()
    gc_banc = gc_all[gc_all["Slot"] == "Banc"].copy()

    nb_F = int((gc_actif["Pos"] == "F").sum())
    nb_D = int((gc_actif["Pos"] == "D").sum())
    nb_G = int((gc_actif["Pos"] == "G").sum())
    total_actifs = nb_F + nb_D + nb_G

    total_gc = int(gc_all["Salaire"].sum())
    total_ce = int(ce_all["Salaire"].sum())
    restant_gc = int(st.session_state["PLAFOND_GC"] - total_gc)
    restant_ce = int(st.session_state["PLAFOND_CE"] - total_ce)

    # Metrics (compact)
    top = st.columns([1.2, 1.2, 1.2, 1.2])
    top[0].metric("Total GC", money(total_gc))
    top[1].metric("Restant GC", money(restant_gc))
    top[2].metric("Total CE", money(total_ce))
    top[3].metric("Restant CE", money(restant_ce))

    st.caption(f"Actifs: F {nb_F}/12 • D {nb_D}/6 • G {nb_G}/2 • Total {total_actifs}/20")

    st.divider()

    def view_for_click(x: pd.DataFrame) -> pd.DataFrame:
        if x is None or x.empty:
            return pd.DataFrame(columns=["Joueur", "Pos", "Equipe", "Salaire"])
        y = x.copy()
        y["_pos_order"] = y["Pos"].apply(pos_sort_key)
        y = y.sort_values(["_pos_order", "Joueur"]).drop(columns=["_pos_order"])
        y["Salaire"] = y["Salaire"].apply(money)
        return y[["Joueur", "Pos", "Equipe", "Salaire"]].reset_index(drop=True)

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown("### 🟢 Actifs")
        df_actifs_ui = view_for_click(gc_actif)
        st.dataframe(df_actifs_ui, use_container_width=True, hide_index=True,
                     selection_mode="single-row", on_select="rerun", key="sel_actifs")

    with col2:
        st.markdown("### 🟡 Banc")
        df_banc_ui = view_for_click(gc_banc)
        st.dataframe(df_banc_ui, use_container_width=True, hide_index=True,
                     selection_mode="single-row", on_select="rerun", key="sel_banc")

    with col3:
        st.markdown("### 🔵 Min")
        df_min_ui = view_for_click(ce_all)
        st.dataframe(df_min_ui, use_container_width=True, hide_index=True,
                     selection_mode="single-row", on_select="rerun", key="sel_min")

    with col4:
        st.markdown("### 🩹 Blessés")
        df_inj_ui = view_for_click(injured_all)
        st.dataframe(df_inj_ui, use_container_width=True, hide_index=True,
                     selection_mode="single-row", on_select="rerun", key="sel_inj")

    def clear_selections():
        for k in ["sel_actifs", "sel_banc", "sel_min", "sel_inj"]:
            if k in st.session_state and isinstance(st.session_state[k], dict):
                st.session_state[k]["selection"] = {"rows": []}

    def get_selected_player():
        if st.session_state.get("sel_actifs") and st.session_state["sel_actifs"].get("selection", {}).get("rows"):
            i = st.session_state["sel_actifs"]["selection"]["rows"][0]
            if i < len(df_actifs_ui):
                return "Actif", str(df_actifs_ui.iloc[i]["Joueur"])
        if st.session_state.get("sel_banc") and st.session_state["sel_banc"].get("selection", {}).get("rows"):
            i = st.session_state["sel_banc"]["selection"]["rows"][0]
            if i < len(df_banc_ui):
                return "Banc", str(df_banc_ui.iloc[i]["Joueur"])
        if st.session_state.get("sel_min") and st.session_state["sel_min"].get("selection", {}).get("rows"):
            i = st.session_state["sel_min"]["selection"]["rows"][0]
            if i < len(df_min_ui):
                return "Min", str(df_min_ui.iloc[i]["Joueur"])
        if st.session_state.get("sel_inj") and st.session_state["sel_inj"].get("selection", {}).get("rows"):
            i = st.session_state["sel_inj"]["selection"]["rows"][0]
            if i < len(df_inj_ui):
                return "Blessé", str(df_inj_ui.iloc[i]["Joueur"])
        return None, None

    def can_add_to_actif(pos: str):
        pos = normalize_pos(pos)
        if pos == "F" and nb_F >= 12:
            return False, "🚫 Déjà 12 F actifs."
        if pos == "D" and nb_D >= 6:
            return False, "🚫 Déjà 6 D actifs."
        if pos == "G" and nb_G >= 2:
            return False, "🚫 Déjà 2 G actifs."
        return True, ""

    def projected_counts(cur_statut, cur_slot, pos, to_statut, to_slot):
        f, d, g = nb_F, nb_D, nb_G
        pos = normalize_pos(pos)
        if cur_statut == "Grand Club" and cur_slot == "Actif":
            if pos == "F": f -= 1
            elif pos == "D": d -= 1
            else: g -= 1
        if to_statut == "Grand Club" and to_slot == "Actif":
            if pos == "F": f += 1
            elif pos == "D": d += 1
            else: g += 1
        return f, d, g

    def projected_totals(salaire_player, cur_statut, cur_slot, to_statut, to_slot):
        pgc, pce = total_gc, total_ce
        s = int(salaire_player)
        from_bucket = counted_bucket(cur_statut, cur_slot)
        to_bucket = counted_bucket(to_statut, to_slot)
        if from_bucket == "GC": pgc -= s
        elif from_bucket == "CE": pce -= s
        if to_bucket == "GC": pgc += s
        elif to_bucket == "CE": pce += s
        return int(pgc), int(pce)

    src, joueur_sel = get_selected_player()

    if joueur_sel:
        if LOCKED:
            st.warning("🔒 Saison verrouillée : aucun changement permis.")
            clear_selections()
        else:
            mask_sel = (
                (st.session_state["data"]["Propriétaire"] == proprietaire)
                & (st.session_state["data"]["Joueur"] == joueur_sel)
            )
            if st.session_state["data"][mask_sel].empty:
                st.error("Sélection invalide.")
                clear_selections()
            else:
                cur = st.session_state["data"][mask_sel].iloc[0]
                cur_statut = str(cur["Statut"])
                cur_slot = str(cur["Slot"])
                cur_pos = str(cur["Pos"])
                cur_equipe = str(cur["Equipe"])
                cur_salaire = int(cur["Salaire"])

                @st.dialog(f"Déplacement — {joueur_sel}")
                def move_dialog():
                    # Ligne d'info compacte + badge
                    st.markdown(
                        f"**{joueur_sel}** • Pos **{cur_pos}** • Équipe **{cur_equipe}** • Salaire **{money(cur_salaire)}**  \n"
                        f"Statut: **{cur_statut}** • Slot: **{cur_slot if cur_slot else '—'}** • {is_counted_label(cur_statut, cur_slot)}"
                    )

                    st.divider()

                    options = []

                    # Blessé
                    if cur_slot != "Blessé":
                        options.append(("🩹 Mettre Blessé (IR)", (cur_statut, "Blessé", "→ Blessé (IR)")))
                    else:
                        # Retirer de blessé => choix
                        options.append(("Grand Club / Actif", ("Grand Club", "Actif", "Blessé → GC (Actif)")))
                        options.append(("Grand Club / Banc", ("Grand Club", "Banc", "Blessé → GC (Banc)")))
                        options.append(("Club École (Min)", ("Club École", "", "Blessé → Min")))

                    # Si non blessé, options normales
                    if cur_slot != "Blessé":
                        if cur_statut == "Club École":
                            options.append(("Grand Club / Actif", ("Grand Club", "Actif", "Min → GC (Actif)")))
                            options.append(("Grand Club / Banc", ("Grand Club", "Banc", "Min → GC (Banc)")))
                        else:
                            if cur_slot == "Actif":
                                options.append(("Grand Club / Banc", ("Grand Club", "Banc", "Actif → Banc")))
                                options.append(("Club École (Min)", ("Club École", "", "GC → Min")))
                            elif cur_slot == "Banc":
                                options.append(("Grand Club / Actif", ("Grand Club", "Actif", "Banc → Actif")))
                                options.append(("Club École (Min)", ("Club École", "", "GC → Min")))
                            else:
                                options.append(("Grand Club / Actif", ("Grand Club", "Actif", "GC → Actif")))
                                options.append(("Grand Club / Banc", ("Grand Club", "Banc", "GC → Banc")))
                                options.append(("Club École (Min)", ("Club École", "", "GC → Min")))

                    labels = [o[0] for o in options]
                    choice = st.radio("Destination", labels)

                    to_statut, to_slot, action_label = dict(options)[choice]

                    # Aperçu compact
                    pf, pd_, pg = projected_counts(cur_statut, cur_slot, cur_pos, to_statut, to_slot)
                    pgc, pce = projected_totals(cur_salaire, cur_statut, cur_slot, to_statut, to_slot)
                    pr_gc = int(st.session_state["PLAFOND_GC"] - pgc)
                    pr_ce = int(st.session_state["PLAFOND_CE"] - pce)

                    st.caption("Aperçu après déplacement")
                    row1 = st.columns([1, 1, 1, 1])
                    row1[0].metric("F", f"{pf}/12")
                    row1[1].metric("D", f"{pd_}/6")
                    row1[2].metric("G", f"{pg}/2")
                    row1[3].metric("Actifs", f"{pf+pd_+pg}/20")

                    row2 = st.columns([1, 1, 1, 1])
                    row2[0].metric("GC", money(pgc))
                    row2[1].metric("R GC", money(pr_gc))
                    row2[2].metric("CE", money(pce))
                    row2[3].metric("R CE", money(pr_ce))

                    if pr_gc < 0:
                        st.warning("🚨 Plafond GC dépassé.")
                    if pr_ce < 0:
                        st.warning("🚨 Plafond CE dépassé.")

                    st.divider()

                    if st.button("✅ Confirmer"):
                        if to_statut == "Grand Club" and to_slot == "Actif":
                            ok, msg = can_add_to_actif(cur_pos)
                            if not ok:
                                st.error(msg)
                                return

                        ok2 = apply_move_with_history(
                            proprietaire=proprietaire,
                            joueur=joueur_sel,
                            to_statut=to_statut,
                            to_slot=to_slot,
                            action_label=action_label,
                        )
                        if ok2:
                            clear_selections()
                            st.success("✅ Déplacement enregistré.")
                            st.rerun()

                    if st.button("Annuler"):
                        clear_selections()
                        st.rerun()

                move_dialog()

# =====================================================
# HISTORIQUE
# =====================================================
with tabH:
    st.subheader("🕘 Historique des changements d’alignement")
    ensure_history_loaded()
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

    head = st.columns([1.5, 1.4, 2.4, 1.0, 1.5, 1.5, 1.6, 0.8, 0.7])
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
        cols = st.columns([1.5, 1.4, 2.4, 1.0, 1.5, 1.5, 1.6, 0.8, 0.7])

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
                cur_statut, cur_slot = str(before["Statut"]), str(before["Slot"])
                pos0, equipe0 = str(before["Pos"]), str(before["Equipe"])

                st.session_state["data"].loc[mask, "Statut"] = str(r["from_statut"])
                st.session_state["data"].loc[mask, "Slot"] = str(r["from_slot"]) if str(r["from_slot"]).strip() else ""
                st.session_state["data"] = clean_data(st.session_state["data"])
                st.session_state["data"].to_csv(DATA_FILE, index=False)

                log_history(
                    owner, joueur, pos0, equipe0,
                    cur_statut, cur_slot,
                    str(r["from_statut"]),
                    (str(r["from_slot"]) if str(r["from_slot"]).strip() else ""),
                    action=f"UNDO #{rid}"
                )

                st.success("✅ Annulation effectuée.")
                st.rerun()

        if cols[8].button("❌", key=f"del_{rid}"):
            ensure_history_loaded()
            h2 = st.session_state["history"].copy()
            h2 = h2[h2["id"] != rid]
            st.session_state["history"] = h2
            save_history(h2)
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

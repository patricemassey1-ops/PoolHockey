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

    df["Salaire"] = (
        df["Salaire"]
        .astype(str)
        .str.replace("$", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace(",", "", regex=False)
        .replace(["None", "nan", "NaN", ""], "0")
    )
    df["Salaire"] = pd.to_numeric(df["Salaire"], errors="coerce").fillna(0).astype(int)

    df["Pos"] = df["Pos"].apply(normalize_pos)

    forbidden = {"none", "skaters", "goalies", "player", "null"}
    df = df[~df["Joueur"].str.lower().isin(forbidden)]
    df = df[df["Joueur"].str.len() > 2]

    df = df[
        ~(
            (df["Salaire"] <= 0)
            & (df["Equipe"].str.lower().isin(["none", "nan", "", "n/a"]))
        )
    ]

    mask_gc_default = (df["Statut"] == "Grand Club") & (df["Slot"].fillna("").eq(""))
    df.loc[mask_gc_default, "Slot"] = "Actif"

    mask_ce = (df["Statut"] == "Club École")
    df.loc[mask_ce, "Slot"] = ""

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
# HELPERS - moves
# =====================================================
def apply_move_with_history(proprietaire: str, joueur: str, to_statut: str, to_slot: str, action_label: str):
    """
    Applique un déplacement (Statut/Slot) + sauvegarde + log historique.
    """
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
# CALCULS - plafonds par propriétaire
# =====================================================
resume = []
for p in df["Propriétaire"].unique():
    d = df[df["Propriétaire"] == p]
    gc_sum = d[d["Statut"] == "Grand Club"]["Salaire"].sum()
    ce_sum = d[d["Statut"] == "Club École"]["Salaire"].sum()

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
# TABLEAU (bonus: Restant GC collé à GC)
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
# ALIGNEMENT (clic joueur -> popup -> déplacement)
# =====================================================
with tabA:
    st.subheader("🧾 Alignement")
    st.caption("Clique sur un joueur (Actifs / Banc / Club École) pour ouvrir un pop-up de déplacement. "
               "Règles Actifs : **12 F**, **6 D**, **2 G** (=20). Banc : illimité (F/D/G).")

    proprietaire = st.selectbox(
        "Propriétaire",
        sorted(st.session_state["data"]["Propriétaire"].unique()),
        key="align_owner",
    )

    # refresh clean + subset
    st.session_state["data"] = clean_data(st.session_state["data"])
    data_all = st.session_state["data"]
    dprop = data_all[data_all["Propriétaire"] == proprietaire].copy()

    gc_all = dprop[dprop["Statut"] == "Grand Club"].copy()
    ce_all = dprop[dprop["Statut"] == "Club École"].copy()

    gc_actif = gc_all[gc_all["Slot"] == "Actif"].copy()
    gc_banc = gc_all[gc_all["Slot"] == "Banc"].copy()

    # Compteurs actifs
    nb_F = int((gc_actif["Pos"] == "F").sum())
    nb_D = int((gc_actif["Pos"] == "D").sum())
    nb_G = int((gc_actif["Pos"] == "G").sum())
    total_actifs = nb_F + nb_D + nb_G

    # Totaux salaires / restants
    total_gc = int(gc_all["Salaire"].sum())
    total_ce = int(ce_all["Salaire"].sum())
    restant_gc = int(st.session_state["PLAFOND_GC"] - total_gc)
    restant_ce = int(st.session_state["PLAFOND_CE"] - total_ce)

    # Metrics (Restant GC à côté de Total GC)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("🏒 Total GC", money(total_gc))
    m2.metric("✅ Restant GC", money(restant_gc))
    m3.metric("🏫 Total CE", money(total_ce))
    m4.metric("✅ Restant CE", money(restant_ce))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("F actifs", f"{nb_F}/12")
    c2.metric("D actifs", f"{nb_D}/6")
    c3.metric("G actifs", f"{nb_G}/2")
    c4.metric("Total actifs", f"{total_actifs}/20")

    if nb_F != 12:
        st.warning("⚠️ Il doit y avoir exactement **12 F** actifs.")
    if nb_D != 6:
        st.warning("⚠️ Il doit y avoir exactement **6 D** actifs.")
    if nb_G != 2:
        st.warning("⚠️ Il doit y avoir exactement **2 G** actifs.")
    if total_actifs != 20:
        st.warning("⚠️ Total des actifs invalide (doit être **20**).")

    st.divider()

    # ---- UI tables (clickable) ----
    def view_for_click(x: pd.DataFrame) -> pd.DataFrame:
        if x is None or x.empty:
            return pd.DataFrame(columns=["Joueur", "Pos", "Equipe", "Salaire"])
        y = x.copy()
        y["_pos_order"] = y["Pos"].apply(pos_sort_key)
        y = y.sort_values(["_pos_order", "Joueur"]).drop(columns=["_pos_order"])
        y["Salaire"] = y["Salaire"].apply(money)
        return y[["Joueur", "Pos", "Equipe", "Salaire"]].reset_index(drop=True)

    colL, colM, colR = st.columns(3)

    with colL:
        st.markdown("### 🟢 Actifs (clique un joueur)")
        df_actifs_ui = view_for_click(gc_actif)
        st.dataframe(
            df_actifs_ui,
            use_container_width=True,
            hide_index=True,
            selection_mode="single-row",
            on_select="rerun",
            key="sel_actifs",
        )

    with colM:
        st.markdown("### 🟡 Banc (clique un joueur)")
        df_banc_ui = view_for_click(gc_banc)
        st.dataframe(
            df_banc_ui,
            use_container_width=True,
            hide_index=True,
            selection_mode="single-row",
            on_select="rerun",
            key="sel_banc",
        )

    with colR:
        st.markdown("### 🔵 Club École (clique un joueur)")
        df_min_ui = view_for_click(ce_all)
        st.dataframe(
            df_min_ui,
            use_container_width=True,
            hide_index=True,
            selection_mode="single-row",
            on_select="rerun",
            key="sel_min",
        )

    # ---- helpers sélection + dialog ----
    def clear_selections():
        for k in ["sel_actifs", "sel_banc", "sel_min"]:
            if k in st.session_state and isinstance(st.session_state[k], dict):
                st.session_state[k]["selection"] = {"rows": []}

    def get_selected_player():
        if st.session_state.get("sel_actifs") and st.session_state["sel_actifs"].get("selection", {}).get("rows"):
            idx = st.session_state["sel_actifs"]["selection"]["rows"][0]
            if idx < len(df_actifs_ui):
                return ("Actif", str(df_actifs_ui.iloc[idx]["Joueur"]))
        if st.session_state.get("sel_banc") and st.session_state["sel_banc"].get("selection", {}).get("rows"):
            idx = st.session_state["sel_banc"]["selection"]["rows"][0]
            if idx < len(df_banc_ui):
                return ("Banc", str(df_banc_ui.iloc[idx]["Joueur"]))
        if st.session_state.get("sel_min") and st.session_state["sel_min"].get("selection", {}).get("rows"):
            idx = st.session_state["sel_min"]["selection"]["rows"][0]
            if idx < len(df_min_ui):
                return ("Min", str(df_min_ui.iloc[idx]["Joueur"]))
        return (None, None)

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

        # retire du groupe actif si actuellement actif GC
        if cur_statut == "Grand Club" and cur_slot == "Actif":
            if pos == "F": f -= 1
            elif pos == "D": d -= 1
            else: g -= 1

        # ajoute au groupe actif si destination actif GC
        if to_statut == "Grand Club" and to_slot == "Actif":
            if pos == "F": f += 1
            elif pos == "D": d += 1
            else: g += 1

        return f, d, g

    def projected_totals(salaire_player, cur_statut, to_statut):
        pgc, pce = total_gc, total_ce
        salaire_player = int(salaire_player)

        if cur_statut == "Club École" and to_statut == "Grand Club":
            pgc += salaire_player
            pce -= salaire_player
        elif cur_statut == "Grand Club" and to_statut == "Club École":
            pgc -= salaire_player
            pce += salaire_player

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
                    st.write(
                        f"**Position :** {cur_pos}  \n"
                        f"**Équipe :** {cur_equipe}  \n"
                        f"**Salaire :** {money(cur_salaire)}  \n"
                        f"**Statut/Slot actuel :** {cur_statut} ({cur_slot if cur_slot else '—'})"
                    )

                    st.divider()

                    # Options selon l’état
                    options = []
                    if cur_statut == "Club École":
                        options.append(("Grand Club / Actif", ("Grand Club", "Actif", "Min → GC (Actif)")))
                        options.append(("Grand Club / Banc", ("Grand Club", "Banc", "Min → GC (Banc)")))
                    else:
                        # Grand Club
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
                    choice = st.radio("Choisir la destination", labels)

                    to_statut, to_slot, action_label = dict(options)[choice]

                    # Prévisualisation quotas + plafonds
                    pf, pd_, pg = projected_counts(cur_statut, cur_slot, cur_pos, to_statut, to_slot)
                    p_total_actifs = pf + pd_ + pg

                    pgc, pce = projected_totals(cur_salaire, cur_statut, to_statut)
                    pr_gc = int(st.session_state["PLAFOND_GC"] - pgc)
                    pr_ce = int(st.session_state["PLAFOND_CE"] - pce)

                    st.markdown("#### 🔎 Aperçu après déplacement")
                    a1, a2, a3, a4 = st.columns(4)
                    a1.metric("F actifs", f"{pf}/12")
                    a2.metric("D actifs", f"{pd_}/6")
                    a3.metric("G actifs", f"{pg}/2")
                    a4.metric("Total actifs", f"{p_total_actifs}/20")

                    b1, b2, b3, b4 = st.columns(4)
                    b1.metric("Total GC", money(pgc))
                    b2.metric("Restant GC", money(pr_gc))
                    b3.metric("Total CE", money(pce))
                    b4.metric("Restant CE", money(pr_ce))

                    if pr_gc < 0:
                        st.warning("🚨 Après ce déplacement, le **plafond GC** serait dépassé.")
                    if pr_ce < 0:
                        st.warning("🚨 Après ce déplacement, le **plafond CE** serait dépassé.")

                    st.divider()

                    if st.button("✅ Confirmer le déplacement"):
                        # validation quotas si destination Actif
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
# HISTORIQUE (filtre propriétaire + undo + delete)
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

    st.caption("↩️ = annuler ce changement (retour à l’état précédent). ❌ = supprimer l’entrée (sans modifier l’alignement).")

    head = st.columns([1.6, 1.6, 2.6, 1.1, 1.6, 1.6, 1.6, 0.9, 0.7])
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
        cols = st.columns([1.6, 1.6, 2.6, 1.1, 1.6, 1.6, 1.6, 0.9, 0.7])

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
                st.error("Impossible d'annuler : joueur introuvable dans les données.")
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

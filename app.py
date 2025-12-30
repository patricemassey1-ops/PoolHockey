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

# =========================
# ✅ BLOC 1 — clean_data() COMPLET (avec suppression de doublons)
# =========================
def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    for col in ["Propriétaire", "Joueur", "Salaire", "Statut", "Slot", "Pos", "Equipe"]:
        if col not in df.columns:
            df[col] = "" if col != "Salaire" else 0

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

    # Slot par défaut si GC
    mask_gc_default = (df["Statut"] == "Grand Club") & (df["Slot"].fillna("").eq(""))
    df.loc[mask_gc_default, "Slot"] = "Actif"

    # si Club École => Slot vide
    mask_ce = (df["Statut"] == "Club École")
    df.loc[mask_ce, "Slot"] = ""

    # -------------------------------------------------
    # ✅ AUCUN DOUBLON: (Propriétaire, Joueur) unique
    # On garde la dernière occurrence (la plus récente)
    # -------------------------------------------------
    df = df.drop_duplicates(subset=["Propriétaire", "Joueur"], keep="last")

    return df.reset_index(drop=True)


    # Slot par défaut si GC
    mask_gc_default = (df["Statut"] == "Grand Club") & (df["Slot"].fillna("").eq(""))
    df.loc[mask_gc_default, "Slot"] = "Actif"

    # si Club École => Slot vide
    mask_ce = (df["Statut"] == "Club École")
    df.loc[mask_ce, "Slot"] = ""

    return df.reset_index(drop=True)

# =====================================================
# PARSER FANTRAX (Skaters + Goalies)
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

    out = clean_data(out)
    return out

# =====================================================
# SIDEBAR
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

# =========================
# ✅ BLOC 2 — DATA COMPLET (avec sauvegarde immédiate après nettoyage)
# Remplace TOUT ton bloc DATA actuel par celui-ci.
# =========================
if "season" not in st.session_state or st.session_state["season"] != season:
    if os.path.exists(DATA_FILE):
        st.session_state["data"] = pd.read_csv(DATA_FILE)
        st.session_state["data"] = clean_data(st.session_state["data"])

        # ✅ Sauvegarde immédiate après nettoyage (retire les doublons du fichier)
        st.session_state["data"].to_csv(DATA_FILE, index=False)
    else:
        st.session_state["data"] = pd.DataFrame(
            columns=["Propriétaire", "Joueur", "Salaire", "Statut", "Slot", "Pos", "Equipe"]
        )

    if "Slot" not in st.session_state["data"].columns:
        st.session_state["data"]["Slot"] = ""

    st.session_state["data"] = clean_data(st.session_state["data"])
    st.session_state["season"] = season


# =====================================================
# IMPORT FANTRAX (uploader toujours visible)
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
            if df_import is None or not isinstance(df_import, pd.DataFrame) or df_import.empty:
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
# CALCULS (plafonds par propriétaire)
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
            "GC": gc_sum,
            "CE": ce_sum,
            "Restant GC": st.session_state["PLAFOND_GC"] - gc_sum,
            "Restant CE": st.session_state["PLAFOND_CE"] - ce_sum,
        }
    )

plafonds = pd.DataFrame(resume)

# =====================================================
# ONGLETs
# =====================================================
tab1, tab4, tab2, tab3 = st.tabs(
    ["📊 Tableau", "🧾 Alignement", "⚖️ Transactions", "🧠 Recommandations"]
)

# =========================
# ✅ BLOC 3 — TAB1 (Tableau) COMPLET avec BONUS:
# Restant GC collé à Grand Club (ordre changé)
# Remplace TOUT ton bloc "with tab1:" par celui-ci.
# =========================
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

        # ✅ Ordre: GC, Restant GC, CE, Restant CE
        cols[1].markdown(money(r["GC"]))
        cols[2].markdown(money(r["Restant GC"]))
        cols[3].markdown(money(r["CE"]))
        cols[4].markdown(money(r["Restant CE"]))


# =====================================================
# ALIGNEMENT (Actifs: 12F / 6D / 2G = 20) + Banc illimité (F/D/G autorisés)
# =====================================================
with tab4:
    st.subheader("🧾 Alignement")
    st.caption("Règles Actifs : **12 F**, **6 D**, **2 G** (=20). Banc : illimité (F/D/G autorisés).")

    proprietaire = st.selectbox(
        "Propriétaire",
        sorted(st.session_state["data"]["Propriétaire"].unique()),
        key="align_owner",
    )

    st.session_state["data"] = clean_data(st.session_state["data"])
    data_all = st.session_state["data"]
    dprop = data_all[data_all["Propriétaire"] == proprietaire].copy()

    gc_all = dprop[dprop["Statut"] == "Grand Club"].copy()
    ce_all = dprop[dprop["Statut"] == "Club École"].copy()

    if "Slot" not in st.session_state["data"].columns:
        st.session_state["data"]["Slot"] = ""

    # Default: GC & Slot vide => Actif
    mask_default = (gc_all["Slot"].fillna("").eq(""))
    if mask_default.any():
        mask_all = (
            (st.session_state["data"]["Propriétaire"] == proprietaire)
            & (st.session_state["data"]["Statut"] == "Grand Club")
            & (st.session_state["data"]["Slot"].fillna("").eq(""))
        )
        st.session_state["data"].loc[mask_all, "Slot"] = "Actif"
        st.session_state["data"] = clean_data(st.session_state["data"])
        st.session_state["data"].to_csv(DATA_FILE, index=False)
        dprop = st.session_state["data"][st.session_state["data"]["Propriétaire"] == proprietaire].copy()
        gc_all = dprop[dprop["Statut"] == "Grand Club"].copy()
        ce_all = dprop[dprop["Statut"] == "Club École"].copy()

    gc_actif = gc_all[gc_all["Slot"] == "Actif"].copy()
    gc_banc = gc_all[gc_all["Slot"] == "Banc"].copy()

    nb_F = (gc_actif["Pos"] == "F").sum()
    nb_D = (gc_actif["Pos"] == "D").sum()
    nb_G = (gc_actif["Pos"] == "G").sum()
    total_actifs = int(nb_F + nb_D + nb_G)

    nb_banc = len(gc_banc)

    total_gc = gc_all["Salaire"].sum()
    total_ce = ce_all["Salaire"].sum()
    restant_gc = st.session_state["PLAFOND_GC"] - total_gc
    restant_ce = st.session_state["PLAFOND_CE"] - total_ce

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("🏒 Total GC", money(total_gc))
    m2.metric("🏫 Total CE", money(total_ce))
    m3.metric("✅ Restant GC", money(restant_gc))
    m4.metric("✅ Restant CE", money(restant_ce))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("F actifs", f"{int(nb_F)}/12")
    c2.metric("D actifs", f"{int(nb_D)}/6")
    c3.metric("G actifs", f"{int(nb_G)}/2")
    c4.metric("Banc", f"{int(nb_banc)}")

    if nb_F != 12:
        st.warning("⚠️ Il doit y avoir exactement **12 F** actifs.")
    if nb_D != 6:
        st.warning("⚠️ Il doit y avoir exactement **6 D** actifs.")
    if nb_G != 2:
        st.warning("⚠️ Il doit y avoir exactement **2 G** actifs.")
    if total_actifs != 20:
        st.warning("⚠️ Total des actifs invalide (doit être **20**).")

    st.divider()

    def sorted_view(x: pd.DataFrame) -> pd.DataFrame:
        if x.empty:
            return x
        y = x.copy()
        y["Salaire"] = y["Salaire"].apply(money)
        y["_pos_order"] = y["Pos"].apply(pos_sort_key)
        y = y.sort_values(["_pos_order", "Joueur"]).drop(columns=["_pos_order"])
        return y[["Joueur", "Pos", "Equipe", "Salaire"]].reset_index(drop=True)

    colA, colB, colC = st.columns(3)
    with colA:
        st.markdown("### 🟢 Actifs (F/D/G)")
        st.dataframe(sorted_view(gc_actif), use_container_width=True, hide_index=True)

    with colB:
        st.markdown("### 🟡 Banc (F/D/G)")
        st.dataframe(sorted_view(gc_banc), use_container_width=True, hide_index=True)

    with colC:
        st.markdown("### 🔵 Club École (Min)")
        st.dataframe(sorted_view(ce_all), use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("### 🔁 Déplacements")

    if LOCKED:
        st.warning("🔒 Saison verrouillée : aucun changement d’alignement n’est permis.")
        st.stop()

    def can_add_to_actif(pos: str):
        pos = normalize_pos(pos)
        if pos == "F" and nb_F >= 12:
            return False, "🚫 Déjà 12 F actifs."
        if pos == "D" and nb_D >= 6:
            return False, "🚫 Déjà 6 D actifs."
        if pos == "G" and nb_G >= 2:
            return False, "🚫 Déjà 2 G actifs."
        return True, ""

    def can_add_to_banc(pos: str):
        # Banc illimité et positions F/D/G autorisées
        return True, ""

    a1, a2, a3 = st.columns(3)

    # 1) Club École -> GC (Actif/Banc)
    with a1:
        st.markdown("**⬆️ Rappel (Min → GC)**")
        ce_players = ce_all["Joueur"].tolist()
        ce_choice = st.selectbox(
            "Joueur (Club École)",
            ce_players if ce_players else ["—"],
            disabled=(len(ce_players) == 0),
            key="recall_player",
        )
        dest = st.radio(
            "Destination",
            ["Actif", "Banc"],
            horizontal=True,
            key="recall_dest",
            disabled=(len(ce_players) == 0),
        )

        if st.button("Rappeler", disabled=(len(ce_players) == 0), key="btn_recall"):
            row = ce_all[ce_all["Joueur"] == ce_choice].iloc[0]
            pos = normalize_pos(row["Pos"])

            if dest == "Actif":
                ok, msg = can_add_to_actif(pos)
                if not ok:
                    st.error(msg)
                else:
                    mask = (st.session_state["data"]["Propriétaire"] == proprietaire) & (st.session_state["data"]["Joueur"] == ce_choice)
                    st.session_state["data"].loc[mask, "Statut"] = "Grand Club"
                    st.session_state["data"].loc[mask, "Slot"] = "Actif"
                    st.session_state["data"] = clean_data(st.session_state["data"])
                    st.session_state["data"].to_csv(DATA_FILE, index=False)
                    st.success(f"✅ {ce_choice} rappelé au Grand Club (Actif)")
                    st.rerun()
            else:
                ok, msg = can_add_to_banc(pos)
                if not ok:
                    st.error(msg)
                else:
                    mask = (st.session_state["data"]["Propriétaire"] == proprietaire) & (st.session_state["data"]["Joueur"] == ce_choice)
                    st.session_state["data"].loc[mask, "Statut"] = "Grand Club"
                    st.session_state["data"].loc[mask, "Slot"] = "Banc"
                    st.session_state["data"] = clean_data(st.session_state["data"])
                    st.session_state["data"].to_csv(DATA_FILE, index=False)
                    st.success(f"✅ {ce_choice} rappelé au Grand Club (Banc)")
                    st.rerun()

    # 2) GC -> Club École
    with a2:
        st.markdown("**⬇️ Rétrogradation (GC → Min)**")
        gc_players = gc_all["Joueur"].tolist()
        gc_choice = st.selectbox(
            "Joueur (Grand Club)",
            gc_players if gc_players else ["—"],
            disabled=(len(gc_players) == 0),
            key="senddown_player",
        )

        if st.button("Envoyer au Club École", disabled=(len(gc_players) == 0), key="btn_senddown"):
            mask = (st.session_state["data"]["Propriétaire"] == proprietaire) & (st.session_state["data"]["Joueur"] == gc_choice)
            st.session_state["data"].loc[mask, "Statut"] = "Club École"
            st.session_state["data"].loc[mask, "Slot"] = ""
            st.session_state["data"] = clean_data(st.session_state["data"])
            st.session_state["data"].to_csv(DATA_FILE, index=False)
            st.success(f"✅ {gc_choice} envoyé au Club École (Min)")
            st.rerun()

    # 3) Actif <-> Banc (F/D/G autorisés)
    with a3:
        st.markdown("**↔️ Actif ⇄ Banc (F/D/G)**")

        actifs_list = gc_actif["Joueur"].tolist()
        banc_list = gc_banc["Joueur"].tolist()

        sel_actif = st.selectbox(
            "Actif → Banc",
            actifs_list if actifs_list else ["—"],
            disabled=(len(actifs_list) == 0),
            key="actif_to_banc",
        )
        if st.button("Mettre sur le banc", disabled=(len(actifs_list) == 0), key="btn_actif_to_banc"):
            mask = (st.session_state["data"]["Propriétaire"] == proprietaire) & (st.session_state["data"]["Joueur"] == sel_actif)
            st.session_state["data"].loc[mask, "Slot"] = "Banc"
            st.session_state["data"] = clean_data(st.session_state["data"])
            st.session_state["data"].to_csv(DATA_FILE, index=False)
            st.success(f"✅ {sel_actif} déplacé vers Banc")
            st.rerun()

        st.divider()

        sel_banc = st.selectbox(
            "Banc → Actif",
            banc_list if banc_list else ["—"],
            disabled=(len(banc_list) == 0),
            key="banc_to_actif",
        )
        if st.button("Rendre actif", disabled=(len(banc_list) == 0), key="btn_banc_to_actif"):
            row = gc_banc[gc_banc["Joueur"] == sel_banc].iloc[0]
            pos = normalize_pos(row["Pos"])
            ok, msg = can_add_to_actif(pos)
            if not ok:
                st.error(msg)
            else:
                mask = (st.session_state["data"]["Propriétaire"] == proprietaire) & (st.session_state["data"]["Joueur"] == sel_banc)
                st.session_state["data"].loc[mask, "Slot"] = "Actif"
                st.session_state["data"] = clean_data(st.session_state["data"])
                st.session_state["data"].to_csv(DATA_FILE, index=False)
                st.success(f"✅ {sel_banc} déplacé vers Actif")
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

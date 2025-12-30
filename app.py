import streamlit as st
import pandas as pd
import io
import os
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

LOGO_SIZE = 55  # taille des logos (px)

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
    # 12 500 000 $
    return f"{int(v):,}".replace(",", " ") + " $"

# =====================================================
# PARSER FANTRAX
# =====================================================
def parse_fantrax(upload):
    raw_lines = upload.read().decode("utf-8", errors="ignore").splitlines()

    # Enlève les lignes complètement vides (mais on garde l'information de séparation)
    # Fantrax: souvent 1 ligne d'entête "Skaters" puis un tableau CSV, puis une ligne vide,
    # puis "Goalies" + un autre tableau CSV.
    #
    # Stratégie:
    # - On repère les index des lignes vides (séparateurs)
    # - On tente de lire 1 ou 2 blocs CSV
    # - On fusionne

    # 1) Trouver les séparateurs (lignes vides)
    blank_idx = [i for i, line in enumerate(raw_lines) if str(line).strip() == ""]

    # 2) Définir les blocs (avant et après la première ligne vide "réelle")
    #    Si pas de ligne vide => on traite en un seul bloc (fallback).
    blocks = []
    if blank_idx:
        cut = blank_idx[0]
        block1 = raw_lines[:cut]
        block2 = raw_lines[cut + 1 :]
        # Nettoyage: enlever les lignes vides résiduelles aux extrémités
        block1 = [l for l in block1 if str(l).strip() != ""]
        block2 = [l for l in block2 if str(l).strip() != ""]
        if len(block1) > 2:
            blocks.append(block1)
        if len(block2) > 2:
            blocks.append(block2)
    else:
        blocks = [[l for l in raw_lines if str(l).strip() != ""]]

    def read_one_block(lines):
        """
        Fantrax ajoute souvent une première ligne 'Skaters' / 'Goalies' ou autre.
        Ton ancien code faisait raw[1:] : on garde cette logique MAIS on la sécurise.
        """
        # Si la 1re ligne n'a pas de virgule, c'est probablement un titre (Skaters/Goalies)
        if lines and ("," not in lines[0]):
            lines = lines[1:]

        csv_text = "\n".join(lines)
        dfx = pd.read_csv(io.StringIO(csv_text), engine="python", on_bad_lines="skip")
        dfx.columns = [c.replace('"', "").strip() for c in dfx.columns]
        return dfx

    # 3) Lire chaque bloc
    dfs = []
    for b in blocks:
        try:
            dfs.append(read_one_block(b))
        except Exception:
            # si un bloc ne se lit pas, on l'ignore
            pass

    if not dfs:
        raise ValueError("Impossible de lire le fichier Fantrax (format inattendu).")

    df = pd.concat(dfs, ignore_index=True)

    # 4) Validation colonnes
    if "Player" not in df.columns or "Salary" not in df.columns:
        raise ValueError("Colonnes Fantrax non détectées (Player/Salary).")

    # 5) Normalisation vers ton format app
    out = pd.DataFrame()
    out["Joueur"] = df["Player"].astype(str)
    out["Pos"] = df.get("Pos", "N/A")
    out["Equipe"] = df.get("Team", "N/A")

    sal = (
        df["Salary"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .replace(["None", "nan", "NaN", ""], "0")
    )

    out["Salaire"] = pd.to_numeric(sal, errors="coerce").fillna(0) * 1000
    out["Statut"] = df.get("Status", "").apply(
        lambda x: "Club École" if "min" in str(x).lower() else "Grand Club"
    )

    return out[out["Joueur"].str.len() > 2]


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

# =====================================================
# DATA
# =====================================================
if "season" not in st.session_state or st.session_state["season"] != season:
    if os.path.exists(DATA_FILE):
        st.session_state["data"] = pd.read_csv(DATA_FILE)
    else:
        st.session_state["data"] = pd.DataFrame(
            columns=["Propriétaire", "Joueur", "Salaire", "Statut", "Pos", "Equipe"]
        )
    st.session_state["season"] = season

# =====================================================
# IMPORT
# =====================================================
st.sidebar.header("📥 Import Fantrax")
if not LOCKED:
    uploaded = st.sidebar.file_uploader("CSV Fantrax", type=["csv", "txt"])
    if uploaded:
        df_import = parse_fantrax(uploaded)
        df_import["Propriétaire"] = uploaded.name.replace(".csv", "")
        st.session_state["data"] = (
            pd.concat([st.session_state["data"], df_import], ignore_index=True)
            .drop_duplicates(subset=["Propriétaire", "Joueur"])
        )
        st.session_state["data"].to_csv(DATA_FILE, index=False)
        st.sidebar.success("✅ Import réussi")

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
        if k.lower() in p.lower():
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
# ONGLETs (Alignement juste après Tableau)
# =====================================================
tab1, tab4, tab2, tab3 = st.tabs(
    ["📊 Tableau", "🧾 Alignement", "⚖️ Transactions", "🧠 Recommandations"]
)

# =====================================================
# TABLEAU (logo + nom sans HTML => corrige l'affichage du <img ...>)
# =====================================================
with tab1:
    headers = st.columns([4, 2, 2, 2, 2])
    headers[0].markdown("**Équipe**")
    headers[1].markdown("**Grand Club**")
    headers[2].markdown("**Club École**")
    headers[3].markdown("**Restant GC**")
    headers[4].markdown("**Restant CE**")

    for _, r in plafonds.iterrows():
        cols = st.columns([4, 2, 2, 2, 2])

        owner = str(r["Propriétaire"])
        logo_path = str(r["Logo"]).strip()

        # Colonne Équipe: logo + propriétaire
        with cols[0]:
            a, b = st.columns([1, 4])
            if logo_path and os.path.exists(logo_path):
                a.image(logo_path, width=LOGO_SIZE)
            else:
                a.markdown("—")
            b.markdown(f"**{owner}**")

        cols[1].markdown(money(r["GC"]))
        cols[2].markdown(money(r["CE"]))
        cols[3].markdown(money(r["Restant GC"]))
        cols[4].markdown(money(r["Restant CE"]))

# =====================================================
# ALIGNEMENT (GC=Act / CE=Min) + DÉPLACEMENT + TOTAUX
# Salaires affichés en dollars complets: 12 500 000 $
# =====================================================
with tab4:
    st.subheader("🧾 Alignement (Grand Club = Act | Club École = Min)")

    proprietaire = st.selectbox(
        "Propriétaire",
        sorted(df["Propriétaire"].unique()),
        key="align_owner",
    )

    data_all = st.session_state["data"]
    dprop = data_all[data_all["Propriétaire"] == proprietaire].copy()

    total_gc = dprop[dprop["Statut"] == "Grand Club"]["Salaire"].sum()
    total_ce = dprop[dprop["Statut"] == "Club École"]["Salaire"].sum()
    restant_gc = st.session_state["PLAFOND_GC"] - total_gc
    restant_ce = st.session_state["PLAFOND_CE"] - total_ce

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("🏒 Total Grand Club (Act)", money(total_gc))
    m2.metric("🏫 Total Club École (Min)", money(total_ce))
    m3.metric("✅ Restant GC", money(restant_gc))
    m4.metric("✅ Restant CE", money(restant_ce))

    if restant_gc < 0 and restant_ce < 0:
        st.error("🚨 Dépassement des plafonds GC ET CE.")
    elif restant_gc < 0:
        st.error("🚨 Dépassement du plafond Grand Club (GC).")
    elif restant_ce < 0:
        st.error("🚨 Dépassement du plafond Club École (CE).")

    st.divider()

    gc = dprop[dprop["Statut"] == "Grand Club"].sort_values(["Pos", "Joueur"])
    ce = dprop[dprop["Statut"] == "Club École"].sort_values(["Pos", "Joueur"])

    c1, c2 = st.columns(2)

    with c1:
        st.markdown("### 🏒 Grand Club (**Act**)")
        if gc.empty:
            st.info("Aucun joueur dans le Grand Club.")
        else:
            gc_view = gc.copy()
            gc_view["Salaire"] = gc_view["Salaire"].apply(money)
            st.dataframe(
                gc_view[["Joueur", "Pos", "Equipe", "Salaire"]].reset_index(drop=True),
                use_container_width=True,
                hide_index=True,
            )

    with c2:
        st.markdown("### 🏫 Club École (**Min**)")
        if ce.empty:
            st.info("Aucun joueur dans le Club École.")
        else:
            ce_view = ce.copy()
            ce_view["Salaire"] = ce_view["Salaire"].apply(money)
            st.dataframe(
                ce_view[["Joueur", "Pos", "Equipe", "Salaire"]].reset_index(drop=True),
                use_container_width=True,
                hide_index=True,
            )

    st.divider()
    st.markdown("### 🔁 Déplacer un joueur")

    if LOCKED:
        st.warning("Saison verrouillée : aucun changement d’alignement n’est permis.")
        st.stop()

    col_move1, col_move2 = st.columns(2)

    # --- GC -> CE
    with col_move1:
        joueurs_gc = gc["Joueur"].tolist()
        joueur_gc = st.selectbox(
            "Déplacer du Grand Club vers Club École",
            joueurs_gc if joueurs_gc else ["—"],
            disabled=(len(joueurs_gc) == 0),
            key="move_gc_to_ce",
        )

        if st.button("➡️ Envoyer au Club École (Min)", disabled=(len(joueurs_gc) == 0), key="btn_gc_to_ce"):
            mask = (st.session_state["data"]["Propriétaire"] == proprietaire) & (
                st.session_state["data"]["Joueur"] == joueur_gc
            )
            st.session_state["data"].loc[mask, "Statut"] = "Club École"
            st.session_state["data"].to_csv(DATA_FILE, index=False)
            st.success(f"✅ {joueur_gc} déplacé vers **Club École (Min)**")
            st.rerun()

    # --- CE -> GC
    with col_move2:
        joueurs_ce = ce["Joueur"].tolist()
        joueur_ce = st.selectbox(
            "Déplacer du Club École vers Grand Club",
            joueurs_ce if joueurs_ce else ["—"],
            disabled=(len(joueurs_ce) == 0),
            key="move_ce_to_gc",
        )

        if st.button("⬅️ Rappeler au Grand Club (Act)", disabled=(len(joueurs_ce) == 0), key="btn_ce_to_gc"):
            mask = (st.session_state["data"]["Propriétaire"] == proprietaire) & (
                st.session_state["data"]["Joueur"] == joueur_ce
            )
            st.session_state["data"].loc[mask, "Statut"] = "Grand Club"
            st.session_state["data"].to_csv(DATA_FILE, index=False)
            st.success(f"✅ {joueur_ce} déplacé vers **Grand Club (Act)**")
            st.rerun()

# =====================================================
# TRANSACTIONS (validation simple)
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
# RECOMMANDATIONS (simple)
# =====================================================
with tab3:
    for _, r in plafonds.iterrows():
        if r["Restant GC"] < 2_000_000:
            st.warning(f"{r['Propriétaire']} : rétrogradation recommandée")
        if r["Restant CE"] > 10_000_000:
            st.info(f"{r['Propriétaire']} : rappel possible")

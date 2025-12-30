import streamlit as st
import pandas as pd
import io
import os
import base64
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
    return f"{int(v):,}".replace(",", " ") + " $"

def salaire_fantrax(v):
    """
    Affiche un salaire Fantrax au format: 12,500 $ x 1000
    (v est stocké en dollars, ex: 12500000)
    """
    return f"{int(v/1000):,}" + " $ x 1000"

# =====================================================
# HTML helpers (logo + cellule)
# =====================================================
def img_to_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def text_cell(text: str, size: int = 55, align: str = "left") -> str:
    return f"""
    <div style="height:{size}px; line-height:{size}px; text-align:{align};">
        {text}
    </div>
    """

def owner_cell(owner: str, logo_path: str, size: int = 55) -> str:
    if logo_path and os.path.exists(logo_path):
        b64 = img_to_base64(logo_path)
        img_html = f"""
        <img src="data:image/png;base64,{b64}"
             style="height:{size}px; width:{size}px; object-fit:contain; display:block;" />
        """
    else:
        img_html = f"""
        <div style="height:{size}px; width:{size}px; display:flex; align-items:center; justify-content:center;">
            —
        </div>
        """

    return f"""
    <div style="height:{size}px; display:flex; align-items:center; gap:12px;">
        <div style="flex:0 0 {size}px; display:flex; align-items:center; justify-content:center;">
            {img_html}
        </div>
        <div style="line-height:1.1;">
            <div style="font-weight:600;">{owner}</div>
        </div>
    </div>
    """

# =====================================================
# PARSER FANTRAX
# =====================================================
def parse_fantrax(upload):
    raw = upload.read().decode("utf-8", errors="ignore").splitlines()
    csv_text = "\n".join(raw[1:])

    df = pd.read_csv(io.StringIO(csv_text), engine="python", on_bad_lines="skip")
    df.columns = [c.replace('"', "").strip() for c in df.columns]

    if "Player" not in df.columns or "Salary" not in df.columns:
        raise ValueError("Colonnes Fantrax non détectées")

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

    # Fantrax = salaire en milliers -> on stocke en dollars
    out["Salaire"] = pd.to_numeric(sal, errors="coerce").fillna(0) * 1000

    # Status contenant "min" => Club École, sinon Grand Club
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
    gc = d[d["Statut"] == "Grand Club"]["Salaire"].sum()
    ce = d[d["Statut"] == "Club École"]["Salaire"].sum()

    logo = ""
    for k, v in LOGOS.items():
        if k.lower() in p.lower():
            logo = v

    resume.append(
        {
            "Propriétaire": p,
            "Logo": logo,
            "GC": gc,
            "CE": ce,
            "Restant GC": st.session_state["PLAFOND_GC"] - gc,
            "Restant CE": st.session_state["PLAFOND_CE"] - ce,
        }
    )

plafonds = pd.DataFrame(resume)

# =====================================================
# ONGLETs
# =====================================================
tab1, tab2, tab3, tab4 = st.tabs(
    ["📊 Tableau", "⚖️ Transactions", "🧠 Recommandations", "🧾 Alignement"]
)

# =====================================================
# TABLEAU (LOGO + NOM DANS LA MÊME COLONNE)
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

        cols[0].markdown(owner_cell(owner, logo_path, LOGO_SIZE), unsafe_allow_html=True)
        cols[1].markdown(text_cell(money(r["GC"]), LOGO_SIZE, "left"), unsafe_allow_html=True)
        cols[2].markdown(text_cell(money(r["CE"]), LOGO_SIZE, "left"), unsafe_allow_html=True)
        cols[3].markdown(text_cell(money(r["Restant GC"]), LOGO_SIZE, "left"), unsafe_allow_html=True)
        cols[4].markdown(text_cell(money(r["Restant CE"]), LOGO_SIZE, "left"), unsafe_allow_html=True)

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

# =====================================================
# ALIGNEMENT (GC=Act / CE=Min) + DÉPLACEMENT + TOTAUX
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

    # Totaux / restants
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
            gc_view = gc.assign(Salaire=gc["Salaire"].apply(salaire_fantrax))
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
            ce_view = ce.assign(Salaire=ce["Salaire"].apply(salaire_fantrax))
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

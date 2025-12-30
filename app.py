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
import csv
import re

def parse_fantrax(upload):
    import csv
    import re

    raw_lines = upload.read().decode("utf-8", errors="ignore").splitlines()
    raw_lines = [re.sub(r"[\x00-\x1f\x7f]", "", l) for l in raw_lines]

    # Détection du séparateur
    def detect_sep(lines):
        for l in lines:
            if "Player" in l and ("Salary" in l):
                for d in [",", ";", "\t"]:
                    if d in l:
                        return d
        return ","

    sep = detect_sep(raw_lines)

    # Détection des headers valides
    header_idxs = [
        i for i, l in enumerate(raw_lines)
        if "player" in l.lower() and "salary" in l.lower()
    ]

    if not header_idxs:
        raise ValueError("Aucune section Fantrax valide détectée (Player / Salary).")

    def read_section(start, end):
        lines = raw_lines[start:end]
        lines = [l for l in lines if l.strip()]
        if len(lines) < 2:
            return None

        df = pd.read_csv(
            io.StringIO("\n".join(lines)),
            sep=sep,
            engine="python",
            on_bad_lines="skip"
        )
        df.columns = [c.strip().replace('"', "") for c in df.columns]
        return df

    dfs = []
    for i, h in enumerate(header_idxs):
        end = header_idxs[i + 1] if i + 1 < len(header_idxs) else len(raw_lines)
        df_part = read_section(h, end)
        if df_part is not None and not df_part.empty:
            dfs.append(df_part)

    if not dfs:
        raise ValueError("Sections Fantrax détectées mais aucune donnée exploitable.")

    df = pd.concat(dfs, ignore_index=True)

    # Normalisation colonnes
    cols = {c.lower(): c for c in df.columns}

    if "player" not in cols or "salary" not in cols:
        raise ValueError(f"Colonnes Fantrax manquantes. Colonnes trouvées: {list(df.columns)}")

    out = pd.DataFrame()
    out["Joueur"] = df[cols["player"]].astype(str)

    # 👉 ÉQUIPE DU JOUEUR (Team)
    out["Equipe"] = df[cols["team"]] if "team" in cols else "N/A"

    out["Pos"] = df[cols["pos"]] if "pos" in cols else "N/A"

    sal = (
        df[cols["salary"]]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.replace(" ", "", regex=False)
        .replace(["None", "nan", "NaN", ""], "0")
    )

    out["Salaire"] = pd.to_numeric(sal, errors="coerce").fillna(0) * 1000

    if "status" in cols:
        out["Statut"] = df[cols["status"]].apply(
            lambda x: "Club École" if "min" in str(x).lower() else "Grand Club"
        )
    else:
        out["Statut"] = "Grand Club"

    # Sécurité finale
    out = out[out["Joueur"].str.len() > 2].reset_index(drop=True)

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

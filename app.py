import streamlit as st
import pandas as pd
import os
from datetime import datetime

# =====================================================
# CONFIG
# =====================================================
st.set_page_config(page_title="Pool Hockey", layout="wide")

DATA_FILE = "data_pool.csv"
HISTORY_FILE = "historique_mouvements.csv"

# =====================================================
# UTILS
# =====================================================
def money(x):
    try:
        return f"{float(x):,.0f} $"
    except Exception:
        return "—"

def logo_for_owner(owner):
    logos = {
        "Nordiques": "Nordiques_Logo.png",
        "Canadiens": "Canadiens_Logo.png",
        "Cracheurs": "Cracheurs_Logo.png",
        "Prédateurs": "Predateurs_Logo.png",
        "Red Wings": "Red_Wings_Logo.png",
        "Whalers": "Whalers_Logo.png",
    }
    return logos.get(owner, "")

def safe_col(df, name, default=""):
    if name in df.columns:
        return df[name]
    return pd.Series([default] * len(df), index=df.index)

# =====================================================
# HEADER
# =====================================================
if os.path.exists("Logo_Pool.png"):
    st.image("Logo_Pool.png", width=500)

st.title("🏒 Gestion du Pool Hockey")

# =====================================================
# SIDEBAR – PLAFONDS
# =====================================================
st.sidebar.header("⚖️ Plafonds salariaux")

st.session_state["PLAFOND_GC"] = st.sidebar.number_input(
    "Grand Club (GC)",
    value=85_000_000,
    step=1_000_000
)

st.session_state["PLAFOND_CE"] = st.sidebar.number_input(
    "Club École (CE)",
    value=15_000_000,
    step=500_000
)

st.sidebar.divider()

uploaded = st.sidebar.file_uploader(
    "📥 Import CSV Fantrax (Skaters + Goalies)",
    type=["csv"]
)

# =====================================================
# SESSION INIT
# =====================================================
if "data" not in st.session_state:
    st.session_state.data = None

# =====================================================
# IMPORT FANTRAX
# =====================================================
if uploaded:
    try:
        df = pd.read_csv(
            uploaded,
            engine="python",
            sep=",",
            on_bad_lines="skip"
        )

        df.columns = [c.strip() for c in df.columns]

        df["Joueur"] = safe_col(df, "Player")
        df["Pos"] = safe_col(df, "Pos")
        df["Équipe"] = safe_col(df, "Team")
        df["Statut"] = safe_col(df, "Statut", "Grand Club")
        df["Propriétaire"] = safe_col(df, "Owner", "Nordiques")

        df["Salaire"] = pd.to_numeric(
            safe_col(df, "Salary", 0),
            errors="coerce"
        ).fillna(0)

        df["Logo"] = df["Propriétaire"].apply(logo_for_owner)

        df = df[
            ["Logo", "Propriétaire", "Joueur", "Pos", "Équipe", "Salaire", "Statut"]
        ]

        df.to_csv(DATA_FILE, index=False)
        st.session_state.data = df

        st.success("✅ Import Fantrax réussi")

    except Exception as e:
        st.error(f"❌ Import impossible : {e}")

# =====================================================
# MAIN
# =====================================================
if st.session_state.data is not None:
    df = st.session_state.data

    tab1, tab2, tab3 = st.tabs(
        ["📋 Tableau", "🧾 Alignement GC / CE", "📜 Historique"]
    )

    # =================================================
    # TAB 1 – TABLEAU
    # =================================================
    with tab1:
        total_gc = df[df["Statut"] == "Grand Club"]["Salaire"].sum()
        total_ce = df[df["Statut"] == "Club École"]["Salaire"].sum()

        c1, c2 = st.columns(2)
        c1.metric(
            "💰 Grand Club",
            money(total_gc),
            delta=money(st.session_state["PLAFOND_GC"] - total_gc),
        )
        c2.metric(
            "💰 Club École",
            money(total_ce),
            delta=money(st.session_state["PLAFOND_CE"] - total_ce),
        )

        st.divider()

        display_df = df.copy()
        display_df["Salaire"] = display_df["Salaire"].apply(money)

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True
        )

    # =================================================
    # TAB 2 – MODIFICATION GC / CE
    # =================================================
    with tab2:
        st.subheader("🧾 Gestion de l’alignement (Grand Club / Club École)")

        proprietaire = st.selectbox(
            "Propriétaire",
            sorted(df["Propriétaire"].unique())
        )

        joueurs_prop = df[df["Propriétaire"] == proprietaire]

        joueur = st.selectbox(
            "Joueur",
            joueurs_prop["Joueur"].sort_values().unique()
        )

        ligne = joueurs_prop[joueurs_prop["Joueur"] == joueur].iloc[0]

        statut_actuel = ligne["Statut"]
        salaire = ligne["Salaire"]

        st.info(
            f"Statut actuel : **{statut_actuel}** — "
            f"Salaire : **{money(salaire)}**"
        )

        nouveau_statut = st.radio(
            "Nouveau statut",
            ["Grand Club", "Club École"],
            index=0 if statut_actuel == "Grand Club" else 1
        )

        if st.button("✅ Appliquer le changement"):
            temp = df.copy()

            mask = (
                (temp["Propriétaire"] == proprietaire)
                & (temp["Joueur"] == joueur)
            )

            temp.loc[mask, "Statut"] = nouveau_statut

            d = temp[temp["Propriétaire"] == proprietaire]
            gc = d[d["Statut"] == "Grand Club"]["Salaire"].sum()
            ce = d[d["Statut"] == "Club École"]["Salaire"].sum()

            if gc > st.session_state["PLAFOND_GC"]:
                st.error("🚨 Dépassement du plafond Grand Club")
            elif ce > st.session_state["PLAFOND_CE"]:
                st.error("🚨 Dépassement du plafond Club École")
            else:
                df.loc[mask, "Statut"] = nouveau_statut
                df.to_csv(DATA_FILE, index=False)
                st.session_state.data = df

                hist = {
                    "Date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "Propriétaire": proprietaire,
                    "Joueur": joueur,
                    "De": statut_actuel,
                    "À": nouveau_statut,
                    "Salaire": salaire,
                }

                if os.path.exists(HISTORY_FILE):
                    h = pd.read_csv(HISTORY_FILE)
                    h = pd.concat([h, pd.DataFrame([hist])])
                else:
                    h = pd.DataFrame([hist])

                h.to_csv(HISTORY_FILE, index=False)

                st.success("✅ Alignement mis à jour")
                st.rerun()

    # =================================================
    # TAB 3 – HISTORIQUE
    # =================================================
    with tab3:
        if os.path.exists(HISTORY_FILE):
            hist = pd.read_csv(HISTORY_FILE)
            hist["Salaire"] = hist["Salaire"].apply(money)
            st.dataframe(hist, use_container_width=True, hide_index=True)
        else:
            st.info("Aucun mouvement enregistré")

else:
    st.info("📥 Importez un fichier CSV Fantrax pour commencer")

import streamlit as st
import pandas as pd
import os
from datetime import datetime

st.set_page_config(page_title="Pool Hockey", layout="wide")

# ===================== UTILS =====================
def money(x):
    try:
        return f"{float(x):,.0f} $"
    except:
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

# ===================== HEADER =====================
if os.path.exists("Logo_Pool.png"):
    st.image("Logo_Pool.png", width=450)

st.title("🏒 Gestion Pool Hockey")

# ===================== SIDEBAR =====================
st.sidebar.header("⚖️ Plafonds salariaux")

plafond_gc = st.sidebar.number_input(
    "Grand Club (GC)", value=95_500_000, step=500_000
)

plafond_ce = st.sidebar.number_input(
    "Club École (CE)", value=47_750_000, step=500_000
)

st.sidebar.divider()

uploaded = st.sidebar.file_uploader(
    "📥 Import CSV Fantrax (Skaters + Goalies)",
    type=["csv"]
)

# ===================== SESSION =====================
if "df" not in st.session_state:
    st.session_state.df = None

if "history" not in st.session_state:
    st.session_state.history = []

# ===================== IMPORT FANTRAX =====================
if uploaded:
    try:
        df = pd.read_csv(
            uploaded,
            engine="python",
            sep=",",
            on_bad_lines="skip"
        )

        df.columns = [c.strip() for c in df.columns]

        df["Player"] = safe_col(df, "Player")
        df["Pos"] = safe_col(df, "Pos")
        df["Team"] = safe_col(df, "Team")
        df["Status"] = safe_col(df, "Status")

        df["Salary"] = pd.to_numeric(
            safe_col(df, "Salary", 0),
            errors="coerce"
        ).fillna(0)

        if "Club" not in df.columns:
            df["Club"] = "GC"

        if "Owner" not in df.columns:
            df["Owner"] = "Nordiques"

        df["Logo"] = df["Owner"].apply(logo_for_owner)

        df = df[
            ["Logo", "Player", "Pos", "Team", "Salary", "Status", "Club"]
        ]

        st.session_state.df = df
        st.success("✅ Import Fantrax réussi")

    except Exception as e:
        st.error(f"❌ Import impossible : {e}")

# ===================== MAIN =====================
if st.session_state.df is not None:
    df = st.session_state.df

    tab1, tab2 = st.tabs(["📋 Tableau", "📜 Historique"])

    # ---------- TABLEAU ----------
    with tab1:
        total_gc = df[df["Club"] == "GC"]["Salary"].sum()
        total_ce = df[df["Club"] == "CE"]["Salary"].sum()

        c1, c2 = st.columns(2)
        c1.metric(
            "💰 Grand Club",
            money(total_gc),
            delta=money(plafond_gc - total_gc)
        )
        c2.metric(
            "💰 Club École",
            money(total_ce),
            delta=money(plafond_ce - total_ce)
        )

        st.divider()

        display_df = df.copy()
        display_df["Salaire"] = display_df["Salary"].apply(money)
        display_df = display_df.drop(columns=["Salary"])

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True
        )

        st.divider()
        st.subheader("🔄 Déplacement GC ↔ CE")

        joueur = st.selectbox("Joueur", df["Player"].unique())
        destination = st.radio("Vers", ["GC", "CE"], horizontal=True)

        if st.button("Appliquer le changement"):
            idx = df[df["Player"] == joueur].index[0]
            origine = df.at[idx, "Club"]
            df.at[idx, "Club"] = destination

            st.session_state.history.append({
                "Date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "Joueur": joueur,
                "De": origine,
                "À": destination
            })

            st.success(f"{joueur} déplacé de {origine} vers {destination}")

    # ---------- HISTORIQUE ----------
    with tab2:
        if st.session_state.history:
            st.dataframe(
                pd.DataFrame(st.session_state.history),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("Aucun mouvement enregistré")

else:
    st.info("📥 Importez un fichier CSV Fantrax pour commencer")

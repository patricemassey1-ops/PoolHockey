import streamlit as st
import pandas as pd
import os
from datetime import datetime

st.set_page_config(page_title="Pool Hockey", layout="wide")

# ---------------- UTILS ----------------
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
    return logos.get(owner, None)

def col(df, name, default=""):
    return df[name] if name in df.columns else default

# ---------------- HEADER ----------------
if os.path.exists("Logo_Pool.png"):
    st.image("Logo_Pool.png", width=350)

st.title("🏒 Gestion Pool Hockey")

# ---------------- SIDEBAR ----------------
st.sidebar.header("⚖️ Plafonds salariaux")

plafond_gc = st.sidebar.number_input(
    "Grand Club (GC)", value=85000000, step=1_000_000
)

plafond_ce = st.sidebar.number_input(
    "Club École (CE)", value=15_000_000, step=500_000
)

st.sidebar.divider()

uploaded = st.sidebar.file_uploader(
    "📥 Importer un fichier Fantrax CSV",
    type=["csv"]
)

# ---------------- SESSION ----------------
if "df" not in st.session_state:
    st.session_state.df = None

if "history" not in st.session_state:
    st.session_state.history = []

# ---------------- IMPORT FANTRAX ----------------
if uploaded:
    try:
        df = pd.read_csv(
            uploaded,
            engine="python",
            sep=",",
            on_bad_lines="skip"
        )

        df.columns = [c.strip() for c in df.columns]

        # Colonnes essentielles Fantrax
        df["Player"] = col(df, "Player")
        df["Pos"] = col(df, "Pos")
        df["Team"] = col(df, "Team")

        df["Salary"] = pd.to_numeric(
            col(df, "Salary", 0),
            errors="coerce"
        ).fillna(0)

        if "Club" not in df.columns:
            df["Club"] = "GC"

        if "Owner" not in df.columns:
            df["Owner"] = "Nordiques"

        df["Logo"] = df["Owner"].apply(logo_for_owner)

        st.session_state.df = df
        st.success("✅ Import Fantrax réussi")

    except Exception as e:
        st.error(f"❌ Import impossible : {e}")

# ---------------- MAIN ----------------
if st.session_state.df is not None:
    df = st.session_state.df

    tab1, tab2, tab3 = st.tabs([
        "📋 Tableau",
        "🔄 Mouvements",
        "📄 Export PDF"
    ])

    # ---------- TABLEAU ----------
    with tab1:
        st.subheader("Alignement")

        total_gc = df[df["Club"] == "GC"]["Salary"].sum()
        total_ce = df[df["Club"] == "CE"]["Salary"].sum()

        c1, c2 = st.columns(2)
        c1.metric(
            "💰 Grand Club",
            money(total_gc),
            delta=f"{money(plafond_gc - total_gc)} restant"
        )
        c2.metric(
            "💰 Club École",
            money(total_ce),
            delta=f"{money(plafond_ce - total_ce)} restant"
        )

        st.divider()

        for _, r in df.iterrows():
            cols = st.columns([1, 4, 1, 1, 1, 1])

            if r["Logo"] and os.path.exists(r["Logo"]):
                cols[0].image(r["Logo"], width=45)
            else:
                cols[0].markdown("—")

            cols[1].markdown(f"**{r['Player']}**")
            cols[2].markdown(r["Pos"])
            cols[3].markdown(r["Team"])
            cols[4].markdown(money(r["Salary"]))
            cols[5].markdown("GC" if r["Club"] == "GC" else "CE")

        st.divider()

        st.subheader("🔄 Modifier l’affectation")

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
        st.subheader("📜 Historique des mouvements")
        if st.session_state.history:
            st.dataframe(
                pd.DataFrame(st.session_state.history),
                use_container_width=True
            )
        else:
            st.info("Aucun mouvement effectué")

    # ---------- EXPORT PDF ----------
    with tab3:
        st.info("📄 Export PDF stylé (identique Excel)")
        st.write("• Logos\n• GC / CE\n• Salaires\n• Mise en page prête")

else:
    st.info("📥 Importez un fichier Fantrax CSV pour commencer")

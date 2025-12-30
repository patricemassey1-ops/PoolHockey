import streamlit as st
import pandas as pd
import os
from datetime import datetime
from zoneinfo import ZoneInfo

# ================= CONFIG =================
st.set_page_config(page_title="Calculateur Fantrax", layout="wide")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

PLAFOND_GC = 95_500_000
PLAFOND_CE = 47_750_000

# ================= UTILS =================
def format_currency(v):
    try:
        return f"{int(float(v)):,}".replace(",", " ") + " $"
    except:
        return "0 $"

def season_files(season):
    return (
        f"{DATA_DIR}/fantrax_{season}.csv",
        f"{DATA_DIR}/actions_{season}.csv",
    )

def save(df, f):
    df.drop_duplicates().to_csv(f, index=False)

def log_action(season, p, a, j, d):
    tz = ZoneInfo("America/Montreal")
    now = datetime.now(tz)
    row = pd.DataFrame([{
        "Date": now.strftime("%Y-%m-%d"),
        "Heure": now.strftime("%H:%M:%S"),
        "Saison": season,
        "Propriétaire": p,
        "Action": a,
        "Joueur": j,
        "Details": d
    }])
    st.session_state["actions"] = pd.concat([st.session_state["actions"], row], ignore_index=True)
    save(st.session_state["actions"], ACTIONS_FILE)

# ================= SIDEBAR – SAISON =================
st.sidebar.header("📅 Saison")
season = st.sidebar.selectbox(
    "Choisir la saison",
    ["2024-2025", "2025-2026", "2026-2027"]
)

DATA_FILE, ACTIONS_FILE = season_files(season)

# ================= SESSION =================
if "data" not in st.session_state or st.session_state.get("season") != season:
    st.session_state["data"] = (
        pd.read_csv(DATA_FILE)
        if os.path.exists(DATA_FILE)
        else pd.DataFrame(columns=["Propriétaire", "Joueur", "Salaire", "Statut"])
    )
    st.session_state["actions"] = (
        pd.read_csv(ACTIONS_FILE)
        if os.path.exists(ACTIONS_FILE)
        else pd.DataFrame(columns=["Date","Heure","Saison","Propriétaire","Action","Joueur","Details"])
    )
    st.session_state["season"] = season

# ================= SIDEBAR IMPORT =================
st.sidebar.header("📥 Import Fantrax")
file = st.sidebar.file_uploader("CSV Fantrax", type="csv")

if file:
    df = pd.read_csv(file)

    df["Salaire"] = (
        df["Salary"]
        .astype(str)
        .str.replace(r"[\$, ]", "", regex=True)
        .astype(float)
        * 1000
    )

    df["Statut"] = df["Status"].apply(
        lambda x: "Club École" if "MIN" in str(x) else "Grand Club"
    )

    df["Propriétaire"] = file.name.replace(".csv", "")
    df = df[["Propriétaire", "Player", "Salaire", "Statut"]]
    df.columns = ["Propriétaire", "Joueur", "Salaire", "Statut"]

    st.session_state["data"] = pd.concat([st.session_state["data"], df], ignore_index=True)
    save(st.session_state["data"], DATA_FILE)

    log_action(season, "SYSTEM", "IMPORT", "-", file.name)
    st.sidebar.success("Import réussi")

# ================= TABS =================
tab1, tab2, tab3, tab4 = st.tabs(
    ["📊 Dashboard", "⚖️ Simulateur", "🧠 Suggestions", "📜 Historique"]
)

# ================= DASHBOARD =================
with tab1:
    st.header(f"📊 Masse salariale – Saison {season}")

    if st.session_state["data"].empty:
        st.info("Aucune donnée.")
    else:
        g = (
            st.session_state["data"]
            .groupby(["Propriétaire", "Statut"])["Salaire"]
            .sum()
            .unstack(fill_value=0)
        )

        st.bar_chart(g)
        st.dataframe(g.applymap(format_currency), use_container_width=True)

        # EXPORT CSV
        csv = g.reset_index().to_csv(index=False).encode("utf-8")
        st.download_button("📤 Export CSV", csv, f"masse_{season}.csv")

        # EXPORT EXCEL MULTI-FEUILLES
        excel_path = f"{DATA_DIR}/export_{season}.xlsx"
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            g.to_excel(writer, sheet_name="Résumé")
            for p in g.index:
                st.session_state["data"][
                    st.session_state["data"]["Propriétaire"] == p
                ].to_excel(writer, sheet_name=p[:31], index=False)

        with open(excel_path, "rb") as f:
            st.download_button("📊 Export Excel", f, file_name=f"fantrax_{season}.xlsx")

        # EXPORT PDF HTML
        html = g.reset_index().to_html(index=False)
        st.download_button(
            "📄 Export PDF (HTML)",
            html,
            file_name=f"fantrax_{season}.html",
            mime="text/html"
        )

# ================= SIMULATEUR =================
with tab2:
    st.header("⚖️ Simulateur")

    if st.session_state["data"].empty:
        st.info("Importer des données.")
    else:
        p = st.selectbox("Propriétaire", st.session_state["data"]["Propriétaire"].unique())
        dfp = st.session_state["data"][st.session_state["data"]["Propriétaire"] == p]

        joueur = st.selectbox("Joueur", dfp["Joueur"])
        j = dfp[dfp["Joueur"] == joueur].iloc[0]

        if st.button("Simuler retrait"):
            total = dfp[dfp["Statut"] == j["Statut"]]["Salaire"].sum()
            nouveau = total - j["Salaire"]
            plafond = PLAFOND_GC if j["Statut"] == "Grand Club" else PLAFOND_CE

            st.info(
                f"Nouveau total {j['Statut']} : {format_currency(nouveau)} "
                f"(plafond {format_currency(plafond)})"
            )

# ================= SUGGESTIONS =================
with tab3:
    st.header("🧠 Suggestions")

    for p in st.session_state["data"]["Propriétaire"].unique():
        dfp = st.session_state["data"][st.session_state["data"]["Propriétaire"] == p]
        total_gc = dfp[dfp["Statut"] == "Grand Club"]["Salaire"].sum()

        if total_gc > PLAFOND_GC:
            surplus = total_gc - PLAFOND_GC
            worst = dfp[dfp["Statut"] == "Grand Club"].sort_values("Salaire", ascending=False).iloc[0]
            st.warning(f"{p} dépasse de {format_currency(surplus)} → Descendre {worst['Joueur']}")

# ================= HISTORIQUE =================
with tab4:
    st.header("📜 Historique")

    if st.session_state["actions"].empty:
        st.info("Aucune action.")
    else:
        st.dataframe(st.session_state["actions"], use_container_width=True)

        if st.button("↩️ Undo dernière action"):
            st.session_state["actions"] = st.session_state["actions"].iloc[:-1]
            save(st.session_state["actions"], ACTIONS_FILE)
            st.success("Action annulée")

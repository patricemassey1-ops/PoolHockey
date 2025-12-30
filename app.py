import streamlit as st
import pandas as pd
import io
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet

# ================= CONFIG =================
st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

DB_FILE = "historique_fantrax.csv"
HISTORIQUE_FILE = "historique_actions.csv"

PLAFOND_GC = 95_500_000
PLAFOND_CE = 47_750_000

# ================= UTILS =================
def format_currency(v):
    try:
        return f"{int(float(v)):,}".replace(",", " ") + " $"
    except:
        return "0 $"

def save(df, f): df.to_csv(f, index=False)

def log_action(p, a, j, d):
    tz = ZoneInfo("America/Montreal")
    now = datetime.now(tz)
    row = pd.DataFrame([{
        "Date": now.strftime("%Y-%m-%d"),
        "Heure": now.strftime("%H:%M:%S"),
        "Propriétaire": p,
        "Action": a,
        "Joueur": j,
        "Details": d
    }])
    st.session_state["actions"] = pd.concat([st.session_state["actions"], row])
    save(st.session_state["actions"], HISTORIQUE_FILE)

# ================= SESSION =================
if "data" not in st.session_state:
    st.session_state["data"] = pd.read_csv(DB_FILE) if os.path.exists(DB_FILE) else pd.DataFrame(
        columns=["Propriétaire","Joueur","Salaire","Statut"]
    )

if "actions" not in st.session_state:
    st.session_state["actions"] = pd.read_csv(HISTORIQUE_FILE) if os.path.exists(HISTORIQUE_FILE) else pd.DataFrame(
        columns=["Date","Heure","Propriétaire","Action","Joueur","Details"]
    )

# ================= SIDEBAR IMPORT =================
st.sidebar.header("📥 Importer un fichier Fantrax")
file = st.sidebar.file_uploader("CSV Fantrax", type="csv")

if file:
    df = pd.read_csv(file)
    df["Salaire"] = df["Salary"].astype(str).str.replace(r"[\$, ]","",regex=True).astype(float)*1000
    df["Statut"] = df["Status"].apply(lambda x: "Club École" if "MIN" in str(x) else "Grand Club")
    df["Propriétaire"] = file.name.replace(".csv","")
    df = df[["Propriétaire","Player","Salaire","Statut"]]
    df.columns = ["Propriétaire","Joueur","Salaire","Statut"]

    st.session_state["data"] = pd.concat([st.session_state["data"], df])
    save(st.session_state["data"], DB_FILE)
    st.sidebar.success("Import réussi")

# ================= TABS =================
tab1,tab2,tab3,tab4 = st.tabs(["📊 Dashboard","⚖️ Simulateur","🧠 Suggestions","📜 Historique"])

# ================= DASHBOARD + GRAPHIQUES =================
with tab1:
    st.header("📊 Masse salariale")
    if st.session_state["data"].empty:
        st.info("Aucune donnée")
    else:
        g = st.session_state["data"].groupby(["Propriétaire","Statut"])["Salaire"].sum().unstack(fill_value=0)
        st.bar_chart(g)
        st.dataframe(g.applymap(format_currency), use_container_width=True)

        # EXPORT PDF
        if st.button("📄 Export PDF"):
            pdf = "export.pdf"
            doc = SimpleDocTemplate(pdf)
            styles = getSampleStyleSheet()
            content = [Paragraph("Masse salariale", styles["Title"])]
            for p,row in g.iterrows():
                content.append(Paragraph(f"{p} : GC {format_currency(row.get('Grand Club',0))}", styles["Normal"]))
            doc.build(content)
            with open(pdf,"rb") as f:
                st.download_button("Télécharger PDF", f, file_name="fantrax.pdf")

# ================= SIMULATEUR + PREVIEW =================
with tab2:
    st.header("⚖️ Simulateur avec aperçu")
    p = st.selectbox("Propriétaire", st.session_state["data"]["Propriétaire"].unique())
    dfp = st.session_state["data"][st.session_state["data"]["Propriétaire"]==p]

    joueur = st.selectbox("Joueur", dfp["Joueur"])
    j = dfp[dfp["Joueur"]==joueur].iloc[0]

    if st.button("Simuler déplacement"):
        if j["Statut"]=="Grand Club":
            nouveau = dfp[dfp["Statut"]=="Grand Club"]["Salaire"].sum() - j["Salaire"]
            st.info(f"Nouveau total GC: {format_currency(nouveau)}")
        else:
            nouveau = dfp[dfp["Statut"]=="Club École"]["Salaire"].sum() - j["Salaire"]
            st.info(f"Nouveau total CE: {format_currency(nouveau)}")

# ================= SUGGESTIONS AUTO =================
with tab3:
    st.header("🧠 Suggestions automatiques")
    for p in st.session_state["data"]["Propriétaire"].unique():
        dfp = st.session_state["data"][st.session_state["data"]["Propriétaire"]==p]
        total_gc = dfp[dfp["Statut"]=="Grand Club"]["Salaire"].sum()
        if total_gc > PLAFOND_GC:
            surplus = total_gc - PLAFOND_GC
            worst = dfp[dfp["Statut"]=="Grand Club"].sort_values("Salaire",ascending=False).iloc[0]
            st.warning(f"{p} dépasse de {format_currency(surplus)} → Descendre {worst['Joueur']}")

# ================= HISTORIQUE + UNDO =================
with tab4:
    st.header("📜 Historique + Undo")
    st.dataframe(st.session_state["actions"], use_container_width=True)

    if not st.session_state["actions"].empty:
        if st.button("↩️ Annuler dernière action"):
            st.session_state["actions"] = st.session_state["actions"].iloc[:-1]
            save(st.session_state["actions"], HISTORIQUE_FILE)
            st.success("Dernière action annulée")

import streamlit as st
import pandas as pd
import io, os
from datetime import datetime
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import LETTER

# =====================================================
# CONFIG
# =====================================================
st.set_page_config("Pool Hockey – GM", layout="wide")
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# =====================================================
# PLAFONDS (SESSION)
# =====================================================
st.session_state.setdefault("PLAFOND_GC", 95_500_000)
st.session_state.setdefault("PLAFOND_CE", 47_750_000)

# =====================================================
# LOGOS
# =====================================================
LOGOS = {
    "Nordiques": "Nordiques_Logo.png",
    "Cracheurs": "Cracheurs_Logo.png",
    "Prédateurs": "Prédateurs_Logo.png",
    "Red Wings": "Red_Wings_Logo.png",
    "Whalers": "Whalers_Logo.png",
    "Canadiens": "Canadiens_Logo.png"
}

# =====================================================
# UTILS
# =====================================================
def money(v): return f"{int(v):,}".replace(",", " ") + " $"

def saison_auto():
    now = datetime.now()
    return f"{now.year}-{now.year+1}" if now.month >= 9 else f"{now.year-1}-{now.year}"

def saison_verrouillee(s): return int(s[:4]) < int(saison_auto()[:4])

# =====================================================
# PARSER FANTRAX
# =====================================================
def parse_fantrax(upload):
    raw = upload.read().decode("utf-8", errors="ignore").splitlines()
    df = pd.read_csv(io.StringIO("\n".join(raw[1:])), engine="python", on_bad_lines="skip")
    df.columns = [c.strip() for c in df.columns]

    out = pd.DataFrame()
    out["Joueur"] = df["Player"]
    out["Salaire"] = (
        df["Salary"].astype(str)
        .str.replace(",", "")
        .replace(["None", "nan", ""], "0")
        .astype(float) * 1000
    )
    out["Statut"] = df.get("Status", "").apply(
        lambda x: "Club École" if "min" in str(x).lower() else "Grand Club"
    )
    return out

# =====================================================
# SIDEBAR – SAISON & PLAFONDS
# =====================================================
st.sidebar.header("📅 Saison")
saisons = ["2024-2025", "2025-2026", "2026-2027"]
auto = saison_auto()
if auto not in saisons: saisons.append(auto)
season = st.sidebar.selectbox("Saison", saisons, index=saisons.index(auto))
LOCKED = saison_verrouillee(season)

DATA_FILE = f"{DATA_DIR}/data_{season}.csv"
HIST_FILE = f"{DATA_DIR}/history_{season}.csv"

st.sidebar.divider()
if st.sidebar.button("✏️ Modifier plafonds"):
    st.session_state["PLAFOND_GC"] = st.sidebar.number_input("Plafond GC", value=st.session_state["PLAFOND_GC"])
    st.session_state["PLAFOND_CE"] = st.sidebar.number_input("Plafond CE", value=st.session_state["PLAFOND_CE"])

st.sidebar.metric("🏒 Grand Club", money(st.session_state["PLAFOND_GC"]))
st.sidebar.metric("🏫 Club École", money(st.session_state["PLAFOND_CE"]))

# =====================================================
# DATA LOAD
# =====================================================
if "data" not in st.session_state:
    st.session_state["data"] = pd.read_csv(DATA_FILE) if os.path.exists(DATA_FILE) else pd.DataFrame(
        columns=["Propriétaire", "Joueur", "Salaire", "Statut"]
    )

df = st.session_state["data"]

# =====================================================
# IMPORT
# =====================================================
st.sidebar.header("📥 Import Fantrax")
if not LOCKED:
    up = st.sidebar.file_uploader("CSV Fantrax", type="csv")
    if up:
        temp = parse_fantrax(up)
        temp["Propriétaire"] = up.name.replace(".csv", "")
        df = pd.concat([df, temp]).drop_duplicates(["Propriétaire", "Joueur"])
        df.to_csv(DATA_FILE, index=False)
        st.session_state["data"] = df
        st.sidebar.success("Import OK")

# =====================================================
# HEADER
# =====================================================
st.image("Logo_Pool.png", width=400)
st.title("🏒 Gestion GM – Pool Hockey")

if df.empty:
    st.info("Aucune donnée")
    st.stop()

# =====================================================
# CALCULS
# =====================================================
resume = []
for p in df["Propriétaire"].unique():
    d = df[df["Propriétaire"] == p]
    gc = d[d["Statut"] == "Grand Club"]["Salaire"].sum()
    ce = d[d["Statut"] == "Club École"]["Salaire"].sum()
    logo = next((v for k,v in LOGOS.items() if k.lower() in p.lower()), "")
    resume.append({
        "Propriétaire": p,
        "Logo": logo,
        "GC": gc,
        "CE": ce,
        "Restant GC": st.session_state["PLAFOND_GC"] - gc,
        "Restant CE": st.session_state["PLAFOND_CE"] - ce
    })
plafonds = pd.DataFrame(resume)

# =====================================================
# TABS
# =====================================================
tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Tableau",
    "🔄 Alignement",
    "📜 Historique",
    "📄 Export PDF"
])

# =====================================================
# 📊 TABLEAU
# =====================================================
with tab1:
    for _, r in plafonds.iterrows():
        c = st.columns([1,2,2,2,2,2])
        c[0].image(r["Logo"], width=50) if r["Logo"] else c[0].markdown("—")
        c[1].markdown(f"**{r['Propriétaire']}**")
        c[2].markdown(money(r["GC"]))
        c[3].markdown(money(r["CE"]))
        c[4].markdown(money(r["Restant GC"]))
        c[5].markdown(money(r["Restant CE"]))

# =====================================================
# 🔄 DRAG & DROP (GC / CE)
# =====================================================
with tab2:
    prop = st.selectbox("Propriétaire", df["Propriétaire"].unique())
    d = df[df["Propriétaire"] == prop]

    col1, col2 = st.columns(2)
    with col1:
        gc_player = st.selectbox("🏒 Grand Club", d[d["Statut"]=="Grand Club"]["Joueur"])
    with col2:
        ce_player = st.selectbox("🏫 Club École", d[d["Statut"]=="Club École"]["Joueur"])

    if st.button("⇄ Basculer"):
        joueur = gc_player or ce_player
        new = "Club École" if gc_player else "Grand Club"
        df.loc[(df["Propriétaire"]==prop)&(df["Joueur"]==joueur),"Statut"]=new
        df.to_csv(DATA_FILE, index=False)

        hist = pd.DataFrame([{
            "Date": datetime.now(),
            "Propriétaire": prop,
            "Joueur": joueur,
            "Vers": new
        }])
        hist.to_csv(HIST_FILE, mode="a", header=not os.path.exists(HIST_FILE), index=False)
        st.success("Alignement mis à jour")
        st.rerun()

# =====================================================
# 📜 HISTORIQUE
# =====================================================
with tab3:
    if os.path.exists(HIST_FILE):
        st.dataframe(pd.read_csv(HIST_FILE))
    else:
        st.info("Aucun mouvement")

# =====================================================
# 📄 EXPORT PDF
# =====================================================
with tab4:
    p = st.selectbox("Exporter pour", df["Propriétaire"].unique())
    if st.button("📄 Générer PDF"):
        pdf_path = f"/tmp/{p}.pdf"
        doc = SimpleDocTemplate(pdf_path, pagesize=LETTER)
        styles = getSampleStyleSheet()
        elements = [Paragraph(f"<b>{p}</b>", styles["Title"]), Spacer(1,12)]

        data = df[df["Propriétaire"]==p][["Joueur","Statut","Salaire"]]
        table = Table([data.columns.tolist()] + data.values.tolist())
        elements.append(table)

        doc.build(elements)
        with open(pdf_path,"rb") as f:
            st.download_button("⬇️ Télécharger PDF", f, file_name=f"{p}.pdf")

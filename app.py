import streamlit as st
import pandas as pd
import io
import os
from datetime import datetime
import matplotlib.pyplot as plt

# =====================================================
# CONFIG
# =====================================================
st.set_page_config("Fantrax Pool Hockey", layout="wide")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

PLAFOND_GC = 95_500_000
PLAFOND_CE = 47_750_000

# =====================================================
# SAISON AUTO
# =====================================================
def saison_auto():
    now = datetime.now()
    return f"{now.year}-{now.year+1}" if now.month >= 9 else f"{now.year-1}-{now.year}"

def saison_verrouillee(season):
    return int(season[:4]) < int(saison_auto()[:4])

# =====================================================
# FORMAT
# =====================================================
def money(v):
    return f"{int(v):,}".replace(",", " ") + " $"

# =====================================================
# PARSER FANTRAX ROBUSTE (TESTÉ AVEC Nordiques.csv)
# =====================================================
def parse_fantrax(upload):
    raw = upload.read().decode("utf-8", errors="ignore").splitlines()

    if len(raw) < 3:
        raise ValueError("Fichier trop court")

    # Ignorer la 1re ligne vide / Skaters
    csv_text = "\n".join(raw[1:])

    df = pd.read_csv(
        io.StringIO(csv_text),
        engine="python",
        on_bad_lines="skip"
    )

    df.columns = [c.replace('"', '').strip() for c in df.columns]

    if "Player" not in df.columns or "Salary" not in df.columns:
        raise ValueError("Colonnes Fantrax introuvables")

    out = pd.DataFrame()
    out["Joueur"] = df["Player"].astype(str)
    out["Pos"] = df.get("Pos", "N/A")
    out["Equipe"] = df.get("Team", "N/A")

    out["Salaire"] = (
        df["Salary"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .replace("", "0")
        .astype(float) * 1000
    )

    out["Statut"] = df.get("Status", "").apply(
        lambda x: "Club École" if "min" in str(x).lower() else "Grand Club"
    )

    return out[out["Joueur"].str.len() > 2]

# =====================================================
# SIDEBAR – SAISON
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

# =====================================================
# SESSION
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
        try:
            df = parse_fantrax(uploaded)
            df["Propriétaire"] = uploaded.name.replace(".csv", "")

            st.session_state["data"] = pd.concat(
                [st.session_state["data"], df],
                ignore_index=True
            ).drop_duplicates(subset=["Propriétaire", "Joueur"])

            st.session_state["data"].to_csv(DATA_FILE, index=False)
            st.sidebar.success(f"✅ {len(df)} joueurs importés")

        except Exception as e:
            st.sidebar.error("❌ Import impossible")
            st.sidebar.code(str(e))
else:
    st.sidebar.warning("🔒 Saison verrouillée")

# =====================================================
# DASHBOARD
# =====================================================
st.title("🏒 Fantrax – Gestion Salariale")

df = st.session_state["data"]

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
    resume.append({
        "Propriétaire": p,
        "GC": gc,
        "CE": ce,
        "Restant GC": PLAFOND_GC - gc,
        "Restant CE": PLAFOND_CE - ce
    })

plafonds = pd.DataFrame(resume)

# =====================================================
# TABLE
# =====================================================
st.subheader("📊 Plafonds")
display = plafonds.copy()
for c in display.columns[1:]:
    display[c] = display[c].apply(money)
st.dataframe(display, use_container_width=True)

# =====================================================
# 📊 GRAPHIQUE TEMPS RÉEL (BUG FIXÉ)
# =====================================================
st.subheader("📈 Masse salariale Grand Club")

fig, ax = plt.subplots()
ax.bar(plafonds["Propriétaire"], plafonds["GC"])
ax.axhline(PLAFOND_GC, linestyle="--")
ax.set_ylabel("Salaire")
plt.xticks(rotation=45, ha="right")
st.pyplot(fig)

# =====================================================
# ⚖️ CONTRÔLE TRANSACTION
# =====================================================
st.subheader("⚖️ Vérification transaction")

p = st.selectbox("Propriétaire", plafonds["Propriétaire"])
salaire_test = st.number_input("Salaire du joueur", min_value=0, step=100000)
statut = st.radio("Statut", ["Grand Club", "Club École"])

ligne = plafonds[plafonds["Propriétaire"] == p].iloc[0]
reste = ligne["Restant GC"] if statut == "Grand Club" else ligne["Restant CE"]

if salaire_test > reste:
    st.error("🚨 Dépassement du plafond")
else:
    st.success("✅ Transaction valide")

# =====================================================
# 🧠 IA RECOMMANDATIONS
# =====================================================
st.subheader("🧠 Recommandations IA")

for _, r in plafonds.iterrows():
    if r["Restant GC"] < 2_000_000:
        st.warning(f"{r['Propriétaire']} : envisager rétrogradation")
    if r["Restant CE"] > 10_000_000:
        st.info(f"{r['Propriétaire']} : potentiel rappel du club école")

# =====================================================
# 📄 EXPORT PDF (OPTIONNEL – SAFE)
# =====================================================
st.subheader("📄 Export PDF")

if st.button("Générer PDF"):
    try:
        from reportlab.platypus import SimpleDocTemplate, Paragraph
        from reportlab.lib.styles import getSampleStyleSheet

        pdf_path = f"{DATA_DIR}/resume_{season}.pdf"
        doc = SimpleDocTemplate(pdf_path)
        styles = getSampleStyleSheet()
        story = [Paragraph("Résumé salarial Fantrax", styles["Title"])]

        for _, r in plafonds.iterrows():
            story.append(Paragraph(
                f"{r['Propriétaire']} – GC {money(r['GC'])} / CE {money(r['CE'])}",
                styles["Normal"]
            ))

        doc.build(story)
        st.success("PDF généré")
        with open(pdf_path, "rb") as f:
            st.download_button("📥 Télécharger PDF", f, file_name=f"fantrax_{season}.pdf")

    except Exception:
        st.warning("PDF indisponible (ReportLab non installé)")

from __future__ import annotations

import os
import io
import re
import json
import pandas as pd
import streamlit as st
from datetime import datetime
from zoneinfo import ZoneInfo

# =====================================================
# 1. CONFIGURATION & CONSTANTES
# =====================================================
st.set_page_config(page_title="PMS - Fantasy Hockey Pool", layout="wide")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

REQUIRED_COLS = ["Propriétaire", "Joueur", "Pos", "Equipe", "Salaire", "Level", "Statut", "Slot", "IR Date"]
SLOT_ACTIF = "Actif"
SLOT_BANC = "Banc"
SLOT_IR = "Blessé"
STATUT_GC = "Grand Club"
STATUT_CE = "Club École"

PLAFOND_GC_DEFAULT = 95_500_000
PLAFOND_CE_DEFAULT = 47_750_000

# =====================================================
# 2. STYLE CSS (IDENTIQUE À VOTRE CAPTURE)
# =====================================================
st.markdown("""
<style>
    div.stButton > button {
        border-radius: 10px;
        background-color: #1e2129;
        border: 1px solid #3e4451;
        color: white;
        width: 100%;
        text-align: center;
        padding: 5px;
    }
    .pos-badge {
        display: inline-block;
        width: 24px; height: 24px;
        border-radius: 50%;
        text-align: center;
        line-height: 24px;
        font-weight: bold;
        font-size: 11px;
        color: white;
    }
    .pos-f { background-color: #16a34a; }
    .pos-d { background-color: #2563eb; }
    .pos-g { background-color: #7c3aed; }
    .pms-header {
        border-radius: 18px; padding: 15px;
        background: linear-gradient(90deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02));
        border: 1px solid rgba(255,255,255,0.1);
        text-align: center; margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

# =====================================================
# 3. LOGIQUE DES DONNÉES & HISTORIQUE
# =====================================================

def save_all_data():
    season = st.session_state.get("season", "2024-2025")
    st.session_state["data"].to_csv(os.path.join(DATA_DIR, f"fantrax_{season}.csv"), index=False)
    st.session_state["history"].to_csv(os.path.join(DATA_DIR, f"history_{season}.csv"), index=False)

def log_change(owner, player, action):
    """Enregistre un changement dans l'historique."""
    new_entry = {
        "Date": datetime.now(ZoneInfo("America/Toronto")).strftime("%Y-%m-%d %H:%M"),
        "Équipe": owner,
        "Joueur": player,
        "Action": action
    }
    st.session_state["history"] = pd.concat([st.session_state["history"], pd.DataFrame([new_entry])], ignore_index=True)

def money(v) -> str:
    return f"{int(v or 0):,}".replace(",", " ") + " $"

def normalize_pos(pos: str) -> str:
    p = str(pos or "").upper()
    if "G" in p: return "G"
    if "D" in p: return "D"
    return "F"

def get_pos_html(pos):
    p = normalize_pos(pos)
    cls = "pos-f" if p == "F" else "pos-d" if p == "D" else "pos-g"
    return f'<div class="pos-badge {cls}">{p}</div>'

# =====================================================
# 4. POPUP : DÉPLACER UN JOUEUR
# =====================================================

@st.dialog("Mouvement de personnel")
def move_player_dialog(player_name, owner):
    df = st.session_state["data"]
    idx = df[(df["Joueur"] == player_name) & (df["Propriétaire"] == owner)].index[0]
    
    st.write(f"Déplacer **{player_name}**")
    
    options = {
        "🟢 Actif (Grand Club)": (STATUT_GC, SLOT_ACTIF),
        "🟡 Banc (Grand Club)": (STATUT_GC, SLOT_BANC),
        "🔵 Mineur (Club École)": (STATUT_CE, ""),
        "🩹 Blessé (IR)": (df.at[idx, "Statut"], SLOT_IR)
    }
    
    dest = st.radio("Destination", list(options.keys()))
    
    if st.button("Confirmer le mouvement"):
        new_statut, new_slot = options[dest]
        st.session_state["data"].at[idx, "Statut"] = new_statut
        st.session_state["data"].at[idx, "Slot"] = new_slot
        
        log_change(owner, player_name, f"Déplacé vers {dest}")
        save_all_data()
        st.rerun()

# =====================================================
# 5. ONGLET : HOME (Leaderboard & Historique)
# =====================================================

def render_tab_home():
    st.markdown("<div class='pms-header'><h1>🏆 Accueil PMS Pool</h1></div>", unsafe_allow_html=True)
    
    c1, c2 = st.columns([1, 1])
    
    with c1:
        st.subheader("📊 Classement (Masse Salariale)")
        df = st.session_state["data"]
        if not df.empty:
            # Calcul rapide de la valeur de l'équipe (simple exemple ici)
            classement = df.groupby("Propriétaire")["Salaire"].sum().reset_index()
            classement = classement.sort_values("Salaire", ascending=False)
            st.dataframe(classement, use_container_width=True, hide_index=True)
        else:
            st.info("Aucune donnée disponible.")

    with c2:
        st.subheader("🕘 Derniers changements")
        hist = st.session_state["history"]
        if not hist.empty:
            st.dataframe(hist.sort_index(ascending=False).head(15), use_container_width=True, hide_index=True)
        else:
            st.caption("Aucun historique pour le moment.")

# =====================================================
# 6. ONGLET : ALIGNEMENT
# =====================================================

def render_roster_table(df_roster, owner):
    if df_roster.empty:
        st.caption("Vide")
        return
    h1, h2, h3, h4, h5 = st.columns([0.5, 1, 3, 1, 1.5])
    h1.write("**Pos**"); h2.write("**Équipe**"); h3.write("**Joueur**"); h4.write("**Lvl**"); h5.write("**Salaire**")
    
    for _, row in df_roster.iterrows():
        c1, c2, c3, c4, c5 = st.columns([0.5, 1, 3, 1, 1.5])
        c1.markdown(get_pos_html(row['Pos']), unsafe_allow_html=True)
        c2.write(row['Equipe'])
        if c3.button(row['Joueur'], key=f"align_{row['Joueur']}_{_}"):
            move_player_dialog(row['Joueur'], owner)
        c4.write(row['Level'])
        c5.write(money(row['Salaire']))

def render_tab_alignment():
    owner = st.session_state["selected_team"]
    df = st.session_state["data"]
    dprop = df[df["Propriétaire"] == owner].copy()
    
    if dprop.empty:
        st.warning(f"L'équipe {owner} n'a pas de joueurs.")
        return

    # Calculs
    used_gc = dprop[dprop["Statut"] == STATUT_GC]["Salaire"].sum()
    used_ce = dprop[dprop["Statut"] == STATUT_CE]["Salaire"].sum()
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"📊 **Plafond GC** : {money(PLAFOND_GC_DEFAULT - used_gc)} libre")
        st.progress(min(used_gc/PLAFOND_GC_DEFAULT, 1.0))
    with col2:
        st.markdown(f"📊 **Plafond CE** : {money(PLAFOND_CE_DEFAULT - used_ce)} libre")
        st.progress(min(used_ce/PLAFOND_CE_DEFAULT, 1.0))

    st.write(f"**GC:** {money(used_gc)} | **CE:** {money(used_ce)} | **Banc:** {len(dprop[dprop['Slot']==SLOT_BANC])}")
    st.divider()

    l, r = st.columns(2)
    with l:
        st.markdown("### 🟢 Actifs (Grand Club)")
        render_roster_table(dprop[(dprop["Statut"] == STATUT_GC) & (dprop["Slot"] == SLOT_ACTIF)], owner)
        with st.expander("🟡 Banc"):
            render_roster_table(dprop[dprop["Slot"] == SLOT_BANC], owner)
    with r:
        st.markdown("### 🔵 Mineur (Club École)")
        render_roster_table(dprop[dprop["Statut"] == STATUT_CE], owner)
        with st.expander("🩹 Blessés (IR)"):
            render_roster_table(dprop[dprop["Slot"] == SLOT_IR], owner)

# =====================================================
# 7. ONGLET : GM (Choix de repêchage)
# =====================================================

def render_tab_gm():
    st.title(f"🧊 Bureau du GM - {st.session_state['selected_team']}")
    
    st.subheader("🎯 Choix de repêchage")
    st.caption("Le 8e choix de chaque année est verrouillé (non-échangeable).")
    
    years = [2026, 2027, 2028]
    
    # Simuler le stockage des picks s'il n'existe pas
    if "picks" not in st.session_state:
        st.session_state["picks"] = {}

    for year in years:
        with st.expander(f"📅 Année {year}", expanded=True):
            cols = st.columns(8)
            for round_num in range(1, 9):
                is_locked = (round_num == 8)
                label = "🔒 R8" if is_locked else f"R{round_num}"
                
                with cols[round_num-1]:
                    st.markdown(f"**{label}**")
                    if is_locked:
                        st.info(st.session_state["selected_team"])
                    else:
                        # Ici on pourrait ajouter un selectbox pour changer le propriétaire
                        st.write(st.session_state["selected_team"])

# =====================================================
# 8. ONGLET : JOUEURS AUTONOMES (Free Agents)
# =====================================================

def render_tab_autonomes():
    st.title("👤 Joueurs autonomes")
    if not os.path.exists("hockey.players.csv"):
        st.error("Base de données hockey.players.csv manquante.")
        return

    db = pd.read_csv("hockey.players.csv")
    query = st.text_input("Rechercher un joueur (Nom)")
    
    if query:
        results = db[db["Player"].str.contains(query, case=False, na=False)]
        # Exclure les joueurs déjà pris
        taken = st.session_state["data"]["Joueur"].tolist()
        results = results[~results["Player"].isin(taken)]
        
        if not results.empty:
            for _, r in results.head(10).iterrows():
                c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
                c1.write(f"**{r['Player']}** ({r['Team']})")
                c2.write(r['Level'])
                c3.write(r['Cap Hit'])
                if c4.button("Signer", key=f"sign_{r['Player']}"):
                    new_p = {
                        "Propriétaire": st.session_state["selected_team"],
                        "Joueur": r['Player'], "Pos": r['Position'], "Equipe": r['Team'],
                        "Salaire": int(str(r['Cap Hit']).replace(" ","").replace("$","")),
                        "Level": r['Level'], "Statut": STATUT_GC, "Slot": SLOT_BANC, "IR Date": ""
                    }
                    st.session_state["data"] = pd.concat([st.session_state["data"], pd.DataFrame([new_p])], ignore_index=True)
                    log_change(st.session_state["selected_team"], r['Player'], "Signature (Agent Libre)")
                    save_all_data()
                    st.rerun()

# =====================================================
# 9. ADMIN & IMPORT
# =====================================================

def parse_fantrax_robust(uploaded_file, team_owner):
    # Logique simplifiée mais robuste pour cet export
    raw_text = uploaded_file.read().decode("utf-8", errors="ignore")
    lines = raw_text.splitlines()
    data = []
    headers = None
    for line in lines:
        parts = [p.strip().replace('"', '') for p in line.split(',')]
        if "Player" in parts: headers = [p.lower() for p in parts]; continue
        if headers and len(parts) == len(headers):
            row = dict(zip(headers, parts))
            if row.get("player"): data.append(row)
    
    df_raw = pd.DataFrame(data)
    df_final = pd.DataFrame()
    df_final["Joueur"] = df_raw["player"]
    df_final["Equipe"] = df_raw["team"]
    df_final["Pos"] = df_raw["pos"].apply(normalize_pos)
    df_final["Salaire"] = df_raw["salary"].apply(lambda x: int(str(x).replace(",","").replace("$","").replace(" ","")))
    df_final["Propriétaire"] = team_owner
    df_final["Statut"] = df_raw["status"].apply(lambda x: STATUT_CE if "min" in str(x).lower() else STATUT_GC)
    df_final["Slot"] = df_raw["status"].apply(lambda x: SLOT_ACTIF if "act" in str(x).lower() else SLOT_BANC)
    df_final["Level"] = df_raw.get("contract", "STD")
    df_final["IR Date"] = ""
    return df_final

def render_tab_admin():
    st.title("🛠️ Gestion Admin")
    target = st.selectbox("Équipe destinataire", ["Whalers", "Nordiques", "Cracheurs", "Prédateurs", "Red Wings", "Canadiens"])
    file = st.file_uploader("CSV Fantrax", type=["csv"])
    if file and st.button("Lancer l'importation"):
        df_new = parse_fantrax_robust(file, target)
        df_cur = st.session_state["data"]
        df_cur = df_cur[df_cur["Propriétaire"] != target]
        st.session_state["data"] = pd.concat([df_cur, df_new], ignore_index=True)
        save_all_data()
        st.success("Importation terminée.")

# =====================================================
# 10. MAIN ROUTING
# =====================================================

def main():
    # Initialisation
    if "season" not in st.session_state: st.session_state["season"] = "2024-2025"
    s = st.session_state["season"]
    
    if "data" not in st.session_state:
        p = os.path.join(DATA_DIR, f"fantrax_{s}.csv")
        st.session_state["data"] = pd.read_csv(p) if os.path.exists(p) else pd.DataFrame(columns=REQUIRED_COLS)
    
    if "history" not in st.session_state:
        p = os.path.join(DATA_DIR, f"history_{s}.csv")
        st.session_state["history"] = pd.read_csv(p) if os.path.exists(p) else pd.DataFrame(columns=["Date", "Équipe", "Joueur", "Action"])

    # Sidebar
    st.sidebar.title("🏒 PMS Pool")
    st.session_state["selected_team"] = st.sidebar.selectbox("Équipe", ["Whalers", "Nordiques", "Cracheurs", "Prédateurs", "Red Wings", "Canadiens"])
    
    menu = ["🏠 Home", "🧾 Alignement", "🧊 GM", "👤 Joueurs autonomes"]
    if st.session_state["selected_team"] == "Whalers": menu.append("🛠️ Gestion Admin")
    
    choice = st.sidebar.radio("Navigation", menu)
    
    if choice == "🏠 Home": render_tab_home()
    elif choice == "🧾 Alignement": render_tab_alignment()
    elif choice == "🧊 GM": render_tab_gm()
    elif choice == "👤 Joueurs autonomes": render_tab_autonomes()
    elif choice == "🛠️ Gestion Admin": render_tab_admin()

if __name__ == "__main__":
    main()
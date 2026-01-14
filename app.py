from __future__ import annotations

import os
import io
import re
import requests
import pandas as pd
import streamlit as st
from datetime import datetime
from zoneinfo import ZoneInfo

# =====================================================
# 1. CONFIGURATION & CONSTANTES
# =====================================================
st.set_page_config(page_title="PMS - Pool Hockey", layout="wide")

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

# Barème de points NHL
SCORING_RULES = {
    "F": {"goals": 3, "assists": 2},
    "D": {"goals": 5, "assists": 3},
    "G": {"wins": 5, "shutouts": 5, "saves": 0.05}
}

# =====================================================
# 2. STYLE CSS (Style Pro & Boutons Arrondis)
# =====================================================
st.markdown("""
<style>
    /* Boutons de joueurs arrondis style capture */
    div.stButton > button {
        border-radius: 10px;
        background-color: #1e2129;
        border: 1px solid #3e4451;
        color: white;
        width: 100%;
        text-align: center;
        padding: 5px;
        transition: 0.2s;
    }
    div.stButton > button:hover {
        background-color: #2c313c;
        border-color: #528bff;
    }
    /* Badges de position circulaires */
    .pos-badge {
        display: inline-block;
        width: 28px; height: 28px;
        border-radius: 50%;
        text-align: center;
        line-height: 28px;
        font-weight: bold;
        font-size: 12px;
        color: white;
    }
    .pos-f { background-color: #16a34a; }
    .pos-d { background-color: #2563eb; }
    .pos-g { background-color: #7c3aed; }
</style>
""", unsafe_allow_html=True)

# =====================================================
# 3. FONCTIONS UTILITAIRES (Argent, Position, Save)
# =====================================================

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

def save_to_csv(df):
    season = st.session_state.get("season", "2024-2025")
    path = os.path.join(DATA_DIR, f"fantrax_{season}.csv")
    df.to_csv(path, index=False)
    st.session_state["data"] = df

# =====================================================
# 4. MOTEUR D'IMPORTATION ROBUSTE (Anti-Erreur 21 fields)
# =====================================================

def parse_fantrax_robust(uploaded_file, team_owner):
    raw_text = uploaded_file.read().decode("utf-8", errors="ignore")
    lines = raw_text.splitlines()
    data_rows = []
    current_headers = None
    
    for line in lines:
        parts = [p.strip().replace('"', '') for p in line.split(',')]
        if not parts or parts[0] == "": continue
        
        # Détection d'un nouvel en-tête (Skaters ou Goalies)
        if any(x in parts[0].lower() for x in ["player", "joueur"]):
            current_headers = [p.lower() for p in parts]
            continue
        
        # On n'ajoute la ligne que si elle correspond au dernier en-tête trouvé
        if current_headers and len(parts) == len(current_headers):
            row = dict(zip(current_headers, parts))
            if row.get("player") or row.get("joueur"):
                data_rows.append(row)

    df_raw = pd.DataFrame(data_rows)
    if df_raw.empty: return pd.DataFrame()

    # Mapping intelligent des colonnes
    def find_k(keys):
        for c in df_raw.columns:
            if any(x in c for x in keys): return c
        return None

    k_p = find_k(['player', 'joueur'])
    k_t = find_k(['team', 'equipe'])
    k_pos = find_k(['pos', 'position'])
    k_s = find_k(['salary', 'salaire', 'cap hit', 'aav'])
    k_stat = find_k(['status', 'statut'])

    df_final = pd.DataFrame()
    df_final["Joueur"] = df_raw[k_p]
    df_final["Equipe"] = df_raw[k_t] if k_t else "N/A"
    df_final["Pos"] = df_raw[k_pos].apply(normalize_pos) if k_pos else "F"
    
    # Nettoyage salaire
    def clean_s(v):
        s = str(v).replace("$","").replace(",","").replace("\xa0","").strip()
        s = re.sub(r'\s+', '', s)
        try: return int(float(s))
        except: return 0
    
    df_final["Salaire"] = df_raw[k_s].apply(clean_s) if k_s else 0
    df_final["Propriétaire"] = team_owner
    df_final["Statut"] = df_raw[k_stat].apply(lambda x: STATUT_CE if "min" in str(x).lower() else STATUT_GC)
    df_final["Slot"] = df_raw[k_stat].apply(lambda x: "Actif" if "act" in str(x).lower() else "Banc")
    df_final["Level"] = df_raw.get("level", "0")
    df_final["IR Date"] = ""
    
    return df_final[REQUIRED_COLS]

# =====================================================
# 5. POPUP DE MOUVEMENT
# =====================================================

@st.dialog("Déplacer le joueur")
def move_player_dialog(player_name, owner):
    df = st.session_state["data"]
    idx = df[(df["Joueur"] == player_name) & (df["Propriétaire"] == owner)].index[0]
    
    st.write(f"Déplacer **{player_name}** vers :")
    
    options = {
        "🟢 Actif (Grand Club)": (STATUT_GC, SLOT_ACTIF),
        "🟡 Banc (Grand Club)": (STATUT_GC, SLOT_BANC),
        "🔵 Mineur (Club École)": (STATUT_CE, ""),
        "🩹 Liste des blessés (IR)": (df.at[idx, "Statut"], SLOT_IR)
    }
    
    dest = st.radio("Destination", list(options.keys()))
    
    if st.button("Confirmer le mouvement", type="primary"):
        new_statut, new_slot = options[dest]
        st.session_state["data"].at[idx, "Statut"] = new_statut
        st.session_state["data"].at[idx, "Slot"] = new_slot
        save_to_csv(st.session_state["data"])
        st.success("Mise à jour effectuée !")
        st.rerun()

# =====================================================
# 6. RENDU DES ONGLETS
# =====================================================

def render_roster_table(df_roster, owner):
    if df_roster.empty:
        st.caption("Aucun joueur.")
        return
    h1, h2, h3, h4, h5 = st.columns([0.5, 1, 3, 1, 1.5])
    h1.write("Pos"); h2.write("Équipe"); h3.write("Joueur"); h4.write("Lvl"); h5.write("Salaire")
    
    for _, row in df_roster.iterrows():
        c1, c2, c3, c4, c5 = st.columns([0.5, 1, 3, 1, 1.5])
        c1.markdown(get_pos_html(row['Pos']), unsafe_allow_html=True)
        c2.write(row['Equipe'])
        if c3.button(row['Joueur'], key=f"btn_{row['Joueur']}_{owner}_{_}"):
            move_player_dialog(row['Joueur'], owner)
        c4.write(str(row['Level']))
        c5.write(money(row['Salaire']))

def render_tab_alignment():
    owner = st.session_state.get("selected_team", "Whalers")
    df = st.session_state["data"]
    dprop = df[df["Propriétaire"] == owner].copy()
    
    if dprop.empty:
        st.info("Alignement vide. Importez vos joueurs dans l'onglet Admin.")
        return

    # Calculs masses
    gc_p = dprop[dprop["Statut"] == STATUT_GC]
    ce_p = dprop[dprop["Statut"] == STATUT_CE]
    used_gc, used_ce = gc_p["Salaire"].sum(), ce_p["Salaire"].sum()
    
    # Progress bars
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.markdown(f"**Plafond GC — {owner}** <span style='float:right; color:#22c55e;'>{money(PLAFOND_GC_DEFAULT - used_gc)}</span>", unsafe_allow_html=True)
        st.progress(min(used_gc / PLAFOND_GC_DEFAULT, 1.0))
    with col_p2:
        st.markdown(f"**Plafond CE — {owner}** <span style='float:right; color:#22c55e;'>{money(PLAFOND_CE_DEFAULT - used_ce)}</span>", unsafe_allow_html=True)
        st.progress(min(used_ce / PLAFOND_CE_DEFAULT, 1.0))

    # Métriques
    st.write(f"**GC:** {money(used_gc)} | **CE:** {money(used_ce)} | **IR:** {len(dprop[dprop['Slot']==SLOT_IR])} | **Banc:** {len(gc_p[gc_p['Slot']==SLOT_BANC])}")
    st.divider()

    left, right = st.columns(2)
    with left:
        st.markdown("### 🟢 Actifs (Grand Club)")
        render_roster_table(gc_p[gc_p["Slot"] == SLOT_ACTIF], owner)
        st.write("")
        with st.expander(f"🟡 Banc ({len(gc_p[gc_p['Slot']==SLOT_BANC])})"):
            render_roster_table(gc_p[gc_p["Slot"] == SLOT_BANC], owner)

    with right:
        st.markdown("### 🔵 Mineur (Club École)")
        render_roster_table(ce_p[ce_p["Slot"] != SLOT_IR], owner)
        st.write("")
        with st.expander(f"🩹 Blessés / IR ({len(dprop[dprop['Slot']==SLOT_IR])})"):
            render_roster_table(dprop[dprop["Slot"] == SLOT_IR], owner)

def render_tab_admin():
    st.title("🛠️ Gestion Admin - Importation")
    st.write("Importez un fichier exporté de Fantrax pour remplir l'alignement d'une équipe.")
    
    teams = ["Whalers", "Nordiques", "Cracheurs", "Prédateurs", "Red Wings", "Canadiens"]
    col_a, col_b = st.columns([1, 2])
    target = col_a.selectbox("Équipe cible", teams)
    file = col_b.file_uploader("Fichier CSV Fantrax", type=["csv"])
    
    if file:
        df_new = parse_fantrax_robust(file, target)
        if not df_new.empty:
            st.success(f"{len(df_new)} joueurs détectés.")
            st.dataframe(df_new.head(10), use_container_width=True)
            if st.button(f"Écraser l'alignement actuel de {target}"):
                df_global = st.session_state["data"]
                df_global = df_global[df_global["Propriétaire"] != target]
                df_final = pd.concat([df_global, df_new], ignore_index=True)
                save_to_csv(df_final)
                st.rerun()

# =====================================================
# 7. MAIN ROUTING
# =====================================================

def main():
    if "season" not in st.session_state: st.session_state["season"] = "2024-2025"
    path = os.path.join(DATA_DIR, f"fantrax_{st.session_state['season']}.csv")
    if "data" not in st.session_state:
        st.session_state["data"] = pd.read_csv(path) if os.path.exists(path) else pd.DataFrame(columns=REQUIRED_COLS)

    # SIDEBAR
    st.sidebar.title("🏒 PMS Pool")
    st.session_state["season"] = st.sidebar.selectbox("Saison", ["2024-2025", "2025-2026"])
    selected_team = st.sidebar.selectbox("Mon Équipe", ["Whalers", "Nordiques", "Cracheurs", "Prédateurs", "Red Wings", "Canadiens"], key="selected_team")
    
    # Logo
    logo = os.path.join(DATA_DIR, f"{selected_team}_Logo.png")
    if os.path.exists(logo): st.sidebar.image(logo)

    nav = ["🏆 Classement", "🧾 Alignement"]
    if selected_team == "Whalers": nav.append("🛠️ Gestion Admin")
    choice = st.sidebar.radio("Navigation", nav)
    
    if choice == "🧾 Alignement": render_tab_alignment()
    elif choice == "🛠️ Gestion Admin": render_tab_admin()
    else: st.title(choice); st.write("Contenu à venir...")

if __name__ == "__main__":
    main()
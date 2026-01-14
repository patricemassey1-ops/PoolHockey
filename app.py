from __future__ import annotations

import os
import io
import re
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

# =====================================================
# 2. STYLE CSS
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
# 3. FONCTIONS DE GESTION DES DONNÉES
# =====================================================

def save_to_csv():
    """Sauvegarde l'état actuel du dataframe dans le fichier CSV de la saison."""
    season = st.session_state.get("season", "2024-2025")
    path = os.path.join(DATA_DIR, f"fantrax_{season}.csv")
    st.session_state["data"].to_csv(path, index=False)

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
# 4. POPUP DE MOUVEMENT (MODAL)
# =====================================================

@st.dialog("Gérer le joueur")
def move_player_dialog(player_name, owner):
    df = st.session_state["data"]
    # Trouver le joueur
    idx = df[(df["Joueur"] == player_name) & (df["Propriétaire"] == owner)].index[0]
    player_data = df.loc[idx]

    st.write(f"Où voulez-vous envoyer **{player_name}** ?")
    st.caption(f"Position actuelle : {player_data['Statut']} / {player_data['Slot'] if player_data['Slot'] else 'Aligné'}")

    options = {
        "🟢 Actif (Grand Club)": (STATUT_GC, SLOT_ACTIF),
        "🟡 Banc (Grand Club)": (STATUT_GC, SLOT_BANC),
        "🔵 Mineur (Club École)": (STATUT_CE, ""),
        "🩹 Liste des blessés (IR)": (player_data['Statut'], SLOT_IR)
    }

    choice = st.radio("Destination", list(options.keys()))

    if st.button("Confirmer le déplacement", type="primary"):
        new_statut, new_slot = options[choice]
        
        # Mise à jour
        st.session_state["data"].at[idx, "Statut"] = new_statut
        st.session_state["data"].at[idx, "Slot"] = new_slot
        
        save_to_csv()
        st.success(f"{player_name} déplacé vers {choice}")
        st.rerun()

# =====================================================
# 5. RENDU DE L'INTERFACE
# =====================================================

def render_roster_table(df_roster, owner):
    if df_roster.empty:
        st.caption("Aucun joueur ici.")
        return

    h1, h2, h3, h4, h5 = st.columns([0.5, 1, 3, 1, 1.5])
    h1.markdown("**Pos**")
    h2.markdown("**Équipe**")
    h3.markdown("**Joueur**")
    h4.markdown("**Level**")
    h5.markdown("**Salaire**")
    
    for _, row in df_roster.iterrows():
        c1, c2, c3, c4, c5 = st.columns([0.5, 1, 3, 1, 1.5])
        c1.markdown(get_pos_html(row['Pos']), unsafe_allow_html=True)
        c2.write(row['Equipe'])
        
        # Le clic sur le bouton ouvre le popup
        if c3.button(row['Joueur'], key=f"btn_{row['Joueur']}_{owner}_{_}"):
            move_player_dialog(row['Joueur'], owner)
            
        c4.write(str(row['Level']))
        c5.write(money(row['Salaire']))

def render_tab_alignment():
    owner = st.session_state.get("selected_team", "Whalers")
    df_all = st.session_state["data"]
    dprop = df_all[df_all["Propriétaire"] == owner].copy()
    
    if dprop.empty:
        st.info("Aucun joueur trouvé pour cette équipe.")
        return

    # Séparations pour le rendu
    actifs = dprop[(dprop["Statut"] == STATUT_GC) & (dprop["Slot"] == SLOT_ACTIF)]
    banc = dprop[(dprop["Statut"] == STATUT_GC) & (dprop["Slot"] == SLOT_BANC)]
    mineur = dprop[dprop["Statut"] == STATUT_CE]
    ir = dprop[dprop["Slot"] == SLOT_IR]

    # --- CALCULS MASSES ---
    used_gc = dprop[dprop["Statut"] == STATUT_GC]["Salaire"].sum()
    used_ce = dprop[dprop["Statut"] == STATUT_CE]["Salaire"].sum()
    
    # --- HEADER PROGRESS BARS ---
    col_prog1, col_prog2 = st.columns(2)
    with col_prog1:
        st.markdown(f"📊 **Plafond GC — {owner}** <span style='float:right; color:#22c55e;'>{money(PLAFOND_GC_DEFAULT - used_gc)}</span>", unsafe_allow_html=True)
        st.progress(min(used_gc / PLAFOND_GC_DEFAULT, 1.0))
        
    with col_prog2:
        st.markdown(f"📊 **Plafond CE — {owner}** <span style='float:right; color:#22c55e;'>{money(PLAFOND_CE_DEFAULT - used_ce)}</span>", unsafe_allow_html=True)
        st.progress(min(used_ce / PLAFOND_CE_DEFAULT, 1.0))

    # --- COMPTEURS ---
    st.write(f"**GC:** {money(used_gc)} | **CE:** {money(used_ce)} | **IR:** {len(ir)} | **Banc:** {len(banc)}")
    
    st.divider()

    # --- AFFICHAGE ---
    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown("### 🟢 Actifs (Grand Club)")
        render_roster_table(actifs, owner)
        
        st.write("")
        with st.expander(f"🟡 Banc ({len(banc)})", expanded=False):
            render_roster_table(banc, owner)

    with col_right:
        st.markdown("### 🔵 Mineur (Club École)")
        render_roster_table(mineur, owner)
        
        st.write("")
        with st.expander(f"🩹 Blessés / IR ({len(ir)})", expanded=False):
            render_roster_table(ir, owner)

# =====================================================
# 6. MAIN & ROUTING
# =====================================================

def main():
    if "season" not in st.session_state: st.session_state["season"] = "2024-2025"
    
    # Chargement initial des données en Session State
    path = os.path.join(DATA_DIR, f"fantrax_{st.session_state['season']}.csv")
    if "data" not in st.session_state:
        if os.path.exists(path):
            st.session_state["data"] = pd.read_csv(path)
        else:
            st.session_state["data"] = pd.DataFrame(columns=REQUIRED_COLS)

    # Sidebar
    st.sidebar.title("🏒 PMS Pool")
    st.session_state["season"] = st.sidebar.selectbox("Saison", ["2024-2025", "2025-2026"])
    selected_team = st.sidebar.selectbox("Mon Équipe", ["Whalers", "Nordiques", "Cracheurs", "Prédateurs", "Red Wings", "Canadiens"], key="selected_team")
    
    choice = st.sidebar.radio("Navigation", ["🏆 Classement", "🧾 Alignement", "🛠️ Gestion Admin"])
    
    if choice == "🧾 Alignement":
        render_tab_alignment()
    elif choice == "🛠️ Gestion Admin":
        # (Insérer ici la fonction render_tab_admin de l'étape précédente)
        st.write("Section Admin pour l'importation.")
    else:
        st.title("🏆 Classement")
        st.write("Calcul des scores en cours...")

if __name__ == "__main__":
    main()
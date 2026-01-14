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

# Plafonds par défaut
PLAFOND_GC_DEFAULT = 95_500_000
PLAFOND_CE_DEFAULT = 47_750_000

# =====================================================
# 2. STYLE CSS (POUR CORRESPONDRE À LA CAPTURE)
# =====================================================
st.markdown("""
<style>
    /* Boutons de joueurs arrondis */
    div.stButton > button {
        border-radius: 10px;
        background-color: #1e2129;
        border: 1px solid #3e4451;
        color: white;
        width: 100%;
        text-align: center;
        padding: 5px;
    }
    /* Badges de position */
    .pos-badge {
        display: inline-block;
        width: 28px;
        height: 28px;
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
    
    /* Conteneurs de blocs */
    .roster-block {
        border: 1px solid #3e4451;
        border-radius: 15px;
        padding: 20px;
        background-color: #0e1117;
    }
</style>
""", unsafe_allow_html=True)

# =====================================================
# 3. FONCTIONS UTILITAIRES
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

# =====================================================
# 4. PARSING ROBUSTE (FANTRAX MULTI-SECTIONS)
# =====================================================

def clean_val(v):
    if pd.isna(v): return 0
    s = str(v).replace("$", "").replace(",", "").replace("\xa0", "").strip()
    s = re.sub(r'\s+', '', s)
    try: return int(float(s))
    except: return 0

def parse_fantrax_robust(uploaded_file, team_owner):
    raw_text = uploaded_file.read().decode("utf-8", errors="ignore")
    lines = raw_text.splitlines()
    
    all_data = []
    headers = None
    
    for line in lines:
        parts = [p.strip().replace('"', '') for p in line.split(',')]
        if not parts or parts[0] == "": continue
        
        # Détecter en-tête
        if "player" in parts[0].lower() or "player" in "".join(parts).lower():
            headers = [p.lower() for p in parts]
            continue
        
        if headers and len(parts) >= len(headers):
            row = dict(zip(headers, parts))
            all_data.append(row)

    df_raw = pd.DataFrame(all_data)
    
    # Mapping intelligent
    def find_key(keys):
        for k in df_raw.columns:
            if any(x in k for x in keys): return k
        return None

    k_p = find_key(['player', 'joueur'])
    k_t = find_key(['team', 'equipe'])
    k_pos = find_key(['pos', 'position'])
    k_s = find_key(['salary', 'salaire', 'cap hit', 'aav'])
    k_stat = find_key(['status', 'statut'])

    df_final = pd.DataFrame()
    df_final["Joueur"] = df_raw[k_p]
    df_final["Equipe"] = df_raw[k_t] if k_t else "N/A"
    df_final["Pos"] = df_raw[k_pos].apply(normalize_pos) if k_pos else "F"
    df_final["Salaire"] = df_raw[k_s].apply(clean_val) if k_s else 0
    df_final["Propriétaire"] = team_owner
    df_final["Statut"] = df_raw[k_stat].apply(lambda x: STATUT_CE if "min" in str(x).lower() else STATUT_GC)
    df_final["Slot"] = df_raw[k_stat].apply(lambda x: "Actif" if "act" in str(x).lower() else "Banc")
    df_final["Level"] = df_raw.get("level", "0")
    df_final["IR Date"] = ""
    
    return df_final[REQUIRED_COLS].dropna(subset=["Joueur"])

# =====================================================
# 5. RENDU DE L'ALIGNEMENT (STYLE CAPTURE D'ÉCRAN)
# =====================================================

def render_roster_table(df_roster):
    # En-tête de colonnes
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
        c3.button(row['Joueur'], key=f"btn_{row['Joueur']}_{_}")
        c4.write(str(row['Level']))
        c5.write(money(row['Salaire']))

def render_tab_alignment():
    owner = st.session_state.get("selected_team", "Whalers")
    df_all = st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS))
    dprop = df_all[df_all["Propriétaire"] == owner].copy()
    
    if dprop.empty:
        st.info("Aucun joueur. Importez un fichier dans l'onglet Admin.")
        return

    # --- CALCULS ---
    gc_players = dprop[dprop["Statut"] == STATUT_GC]
    ce_players = dprop[dprop["Statut"] == STATUT_CE]
    
    used_gc = gc_players["Salaire"].sum()
    used_ce = ce_players["Salaire"].sum()
    
    # Comptage des actifs
    active = gc_players[gc_players["Slot"] == "Actif"]
    nb_f = len(active[active["Pos"] == "F"])
    nb_d = len(active[active["Pos"] == "D"])
    nb_g = len(active[active["Pos"] == "G"])
    
    # --- HEADER PROGRESS BARS ---
    col_prog1, col_prog2 = st.columns(2)
    with col_prog1:
        st.markdown(f"📊 **Plafond GC — {owner}** <span style='float:right; color:#22c55e;'>{money(PLAFOND_GC_DEFAULT - used_gc)}</span>", unsafe_allow_html=True)
        st.progress(min(used_gc / PLAFOND_GC_DEFAULT, 1.0))
        st.caption(f"Utilisé : {money(used_gc)} / {money(PLAFOND_GC_DEFAULT)}")
        
    with col_prog2:
        st.markdown(f"📊 **Plafond CE — {owner}** <span style='float:right; color:#22c55e;'>{money(PLAFOND_CE_DEFAULT - used_ce)}</span>", unsafe_allow_html=True)
        st.progress(min(used_ce / PLAFOND_CE_DEFAULT, 1.0))
        st.caption(f"Utilisé : {money(used_ce)} / {money(PLAFOND_CE_DEFAULT)}")

    # --- METRIQUES TEXTE ---
    st.write("")
    m1, m2, m3 = st.columns(3)
    m1.write(f"**GC** {money(used_gc)} / {money(PLAFOND_GC_DEFAULT)}")
    m2.write(f"**CE** {money(used_ce)} / {money(PLAFOND_CE_DEFAULT)}")
    m3.write(f"**IR** {len(dprop[dprop['Slot'] == SLOT_IR])} joueur(s)")
    
    m4, m5, m6 = st.columns(3)
    m4.write(f"**Reste GC** {money(PLAFOND_GC_DEFAULT - used_gc)}")
    m5.write(f"**Reste CE** {money(PLAFOND_CE_DEFAULT - used_ce)}")
    m6.write(f"**Banc** {len(gc_players[gc_players['Slot'] == SLOT_BANC])} joueur(s)")

    # --- COMPTEURS ACTIFS ---
    f_warn = "⚠️" if nb_f > 12 else ""
    d_warn = "⚠️" if nb_d > 6 else ""
    st.write(f"**Actifs** — F <span style='color:red;'>{nb_f}</span>/12 {f_warn} • D <span style='color:red;'>{nb_d}</span>/6 {d_warn} • G {nb_g}/2", unsafe_allow_html=True)

    st.divider()

    # --- GRILLE 2 COLONNES ---
    col_left, col_right = st.columns(2)
    
    with col_left:
        st.markdown("### 🟢 Actifs (Grand Club)")
        render_roster_table(gc_players[gc_players["Slot"] == "Actif"])

    with col_right:
        st.markdown("### 🔵 Mineur (Club École)")
        render_roster_table(ce_players)

# =====================================================
# 6. GESTION ADMIN
# =====================================================

def render_tab_admin():
    st.title("🛠️ Gestion Admin")
    teams = ["Whalers", "Nordiques", "Cracheurs", "Prédateurs", "Red Wings", "Canadiens"]
    
    target_team = st.selectbox("Équipe cible", teams)
    file = st.file_uploader("Importer CSV Fantrax", type=["csv"])
    
    if file:
        df_new = parse_fantrax_robust(file, target_team)
        st.dataframe(df_new.head())
        if st.button("Confirmer l'importation"):
            path = os.path.join(DATA_DIR, f"fantrax_{st.session_state['season']}.csv")
            df_cur = pd.read_csv(path) if os.path.exists(path) else pd.DataFrame(columns=REQUIRED_COLS)
            df_cur = df_cur[df_cur["Propriétaire"] != target_team]
            df_final = pd.concat([df_cur, df_new], ignore_index=True)
            df_final.to_csv(path, index=False)
            st.session_state["data"] = df_final
            st.success("Importation réussie !")

# =====================================================
# 7. MAIN
# =====================================================

def main():
    if "season" not in st.session_state: st.session_state["season"] = "2024-2025"
    path = os.path.join(DATA_DIR, f"fantrax_{st.session_state['season']}.csv")
    if os.path.exists(path):
        st.session_state["data"] = pd.read_csv(path)
    else:
        st.session_state["data"] = pd.DataFrame(columns=REQUIRED_COLS)

    st.sidebar.title("🏒 PMS Pool")
    st.session_state["season"] = st.sidebar.selectbox("Saison", ["2024-2025", "2025-2026"])
    selected_team = st.sidebar.selectbox("Mon Équipe", ["Whalers", "Nordiques", "Cracheurs", "Prédateurs", "Red Wings", "Canadiens"], key="selected_team")
    
    menu = ["🏆 Classement", "🧾 Alignement"]
    if selected_team == "Whalers": menu.append("🛠️ Gestion Admin")
    
    choice = st.sidebar.radio("Navigation", menu)
    
    if choice == "🧾 Alignement":
        render_tab_alignment()
    elif choice == "🛠️ Gestion Admin":
        render_tab_admin()
    else:
        st.title(choice)
        st.write("Contenu à venir...")

if __name__ == "__main__":
    main()
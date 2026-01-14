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
        width: 26px; height: 26px;
        border-radius: 50%;
        text-align: center;
        line-height: 26px;
        font-weight: bold;
        font-size: 11px;
        color: white;
    }
    .pos-f { background-color: #16a34a; }
    .pos-d { background-color: #2563eb; }
    .pos-g { background-color: #7c3aed; }
</style>
""", unsafe_allow_html=True)

# =====================================================
# 3. FONCTIONS UTILITAIRES & DONNÉES
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

def load_players_db():
    """Charge la base de données globale des joueurs NHL."""
    if os.path.exists("hockey.players.csv"):
        return pd.read_csv("hockey.players.csv")
    return pd.DataFrame()

# =====================================================
# 4. MOTEUR D'IMPORTATION (FANTRAX)
# =====================================================

def parse_fantrax_robust(uploaded_file, team_owner):
    raw_text = uploaded_file.read().decode("utf-8", errors="ignore")
    lines = raw_text.splitlines()
    data_rows = []
    current_headers = None
    
    for line in lines:
        parts = [p.strip().replace('"', '') for p in line.split(',')]
        if not parts or parts == [''] or "Skaters" in parts or "Goalies" in parts: continue
        if any(x in parts[0].lower() for x in ["player", "joueur", "id"]):
            current_headers = [p.lower() for p in parts]
            continue
        if current_headers and len(parts) >= len(current_headers):
            row = dict(zip(current_headers, parts))
            if row.get("player"): data_rows.append(row)

    df_raw = pd.DataFrame(data_rows)
    if df_raw.empty: return pd.DataFrame()

    def find_col(aliases):
        for c in df_raw.columns:
            if any(a in c for a in aliases): return c
        return None

    c_p, c_t, c_pos, c_sal, c_stat, c_lvl = find_col(['player']), find_col(['team']), find_col(['pos']), find_col(['salary']), find_col(['status']), find_col(['level'])

    df_final = pd.DataFrame()
    df_final["Joueur"] = df_raw[c_p]
    df_final["Equipe"] = df_raw[c_t] if c_t else "N/A"
    df_final["Pos"] = df_raw[c_pos].apply(normalize_pos)
    
    def clean_s(v):
        s = str(v).replace("$","").replace(",","").replace("\xa0","").strip()
        s = re.sub(r'\s+', '', s)
        try: return int(float(s))
        except: return 0
    
    df_final["Salaire"] = df_raw[c_sal].apply(clean_s)
    df_final["Propriétaire"] = team_owner
    df_final["Statut"] = df_raw[c_stat].apply(lambda s: STATUT_CE if "min" in str(s).lower() else STATUT_GC)
    df_final["Slot"] = df_raw[c_stat].apply(lambda s: SLOT_ACTIF if "act" in str(s).lower() else (SLOT_BANC if "res" in str(s).lower() else ""))
    df_final["Level"] = df_raw[c_lvl] if c_lvl else "STD"
    df_final["IR Date"] = ""
    
    return df_final[REQUIRED_COLS]

# =====================================================
# 5. POPUPS (MOUVEMENT ET AJOUT)
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
        "🩹 Blessé (IR)": (df.at[idx, "Statut"], SLOT_IR)
    }
    dest = st.radio("Destination", list(options.keys()))
    if st.button("Confirmer"):
        new_statut, new_slot = options[dest]
        st.session_state["data"].at[idx, "Statut"] = new_statut
        st.session_state["data"].at[idx, "Slot"] = new_slot
        save_to_csv(st.session_state["data"])
        st.rerun()

# =====================================================
# 6. ONGLET JOUEURS AUTONOMES
# =====================================================

def render_tab_autonomes():
    st.title("👤 Joueurs autonomes")
    st.write("Cherchez un joueur dans la base de données pour l'ajouter à votre équipe.")

    # Chargement DB
    db = load_players_db()
    if db.empty:
        st.error("Fichier 'hockey.players.csv' introuvable.")
        return

    # Recherche
    search_query = st.text_input("Nom du joueur", placeholder="Ex: McDavid...")
    
    if search_query:
        # Filtrage (insensible à la casse)
        results = db[db["Player"].str.contains(search_query, case=False, na=False)].copy()
        
        # Exclure les joueurs déjà dans une équipe
        ligue_joueurs = st.session_state["data"]["Joueur"].tolist()
        results = results[~results["Player"].isin(ligue_joueurs)]

        if results.empty:
            st.warning("Aucun joueur autonome trouvé.")
        else:
            st.write(f"Résultats ({len(results)}) :")
            
            # Affichage
            h1, h2, h3, h4, h5, h6 = st.columns([0.5, 1, 3, 1, 1.5, 1.5])
            h1.write("Pos"); h2.write("Équipe NHL"); h3.write("Joueur"); h4.write("Lvl"); h5.write("Salaire"); h6.write("Action")
            
            for _, row in results.head(20).iterrows():
                c1, c2, c3, c4, c5, c6 = st.columns([0.5, 1, 3, 1, 1.5, 1.5])
                c1.markdown(get_pos_html(row['Position']), unsafe_allow_html=True)
                c2.write(row['Team'])
                c3.write(f"**{row['Player']}**")
                c4.write(row['Level'])
                c5.write(row['Cap Hit'])
                
                if c6.button("Embaucher", key=f"add_{row['Player']}"):
                    # Création du nouveau joueur
                    new_player = {
                        "Propriétaire": st.session_state["selected_team"],
                        "Joueur": row['Player'],
                        "Pos": normalize_pos(row['Position']),
                        "Equipe": row['Team'],
                        "Salaire": int(str(row['Cap Hit']).replace(" ","").replace("$","")),
                        "Level": row['Level'],
                        "Statut": STATUT_GC,
                        "Slot": SLOT_BANC,
                        "IR Date": ""
                    }
                    st.session_state["data"] = pd.concat([st.session_state["data"], pd.DataFrame([new_player])], ignore_index=True)
                    save_to_csv(st.session_state["data"])
                    st.success(f"{row['Player']} a rejoint les {st.session_state['selected_team']} !")
                    st.rerun()

# =====================================================
# 7. RENDU ALIGNEMENT
# =====================================================

def render_roster_table(df_roster, owner):
    if df_roster.empty:
        st.caption("Vide.")
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
        st.info("Équipe vide. Allez dans 'Joueurs autonomes' ou 'Admin'.")
        return

    used_gc = dprop[dprop["Statut"] == STATUT_GC]["Salaire"].sum()
    used_ce = dprop[dprop["Statut"] == STATUT_CE]["Salaire"].sum()
    
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.markdown(f"**GC — {owner}** <span style='float:right; color:#22c55e;'>{money(PLAFOND_GC_DEFAULT - used_gc)}</span>", unsafe_allow_html=True)
        st.progress(min(used_gc / PLAFOND_GC_DEFAULT, 1.0))
    with col_p2:
        st.markdown(f"**CE — {owner}** <span style='float:right; color:#22c55e;'>{money(PLAFOND_CE_DEFAULT - used_ce)}</span>", unsafe_allow_html=True)
        st.progress(min(used_ce / PLAFOND_CE_DEFAULT, 1.0))

    st.divider()
    left, right = st.columns(2)
    with left:
        st.markdown("### 🟢 Actifs")
        render_roster_table(dprop[(dprop["Statut"] == STATUT_GC) & (dprop["Slot"] == SLOT_ACTIF)], owner)
        with st.expander("🟡 Banc"):
            render_roster_table(dprop[(dprop["Statut"] == STATUT_GC) & (dprop["Slot"] == SLOT_BANC)], owner)
    with right:
        st.markdown("### 🔵 Mineur")
        render_roster_table(dprop[dprop["Statut"] == STATUT_CE], owner)
        with st.expander("🩹 Blessés"):
            render_roster_table(dprop[dprop["Slot"] == SLOT_IR], owner)

# =====================================================
# 8. ROUTING PRINCIPAL
# =====================================================

def main():
    if "season" not in st.session_state: st.session_state["season"] = "2024-2025"
    path = os.path.join(DATA_DIR, f"fantrax_{st.session_state['season']}.csv")
    if "data" not in st.session_state:
        st.session_state["data"] = pd.read_csv(path) if os.path.exists(path) else pd.DataFrame(columns=REQUIRED_COLS)

    st.sidebar.title("🏒 PMS Pool")
    selected_team = st.sidebar.selectbox("Équipe", ["Whalers", "Nordiques", "Cracheurs", "Prédateurs", "Red Wings", "Canadiens"], key="selected_team")
    
    choice = st.sidebar.radio("Navigation", ["🏆 Classement", "🧾 Alignement", "👤 Joueurs autonomes", "🛠️ Gestion Admin"])
    
    if choice == "🧾 Alignement": render_tab_alignment()
    elif choice == "👤 Joueurs autonomes": render_tab_autonomes()
    elif choice == "🛠️ Gestion Admin": 
        # (render_tab_admin ici)
        st.write("Section Admin d'importation.")
    else: 
        st.title("🏆 Classement")
        st.dataframe(st.session_state["data"], hide_index=True)

if __name__ == "__main__":
    main()
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
st.set_page_config(page_title="PMS - Gestion d'Équipe", layout="wide")

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

def save_to_csv(df):
    season = st.session_state.get("season", "2024-2025")
    path = os.path.join(DATA_DIR, f"fantrax_{season}.csv")
    df.to_csv(path, index=False)
    st.session_state["data"] = df

# =====================================================
# 4. MOTEUR D'IMPORTATION (SANS LIMITE DE JOUEURS)
# =====================================================

def parse_fantrax_robust(uploaded_file, team_owner):
    raw_text = uploaded_file.read().decode("utf-8", errors="ignore")
    lines = raw_text.splitlines()
    data_rows = []
    current_headers = None
    
    for line in lines:
        parts = [p.strip().replace('"', '') for p in line.split(',')]
        if not parts or parts == [''] or "Skaters" in parts or "Goalies" in parts: continue
        
        # Détection d'en-tête (contient Player)
        if any(x in parts[0].lower() for x in ["player", "joueur", "id"]):
            current_headers = [p.lower() for p in parts]
            continue
        
        # Extraction si la ligne correspond aux colonnes
        if current_headers and len(parts) >= len(current_headers):
            row = dict(zip(current_headers, parts))
            if row.get("player"): data_rows.append(row)

    df_raw = pd.DataFrame(data_rows)
    if df_raw.empty: return pd.DataFrame()

    def find_col(aliases):
        for c in df_raw.columns:
            if any(a in c for a in aliases): return c
        return None

    c_p, c_t, c_pos, c_sal, c_stat = find_col(['player']), find_col(['team']), find_col(['pos']), find_col(['salary']), find_col(['status'])

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
    
    # --- LOGIQUE DE RÉPARTITION (Fantrax Status) ---
    # Act -> Grand Club / Actif
    # Res -> Grand Club / Banc
    # Min -> Club École / Mineur
    def map_statut(s):
        return STATUT_CE if "min" in str(s).lower() else STATUT_GC
    
    def map_slot(s):
        s_low = str(s).lower()
        if "act" in s_low: return SLOT_ACTIF
        if "res" in s_low: return SLOT_BANC
        return "" # Mineur n'a pas de slot spécifique

    df_final["Statut"] = df_raw[c_stat].apply(map_statut)
    df_final["Slot"] = df_raw[c_stat].apply(map_slot)
    df_final["Level"] = df_raw.get("contract", "0")
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
        "🩹 Blessé (IR)": (df.at[idx, "Statut"], SLOT_IR)
    }
    
    dest = st.radio("Destination", list(options.keys()))
    if st.button("Confirmer", type="primary"):
        new_statut, new_slot = options[dest]
        st.session_state["data"].at[idx, "Statut"] = new_statut
        st.session_state["data"].at[idx, "Slot"] = new_slot
        save_to_csv(st.session_state["data"])
        st.rerun()

# =====================================================
# 6. RENDU DE L'INTERFACE
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
        st.info("Alignement vide. Utilisez l'onglet Admin.")
        return

    # Séparations
    gc_p = dprop[dprop["Statut"] == STATUT_GC]
    ce_p = dprop[dprop["Statut"] == STATUT_CE]
    used_gc, used_ce = gc_p[gc_p["Slot"] != SLOT_IR]["Salaire"].sum(), ce_p[ce_p["Slot"] != SLOT_IR]["Salaire"].sum()
    
    # Header stats
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.markdown(f"**Plafond GC — {owner}** <span style='float:right; color:#22c55e;'>{money(PLAFOND_GC_DEFAULT - used_gc)}</span>", unsafe_allow_html=True)
        st.progress(min(used_gc / PLAFOND_GC_DEFAULT, 1.0))
    with col_p2:
        st.markdown(f"**Plafond CE — {owner}** <span style='float:right; color:#22c55e;'>{money(PLAFOND_CE_DEFAULT - used_ce)}</span>", unsafe_allow_html=True)
        st.progress(min(used_ce / PLAFOND_CE_DEFAULT, 1.0))

    st.write(f"**GC:** {money(used_gc)} | **CE:** {money(used_ce)} | **Total Joueurs:** {len(dprop)}")
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
    st.title("🛠️ Gestion Admin")
    target = st.selectbox("Équipe cible", ["Whalers", "Nordiques", "Cracheurs", "Prédateurs", "Red Wings", "Canadiens"])
    file = st.file_uploader("Importer CSV Fantrax", type=["csv"])
    if file:
        df_new = parse_fantrax_robust(file, target)
        if not df_new.empty:
            st.success(f"✅ {len(df_new)} joueurs trouvés.")
            st.dataframe(df_new.head(10), use_container_width=True)
            if st.button(f"Écraser l'alignement de {target}"):
                df_global = st.session_state["data"]
                df_global = df_global[df_global["Propriétaire"] != target]
                df_final = pd.concat([df_global, df_new], ignore_index=True)
                save_to_csv(df_final)
                st.rerun()

# =====================================================
# 6. MAIN
# =====================================================

def main():
    if "season" not in st.session_state: st.session_state["season"] = "2024-2025"
    path = os.path.join(DATA_DIR, f"fantrax_{st.session_state['season']}.csv")
    if "data" not in st.session_state:
        st.session_state["data"] = pd.read_csv(path) if os.path.exists(path) else pd.DataFrame(columns=REQUIRED_COLS)

    st.sidebar.title("🏒 PMS Pool")
    selected_team = st.sidebar.selectbox("Équipe", ["Whalers", "Nordiques", "Cracheurs", "Prédateurs", "Red Wings", "Canadiens"], key="selected_team")
    
    choice = st.sidebar.radio("Navigation", ["🏆 Classement", "🧾 Alignement", "🛠️ Gestion Admin"])
    
    if choice == "🧾 Alignement": render_tab_alignment()
    elif choice == "🛠️ Gestion Admin": render_tab_admin()
    else: st.title("🏆 Classement"); st.dataframe(st.session_state["data"], hide_index=True)

if __name__ == "__main__":
    main()
import streamlit as st
import pandas as pd
import requests
import os
import json
import re

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# -----------------------------
# NHL SEARCH (CLEAN & SAFE)
# -----------------------------
def _nhl_search_playerid(player_name: str):
    if not player_name:
        return None
    try:
        url = "https://search.d3.nhle.com/api/v1/search/player"
        params = {"q": player_name, "limit": 10}
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return None

    items = data.get("items") or []
    if not isinstance(items, list):
        return None

    name_norm = player_name.lower().strip()
    for it in items:
        try:
            pid = it.get("playerId") or it.get("id")
            pid_i = int(pid)
        except Exception:
            continue

        nm = str(
            it.get("name")
            or it.get("playerName")
            or it.get("fullName")
            or ""
        ).strip().lower()

        if not nm:
            continue

        if nm == name_norm or name_norm.split()[-1] in nm:
            return pid_i

    return None

# -----------------------------
# PLAYERS DB UPDATE (SAFE STUB)
# -----------------------------
def update_players_db(path: str):
    if not os.path.exists(path):
        st.error(f"File not found: {path}")
        return

    df = pd.read_csv(path)
    if "Country" not in df.columns:
        df["Country"] = ""

    updated = 0
    for i, row in df.iterrows():
        if row.get("Country"):
            continue
        pid = _nhl_search_playerid(row.get("Player", ""))
        if pid:
            df.at[i, "Country"] = "US"
            updated += 1

    df.to_csv(path, index=False)
    st.success(f"Players DB updated ({updated} rows)")

# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="Pool Hockey", layout="wide")

TABS = ["🏠 Home", "🛠️ Gestion Admin"]
active_tab = st.radio("Navigation", TABS, horizontal=True)

if active_tab == "🏠 Home":
    st.title("🏠 Home")
    st.info("Home tab clean. No Players DB here.")

elif active_tab == "🛠️ Gestion Admin":
    st.title("🛠️ Gestion Admin")

    st.subheader("🗃️ Players DB")
    players_path = os.path.join(DATA_DIR, "hockey.players.csv")

    if st.button("Mettre à jour Players DB"):
        update_players_db(players_path)

    st.caption("Players DB admin tools live only here.")

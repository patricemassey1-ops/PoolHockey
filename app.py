import streamlit as st
import os
import json
from datetime import datetime

# MUST BE FIRST
st.set_page_config(page_title="Pool Hockey", layout="wide")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
CHECKPOINT = os.path.join(DATA_DIR, "nhl_country_checkpoint.json")

st.title("Pool Hockey — Clean Base")

# --- Helper
def checkpoint_status(path):
    if os.path.exists(path):
        ts = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
        return True, ts
    return False, ""

# --- NAV
tab = st.radio("Navigation", ["🏠 Home", "🛠️ Gestion Admin"], horizontal=True)

if tab == "🏠 Home":
    st.info("Home clean.")

elif tab == "🛠️ Gestion Admin":
    st.subheader("Gestion Admin")

    has_ckpt, ckpt_ts = checkpoint_status(CHECKPOINT)

    if has_ckpt:
        st.warning(f"✅ Checkpoint file detected — {ckpt_ts}")
    else:
        st.caption("Aucun checkpoint détecté.")

    if st.button("Create dummy checkpoint"):
        with open(CHECKPOINT, "w") as f:
            json.dump({"cursor": 0}, f)
        st.success("Checkpoint created.")

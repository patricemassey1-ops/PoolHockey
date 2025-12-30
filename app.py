# =====================================================
# TABLEAU (LOGO + NOM DANS LA MÊME COLONNE)
# =====================================================
with tab1:
    # Largeurs: 1 colonne "Équipe" plus large, puis les chiffres
    headers = st.columns([4, 2, 2, 2, 2])
    headers[0].markdown("**Équipe**")
    headers[1].markdown("**Grand Club**")
    headers[2].markdown("**Club École**")
    headers[3].markdown("**Restant GC**")
    headers[4].markdown("**Restant CE**")

    def owner_cell(owner: str, logo_path: str, size: int = LOGO_SIZE) -> str:
        # Logo si dispo, sinon placeholder
        if logo_path and os.path.exists(logo_path):
            b64 = img_to_base64(logo_path)
            img_html = f"""
            <img src="data:image/png;base64,{b64}"
                 style="height:{size}px; width:{size}px; object-fit:contain; display:block;" />
            """
        else:
            img_html = f"""
            <div style="height:{size}px; width:{size}px; display:flex; align-items:center; justify-content:center;">
                —
            </div>
            """

        return f"""
        <div style="height:{size}px; display:flex; align-items:center; gap:12px;">
            <div style="flex:0 0 {size}px; display:flex; align-items:center; justify-content:center;">
                {img_html}
            </div>
            <div style="line-height:1.1;">
                <div style="font-weight:600;">{owner}</div>
            </div>
        </div>
        """

    for _, r in plafonds.iterrows():
        cols = st.columns([4, 2, 2, 2, 2])

        owner = str(r["Propriétaire"])
        logo_path = str(r["Logo"]).strip()

        cols[0].markdown(owner_cell(owner, logo_path, LOGO_SIZE), unsafe_allow_html=True)
        cols[1].markdown(text_cell(money(r["GC"]), LOGO_SIZE, "left"), unsafe_allow_html=True)
        cols[2].markdown(text_cell(money(r["CE"]), LOGO_SIZE, "left"), unsafe_allow_html=True)
        cols[3].markdown(text_cell(money(r["Restant GC"]), LOGO_SIZE, "left"), unsafe_allow_html=True)
        cols[4].markdown(text_cell(money(r["Restant CE"]), LOGO_SIZE, "left"), unsafe_allow_html=True)

# =====================================================
# 🧾 ALIGNEMENT – MODIFIER GC / CE
# =====================================================
with tab2:
    st.subheader("🧾 Gestion de l’alignement (Grand Club / Club École)")

    proprietaire = st.selectbox(
        "Propriétaire",
        sorted(df["Propriétaire"].unique())
    )

    joueurs_prop = df[df["Propriétaire"] == proprietaire]

    joueur = st.selectbox(
        "Joueur",
        joueurs_prop["Joueur"].sort_values()
    )

    ligne_joueur = joueurs_prop[joueurs_prop["Joueur"] == joueur].iloc[0]

    statut_actuel = ligne_joueur["Statut"]
    salaire = ligne_joueur["Salaire"]

    st.info(f"Statut actuel : **{statut_actuel}** — Salaire : **{money(salaire)}**")

    nouveau_statut = st.radio(
        "Nouveau statut",
        ["Grand Club", "Club École"],
        index=0 if statut_actuel == "Grand Club" else 1
    )

    if st.button("✅ Appliquer le changement"):
        # Simulation
        temp = df.copy()
        mask = (
            (temp["Propriétaire"] == proprietaire)
            & (temp["Joueur"] == joueur)
        )
        temp.loc[mask, "Statut"] = nouveau_statut

        # Recalcul plafonds
        d = temp[temp["Propriétaire"] == proprietaire]
        gc = d[d["Statut"] == "Grand Club"]["Salaire"].sum()
        ce = d[d["Statut"] == "Club École"]["Salaire"].sum()

        if gc > st.session_state["PLAFOND_GC"]:
            st.error("🚨 Dépassement du plafond Grand Club")
        elif ce > st.session_state["PLAFOND_CE"]:
            st.error("🚨 Dépassement du plafond Club École")
        else:
            df.loc[mask, "Statut"] = nouveau_statut
            df.to_csv(DATA_FILE, index=False)
            st.session_state["data"] = df

            st.success("✅ Alignement mis à jour avec succès")
            st.rerun()

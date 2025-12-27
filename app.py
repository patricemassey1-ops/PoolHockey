if fichiers_telecharges:
    all_players = []

    for fichier in fichiers_telecharges:
        try:
            # 1. Lecture brute du fichier
            content = fichier.getvalue().decode('utf-8-sig')
            lines = content.splitlines()

            def extract_table(lines, section_keyword):
                start_line_index = -1
                for i, line in enumerate(lines):
                    if section_keyword in line:
                        start_line_index = i
                        break
                
                if start_line_index == -1: return pd.DataFrame()

                header_line_index = -1
                for i in range(start_line_index + 1, len(lines)):
                    if any(kw in lines[i] for kw in ["ID", "Player", "Status", "Salary"]):
                        header_line_index = i
                        break
                
                if header_line_index == -1: return pd.DataFrame()

                # On utilise pandas pour lire directement à partir de la ligne d'en-tête
                # et on gère les lignes incorrectes ici avec 'on_bad_lines="skip"'
                clean_content = "\n".join(lines[header_line_index:])
                
                df = pd.read_csv(
                    io.StringIO(clean_content), 
                    sep=None, 
                    engine='python', 
                    on_bad_lines='skip' # <--- Gère l'erreur 21 champs vs 22
                )
                
                # Le reste de votre logique de filtrage par ID reste valide
                if 'ID' in df.columns:
                    df = df[df['ID'].astype(str).str.strip().str.startswith(('0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '*'))]

                return df

            # Appels inchangés
            df_skaters = extract_table(lines, 'Skaters')
            df_goalies = extract_table(lines, 'Goalies')
            df = pd.concat([df_skaters, df_goalies], ignore_index=True)
            df.dropna(how='all', inplace=True)
            
            # ... (Le reste de votre code de traitement des colonnes suit ici, il est correct)
            # ...

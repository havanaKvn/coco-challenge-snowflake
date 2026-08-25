"""
Dev Assistant — Application Streamlit-in-Snowflake
Permet d'invoquer les 4 skills (dev-objects, dev-ihm, dev-cicd, dev-tests)
via le Cortex Agent DEV_ASSISTANT déployé dans COCO_CHALLENGE_DB.DEV
"""

import streamlit as st
from snowflake.snowpark.context import get_active_session

# ============================================================
# Configuration
# ============================================================
AGENT_FQN = "COCO_CHALLENGE_DB.DEV.DEV_ASSISTANT"

SKILLS = {
    "dev-objects": {
        "label": "🏗️ Création d'Objets",
        "description": "Tables, views, procedures, UDFs, modèles dbt, pipelines Snowpark",
        "placeholder": "Ex: Crée une table FCT_LIVRAISONS avec delivery_id, order_id, status, delivered_at",
    },
    "dev-ihm": {
        "label": "🖥️ Interface (IHM)",
        "description": "Apps Streamlit, dashboards, composants UI, charts",
        "placeholder": "Ex: Crée une page dashboard avec 3 KPIs et un graphique de tendance",
    },
    "dev-cicd": {
        "label": "🔄 CI/CD",
        "description": "Workflows GitHub Actions, pipelines de déploiement, secrets",
        "placeholder": "Ex: Crée un workflow CI pour linter et tester mes modèles dbt sur chaque PR",
    },
    "dev-tests": {
        "label": "🧪 Tests",
        "description": "Tests dbt, pytest, DMFs, validation post-deploy",
        "placeholder": "Ex: Génère les tests dbt pour la table FCT_SALES (PK, FK, not_null)",
    },
}

# ============================================================
# Session Snowflake
# ============================================================
session = get_active_session()

# ============================================================
# Interface utilisateur
# ============================================================
st.set_page_config(page_title="Dev Assistant", page_icon="🛠️", layout="wide")

st.title("🛠️ Dev Assistant")
st.caption("Assistant IA pour développeurs — propulsé par Cortex Agent + Skills")

st.divider()

# Sélection du skill
col_skill, col_info = st.columns([1, 2])

with col_skill:
    skill_key = st.radio(
        "Choisir un skill",
        options=list(SKILLS.keys()),
        format_func=lambda k: SKILLS[k]["label"],
    )

with col_info:
    st.info(f"**{SKILLS[skill_key]['label']}**\n\n{SKILLS[skill_key]['description']}")

st.divider()

# Zone de saisie du prompt
user_prompt = st.text_area(
    "Que voulez-vous faire ?",
    placeholder=SKILLS[skill_key]["placeholder"],
    height=120,
)

# Options avancées
with st.expander("Options avancées"):
    col_opt1, col_opt2 = st.columns(2)
    with col_opt1:
        target_db = st.text_input("Database cible", value="COCO_CHALLENGE_DB")
    with col_opt2:
        target_schema = st.text_input("Schema cible", value="DEV")
    include_context = st.checkbox("Inclure le contexte DB/Schema dans le prompt", value=True)

# Bouton d'exécution
if st.button("🚀 Générer", type="primary", disabled=not user_prompt):
    # Construction du prompt enrichi
    full_prompt = f"[Skill: {skill_key}] "
    if include_context:
        full_prompt += f"[Context: database={target_db}, schema={target_schema}] "
    full_prompt += user_prompt

    with st.spinner("L'agent réfléchit..."):
        try:
            # Appel au Cortex Agent via SQL
            result = session.sql(f"""
                SELECT {AGENT_FQN}!RUN('{full_prompt.replace("'", "''")}')::VARCHAR AS response
            """).collect()

            response_text = result[0]["RESPONSE"]

            # Affichage du résultat
            st.success("Code généré avec succès !")

            # Détection du langage pour la coloration syntaxique
            if "```sql" in response_text.lower() or "CREATE" in response_text:
                lang = "sql"
            elif "```python" in response_text.lower() or "def " in response_text:
                lang = "python"
            elif "```yaml" in response_text.lower() or "version:" in response_text:
                lang = "yaml"
            else:
                lang = "markdown"

            st.code(response_text, language=lang)

            # Bouton copier
            st.download_button(
                label="📋 Télécharger le code",
                data=response_text,
                file_name=f"{skill_key}_output.txt",
                mime="text/plain",
            )

        except Exception as e:
            st.error(f"Erreur lors de l'appel à l'agent : {e}")

# ============================================================
# Historique (session state)
# ============================================================
if "history" not in st.session_state:
    st.session_state.history = []

if user_prompt and st.session_state.get("last_response"):
    st.session_state.history.append({
        "skill": skill_key,
        "prompt": user_prompt,
        "response": st.session_state.get("last_response"),
    })

# Afficher l'historique
if st.session_state.history:
    st.divider()
    with st.expander(f"📜 Historique ({len(st.session_state.history)} requêtes)"):
        for i, entry in enumerate(reversed(st.session_state.history)):
            st.markdown(f"**{SKILLS[entry['skill']]['label']}** — {entry['prompt'][:80]}...")

# ============================================================
# Sidebar : aide rapide
# ============================================================
with st.sidebar:
    st.header("Guide rapide")
    st.markdown("""
    ### Comment utiliser
    1. **Sélectionnez un skill** selon votre besoin
    2. **Décrivez** ce que vous voulez en langage naturel
    3. **Cliquez Générer** pour obtenir le code

    ### Exemples de prompts

    **dev-objects :**
    - "Crée une dynamic table DT_CUSTOMER_360"
    - "Ajoute un stream + task CDC sur RAW_ORDERS"
    - "Génère un modèle dbt staging pour la source SAP"

    **dev-ihm :**
    - "Crée une app Streamlit avec filtres date et KPIs"
    - "Ajoute un graphique plotly de tendance des ventes"

    **dev-cicd :**
    - "Crée un workflow GitHub Actions pour dbt CI"
    - "Ajoute un job de déploiement prod avec approval"

    **dev-tests :**
    - "Génère les tests dbt pour fct_sales"
    - "Crée un DMF de contrôle de nullité sur customer_id"
    """)

    st.divider()
    st.caption(f"Agent : `{AGENT_FQN}`")
    st.caption("Powered by Snowflake Cortex")

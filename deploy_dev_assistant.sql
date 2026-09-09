-- ============================================================
-- SCRIPT DE DEPLOIEMENT : Dev Assistant (Stage + Skills + Proc + Agent)
-- Database : COCO_CHALLENGE_DB
-- Schema   : DEV
-- Warehouse: COMPUT_WHAREHOUSE
-- ============================================================

-- ============================================================
-- STEP 1 : Base, schema, warehouse
-- ============================================================
USE WAREHOUSE COMPUTE_WH;

CREATE DATABASE IF NOT EXISTS COCO_CHALLENGE_DB;
CREATE SCHEMA IF NOT EXISTS COCO_CHALLENGE_DB.DEV;

USE SCHEMA COCO_CHALLENGE_DB.DEV;

-- ============================================================
-- STEP 2 : Stage des skills
-- ============================================================
CREATE STAGE IF NOT EXISTS COCO_CHALLENGE_DB.DEV.SKILLS_STAGE
    DIRECTORY = (ENABLE = TRUE)
    COMMENT = 'Stage contenant les skills du Dev Assistant (SKILL.md files)';

-- ============================================================
-- STEP 3 : Upload des SKILL.md (hors Snowsight)
-- ============================================================
-- Depuis un terminal, a la racine du projet :
-- snow stage copy ".cortex/skills/dev-objects/SKILL.md" "@COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/dev-objects/" --overwrite -c coco_challenge_LOUIS
-- snow stage copy ".cortex/skills/dev-ihm/SKILL.md"     "@COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/dev-ihm/"     --overwrite
-- snow stage copy ".cortex/skills/dev-cicd/SKILL.md"    "@COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/dev-cicd/"    --overwrite
-- snow stage copy ".cortex/skills/dev-tests/SKILL.md"   "@COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/dev-tests/"   --overwrite

-- ============================================================
-- STEP 4 : Procedure appelee par l'agent pour creer les tables
-- ============================================================
-- Les regex sur identifiants et types sont la frontiere de securite :
-- la sortie du modele est une entree non fiable injectee dans du DDL.
CREATE OR REPLACE AGENT COCO_CHALLENGE_DB.DEV.DEV_ASSISTANT
    COMMENT = 'Assistant developpeur Snowflake / dbt / Snowpark / CI-CD'
    PROFILE = '{"display_name": "Dev Assistant"}'
FROM SPECIFICATION $$
{
    "models": { "orchestration": "auto" },
    "instructions": {
        "response": "Tu es un assistant développeur expert en Snowflake, dbt, Python/Snowpark et GitHub Actions. Applique toujours les conventions de nommage et bonnes pratiques définies dans tes skills.",
        "orchestration": "Quand l'utilisateur demande de CRÉER une table, appelle l'outil create_table. Le paramètre columns_json est une CHAÎNE contenant un tableau JSON. Chaque colonne a: name, type (type Snowflake NU, sans contrainte : VARCHAR(50), NUMBER(18,2), TIMESTAMP_NTZ...), et optionnellement not_null, primary_key, autoincrement (booléens) et default. N'inclus JAMAIS 'NOT NULL', 'PRIMARY KEY' ou 'DEFAULT' dans le champ type. Exemple: [{\"name\":\"ID\",\"type\":\"NUMBER\",\"autoincrement\":true,\"primary_key\":true},{\"name\":\"CODE\",\"type\":\"VARCHAR(50)\",\"not_null\":true},{\"name\":\"CREATED_AT\",\"type\":\"TIMESTAMP_NTZ\",\"default\":\"CURRENT_TIMESTAMP()\"}]"
    },
    "tools": [
        {
            "tool_spec": {
                "type": "generic",
                "name": "create_table",
                "description": "Crée physiquement une table dans COCO_CHALLENGE_DB.DEV. À utiliser dès que l'utilisateur demande la création d'une table.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "table_name":    { "type": "string", "description": "Nom de la table, ex: DIM_SITE" },
                        "columns_json":  { "type": "string", "description": "Tableau JSON des colonnes, sérialisé en chaîne" },
                        "table_comment": { "type": "string", "description": "Commentaire fonctionnel de la table" }
                    },
                    "required": ["table_name", "columns_json"]
                }
            }
        }
    ],
    "tool_resources": {
        "create_table": {
            "type": "procedure",
            "execution_environment": {
                "type": "warehouse",
                "warehouse": "COMPUTE_WH",
                "query_timeout": 60
            },
            "identifier": "COCO_CHALLENGE_DB.DEV.SP_CREATE_TABLE"
        }
    },
    "skills": [
        { "name": "dev-objects", "source": { "type": "STAGE", "path": "@COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/dev-objects" } },
        { "name": "dev-ihm",     "source": { "type": "STAGE", "path": "@COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/dev-ihm" } },
        { "name": "dev-cicd",    "source": { "type": "STAGE", "path": "@COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/dev-cicd" } },
        { "name": "dev-tests",   "source": { "type": "STAGE", "path": "@COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/dev-tests" } }
    ]
}
$$;

-- ============================================================
-- STEP 5 : Cortex Agent (skills + outil d'execution)
-- ============================================================
CREATE OR REPLACE PROCEDURE COCO_CHALLENGE_DB.DEV.SP_CREATE_TABLE(TABLE_NAME VARCHAR, COLUMNS_JSON VARCHAR, TABLE_COMMENT VARCHAR)
RETURNS VARCHAR
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'main'
EXECUTE AS OWNER
AS
$$
import json, re

IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,254}$')
DTYPE = re.compile(
    r'^(VARCHAR(\(\d{1,5}\))?|NUMBER(\(\d{1,2},\d{1,2}\))?|INT|INTEGER|FLOAT'
    r'|BOOLEAN|DATE|TIMESTAMP_NTZ|TIMESTAMP_LTZ|TIMESTAMP_TZ|VARIANT|OBJECT|ARRAY)$'
)
DEFAULT_OK = re.compile(
    r"^(CURRENT_TIMESTAMP\(\)|CURRENT_USER\(\)|CURRENT_DATE\(\)|NULL|TRUE|FALSE"
    r"|-?\d{1,18}(\.\d{1,6})?|'[^'\\]{0,255}')$"
)
PREFIXES = ('DIM_', 'FCT_', 'STG_', 'INT_', 'RAW_')

def main(session, table_name, columns_json, table_comment):
    tn = (table_name or '').strip().upper()
    if not IDENT.match(tn):
        return f"REFUS: nom de table invalide '{table_name}'"
    if not tn.startswith(PREFIXES):
        return f"REFUS: '{tn}' ne respecte pas les conventions {PREFIXES}"

    try:
        columns = json.loads(columns_json or '[]')
    except Exception as e:
        return f"REFUS: columns_json illisible ({e})"
    if not isinstance(columns, list) or not columns:
        return "REFUS: aucune colonne fournie"

    defs = []
    for c in columns:
        cn = (c.get('name') or '').strip().upper()
        dt = (c.get('type') or 'VARCHAR').strip().upper()
        if not IDENT.match(cn):
            return f"REFUS: nom de colonne invalide '{cn}'"
        if not DTYPE.match(dt):
            return f"REFUS: type non autorise '{dt}' (constraintes a mettre dans les champs dedies)"

        parts = [f'"{cn}"', dt]
        if c.get('autoincrement'):
            parts.append('AUTOINCREMENT')
        dv = (c.get('default') or '').strip()
        if dv:
            if not DEFAULT_OK.match(dv.upper()) and not DEFAULT_OK.match(dv):
                return f"REFUS: valeur par defaut non autorisee '{dv}'"
            parts.append(f'DEFAULT {dv}')
        if c.get('not_null'):
            parts.append('NOT NULL')
        if c.get('primary_key'):
            parts.append('PRIMARY KEY')
        defs.append(' '.join(parts))

    cmt = (table_comment or '').replace("'", "''")[:1000]
    ddl = (f'CREATE TABLE IF NOT EXISTS COCO_CHALLENGE_DB.DEV."{tn}" ({", ".join(defs)})'
           + (f" COMMENT = '{cmt}'" if cmt else '')
           + ' DATA_RETENTION_TIME_IN_DAYS = 7')
    session.sql(ddl).collect()
    return f"OK: {ddl}"
$$;

-- ============================================================
-- STEP 6 : Verifications
-- ============================================================
LS @COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/;
LS @COCO_CHALLENGE_DB.DEV.APPS_STAGE/APPS/;

DESCRIBE AGENT COCO_CHALLENGE_DB.DEV.DEV_ASSISTANT;

-- Test isole de la procedure
CALL COCO_CHALLENGE_DB.DEV.SP_CREATE_TABLE(
    'DIM_TEST2',
    '[{"name":"ID","type":"NUMBER","autoincrement":true,"primary_key":true},
      {"name":"CODE","type":"VARCHAR(50)","not_null":true},
      {"name":"CREATED_AT","type":"TIMESTAMP_NTZ","default":"CURRENT_TIMESTAMP()"}]',
    'Table de test'
);

select * from COCO_CHALLENGE_DB.DEV.DIM_TEST;

DROP TABLE IF EXISTS COCO_CHALLENGE_DB.DEV.DIM_TEST;

-- ============================================================
-- STEP 7 : Executer l'agent
-- ============================================================
SELECT TRY_PARSE_JSON(
    SNOWFLAKE.CORTEX.DATA_AGENT_RUN(
        'COCO_CHALLENGE_DB.DEV.DEV_ASSISTANT',
        $${"messages":[{"role":"user","content":[{"type":"text","text":"Crée une table DIM_SITE avec code, label, region"}]}]}$$,
        TRUE
    )
) AS response;

-- Detail des etapes : un bloc tool_use = l'outil a bien ete appele
-- WITH run AS (
--     SELECT TRY_PARSE_JSON(
--         SNOWFLAKE.CORTEX.DATA_AGENT_RUN(
--             'COCO_CHALLENGE_DB.DEV.DEV_ASSISTANT',
--             $${"messages":[{"role":"user","content":[{"type":"text","text":"Crée une table DIM_SITE avec code, label, region"}]}]}$$,
--             TRUE
--         )
--     ) AS resp
-- )
-- SELECT f.value:type::VARCHAR                              AS block_type,
--        COALESCE(f.value:text, f.value:tool_use:name)::VARCHAR AS detail
-- FROM run, LATERAL FLATTEN(input => run.resp:content) f;

-- Resultat attendu
SHOW TABLES LIKE 'DIM_SITE' IN SCHEMA COCO_CHALLENGE_DB.DEV;
SELECT * FROM COCO_CHALLENGE_DB.DEV.DIM_SITE;

--------------------------------------------------------test skill streamlit
CREATE OR REPLACE PROCEDURE COCO_CHALLENGE_DB.DEV.SP_CREATE_STREAMLIT(APP_NAME VARCHAR, MAIN_FILE_CONTENT VARCHAR, APP_TITLE VARCHAR)
RETURNS VARCHAR
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'main'
COMMENT = 'Ecrit app.py sur stage puis cree l objet STREAMLIT'
EXECUTE AS OWNER
AS
$$
import io, re

IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,254}$')
STAGE = '@COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills'
MAX_BYTES = 1_000_000

def main(session, app_name, main_file_content, app_title):
    an = (app_name or '').strip().upper()
    if not IDENT.match(an):
        return f"REFUS: nom d'app invalide '{app_name}'"
    if not an.startswith('APP_'):
        return f"REFUS: '{an}' doit commencer par APP_"
    if not main_file_content or not main_file_content.strip():
        return "REFUS: contenu vide"
    data = main_file_content.encode('utf-8')
    if len(data) > MAX_BYTES:
        return f"REFUS: contenu trop volumineux ({len(data)} octets)"

    root = f"{STAGE}/{an}"
    session.file.put_stream(io.BytesIO(data), f"{root}/app.py",
                            auto_compress=False, overwrite=True)

    title = (app_title or an).replace("'", "''")[:255]
    session.sql(f'''
        CREATE OR REPLACE STREAMLIT COCO_CHALLENGE_DB.DEV."{an}"
            ROOT_LOCATION = '{root}'
            MAIN_FILE = 'app.py'
            QUERY_WAREHOUSE = COMPUTE_WH
            TITLE = '{title}'
    ''').collect()

    return f"OK: Streamlit COCO_CHALLENGE_DB.DEV.{an} cree depuis {root}/app.py"
$$;

-------------------------------------------test proc app

CALL COCO_CHALLENGE_DB.DEV.SP_CREATE_STREAMLIT(
    'APP_TEST',
    'import streamlit as st\nst.title("Test")\nst.write("OK")',
    'App de test'
);

SHOW STREAMLITS IN SCHEMA COCO_CHALLENGE_DB.DEV;
DROP STREAMLIT IF EXISTS COCO_CHALLENGE_DB.DEV.APP_TEST;

-----------------------------------------------Create age will create app

CREATE OR REPLACE AGENT COCO_CHALLENGE_DB.DEV.DEV_ASSISTANT_APP
    COMMENT = 'Assistant developpeur Snowflake / dbt / Snowpark / CI-CD'
    PROFILE = '{"display_name": "Dev Assistant"}'
FROM SPECIFICATION $$
{
    "models": { "orchestration": "auto" },
    "instructions": {
        "response": "Tu es un assistant développeur expert en Snowflake, dbt, Python/Snowpark et GitHub Actions. Applique toujours les conventions et bonnes pratiques définies dans tes skills.",
        "orchestration": "CRÉATION DE TABLE : appelle create_table. columns_json est une CHAÎNE contenant un tableau JSON; chaque colonne a name, type (type Snowflake NU sans contrainte) et optionnellement not_null, primary_key, autoincrement, default. N'inclus JAMAIS de contrainte dans le champ type.\n\nCRÉATION D'APP STREAMLIT : charge d'abord le skill dev-ihm, puis appelle create_streamlit. app_name doit commencer par APP_. main_file_content contient le code Python COMPLET du fichier app.py, conforme aux patterns du skill dev-ihm (get_active_session, params bindés, gestion des blocs tool_use/tool_result/text). Ne réponds pas seulement avec le code : appelle l'outil."
    },
    "tools": [
        {
            "tool_spec": {
                "type": "generic",
                "name": "create_table",
                "description": "Crée physiquement une table dans COCO_CHALLENGE_DB.DEV.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "table_name":    { "type": "string", "description": "Nom de la table, ex: DIM_SITE" },
                        "columns_json":  { "type": "string", "description": "Tableau JSON des colonnes, sérialisé en chaîne" },
                        "table_comment": { "type": "string", "description": "Commentaire fonctionnel" }
                    },
                    "required": ["table_name", "columns_json"]
                }
            }
        },
        {
            "tool_spec": {
                "type": "generic",
                "name": "create_streamlit",
                "description": "Crée et déploie une application Streamlit-in-Snowflake dans COCO_CHALLENGE_DB.DEV. À utiliser dès que l'utilisateur demande une IHM, une app, un dashboard ou une interface.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "app_name":          { "type": "string", "description": "Nom de l'app, doit commencer par APP_, ex: APP_DEV_ASSISTANT" },
                        "main_file_content": { "type": "string", "description": "Code Python complet du fichier app.py" },
                        "app_title":         { "type": "string", "description": "Titre affiché de l'application" }
                    },
                    "required": ["app_name", "main_file_content"]
                }
            }
        }
    ],
    "tool_resources": {
        "create_table": {
            "type": "procedure",
            "execution_environment": { "type": "warehouse", "warehouse": "COMPUTE_WH", "query_timeout": 60 },
            "identifier": "COCO_CHALLENGE_DB.DEV.SP_CREATE_TABLE"
        },
        "create_streamlit": {
            "type": "procedure",
            "execution_environment": { "type": "warehouse", "warehouse": "COMPUTE_WH", "query_timeout": 120 },
            "identifier": "COCO_CHALLENGE_DB.DEV.SP_CREATE_STREAMLIT"
        }
    },
    "skills": [
        { "name": "dev-objects", "source": { "type": "STAGE", "path": "@COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/dev-objects" } },
        { "name": "dev-ihm",     "source": { "type": "STAGE", "path": "@COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/dev-ihm" } },
        { "name": "dev-cicd",    "source": { "type": "STAGE", "path": "@COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/dev-cicd" } },
        { "name": "dev-tests",   "source": { "type": "STAGE", "path": "@COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/dev-tests" } }
    ]
}
$$;

-------------------------test agen app

SELECT TRY_PARSE_JSON(
    SNOWFLAKE.CORTEX.DATA_AGENT_RUN(
        'COCO_CHALLENGE_DB.DEV.DEV_ASSISTANT_APP',
        $${"messages":[{"role":"user","content":[{"type":"text","text":"Crée l'application Streamlit APP_DEV_ASSISTANT : une zone de texte qui envoie une instruction à l'agent COCO_CHALLENGE_DB.DEV.DEV_ASSISTANT affiche les blocs tool_use, tool_result et text, plus la liste des tables du schema DEV."}]}]}$$,
        TRUE
    )
) AS response;

SHOW STREAMLITS IN SCHEMA COCO_CHALLENGE_DB.DEV;

---------------------------------------test out put app
select * from dim_personne;

-------------------------------------------------create aent manager

CREATE OR REPLACE AGENT COCO_CHALLENGE_DB.DEV.DEV_ASSISTANT_MANAGER
    COMMENT = 'Routeur : delegue a DEV_ASSISTANT (objets) ou DEV_ASSISTANT_APP (Streamlit)'
    PROFILE = '{"display_name": "Dev Assistant Manager"}'
FROM SPECIFICATION $$
{
    "models": { "orchestration": "auto" },
    "instructions": {
        "response": "Tu es un chef d'orchestre. Tu ne produis jamais de code toi-même : tu délègues à un agent spécialisé et tu restitues son résultat tel quel, en précisant quel agent a été sollicité.",
        "orchestration": "Analyse la demande et route vers UN SEUL outil :\n- OBJETS (table, view, procedure, UDF, stream, task, dynamic table, modèle dbt, pipeline CI/CD, tests) → appelle ask_dev_assistant.\n- IHM (application, app, Streamlit, dashboard, interface, écran, page, formulaire, visualisation) → appelle ask_dev_assistant_app.\nTransmets la demande de l'utilisateur intégralement dans le paramètre prompt, sans la reformuler ni la tronquer. Si la demande couvre les deux, appelle d'abord ask_dev_assistant puis ask_dev_assistant_app. N'écris jamais de code toi-même."
    },
    "tools": [
        {
            "tool_spec": {
                "type": "generic",
                "name": "ask_dev_assistant",
                "description": "Délègue à l'agent spécialiste des objets Snowflake, dbt, CI/CD et tests. Pour toute création ou modification de table, view, procedure, UDF, stream, task, modèle dbt ou pipeline.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "prompt": { "type": "string", "description": "Demande complète de l'utilisateur, transmise telle quelle" }
                    },
                    "required": ["prompt"]
                }
            }
        },
        {
            "tool_spec": {
                "type": "generic",
                "name": "ask_dev_assistant_app",
                "description": "Délègue à l'agent spécialiste des interfaces Streamlit-in-Snowflake. Pour toute demande d'application, d'IHM, de dashboard ou d'écran.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "prompt": { "type": "string", "description": "Demande complète de l'utilisateur, transmise telle quelle" }
                    },
                    "required": ["prompt"]
                }
            }
        }
    ],
    "tool_resources": {
        "ask_dev_assistant": {
            "type": "procedure",
            "execution_environment": { "type": "warehouse", "warehouse": "COMPUTE_WH", "query_timeout": 300 },
            "identifier": "COCO_CHALLENGE_DB.DEV.SP_RUN_DEV_ASSISTANT"
        },
        "ask_dev_assistant_app": {
            "type": "procedure",
            "execution_environment": { "type": "warehouse", "warehouse": "COMPUTE_WH", "query_timeout": 300 },
            "identifier": "COCO_CHALLENGE_DB.DEV.SP_RUN_DEV_ASSISTANT_APP"
        }
    }
}
$$;

---------------------------------------proc call dev assistants
CREATE OR REPLACE PROCEDURE COCO_CHALLENGE_DB.DEV.SP_RUN_DEV_ASSISTANT(PROMPT VARCHAR)
RETURNS VARCHAR
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'main'
EXECUTE AS CALLER
AS
$$
import json

TARGET = 'COCO_CHALLENGE_DB.DEV.DEV_ASSISTANT'

def _summarize(resp):
    out = []
    for b in resp.get('content', []):
        t = b.get('type')
        if t == 'tool_result':
            tr = b['tool_result']
            payload = (tr.get('content') or [{}])[0].get('json', {})
            out.append(f"[{tr.get('name')} -> {tr.get('status')}] "
                       f"{payload.get('result') or payload.get('error') or ''}")
        elif t == 'text':
            out.append(b['text'])
    return "\n\n".join(out).strip()

def main(session, prompt):
    if not prompt or not prompt.strip():
        return "REFUS: prompt vide"
    body = json.dumps({"messages": [
        {"role": "user", "content": [{"type": "text", "text": prompt}]}
    ]})
    row = session.sql(
        "SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN(?, ?, TRUE) AS resp",
        params=[TARGET, body],
    ).collect()[0]
    return _summarize(json.loads(row['RESP'])) or "Aucune reponse exploitable"
$$;

---------------------------------------------------proc calls dev assistant app
CREATE STAGE IF NOT EXISTS COCO_CHALLENGE_DB.DEV.APPS_STAGE
    DIRECTORY = (ENABLE = TRUE)
    COMMENT = 'Code source des apps Streamlit generees par le Dev Assistant';

CREATE TABLE IF NOT EXISTS COCO_CHALLENGE_DB.DEV.APP_SOURCES (
    APP_NAME   VARCHAR(255) PRIMARY KEY,
    CONTENT    VARCHAR,
    APP_TITLE  VARCHAR(255),
    UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    UPDATED_BY VARCHAR(100)  DEFAULT CURRENT_USER()
)
COMMENT = 'Code source des apps Streamlit generees par le Dev Assistant';
------------------------Lecture code app EXistant 
CREATE OR REPLACE PROCEDURE COCO_CHALLENGE_DB.DEV.SP_READ_STREAMLIT(APP_NAME VARCHAR)
RETURNS VARCHAR
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'main'
EXECUTE AS OWNER
AS
$$
import re

IDENT = re.compile(r'^APP_[A-Za-z0-9_]{1,250}$')

def main(session, app_name):
    an = (app_name or '').strip().upper()
    if not IDENT.match(an):
        return f"REFUS: nom d'app invalide '{app_name}'"
    rows = session.sql(
        "SELECT CONTENT FROM COCO_CHALLENGE_DB.DEV.APP_SOURCES WHERE APP_NAME = ?",
        params=[an],
    ).collect()
    if not rows:
        return f"INEXISTANT: aucune app nommee {an}"
    return rows[0][0]
$$;

-----------------------------------------------safe Creation : eviter perte de code par ecraseement
CREATE OR REPLACE PROCEDURE COCO_CHALLENGE_DB.DEV.SP_CREATE_STREAMLIT(
    APP_NAME VARCHAR,
    MAIN_FILE_CONTENT VARCHAR,
    APP_TITLE VARCHAR,
    ALLOW_OVERWRITE BOOLEAN
)
RETURNS VARCHAR
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'main'
EXECUTE AS OWNER
AS
$$
import re

IDENT = re.compile(r'^APP_[A-Za-z0-9_]{1,250}$')
STAGE = '@COCO_CHALLENGE_DB.DEV.APPS_STAGE/apps'
MAX_BYTES = 1_000_000

def main(session, app_name, main_file_content, app_title, allow_overwrite):
    an = (app_name or '').strip().upper()
    if not IDENT.match(an):
        return f"REFUS: nom d'app invalide '{app_name}' (doit commencer par APP_)"
    if not main_file_content or not main_file_content.strip():
        return "REFUS: contenu vide"
    if len(main_file_content.encode('utf-8')) > MAX_BYTES:
        return "REFUS: contenu trop volumineux"

    existing = session.sql(
        "SELECT COUNT(*) FROM COCO_CHALLENGE_DB.DEV.APP_SOURCES WHERE APP_NAME = ?",
        params=[an],
    ).collect()[0][0]
    if existing and not allow_overwrite:
        return (f"REFUS: l'app {an} existe deja. Appelle read_streamlit pour "
                f"recuperer le code actuel, puis rappelle avec allow_overwrite=true.")

    title = app_title or an
    if existing:
        session.sql("""UPDATE COCO_CHALLENGE_DB.DEV.APP_SOURCES
                       SET CONTENT = ?, APP_TITLE = ?, UPDATED_AT = CURRENT_TIMESTAMP(),
                           UPDATED_BY = CURRENT_USER()
                       WHERE APP_NAME = ?""",
                    params=[main_file_content, title, an]).collect()
    else:
        session.sql("""INSERT INTO COCO_CHALLENGE_DB.DEV.APP_SOURCES
                       (APP_NAME, CONTENT, APP_TITLE) VALUES (?, ?, ?)""",
                    params=[an, main_file_content, title]).collect()

    # COPY INTO ecrit le fichier sur le stage : put_stream est inoperant ici.
    root = f"{STAGE}/{an}"
    session.sql(f"""
        COPY INTO {root}/app.py
        FROM (SELECT CONTENT FROM COCO_CHALLENGE_DB.DEV.APP_SOURCES WHERE APP_NAME = '{an}')
        FILE_FORMAT = (TYPE = CSV COMPRESSION = NONE
                       FIELD_DELIMITER = NONE RECORD_DELIMITER = NONE
                       FIELD_OPTIONALLY_ENCLOSED_BY = NONE
                       ESCAPE_UNENCLOSED_FIELD = NONE)
        SINGLE = TRUE
        OVERWRITE = TRUE
    """).collect()

    files = session.sql(f"LIST {root}/app.py").collect()
    if not files:
        return f"ERREUR: fichier non ecrit a {root}/app.py"

    safe_title = title.replace("'", "''")[:255]
    session.sql(f'''
        CREATE OR REPLACE STREAMLIT COCO_CHALLENGE_DB.DEV."{an}"
            ROOT_LOCATION = '{root}'
            MAIN_FILE = 'app.py'
            QUERY_WAREHOUSE = COMPUTE_WH
            TITLE = '{safe_title}'
    ''').collect()

    action = "mise a jour" if existing else "creee"
    return f"OK: app {an} {action}, fichier {files[0][0]} ({files[0][1]} octets)"
$$;

----------------------test 
CALL COCO_CHALLENGE_DB.DEV.SP_CREATE_STREAMLIT(
    'APP_TEST', 'import streamlit as st\nst.title("Test")\nst.write("v1")', 'App de test', FALSE
);

LS @COCO_CHALLENGE_DB.DEV.APPS_STAGE/apps/APP_TEST/;   -- doit lister app.py
CALL COCO_CHALLENGE_DB.DEV.SP_READ_STREAMLIT('APP_TEST');

-- doit REFUSER
CALL COCO_CHALLENGE_DB.DEV.SP_CREATE_STREAMLIT(
    'APP_TEST', 'import streamlit as st\nst.write("v2")', 'App de test', FALSE
);

-- doit passer
CALL COCO_CHALLENGE_DB.DEV.SP_CREATE_STREAMLIT(
    'APP_TEST', 'import streamlit as st\nst.title("Test")\nst.write("v2")', 'App de test', TRUE
);

SELECT APP_NAME, LENGTH(CONTENT) AS taille, UPDATED_AT
FROM COCO_CHALLENGE_DB.DEV.APP_SOURCES;

LS @COCO_CHALLENGE_DB.DEV.APPS_STAGE/apps/;
LS @COCO_CHALLENGE_DB.DEV.APPS_STAGE/apps/APP_TEST/;
SHOW STREAMLITS IN SCHEMA COCO_CHALLENGE_DB.DEV;

SHOW STREAMLITS IN SCHEMA COCO_CHALLENGE_DB.DEV;
SELECT "name", "title", "query_warehouse", "url_id"
FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))
WHERE "name" = 'APP_TEST';
--------------------------------------------------------------agent app
CREATE OR REPLACE AGENT COCO_CHALLENGE_DB.DEV.DEV_ASSISTANT_APP
    COMMENT = 'Specialiste IHM Streamlit-in-Snowflake (creation et modification)'
    PROFILE = '{"display_name": "Dev Assistant - Apps"}'
FROM SPECIFICATION $$
{
    "models": { "orchestration": "auto" },
    "instructions": {
        "response": "Tu es un expert Streamlit-in-Snowflake. Applique strictement les patterns du skill dev-ihm. Indique toujours si tu as créé une nouvelle app ou modifié une app existante.",
        "orchestration": "Charge d'abord le skill dev-ihm.\n\nCRÉATION : si l'app n'existe pas, appelle create_streamlit avec allow_overwrite=false. app_name doit commencer par APP_. main_file_content contient le code Python COMPLET de app.py.\n\nMODIFICATION : si l'utilisateur demande de modifier, ajouter, corriger, enrichir ou supprimer quelque chose dans une app existante, appelle D'ABORD read_streamlit pour récupérer le code actuel. Applique la modification sur CE code en conservant tout le reste à l'identique. Puis appelle create_streamlit avec le fichier COMPLET résultant et allow_overwrite=true. N'appelle JAMAIS create_streamlit sans read_streamlit préalable sur une app existante : tu perdrais tout le code non redécrit.\n\nSi read_streamlit répond INEXISTANT, traite la demande comme une création.\n\nSi create_streamlit répond REFUS parce que l'app existe, appelle read_streamlit puis recommence avec allow_overwrite=true."
    },
    "tools": [
        {
            "tool_spec": {
                "type": "generic",
                "name": "read_streamlit",
                "description": "Retourne le code source actuel de app.py d'une application Streamlit existante. À appeler OBLIGATOIREMENT avant toute modification d'une app existante.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "app_name": { "type": "string", "description": "Nom de l'app, ex: APP_SUIVI" }
                    },
                    "required": ["app_name"]
                }
            }
        },
        {
            "tool_spec": {
                "type": "generic",
                "name": "create_streamlit",
                "description": "Crée ou met à jour une application Streamlit-in-Snowflake dans COCO_CHALLENGE_DB.DEV. Écrit le fichier app.py complet et déploie l'objet STREAMLIT.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "app_name":          { "type": "string",  "description": "Nom de l'app, doit commencer par APP_" },
                        "main_file_content": { "type": "string",  "description": "Code Python COMPLET du fichier app.py, pas un extrait" },
                        "app_title":         { "type": "string",  "description": "Titre affiché de l'application" },
                        "allow_overwrite":   { "type": "boolean", "description": "true uniquement si l'app existe déjà et que son code a été lu via read_streamlit" }
                    },
                    "required": ["app_name", "main_file_content"]
                }
            }
        }
    ],
    "tool_resources": {
        "read_streamlit": {
            "type": "procedure",
            "execution_environment": { "type": "warehouse", "warehouse": "COMPUTE_WH", "query_timeout": 60 },
            "identifier": "COCO_CHALLENGE_DB.DEV.SP_READ_STREAMLIT"
        },
        "create_streamlit": {
            "type": "procedure",
            "execution_environment": { "type": "warehouse", "warehouse": "COMPUTE_WH", "query_timeout": 120 },
            "identifier": "COCO_CHALLENGE_DB.DEV.SP_CREATE_STREAMLIT"
        }
    },
    "skills": [
        { "name": "dev-ihm", "source": { "type": "STAGE", "path": "@COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/dev-ihm" } }
    ]
}
$$;

-- doit router vers ask_dev_assistant
CALL COCO_CHALLENGE_DB.DEV.SP_RUN_DEV_ASSISTANT('Crée une table DIM_CLIENT avec code, nom, pays');
CALL COCO_CHALLENGE_DB.DEV.SP_RUN_DEV_ASSISTANT_APP('Crée l''app APP_SUIVI qui liste les tables du schema DEV');

-- 1. creation
SELECT TRY_PARSE_JSON(SNOWFLAKE.CORTEX.DATA_AGENT_RUN(
    'COCO_CHALLENGE_DB.DEV.DEV_ASSISTANT_APP',
    $${"messages":[{"role":"user","content":[{"type":"text","text":"Crée l'app APP_SUIVI qui liste les tables du schema DEV"}]}]}$$,
    TRUE)) AS response;

-- 2. modification : doit declencher read_streamlit PUIS create_streamlit
WITH run AS (
    SELECT TRY_PARSE_JSON(SNOWFLAKE.CORTEX.DATA_AGENT_RUN(
        'COCO_CHALLENGE_DB.DEV.DEV_ASSISTANT_APP',
        $${"messages":[{"role":"user","content":[{"type":"text","text":" l'appmodifie le code de l'app DEV_ASSISTANT pour qu'il appelle l'agent DEV_ASSIATANT_MANAGER et non plus l'Agent DEV_ASSISTANT"}]}]}$$,
        TRUE)) AS resp
)
SELECT f.value:tool_use:name::VARCHAR      AS outil,
       f.value:tool_result:status::VARCHAR AS statut
FROM run, LATERAL FLATTEN(input => run.resp:content) f
WHERE f.value:type::VARCHAR IN ('tool_use','tool_result');
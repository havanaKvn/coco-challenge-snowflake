-- ============================================================
-- SCRIPT DE DEPLOIEMENT : Dev Assistant (Stage + Skills + Agent)
-- Database : COCO_CHALLENGE_DB
-- Schema   : DEV
-- Warehouse: COMPUT_WHAREHOUSE
-- ============================================================

-- ============================================================
-- STEP 1 : Créer le schema (si inexistant)
-- ============================================================
USE WAREHOUSE COMPUT_WHAREHOUSE;

CREATE SCHEMA IF NOT EXISTS COCO_CHALLENGE_DB.DEV;

USE SCHEMA COCO_CHALLENGE_DB.DEV;

-- ============================================================
-- STEP 2 : Créer le stage pour stocker les skills
-- ============================================================
CREATE STAGE IF NOT EXISTS COCO_CHALLENGE_DB.DEV.SKILLS_STAGE
    COMMENT = 'Stage contenant les skills du Dev Assistant (SKILL.md files)';

-- ============================================================
-- STEP 3 : Uploader les fichiers SKILL.md sur le stage
-- ============================================================
-- Exécuter ces commandes depuis SnowSQL ou snow CLI
-- Adapter le chemin local selon votre machine

-- Option A : Depuis SnowSQL (PUT est une commande cliente : ne fonctionne pas dans Snowsight)
-- Le chemin contient des espaces => l'URI entière doit être entre quotes simples.
/*
PUT 'file://C:/Users/k.rakotohavana/OneDrive - ONEPOINT/Bureau/Elis/Task/.cortex/skills/dev-objects/SKILL.md'
    @COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/dev-objects/
    AUTO_COMPRESS = FALSE OVERWRITE = TRUE;

PUT 'file://C:/Users/k.rakotohavana/OneDrive - ONEPOINT/Bureau/Elis/Task/.cortex/skills/dev-ihm/SKILL.md'
    @COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/dev-ihm/
    AUTO_COMPRESS = FALSE OVERWRITE = TRUE;

PUT 'file://C:/Users/k.rakotohavana/OneDrive - ONEPOINT/Bureau/Elis/Task/.cortex/skills/dev-cicd/SKILL.md'
    @COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/dev-cicd/
    AUTO_COMPRESS = FALSE OVERWRITE = TRUE;

PUT 'file://C:/Users/k.rakotohavana/OneDrive - ONEPOINT/Bureau/Elis/Task/.cortex/skills/dev-tests/SKILL.md'
    @COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/dev-tests/
    AUTO_COMPRESS = FALSE OVERWRITE = TRUE;
*/

-- Option B : Depuis snow CLI (recommandé)
-- snow stage copy .cortex/skills/dev-objects/SKILL.md @COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/dev-objects/ --overwrite
-- snow stage copy .cortex/skills/dev-ihm/SKILL.md @COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/dev-ihm/ --overwrite
-- snow stage copy .cortex/skills/dev-cicd/SKILL.md @COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/dev-cicd/ --overwrite
-- snow stage copy .cortex/skills/dev-tests/SKILL.md @COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/dev-tests/ --overwrite

-- Vérifier les fichiers uploadés :
-- LS @COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/;

-- ============================================================
-- STEP 4 : Créer le Cortex Agent avec les 4 skills
-- ============================================================

CREATE OR REPLACE AGENT COCO_CHALLENGE_DB.DEV.DEV_ASSISTANT
    COMMENT = 'Assistant developpeur Snowflake / dbt / Snowpark / CI-CD'
    PROFILE = '{"display_name": "Dev Assistant"}'
FROM SPECIFICATION $$
    {
        "models": {
            "orchestration": "claude-4-sonnet"
        },
        "instructions": {
            "response": "Tu es un assistant développeur expert en Snowflake, dbt, Python/Snowpark et GitHub Actions. Tu aides les développeurs (applicatifs et data engineers) à créer des objets, des interfaces, des pipelines CI/CD et des tests. Applique toujours les conventions de nommage et bonnes pratiques définies dans tes skills. Génère du code prêt à exécuter."
        },
        "skills": [
            {
                "name": "dev-objects",
                "source": {
                    "type": "STAGE",
                    "path": "@COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/dev-objects"
                }
            },
            {
                "name": "dev-ihm",
                "source": {
                    "type": "STAGE",
                    "path": "@COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/dev-ihm"
                }
            },
            {
                "name": "dev-cicd",
                "source": {
                    "type": "STAGE",
                    "path": "@COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/dev-cicd"
                }
            },
            {
                "name": "dev-tests",
                "source": {
                    "type": "STAGE",
                    "path": "@COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/dev-tests"
                }
            }
        ]
    }
    $$;

-- ============================================================
-- STEP 5 : Vérifications
-- ============================================================

-- Vérifier que le stage contient les skills
LS @COCO_CHALLENGE_DB.DEV.SKILLS_STAGE/skills/;

-- Vérifier que l'agent est créé
DESCRIBE AGENT COCO_CHALLENGE_DB.DEV.DEV_ASSISTANT;

-- Tester l'agent avec un prompt simple
SELECT COCO_CHALLENGE_DB.DEV.DEV_ASSISTANT!RUN('Crée une table DIM_SITE avec code, label, region')::VARCHAR AS response;



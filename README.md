# Assistant IA eStage MEF — Prototype de démonstration

Prototype autonome démontrant ce qu'un assistant IA pourrait apporter à la
plateforme eStage du Ministère de l'Économie et des Finances (MEF) du Bénin :
orientation d'un demandeur de stage vers les structures pertinentes du
ministère, à partir de son profil, avec des explications transparentes.

**Ce que ce prototype N'EST PAS** : une intégration réelle à eStage, un
système de candidature fonctionnel, ni une source d'information
administrative officielle. Voir la section « Statut des données » ci-dessous.

---

## Installation

Prérequis : Python 3.10+ installé.

```bash
# 1. Cloner / copier le dossier du projet, puis :
cd estage-mef-ia/backend
python -m venv venv

# Windows :
venv\Scripts\activate
# macOS/Linux :
source venv/bin/activate

pip install -r requirements.txt

# 2. Configuration (optionnelle — fonctionne sans)
cp ../.env.example .env
# éditer .env si vous voulez activer un LLM (voir plus bas)

# 3. Lancer le backend
uvicorn main:app --reload --port 8000
```

Puis, dans un second terminal, ouvrir le frontend :

```bash
cd estage-mef-ia/frontend
python -m http.server 5500
```

Ouvrir ensuite **http://localhost:5500** dans le navigateur.

---

## Activer un LLM (optionnel)

Par défaut, l'assistant fonctionne **entièrement en local**, sans aucune clé
API : il utilise des réponses gabarit combinées au moteur de recommandation
par mots-clés. C'est volontaire — le prototype doit pouvoir tourner sans
dépendance payante.

### Cascade de génération (NVIDIA → LLM secondaire → gabarit local)

La génération de réponse suit une cascade à 3 niveaux, entièrement
automatique et invisible pour l'utilisateur — il n'y a **aucun sélecteur de
mode** dans l'interface :

```
Question → contexte RAG → NVIDIA (priorité #1)
                              │
                    échec technique ?
                    ┌─────────┴─────────┐
                   non                 oui
                    │                   │
             réponse NVIDIA      LLM secondaire (ex. Groq)
                                        │
                              échec technique ?
                              ┌─────────┴─────────┐
                             non                 oui
                              │                   │
                       réponse LLM         réponse gabarit locale
```

Le basculement d'un niveau à l'autre n'est déclenché **que par une erreur
technique** (clé absente/invalide, timeout, erreur réseau, erreur serveur,
réponse vide) — jamais parce qu'un modèle répond honnêtement qu'il ne sait
pas. Aucun message d'erreur technique n'est jamais montré à l'utilisateur ;
tout est journalisé côté serveur (voir les logs `uvicorn`).

**Configurer NVIDIA (fournisseur principal)** — compte NVIDIA Build requis
(https://build.nvidia.com) :

```
NVIDIA_API_KEY=votre_clé
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_MODEL=deepseek-v4.1-flash
NVIDIA_TIMEOUT_SECONDS=12
```

Modèles NVIDIA testés/compatibles : `deepseek-v4.1-flash`, `glm-5-3`,
`glm-5-3-flash`, `kimi-k3` — changez simplement `NVIDIA_MODEL`.

**Configurer un fallback secondaire (optionnel)** — par exemple **Groq**
(https://console.groq.com, quota gratuit généreux) :

```
LLM_API_KEY=votre_clé
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=llama-3.1-8b-instant
```

Si aucune des deux clés n'est renseignée, le prototype continue de
fonctionner via les réponses gabarit locales — rien ne casse.

**Sécurité** : `NVIDIA_API_KEY` (comme `LLM_API_KEY`) ne vit que côté
backend, lue depuis `.env` (jamais commité — voir `.gitignore`), jamais
transmise au frontend ni renvoyée dans les réponses de l'API.

Le fichier `.env` se charge automatiquement au démarrage du backend (via
`python-dotenv`) — inutile de l'exporter manuellement dans le terminal.

---

## Architecture

```
frontend/          Interface chat statique (HTML/CSS/JS, sans build)
backend/
  main.py          API FastAPI : recommandation + chat
  data/
    structures.json  Base de connaissances des structures du MEF
    faq.json          FAQ de démonstration
```

Choix volontaire : le frontend est en HTML/CSS/JS pur plutôt qu'en
Next.js/React, pour éliminer toute dépendance Node.js et simplifier le
lancement sur un poste Windows personnel, conformément à la priorité du
cahier des charges : *utilité réelle et simplicité > complexité technique*.
Il peut être migré vers React/Next.js sans changer l'API backend, qui est
déjà découplée.

Le moteur de recommandation est un scoring par recouvrement de mots-clés
(transparent, explicable, sans boîte noire) — pas un modèle de machine
learning entraîné, ce qui serait disproportionné pour un prototype de
démonstration et rendrait les explications moins fiables.

---

## Statut des données — À LIRE AVANT TOUTE DÉMONSTRATION

Conformément à la règle « ne jamais inventer une information
administrative », chaque structure dans `data/structures.json` porte un
champ `source_status` et `niveau_confiance` :

| Structure | Statut | Confiance |
|---|---|---|
| Ministère (MEF) | Décret-cadre identifié (n° 2021-307), contenu détaillé à vérifier | Moyen |
| Direction Générale des Douanes | Décret n° 2021-455 consulté directement | **Élevé** |
| DGTCP (Trésor) | Existence confirmée, décret propre non localisé | Moyen |
| DSI-MEF | Déduite d'un arrêté-cadre interministériel, non spécifique au MEF | Faible |
| DGB, INStaD | **DEMO_DATA** — placeholders non vérifiés | Aucun |

Les structures marquées `"demo_data": true` sont signalées comme telles
dans l'interface (badge « Donnée de démonstration »). **Ne pas présenter ces
entrées comme des faits vérifiés devant un public officiel.**

Le registre complet des sources consultées (décrets, textes, liens) se
trouve dans `estage-mef-ia-sources-phase1.md` (document séparé).

### Prochaines étapes pour enrichir la base

1. Récupérer le texte intégral du décret n° 2021-307 (structure actuelle du MEF)
2. Rechercher les décrets propres à la DGB, la DGID, l'IGF, la DSI-MEF (même
   méthode que pour les Douanes : chercher "décret attributions organisation
   fonctionnement Direction Générale [X] Bénin" sur sgg.gouv.bj)
3. Réessayer `finances.bj` (suspendu au moment de cette recherche) — le
   site officiel du ministère documenterait probablement lui-même ses
   structures de façon bien plus riche
4. Remplacer les entrées `demo_data` par des données vérifiées au fur et à
   mesure, ou les retirer si aucune source fiable n'est trouvée

---

## Fonctionnalités livrées dans ce prototype

- [x] Interface de chat professionnelle avec actions rapides
- [x] Base de connaissances structurée (structures + FAQ + procédures) avec traçabilité des sources
- [x] Moteur de recommandation par mots-clés, avec explication du score et du service précis à viser
- [x] Cascade de génération NVIDIA → LLM secondaire → gabarit local, entièrement automatique et invisible pour l'utilisateur
- [x] Distinction claire données vérifiées / DEMO_DATA
- [ ] Mode « Guide-moi » conversationnel multi-étapes (non développé — prochaine itération)
- [ ] Analyse de CV (non développée — prochaine itération)
- [ ] Page « Explorer le MEF » dédiée (les données existent déjà via `/api/structures`, l'UI reste à faire)
- [ ] Intégration réelle à l'API eStage (hors de portée d'un prototype autonome)

## Scénarios testables dès maintenant

1. **Orientation** : « Je suis étudiant en informatique spécialisé en IA, où puis-je faire mon stage au MEF ? »
2. **Structure précise** : cliquer sur « Explorer le MEF » puis interroger sur une structure nommée
3. **Procédure** : « Comment faire une demande de stage au MEF ? »
4. **Documents** : « Quels documents dois-je fournir ? »

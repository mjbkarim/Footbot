# ⚽ FootBot — Système d'inscription aux matchs

Un système simple pour gérer les inscriptions aux matchs de foot via WhatsApp + page web.

---

## 🚀 Déploiement sur Render (gratuit)

### Étape 1 — Mettre le code sur GitHub

1. Va sur [github.com](https://github.com) et crée un compte gratuit
2. Crée un nouveau repository : **"footbot"**
3. Upload tous les fichiers de ce dossier dedans

### Étape 2 — Déployer sur Render

1. Va sur [render.com](https://render.com) et connecte-toi avec GitHub
2. Clique sur **"New Web Service"**
3. Sélectionne ton repo **footbot**
4. Configure :
   - **Environment** : `Python`
   - **Build Command** : `pip install -r requirements.txt`
   - **Start Command** : `gunicorn app:app --bind 0.0.0.0:$PORT`
5. Clique **Deploy** — c'est tout !

Render te donne une URL du type : `https://footbot-xxxx.onrender.com`

---

## 📲 Comment utiliser

### Toi (l'organisateur)

1. Va sur `https://ton-url.onrender.com/admin`
2. Sélectionne le jour (Lundi/Jeudi) et la date
3. Clique **"Ouvrir les inscriptions"**
4. Copie le lien et envoie-le dans WhatsApp :

```
⚽ MATCH LUNDI 20H
Inscris-toi ici : https://ton-url.onrender.com
Les 14 premiers sont sélectionnés !
```

5. Le matin du match → clique **"Passer en confirmation"** et renvoie le lien
6. Après le match → clique **"Clôturer"**

### Les joueurs

1. Cliquent sur le lien dans WhatsApp
2. Tapent leur prénom
3. Appuient sur ✅ IN ou ❌ Se désister
4. Voient leur position en temps réel

---

## ⚙️ Logique automatique

- ✅ Les 14 premiers inscrits sont sélectionnés
- ⏳ Les suivants vont en liste d'attente
- ❌ Si quelqu'un se désiste → le premier en attente monte
- 🔄 La liste se met à jour en temps réel

---

## 📁 Structure des fichiers

```
footbot/
├── app.py              # Serveur Flask (logique principale)
├── requirements.txt    # Dépendances Python
├── Procfile           # Config Render
├── data.json          # Données (créé automatiquement)
└── templates/
    ├── index.html     # Page joueurs
    └── admin.html     # Page admin
```

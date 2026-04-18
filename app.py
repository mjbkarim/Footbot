from flask import Flask, render_template, request, jsonify, session, redirect
from flask_cors import CORS
from datetime import datetime
import json, os, pytz, hashlib

app = Flask(__name__, template_folder=os.path.dirname(os.path.abspath(__file__)))
app.secret_key = os.environ.get("SECRET_KEY", "footbot-secret-2024")
CORS(app)

TIMEZONE = pytz.timezone("Europe/Bucharest")
MAX_PLAYERS = 14
DATA_FILE = "data.json"
PLAYERS_FILE = "players.json"
DEADLINE_CONFIRM = 17  # 17h00
DEADLINE_CANCEL = 19   # 19h00
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin1234")

def now():
    return datetime.now(TIMEZONE)

def hash_pin(pin):
    return hashlib.sha256(pin.encode()).hexdigest()

# ─── Données joueurs ──────────────────────────────────────────────
def load_players():
    if not os.path.exists(PLAYERS_FILE):
        return {}
    with open(PLAYERS_FILE, "r") as f:
        return json.load(f)

def save_players(players):
    with open(PLAYERS_FILE, "w") as f:
        json.dump(players, f, indent=2, ensure_ascii=False)

# ─── Données match ────────────────────────────────────────────────
def load_data():
    if not os.path.exists(DATA_FILE):
        return default_data()
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def default_data():
    return {"match": {
        "active": False, "day": "", "date": "",
        "phase": "closed", "cancelled": False,
        "registrations": []
    }}

def get_selected(regs):
    return [r for r in regs if r["status"] not in ("out", "no_response")][:MAX_PLAYERS]

def get_waiting(regs):
    return [r for r in regs if r["status"] not in ("out", "no_response")][MAX_PLAYERS:]

def check_deadlines(data):
    match = data["match"]
    if match["phase"] != "confirmation" or match.get("cancelled"):
        return False

    changed = False
    h = now().hour

    # 17h : remplacer les non-répondants
    if h >= DEADLINE_CONFIRM:
        for reg in match["registrations"]:
            if reg["status"] == "in":  # pas encore confirmé
                reg["status"] = "no_response"
                changed = True

    # 19h : annuler si liste incomplète
    if h >= DEADLINE_CANCEL:
        selected = get_selected(match["registrations"])
        if len(selected) < MAX_PLAYERS:
            match["cancelled"] = True
            match["phase"] = "done"
            changed = True

    if changed:
        save_data(data)
    return changed

# ─── Routes joueurs ───────────────────────────────────────────────

@app.route("/")
def index():
    data = load_data()
    check_deadlines(data)
    match = data["match"]
    players = load_players()
    selected = get_selected(match["registrations"])
    waiting = get_waiting(match["registrations"])
    username = session.get("username")
    # Trouver la registration du joueur connecté
    my_reg = None
    if username:
        my_reg = next((r for r in match["registrations"] if r["username"] == username), None)
    return render_template("index.html",
        match=match, selected=selected, waiting=waiting,
        max_players=MAX_PLAYERS, now=now(),
        deadline_confirm=DEADLINE_CONFIRM,
        username=username,
        display_name=players.get(username, {}).get("name", "") if username else "",
        my_reg=my_reg
    )

@app.route("/signup", methods=["POST"])
def signup():
    players = load_players()
    username = request.json.get("username", "").strip().lower()
    name = request.json.get("name", "").strip().capitalize()
    pin = request.json.get("pin", "").strip()

    if not username or len(username) < 3:
        return jsonify({"ok": False, "msg": "Username trop court (min 3 caractères)."})
    if not name or len(name) < 2:
        return jsonify({"ok": False, "msg": "Prénom invalide."})
    if not pin or len(pin) != 4 or not pin.isdigit():
        return jsonify({"ok": False, "msg": "Code PIN doit faire 4 chiffres."})
    if username in players:
        return jsonify({"ok": False, "msg": f"Le username '{username}' est déjà pris."})

    players[username] = {"name": name, "pin": hash_pin(pin), "joined": now().strftime("%d/%m/%Y")}
    save_players(players)
    session["username"] = username
    return jsonify({"ok": True, "msg": f"✅ Compte créé ! Bienvenue {name} !", "name": name})

@app.route("/login", methods=["POST"])
def login():
    players = load_players()
    username = request.json.get("username", "").strip().lower()
    pin = request.json.get("pin", "").strip()

    if username not in players:
        return jsonify({"ok": False, "msg": "Username introuvable."})
    if players[username]["pin"] != hash_pin(pin):
        return jsonify({"ok": False, "msg": "Code PIN incorrect."})

    session["username"] = username
    return jsonify({"ok": True, "msg": f"Bienvenue {players[username]['name']} !", "name": players[username]['name']})

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})

@app.route("/register", methods=["POST"])
def register():
    username = session.get("username")
    if not username:
        return jsonify({"ok": False, "msg": "Connecte-toi d'abord."})

    data = load_data()
    check_deadlines(data)
    match = data["match"]
    players = load_players()

    if match.get("cancelled"):
        return jsonify({"ok": False, "msg": "❌ Match annulé."})
    if match["phase"] not in ("registration", "confirmation"):
        return jsonify({"ok": False, "msg": "Les inscriptions sont fermées."})

    existing = next((r for r in match["registrations"] if r["username"] == username), None)
    if existing:
        if existing["status"] in ("out", "no_response"):
            return jsonify({"ok": False, "msg": "Tu t'es désisté. Contacte l'organisateur."})
        active = [r for r in match["registrations"] if r["status"] not in ("out","no_response")]
        pos = active.index(existing) + 1
        if pos <= MAX_PLAYERS:
            return jsonify({"ok": True, "msg": f"Tu es déjà inscrit ! N°{pos}/14.", "status": "selected"})
        else:
            return jsonify({"ok": True, "msg": f"Tu es déjà en attente (n°{pos-MAX_PLAYERS}).", "status": "waiting"})

    reg = {"username": username, "name": players[username]["name"],
           "time": now().strftime("%H:%M:%S"), "status": "in"}
    match["registrations"].append(reg)
    save_data(data)

    active = [r for r in match["registrations"] if r["status"] not in ("out","no_response")]
    pos = active.index(reg) + 1

    if pos <= MAX_PLAYERS:
        return jsonify({"ok": True, "msg": f"✅ Inscrit ! Tu es n°{pos}/14.", "status": "selected"})
    else:
        return jsonify({"ok": True, "msg": f"⏳ Liste d'attente n°{pos-MAX_PLAYERS}.", "status": "waiting"})

@app.route("/confirm", methods=["POST"])
def confirm():
    username = session.get("username")
    if not username:
        return jsonify({"ok": False, "msg": "Connecte-toi d'abord."})

    data = load_data()
    match = data["match"]
    if match["phase"] != "confirmation":
        return jsonify({"ok": False, "msg": "Pas en phase de confirmation."})

    reg = next((r for r in match["registrations"] if r["username"] == username), None)
    if not reg:
        return jsonify({"ok": False, "msg": "Tu n'es pas dans la liste."})

    reg["status"] = "confirmed"
    save_data(data)
    return jsonify({"ok": True, "msg": "✅ Présence confirmée ! À ce soir ⚽"})

@app.route("/dropout", methods=["POST"])
def dropout():
    username = session.get("username")
    if not username:
        return jsonify({"ok": False, "msg": "Connecte-toi d'abord."})

    data = load_data()
    check_deadlines(data)
    match = data["match"]

    if match["phase"] not in ("registration", "confirmation"):
        return jsonify({"ok": False, "msg": "Les inscriptions sont fermées."})

    reg = next((r for r in match["registrations"] if r["username"] == username), None)
    if not reg:
        return jsonify({"ok": False, "msg": "Tu n'es pas dans la liste."})
    if reg["status"] in ("out", "no_response"):
        return jsonify({"ok": False, "msg": "Tu es déjà retiré."})

    reg["status"] = "out"
    save_data(data)

    active = [r for r in match["registrations"] if r["status"] not in ("out","no_response")]
    replacement = active[MAX_PLAYERS-1] if len(active) >= MAX_PLAYERS else None
    msg = f"❌ Tu as été retiré de la liste."
    if replacement:
        msg += f" {replacement['name']} monte depuis la liste d'attente !"
    return jsonify({"ok": True, "msg": msg})

@app.route("/list")
def list_view():
    data = load_data()
    check_deadlines(data)
    match = data["match"]
    def clean(r):
        return {"name": r["name"], "time": r["time"], "status": r["status"]}
    return jsonify({
        "phase": match["phase"], "cancelled": match.get("cancelled", False),
        "day": match["day"], "date": match["date"],
        "selected": [clean(r) for r in get_selected(match["registrations"])],
        "waiting": [clean(r) for r in get_waiting(match["registrations"])],
    })

# ─── Admin ────────────────────────────────────────────────────────

def admin_logged():
    return session.get("admin") is True

@app.route("/admin")
def admin():
    if not admin_logged():
        return redirect("/admin/login")
    data = load_data()
    match = data["match"]
    players = load_players()
    return render_template("admin.html",
        match=match,
        selected=get_selected(match["registrations"]),
        waiting=get_waiting(match["registrations"]),
        players=players,
        max_players=MAX_PLAYERS,
        now=now().strftime("%d/%m %H:%M")
    )

@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if request.method == "POST":
        pwd = request.json.get("password","")
        if pwd == ADMIN_PASSWORD:
            session["admin"] = True
            return jsonify({"ok": True})
        return jsonify({"ok": False, "msg": "Mot de passe incorrect."})
    return render_template("admin_login.html")

@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("admin", None)
    return jsonify({"ok": True})

@app.route("/admin/open", methods=["POST"])
def admin_open():
    if not admin_logged(): return jsonify({"ok": False, "msg": "Non autorisé."})
    data = load_data()
    day = request.json.get("day", "Lundi")
    date = request.json.get("date", "")
    data["match"] = {"active": True, "day": day, "date": date,
                     "phase": "registration", "cancelled": False, "registrations": []}
    save_data(data)
    return jsonify({"ok": True, "msg": f"Inscriptions ouvertes — {day} {date}"})

@app.route("/admin/confirm", methods=["POST"])
def admin_confirm():
    if not admin_logged(): return jsonify({"ok": False, "msg": "Non autorisé."})
    data = load_data()
    data["match"]["phase"] = "confirmation"
    save_data(data)
    return jsonify({"ok": True, "msg": "Phase de confirmation activée"})

@app.route("/admin/close", methods=["POST"])
def admin_close():
    if not admin_logged(): return jsonify({"ok": False, "msg": "Non autorisé."})
    data = load_data()
    data["match"]["phase"] = "done"
    data["match"]["active"] = False
    save_data(data)
    return jsonify({"ok": True, "msg": "Match clôturé"})

@app.route("/admin/remove_player", methods=["POST"])
def admin_remove_player():
    if not admin_logged(): return jsonify({"ok": False, "msg": "Non autorisé."})
    data = load_data()
    username = request.json.get("username","")
    reg = next((r for r in data["match"]["registrations"] if r["username"] == username), None)
    if not reg:
        return jsonify({"ok": False, "msg": "Joueur introuvable."})
    reg["status"] = "out"
    save_data(data)
    active = [r for r in data["match"]["registrations"] if r["status"] not in ("out","no_response")]
    replacement = active[MAX_PLAYERS-1] if len(active) >= MAX_PLAYERS else None
    msg = f"{reg['name']} retiré."
    if replacement:
        msg += f" {replacement['name']} monte !"
    return jsonify({"ok": True, "msg": msg})

@app.route("/admin/reset_pin", methods=["POST"])
def admin_reset_pin():
    if not admin_logged(): return jsonify({"ok": False, "msg": "Non autorisé."})
    players = load_players()
    username = request.json.get("username","")
    new_pin = request.json.get("pin","")
    if username not in players:
        return jsonify({"ok": False, "msg": "Joueur introuvable."})
    if not new_pin or len(new_pin) != 4 or not new_pin.isdigit():
        return jsonify({"ok": False, "msg": "PIN invalide."})
    players[username]["pin"] = hash_pin(new_pin)
    save_players(players)
    return jsonify({"ok": True, "msg": f"PIN de {players[username]['name']} réinitialisé."})

@app.route("/admin/delete_account", methods=["POST"])
def admin_delete_account():
    if not admin_logged(): return jsonify({"ok": False, "msg": "Non autorisé."})
    players = load_players()
    username = request.json.get("username","")
    if username not in players:
        return jsonify({"ok": False, "msg": "Joueur introuvable."})
    name = players[username]["name"]
    del players[username]
    save_players(players)
    return jsonify({"ok": True, "msg": f"Compte de {name} supprimé."})

@app.route("/admin/reset", methods=["POST"])
def admin_reset():
    if not admin_logged(): return jsonify({"ok": False, "msg": "Non autorisé."})
    save_data(default_data())
    return jsonify({"ok": True, "msg": "Match réinitialisé."})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

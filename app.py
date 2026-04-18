from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from datetime import datetime
import json
import os
import pytz

app = Flask(__name__, template_folder=os.path.dirname(os.path.abspath(__file__)))
CORS(app)

TIMEZONE = pytz.timezone("Europe/Bucharest")
MAX_PLAYERS = 14
DATA_FILE = "data.json"
DEADLINE_HOUR = 19  # 19h = heure limite

def now():
    return datetime.now(TIMEZONE)

def load_data():
    if not os.path.exists(DATA_FILE):
        return default_data()
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def default_data():
    return {
        "match": {
            "active": False,
            "day": "",
            "date": "",
            "phase": "closed",
            "cancelled": False,
            "registrations": [],
        }
    }

def get_selected(registrations):
    return [r for r in registrations if r["status"] != "out"][:MAX_PLAYERS]

def get_waiting(registrations):
    return [r for r in registrations if r["status"] != "out"][MAX_PLAYERS:]

def check_cancellation(data):
    """Annule le match si < 14 joueurs à 19h le jour du match."""
    match = data["match"]
    if match["phase"] != "confirmation":
        return
    if match.get("cancelled"):
        return
    current = now()
    if current.hour >= DEADLINE_HOUR:
        selected = get_selected(match["registrations"])
        if len(selected) < MAX_PLAYERS:
            match["cancelled"] = True
            match["phase"] = "done"
            save_data(data)

# ─── Routes principales ───────────────────────────────────────────

@app.route("/")
def index():
    data = load_data()
    check_cancellation(data)
    match = data["match"]
    selected = get_selected(match["registrations"])
    waiting = get_waiting(match["registrations"])
    return render_template("index.html",
        match=match,
        selected=selected,
        waiting=waiting,
        max_players=MAX_PLAYERS,
        now=now().strftime("%H:%M")
    )

@app.route("/register", methods=["POST"])
def register():
    data = load_data()
    check_cancellation(data)
    match = data["match"]

    if match.get("cancelled"):
        return jsonify({"ok": False, "msg": "❌ Match annulé — liste incomplète à 19h."})

    if match["phase"] not in ("registration", "confirmation"):
        return jsonify({"ok": False, "msg": "Les inscriptions sont fermées."})

    name = request.json.get("name", "").strip()
    pin = request.json.get("pin", "").strip()

    if not name or len(name) < 2:
        return jsonify({"ok": False, "msg": "Prénom invalide."})

    if not pin or len(pin) != 4 or not pin.isdigit():
        return jsonify({"ok": False, "msg": "Entre un code à 4 chiffres."})

    name = name.capitalize()

    existing = next((r for r in match["registrations"] if r["name"].lower() == name.lower()), None)
    if existing:
        if existing["status"] == "out":
            return jsonify({"ok": False, "msg": f"{name}, tu t'es désisté. Contacte l'organisateur."})
        active = [r for r in match["registrations"] if r["status"] != "out"]
        position = active.index(existing) + 1
        if position <= MAX_PLAYERS:
            return jsonify({"ok": True, "already": True, "msg": f"{name}, tu es déjà inscrit ! Tu es n°{position}/14.", "status": "selected"})
        else:
            return jsonify({"ok": True, "already": True, "msg": f"{name}, tu es en liste d'attente (n°{position - MAX_PLAYERS}).", "status": "waiting"})

    reg = {
        "name": name,
        "pin": pin,
        "time": now().strftime("%H:%M:%S"),
        "date": now().strftime("%d/%m/%Y"),
        "status": "in"
    }
    match["registrations"].append(reg)
    save_data(data)

    active = [r for r in match["registrations"] if r["status"] != "out"]
    position = active.index(reg) + 1

    if position <= MAX_PLAYERS:
        return jsonify({"ok": True, "msg": f"✅ {name}, tu es inscrit ! Tu es n°{position}/14.", "status": "selected"})
    else:
        return jsonify({"ok": True, "msg": f"⏳ {name}, tu es n°{position - MAX_PLAYERS} sur la liste d'attente.", "status": "waiting"})

@app.route("/dropout", methods=["POST"])
def dropout():
    data = load_data()
    check_cancellation(data)
    match = data["match"]

    if match.get("cancelled"):
        return jsonify({"ok": False, "msg": "❌ Match déjà annulé."})

    if match["phase"] not in ("registration", "confirmation"):
        return jsonify({"ok": False, "msg": "Les inscriptions sont fermées."})

    name = request.json.get("name", "").strip().capitalize()
    pin = request.json.get("pin", "").strip()

    if not pin or len(pin) != 4 or not pin.isdigit():
        return jsonify({"ok": False, "msg": "Entre ton code à 4 chiffres pour confirmer."})

    reg = next((r for r in match["registrations"] if r["name"].lower() == name.lower()), None)

    if not reg:
        return jsonify({"ok": False, "msg": f"{name} n'est pas dans la liste."})
    if reg["status"] == "out":
        return jsonify({"ok": False, "msg": f"{name} est déjà marqué OUT."})
    if reg.get("pin", "") != pin:
        return jsonify({"ok": False, "msg": "❌ Code incorrect. Ce n'est pas ton compte."})

    reg["status"] = "out"
    save_data(data)

    active = [r for r in match["registrations"] if r["status"] != "out"]
    replacement = active[MAX_PLAYERS - 1] if len(active) >= MAX_PLAYERS else None

    msg = f"❌ {name}, tu as été retiré de la liste."
    if replacement:
        msg += f" {replacement['name']} passe de la liste d'attente !"

    return jsonify({"ok": True, "msg": msg})

@app.route("/list")
def list_view():
    data = load_data()
    check_cancellation(data)
    match = data["match"]
    selected = get_selected(match["registrations"])
    waiting = get_waiting(match["registrations"])
    def clean(r):
        return {"name": r["name"], "time": r["time"], "status": r["status"]}
    return jsonify({
        "phase": match["phase"],
        "cancelled": match.get("cancelled", False),
        "day": match["day"],
        "date": match["date"],
        "selected": [clean(r) for r in selected],
        "waiting": [clean(r) for r in waiting],
    })

# ─── Routes admin ─────────────────────────────────────────────────

@app.route("/admin")
def admin():
    data = load_data()
    match = data["match"]
    selected = get_selected(match["registrations"])
    waiting = get_waiting(match["registrations"])
    return render_template("admin.html",
        match=match,
        selected=selected,
        waiting=waiting,
        max_players=MAX_PLAYERS,
        now=now().strftime("%d/%m %H:%M")
    )

@app.route("/admin/open", methods=["POST"])
def admin_open():
    data = load_data()
    day = request.json.get("day", "Lundi")
    date = request.json.get("date", "")
    data["match"] = {
        "active": True,
        "day": day,
        "date": date,
        "phase": "registration",
        "cancelled": False,
        "registrations": []
    }
    save_data(data)
    return jsonify({"ok": True, "msg": f"Inscriptions ouvertes pour {day} {date}"})

@app.route("/admin/confirm", methods=["POST"])
def admin_confirm():
    data = load_data()
    data["match"]["phase"] = "confirmation"
    save_data(data)
    return jsonify({"ok": True, "msg": "Phase de confirmation activée"})

@app.route("/admin/close", methods=["POST"])
def admin_close():
    data = load_data()
    data["match"]["phase"] = "done"
    data["match"]["active"] = False
    save_data(data)
    return jsonify({"ok": True, "msg": "Match clôturé"})

@app.route("/admin/reset", methods=["POST"])
def admin_reset():
    save_data(default_data())
    return jsonify({"ok": True, "msg": "Données réinitialisées"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

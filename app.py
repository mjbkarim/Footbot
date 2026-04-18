from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_cors import CORS
from datetime import datetime
import json
import os
import pytz

import os
app = Flask(__name__, template_folder=os.path.dirname(os.path.abspath(__file__)))

CORS(app)

# ─── Configuration ───────────────────────────────────────────────
TIMEZONE = pytz.timezone("Europe/Bucharest")  # Roumanie
MAX_PLAYERS = 14
DATA_FILE = "data.json"

# ─── Helpers ─────────────────────────────────────────────────────
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
            "day": "",           # "Lundi" ou "Jeudi"
            "date": "",
            "phase": "closed",   # closed | registration | confirmation | done
            "registrations": [], # [{name, time, rank, status: in/out/confirmed}]
        }
    }

def get_selected(registrations):
    ins = [r for r in registrations if r["status"] != "out"]
    return ins[:MAX_PLAYERS]

def get_waiting(registrations):
    ins = [r for r in registrations if r["status"] != "out"]
    return ins[MAX_PLAYERS:]

# ─── Routes principales ───────────────────────────────────────────

@app.route("/")
def index():
    data = load_data()
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
    match = data["match"]

    if match["phase"] not in ("registration", "confirmation"):
        return jsonify({"ok": False, "msg": "Les inscriptions sont fermées."})

    name = request.json.get("name", "").strip()
    if not name or len(name) < 2:
        return jsonify({"ok": False, "msg": "Prénom invalide."})

    name = name.capitalize()

    # Vérifier si déjà inscrit
    existing = next((r for r in match["registrations"] if r["name"].lower() == name.lower()), None)
    if existing:
        if existing["status"] == "out":
            return jsonify({"ok": False, "msg": f"{name}, tu t'es désisté. Contacte l'organisateur."})
        rank = match["registrations"].index(existing) + 1
        selected_count = len([r for r in match["registrations"] if r["status"] != "out"])
        position = [r for r in match["registrations"] if r["status"] != "out"].index(existing) + 1
        if position <= MAX_PLAYERS:
            return jsonify({"ok": True, "already": True, "msg": f"{name}, tu es déjà inscrit ! Tu es n°{position} sur {MAX_PLAYERS}.", "position": position, "status": "selected"})
        else:
            return jsonify({"ok": True, "already": True, "msg": f"{name}, tu es déjà en liste d'attente (n°{position - MAX_PLAYERS}).", "position": position, "status": "waiting"})

    # Nouvel inscrit
    reg = {
        "name": name,
        "time": now().strftime("%H:%M:%S"),
        "date": now().strftime("%d/%m/%Y"),
        "status": "in"
    }
    match["registrations"].append(reg)
    save_data(data)

    active = [r for r in match["registrations"] if r["status"] != "out"]
    position = active.index(reg) + 1

    if position <= MAX_PLAYERS:
        msg = f"✅ {name}, tu es inscrit ! Tu es n°{position} sur {MAX_PLAYERS}."
        status = "selected"
    else:
        wait_pos = position - MAX_PLAYERS
        msg = f"⏳ {name}, tu es n°{wait_pos} sur la liste d'attente."
        status = "waiting"

    return jsonify({"ok": True, "already": False, "msg": msg, "position": position, "status": status})

@app.route("/dropout", methods=["POST"])
def dropout():
    data = load_data()
    match = data["match"]

    if match["phase"] not in ("registration", "confirmation"):
        return jsonify({"ok": False, "msg": "Les inscriptions sont fermées."})

    name = request.json.get("name", "").strip().capitalize()
    reg = next((r for r in match["registrations"] if r["name"].lower() == name.lower()), None)

    if not reg:
        return jsonify({"ok": False, "msg": f"{name} n'est pas dans la liste."})

    if reg["status"] == "out":
        return jsonify({"ok": False, "msg": f"{name} est déjà marqué OUT."})

    reg["status"] = "out"
    save_data(data)

    # Qui prend sa place ?
    active = [r for r in match["registrations"] if r["status"] != "out"]
    replacement = active[MAX_PLAYERS - 1] if len(active) >= MAX_PLAYERS else None

    msg = f"❌ {name}, tu as été retiré de la liste."
    if replacement:
        msg += f" {replacement['name']} passe de la liste d'attente !"

    return jsonify({"ok": True, "msg": msg, "replacement": replacement["name"] if replacement else None})

@app.route("/list")
def list_view():
    data = load_data()
    match = data["match"]
    selected = get_selected(match["registrations"])
    waiting = get_waiting(match["registrations"])
    return jsonify({
        "phase": match["phase"],
        "day": match["day"],
        "date": match["date"],
        "selected": selected,
        "waiting": waiting,
        "total": len([r for r in match["registrations"] if r["status"] != "out"])
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

# ─── Lancement ────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

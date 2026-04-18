from flask import Flask, render_template, request, jsonify, session, redirect
from flask_cors import CORS
from datetime import datetime
import os, pytz, hashlib, psycopg2, psycopg2.extras, json

app = Flask(__name__, template_folder=os.path.dirname(os.path.abspath(__file__)))
app.secret_key = os.environ.get("SECRET_KEY", "footbot-secret-2024")
CORS(app)

TIMEZONE = pytz.timezone("Europe/Bucharest")
MAX_PLAYERS = 14
DEADLINE_CONFIRM = 17
DEADLINE_CANCEL = 19
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin1234")

def now():
    return datetime.now(TIMEZONE)

def hash_pin(pin):
    return hashlib.sha256(pin.encode()).hexdigest()

# ─── Database ─────────────────────────────────────────────────────
def get_db():
    conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
    conn.autocommit = True
    return conn

def init_db():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS players (
                username TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                pin TEXT NOT NULL,
                joined TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS match_state (
                id INTEGER PRIMARY KEY DEFAULT 1,
                day TEXT DEFAULT '',
                date TEXT DEFAULT '',
                phase TEXT DEFAULT 'closed',
                cancelled BOOLEAN DEFAULT FALSE,
                registrations JSONB DEFAULT '[]'
            );
            INSERT INTO match_state (id) VALUES (1) ON CONFLICT DO NOTHING;
        """)

init_db()

# ─── Helpers DB ───────────────────────────────────────────────────
def load_match():
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM match_state WHERE id=1")
        row = cur.fetchone()
        row = dict(row)
        row['registrations'] = row['registrations'] if isinstance(row['registrations'], list) else json.loads(row['registrations'])
        return row

def save_match(match):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE match_state SET day=%s, date=%s, phase=%s, cancelled=%s, registrations=%s WHERE id=1
        """, (match['day'], match['date'], match['phase'], match['cancelled'],
              json.dumps(match['registrations'], ensure_ascii=False)))

def load_players():
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM players ORDER BY joined")
        return {r['username']: dict(r) for r in cur.fetchall()}

def get_selected(regs):
    return [r for r in regs if r["status"] not in ("out","no_response")][:MAX_PLAYERS]

def get_waiting(regs):
    return [r for r in regs if r["status"] not in ("out","no_response")][MAX_PLAYERS:]

def check_deadlines(match):
    if match["phase"] != "confirmation" or match.get("cancelled"):
        return False
    changed = False
    h = now().hour
    if h >= DEADLINE_CONFIRM:
        for reg in match["registrations"]:
            if reg["status"] == "in":
                reg["status"] = "no_response"
                changed = True
    if h >= DEADLINE_CANCEL:
        if len(get_selected(match["registrations"])) < MAX_PLAYERS:
            match["cancelled"] = True
            match["phase"] = "done"
            changed = True
    if changed:
        save_match(match)
    return changed

# ─── Routes joueurs ───────────────────────────────────────────────

@app.route("/")
def index():
    match = load_match()
    check_deadlines(match)
    players = load_players()
    selected = get_selected(match["registrations"])
    waiting = get_waiting(match["registrations"])
    username = session.get("username")
    my_reg = next((r for r in match["registrations"] if r.get("username") == username), None) if username else None
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
    username = request.json.get("username","").strip().lower()
    name = request.json.get("name","").strip().capitalize()
    pin = request.json.get("pin","").strip()

    if not username or len(username) < 3:
        return jsonify({"ok": False, "msg": "Username trop court (min 3 caractères)."})
    if not name or len(name) < 2:
        return jsonify({"ok": False, "msg": "Prénom invalide."})
    if not pin or len(pin) != 4 or not pin.isdigit():
        return jsonify({"ok": False, "msg": "Code PIN doit faire 4 chiffres."})

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT username FROM players WHERE username=%s", (username,))
        if cur.fetchone():
            return jsonify({"ok": False, "msg": f"Le username '{username}' est déjà pris."})
        cur.execute("INSERT INTO players VALUES (%s,%s,%s,%s)",
                    (username, name, hash_pin(pin), now().strftime("%d/%m/%Y")))

    session["username"] = username
    return jsonify({"ok": True, "msg": f"✅ Bienvenue {name} !", "name": name})

@app.route("/login", methods=["POST"])
def login():
    username = request.json.get("username","").strip().lower()
    pin = request.json.get("pin","").strip()

    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM players WHERE username=%s", (username,))
        p = cur.fetchone()

    if not p:
        return jsonify({"ok": False, "msg": "Username introuvable."})
    if p["pin"] != hash_pin(pin):
        return jsonify({"ok": False, "msg": "Code PIN incorrect."})

    session["username"] = username
    return jsonify({"ok": True, "msg": f"Bienvenue {p['name']} !", "name": p["name"]})

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})

@app.route("/register", methods=["POST"])
def register():
    username = session.get("username")
    if not username:
        return jsonify({"ok": False, "msg": "Connecte-toi d'abord."})

    match = load_match()
    check_deadlines(match)
    players = load_players()

    if match.get("cancelled"):
        return jsonify({"ok": False, "msg": "❌ Match annulé."})
    if match["phase"] not in ("registration","confirmation"):
        return jsonify({"ok": False, "msg": "Les inscriptions sont fermées."})

    existing = next((r for r in match["registrations"] if r.get("username") == username), None)
    if existing:
        if existing["status"] in ("out","no_response"):
            return jsonify({"ok": False, "msg": "Tu t'es désisté. Contacte l'organisateur."})
        active = [r for r in match["registrations"] if r["status"] not in ("out","no_response")]
        pos = active.index(existing) + 1
        if pos <= MAX_PLAYERS:
            return jsonify({"ok": True, "msg": f"Tu es déjà inscrit ! N°{pos}/14.", "status": "selected"})
        return jsonify({"ok": True, "msg": f"Tu es en attente (n°{pos-MAX_PLAYERS}).", "status": "waiting"})

    reg = {"username": username, "name": players[username]["name"],
           "time": now().strftime("%H:%M:%S"), "status": "in"}
    match["registrations"].append(reg)
    save_match(match)

    active = [r for r in match["registrations"] if r["status"] not in ("out","no_response")]
    pos = active.index(reg) + 1
    if pos <= MAX_PLAYERS:
        return jsonify({"ok": True, "msg": f"✅ Inscrit ! Tu es n°{pos}/14.", "status": "selected"})
    return jsonify({"ok": True, "msg": f"⏳ Liste d'attente n°{pos-MAX_PLAYERS}.", "status": "waiting"})

@app.route("/confirm", methods=["POST"])
def confirm():
    username = session.get("username")
    if not username:
        return jsonify({"ok": False, "msg": "Connecte-toi d'abord."})
    match = load_match()
    if match["phase"] != "confirmation":
        return jsonify({"ok": False, "msg": "Pas en phase de confirmation."})
    reg = next((r for r in match["registrations"] if r.get("username") == username), None)
    if not reg:
        return jsonify({"ok": False, "msg": "Tu n'es pas dans la liste."})
    reg["status"] = "confirmed"
    save_match(match)
    return jsonify({"ok": True, "msg": "✅ Présence confirmée ! À ce soir ⚽"})

@app.route("/dropout", methods=["POST"])
def dropout():
    username = session.get("username")
    if not username:
        return jsonify({"ok": False, "msg": "Connecte-toi d'abord."})
    match = load_match()
    check_deadlines(match)
    if match["phase"] not in ("registration","confirmation"):
        return jsonify({"ok": False, "msg": "Les inscriptions sont fermées."})
    reg = next((r for r in match["registrations"] if r.get("username") == username), None)
    if not reg:
        return jsonify({"ok": False, "msg": "Tu n'es pas dans la liste."})
    if reg["status"] in ("out","no_response"):
        return jsonify({"ok": False, "msg": "Tu es déjà retiré."})
    reg["status"] = "out"
    save_match(match)
    active = [r for r in match["registrations"] if r["status"] not in ("out","no_response")]
    replacement = active[MAX_PLAYERS-1] if len(active) >= MAX_PLAYERS else None
    msg = "❌ Tu as été retiré de la liste."
    if replacement:
        msg += f" {replacement['name']} monte depuis la liste d'attente !"
    return jsonify({"ok": True, "msg": msg})

@app.route("/list")
def list_view():
    match = load_match()
    check_deadlines(match)
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
    match = load_match()
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
        if request.json.get("password","") == ADMIN_PASSWORD:
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
    day = request.json.get("day","Lundi")
    date = request.json.get("date","")
    match = {"day": day, "date": date, "phase": "registration", "cancelled": False, "registrations": []}
    save_match(match)
    return jsonify({"ok": True, "msg": f"Inscriptions ouvertes — {day} {date}"})

@app.route("/admin/confirm", methods=["POST"])
def admin_confirm():
    if not admin_logged(): return jsonify({"ok": False, "msg": "Non autorisé."})
    match = load_match()
    match["phase"] = "confirmation"
    save_match(match)
    return jsonify({"ok": True, "msg": "Phase de confirmation activée"})

@app.route("/admin/close", methods=["POST"])
def admin_close():
    if not admin_logged(): return jsonify({"ok": False, "msg": "Non autorisé."})
    match = load_match()
    match["phase"] = "done"
    save_match(match)
    return jsonify({"ok": True, "msg": "Match clôturé"})

@app.route("/admin/remove_player", methods=["POST"])
def admin_remove_player():
    if not admin_logged(): return jsonify({"ok": False, "msg": "Non autorisé."})
    match = load_match()
    username = request.json.get("username","")
    reg = next((r for r in match["registrations"] if r.get("username") == username), None)
    if not reg:
        return jsonify({"ok": False, "msg": "Joueur introuvable."})
    reg["status"] = "out"
    save_match(match)
    active = [r for r in match["registrations"] if r["status"] not in ("out","no_response")]
    replacement = active[MAX_PLAYERS-1] if len(active) >= MAX_PLAYERS else None
    msg = f"{reg['name']} retiré."
    if replacement: msg += f" {replacement['name']} monte !"
    return jsonify({"ok": True, "msg": msg})

@app.route("/admin/reset_pin", methods=["POST"])
def admin_reset_pin():
    if not admin_logged(): return jsonify({"ok": False, "msg": "Non autorisé."})
    username = request.json.get("username","")
    new_pin = request.json.get("pin","")
    if not new_pin or len(new_pin) != 4 or not new_pin.isdigit():
        return jsonify({"ok": False, "msg": "PIN invalide."})
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE players SET pin=%s WHERE username=%s", (hash_pin(new_pin), username))
    return jsonify({"ok": True, "msg": f"PIN réinitialisé."})

@app.route("/admin/delete_account", methods=["POST"])
def admin_delete_account():
    if not admin_logged(): return jsonify({"ok": False, "msg": "Non autorisé."})
    username = request.json.get("username","")
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM players WHERE username=%s", (username,))
    return jsonify({"ok": True, "msg": f"Compte supprimé."})

@app.route("/admin/reset", methods=["POST"])
def admin_reset():
    if not admin_logged(): return jsonify({"ok": False, "msg": "Non autorisé."})
    match = {"day":"","date":"","phase":"closed","cancelled":False,"registrations":[]}
    save_match(match)
    return jsonify({"ok": True, "msg": "Match réinitialisé."})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

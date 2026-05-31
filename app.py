"""
SocietyLedger - Flask + SQLite backend
Run:  pip install flask
      python app.py
Then open http://localhost:5000
"""

from flask import Flask, request, jsonify, render_template, send_from_directory
import sqlite3, os, math
from datetime import date, datetime

app = Flask(__name__)
DB = "ledger.db"


# ── Database setup ────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS houses (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            no      TEXT NOT NULL,
            owner   TEXT NOT NULL,
            phone   TEXT,
            email   TEXT,
            amount  REAL,
            since   TEXT
        );
        CREATE TABLE IF NOT EXISTS payments (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            house_id  INTEGER NOT NULL,
            month     TEXT NOT NULL,
            date      TEXT NOT NULL,
            principal REAL NOT NULL,
            interest  REAL NOT NULL DEFAULT 0,
            total     REAL NOT NULL,
            note      TEXT,
            FOREIGN KEY (house_id) REFERENCES houses(id)
        );
        """)
        # Default settings
        defaults = {
            "name": "Sunrise Heights",
            "amount": "1500",
            "due_day": "5",
            "rate": "2"
        }
        for k, v in defaults.items():
            db.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (k, v))
        db.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_setting(db, key, default=None):
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default

def get_house_amount(house, default_amount):
    return float(house["amount"]) if house["amount"] else float(default_amount)

def calc_interest(amount, rate_pct, for_month, pay_date_str, due_day):
    """Simple interest = amount × rate% × (days_late / 30)"""
    year, month = map(int, for_month.split("-"))
    due = date(year, month, int(due_day))
    paid = datetime.strptime(pay_date_str, "%Y-%m-%d").date()
    if paid <= due:
        return 0.0
    days_late = (paid - due).days
    interest = amount * (float(rate_pct) / 100) * (days_late / 30)
    return round(interest, 2)

def paid_months_for_house(db, house_id):
    rows = db.execute("SELECT month FROM payments WHERE house_id=?", (house_id,)).fetchall()
    return {r["month"] for r in rows}

def get_overdue_list(db):
    today = date.today()
    amount_default = get_setting(db, "amount", "1500")
    due_day = int(get_setting(db, "due_day", "5"))
    rate = get_setting(db, "rate", "2")
    houses = db.execute("SELECT * FROM houses").fetchall()
    result = []

    for h in houses:
        paid = paid_months_for_house(db, h["id"])
        since_str = h["since"] or f"{today.year - 1}-01"
        sy, sm = map(int, since_str.split("-"))
        cur_year, cur_month = sy, sm
        overdue_months = []

        while (cur_year, cur_month) <= (today.year, today.month):
            key = f"{cur_year}-{cur_month:02d}"
            due_date = date(cur_year, cur_month, min(due_day, 28))
            if key not in paid and today > due_date:
                overdue_months.append(key)
            cur_month += 1
            if cur_month > 12:
                cur_month = 1
                cur_year += 1

        if overdue_months:
            amt = get_house_amount(h, amount_default)
            principal = len(overdue_months) * amt
            interest = 0.0
            for m in overdue_months:
                my, mm = map(int, m.split("-"))
                due = date(my, mm, min(due_day, 28))
                days_late = max(0, (today - due).days)
                interest += round(amt * float(rate) / 100 * (days_late / 30), 2)
            result.append({
                "house_id": h["id"],
                "house_no": h["no"],
                "owner": h["owner"],
                "months": overdue_months,
                "principal": round(principal, 2),
                "interest": round(interest, 2),
                "total": round(principal + interest, 2)
            })
    return result


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# Settings
@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    with get_db() as db:
        rows = db.execute("SELECT key, value FROM settings").fetchall()
        return jsonify({r["key"]: r["value"] for r in rows})

@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    data = request.json
    with get_db() as db:
        for k, v in data.items():
            db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (k, str(v)))
        db.commit()
    return jsonify({"ok": True})


# Houses
@app.route("/api/houses", methods=["GET"])
def api_get_houses():
    with get_db() as db:
        rows = db.execute("SELECT * FROM houses ORDER BY no").fetchall()
        return jsonify([dict(r) for r in rows])

@app.route("/api/houses", methods=["POST"])
def api_add_house():
    d = request.json
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO houses (no,owner,phone,email,amount,since) VALUES (?,?,?,?,?,?)",
            (d["no"], d["owner"], d.get("phone",""), d.get("email",""),
             d.get("amount") or None, d.get("since",""))
        )
        db.commit()
        return jsonify({"id": cur.lastrowid})

@app.route("/api/houses/<int:hid>", methods=["PUT"])
def api_update_house(hid):
    d = request.json
    with get_db() as db:
        db.execute(
            "UPDATE houses SET no=?,owner=?,phone=?,email=?,amount=?,since=? WHERE id=?",
            (d["no"], d["owner"], d.get("phone",""), d.get("email",""),
             d.get("amount") or None, d.get("since",""), hid)
        )
        db.commit()
    return jsonify({"ok": True})

@app.route("/api/houses/<int:hid>", methods=["DELETE"])
def api_delete_house(hid):
    with get_db() as db:
        db.execute("DELETE FROM houses WHERE id=?", (hid,))
        db.commit()
    return jsonify({"ok": True})


# Payments
@app.route("/api/payments", methods=["GET"])
def api_get_payments():
    house_id = request.args.get("house_id")
    year = request.args.get("year")
    with get_db() as db:
        q = "SELECT * FROM payments WHERE 1=1"
        params = []
        if house_id:
            q += " AND house_id=?"; params.append(house_id)
        if year:
            q += " AND month LIKE ?"; params.append(f"{year}%")
        q += " ORDER BY id DESC"
        rows = db.execute(q, params).fetchall()
        return jsonify([dict(r) for r in rows])

@app.route("/api/payments", methods=["POST"])
def api_add_payment():
    d = request.json
    with get_db() as db:
        house = db.execute("SELECT * FROM houses WHERE id=?", (d["house_id"],)).fetchone()
        if not house:
            return jsonify({"error": "House not found"}), 404
        amount_default = get_setting(db, "amount", "1500")
        due_day = get_setting(db, "due_day", "5")
        rate = get_setting(db, "rate", "2")
        principal = get_house_amount(house, amount_default)
        interest = calc_interest(principal, rate, d["month"], d["date"], due_day)
        # Allow manual override of interest
        if "interest" in d and d["interest"] is not None:
            interest = float(d["interest"])
        total = principal + interest
        cur = db.execute(
            "INSERT INTO payments (house_id,month,date,principal,interest,total,note) VALUES (?,?,?,?,?,?,?)",
            (d["house_id"], d["month"], d["date"], principal, interest, total, d.get("note",""))
        )
        db.commit()
        return jsonify({"id": cur.lastrowid, "principal": principal, "interest": interest, "total": total})


# Dashboard data
@app.route("/api/dashboard", methods=["GET"])
def api_dashboard():
    with get_db() as db:
        today = date.today()
        this_month = f"{today.year}-{today.month:02d}"
        overdue = get_overdue_list(db)
        total_due = sum(x["total"] for x in overdue)
        total_interest = sum(x["interest"] for x in overdue)
        collected = db.execute(
            "SELECT COALESCE(SUM(total),0) as s FROM payments WHERE month=?", (this_month,)
        ).fetchone()["s"]
        house_count = db.execute("SELECT COUNT(*) as c FROM houses").fetchone()["c"]
        recent = db.execute(
            """SELECT p.*, h.no, h.owner FROM payments p
               JOIN houses h ON p.house_id=h.id
               ORDER BY p.id DESC LIMIT 8"""
        ).fetchall()
        return jsonify({
            "total_due": round(total_due, 2),
            "total_interest": round(total_interest, 2),
            "collected_this_month": round(float(collected), 2),
            "house_count": house_count,
            "overdue_count": len(overdue),
            "overdue": overdue,
            "recent_payments": [dict(r) for r in recent]
        })


# Interest preview
@app.route("/api/calc_interest", methods=["GET"])
def api_calc_interest():
    house_id = request.args.get("house_id")
    month = request.args.get("month")
    pay_date = request.args.get("date")
    with get_db() as db:
        house = db.execute("SELECT * FROM houses WHERE id=?", (house_id,)).fetchone()
        if not house:
            return jsonify({"error": "Not found"}), 404
        amount_default = get_setting(db, "amount", "1500")
        due_day = get_setting(db, "due_day", "5")
        rate = get_setting(db, "rate", "2")
        principal = get_house_amount(house, amount_default)
        interest = calc_interest(principal, rate, month, pay_date, due_day)
        return jsonify({"principal": principal, "interest": interest, "total": principal + interest, "rate": rate})


if __name__ == "__main__":
    init_db()
    print("\n✅  SocietyLedger running → http://localhost:5000\n")
    app.run(debug=True)

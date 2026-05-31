"""
SocietyLedger - Flask + SQLite backend
Billing rules:
  - Demand raised on 1st of every month
  - Grace period: pay by 15th of that month → no interest
  - If paid after 15th: interest = principal × (annual_rate/12/100) per overdue month
  - Each additional calendar month unpaid adds another month of interest

Run:  pip install flask
      python app.py
Then open http://localhost:5000
"""

from flask import Flask, request, jsonify, render_template
import sqlite3
from datetime import date, datetime

app = Flask(__name__)
DB = "ledger.db"

# ── Database ──────────────────────────────────────────────────────────────────

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
        defaults = {"name": "Sunrise Heights", "amount": "1500", "annual_rate": "24"}
        for k, v in defaults.items():
            db.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (k, v))
        db.commit()

init_db()

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_setting(db, key, default=None):
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default

def get_house_amount(house, default_amount):
    return float(house["amount"]) if house["amount"] else float(default_amount)

def calc_interest(principal, annual_rate_pct, for_month, pay_date_str):
    """
    Demand on 1st. Grace until 15th (inclusive).
    After 15th: charge (annual_rate/12)% per calendar month late (minimum 1 month).
    """
    year, month = map(int, for_month.split("-"))
    grace_deadline = date(year, month, 15)
    pay_date = datetime.strptime(pay_date_str, "%Y-%m-%d").date()

    if pay_date <= grace_deadline:
        return 0.0

    monthly_rate = float(annual_rate_pct) / 12 / 100  # e.g. 24/12/100 = 0.02
    pay_year, pay_month = pay_date.year, pay_date.month
    months_late = max(1, (pay_year - year) * 12 + (pay_month - month) + 1)
    return round(principal * monthly_rate * months_late, 2)

def paid_months_for_house(db, house_id):
    rows = db.execute("SELECT month FROM payments WHERE house_id=?", (house_id,)).fetchall()
    return {r["month"] for r in rows}

def get_overdue_list(db):
    today = date.today()
    amount_default = get_setting(db, "amount", "1500")
    annual_rate = float(get_setting(db, "annual_rate", "24"))
    monthly_rate = annual_rate / 12 / 100  # e.g. 0.02
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
            grace = date(cur_year, cur_month, 15)
            # Demand is active once 1st passes; overdue once grace expires
            if key not in paid and today > grace:
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
                # Months elapsed since demand (minimum 1)
                months_late = max(1, (today.year - my) * 12 + (today.month - mm) + 1)
                interest += round(amt * monthly_rate * months_late, 2)
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

        # Duplicate check
        existing = db.execute(
            "SELECT id FROM payments WHERE house_id=? AND month=?",
            (d["house_id"], d["month"])
        ).fetchone()
        if existing:
            return jsonify({"error": f"Payment for {d['month']} already recorded for this house."}), 400

        amount_default = get_setting(db, "amount", "1500")
        annual_rate = get_setting(db, "annual_rate", "24")
        principal = get_house_amount(house, amount_default)

        # Auto-calculate; allow manual override
        interest = calc_interest(principal, annual_rate, d["month"], d["date"])
        if "interest" in d and d["interest"] is not None:
            interest = float(d["interest"])

        total = principal + interest
        cur = db.execute(
            "INSERT INTO payments (house_id,month,date,principal,interest,total,note) VALUES (?,?,?,?,?,?,?)",
            (d["house_id"], d["month"], d["date"], principal, interest, total, d.get("note",""))
        )
        db.commit()
        return jsonify({"id": cur.lastrowid, "principal": principal, "interest": interest, "total": total})

@app.route("/api/payments/<int:pid>", methods=["PUT"])
def api_update_payment(pid):
    d = request.json
    principal = float(d.get("principal", 0))
    interest = float(d.get("interest", 0))
    total = principal + interest
    with get_db() as db:
        db.execute(
            "UPDATE payments SET principal=?,interest=?,total=?,note=? WHERE id=?",
            (principal, interest, total, d.get("note",""), pid)
        )
        db.commit()
    return jsonify({"ok": True, "principal": principal, "interest": interest, "total": total})

@app.route("/api/payments/<int:pid>", methods=["DELETE"])
def api_delete_payment(pid):
    with get_db() as db:
        db.execute("DELETE FROM payments WHERE id=?", (pid,))
        db.commit()
    return jsonify({"ok": True})

# Dashboard
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
        annual_rate = get_setting(db, "annual_rate", "24")
        principal = get_house_amount(house, amount_default)
        interest = calc_interest(principal, annual_rate, month, pay_date)
        # Compute months_late for display
        year, mon = map(int, month.split("-"))
        pd = datetime.strptime(pay_date, "%Y-%m-%d").date()
        grace = date(year, mon, 15)
        months_late = max(1, (pd.year - year) * 12 + (pd.month - mon) + 1) if pd > grace else 0
        return jsonify({
            "principal": principal,
            "interest": interest,
            "total": principal + interest,
            "annual_rate": annual_rate,
            "monthly_rate": float(annual_rate) / 12,
            "months_late": months_late,
            "on_time": pd <= grace
        })

if __name__ == "__main__":
    print("\n✅  SocietyLedger running → http://localhost:5000")
    print("   Billing: Demand on 1st | Grace till 15th | 24% p.a. interest after\n")
    app.run(debug=True)
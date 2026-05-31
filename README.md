# SocietyLedger — Python/Flask App

A maintenance ledger for housing societies with automatic interest calculation.

## Project Structure

```
society_ledger_python/
├── app.py               ← Flask backend + REST API
├── templates/
│   └── index.html       ← Frontend (calls the API)
├── ledger.db            ← SQLite database (auto-created on first run)
└── README.md
```

## Setup & Run

### 1. Install dependencies
```bash
pip install flask
```

### 2. Run the app
```bash
python app.py
```

### 3. Open in browser
```
http://localhost:5000
```

That's it! The SQLite database (`ledger.db`) is created automatically on first run.

---

## Features

- **Houses** — Add/edit/delete flats with owner name, phone, custom monthly amount
- **Payments** — Record payments; interest auto-calculated if late
- **Interest** — Simple interest: `Amount × Rate% × (Days Late / 30)`
- **Dashboard** — Live overdue list, metrics, recent payments
- **Ledger** — Full history, filter by house/year, export CSV
- **Receipts** — Printable receipt for every payment
- **Settings** — Society name, monthly amount, due day, interest rate

## API Endpoints

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/api/settings` | Get all settings |
| POST | `/api/settings` | Save settings |
| GET | `/api/houses` | List all houses |
| POST | `/api/houses` | Add a house |
| PUT | `/api/houses/<id>` | Update a house |
| DELETE | `/api/houses/<id>` | Delete a house |
| GET | `/api/payments` | List payments (filter: house_id, year) |
| POST | `/api/payments` | Record a payment |
| GET | `/api/dashboard` | Dashboard summary data |
| GET | `/api/calc_interest` | Preview interest before recording |

## Interest Formula

```
Interest = Principal × (Rate / 100) × (Days Late / 30)
```

Where **Days Late** = Payment Date − Due Date (due date = due_day of that month).

## Upgrading to PostgreSQL / MySQL

Replace the `sqlite3` calls in `app.py` with `psycopg2` or `PyMySQL`.
The SQL is standard and will work without changes.

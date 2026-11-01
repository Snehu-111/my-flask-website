import os
import sqlite3
import math
from datetime import date
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import csv
import io

app = Flask(__name__)
app.secret_key = "student_finance_secret_key"

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "finance.db")

def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with connect_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                profile_pic TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT,
                category TEXT,
                amount REAL,
                date TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS wallet (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                type TEXT,
                amount REAL,
                note TEXT,
                date TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                category TEXT,
                amount REAL,
                month TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS savings_goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                goal_name TEXT,
                target_amount REAL,
                saved_amount REAL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS recurring (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT,
                amount REAL,
                frequency TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS split_bills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT,
                total_amount REAL,
                shares TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS debts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                friend_name TEXT,
                amount REAL,
                type TEXT,
                note TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS emergency_fund (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                target_amount REAL,
                current_amount REAL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                service_name TEXT,
                amount REAL,
                renewal_date TEXT
            )
        """)

def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapped

# --- AUTH ROUTES ---
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        with connect_db() as db:
            user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("index"))
        
        flash("Invalid username or password.")
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("All fields are required.")
            return redirect(url_for("register"))

        hashed_pw = generate_password_hash(password)

        try:
            with connect_db() as db:
                db.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_pw))
            flash("Registered successfully! Please log in.")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username already exists.")
    return render_template("register.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# --- APP ROUTES ---
@app.route("/")
@login_required
def index():
    user_id = session["user_id"]
    with connect_db() as db:
        expenses = db.execute("SELECT * FROM expenses WHERE user_id = ? ORDER BY date DESC", (user_id,)).fetchall()
        wallet_txs = db.execute("SELECT * FROM wallet WHERE user_id = ?", (user_id,)).fetchall()

    total = sum(e["amount"] for e in expenses)
    monthly_total = sum(e["amount"] for e in expenses if e["date"] and e["date"].startswith(date.today().isoformat()[:7]))
    average_monthly = total / 6 if total > 0 else 0

    wallet_balance = 0
    for w in wallet_txs:
        if "Deposit" in w["type"] or "Add" in w["type"]:
            wallet_balance += w["amount"]
        else:
            wallet_balance -= w["amount"]

    categories = {}
    for e in expenses:
        cat = e["category"] or "Other"
        categories[cat] = categories.get(cat, 0) + e["amount"]

    return render_template("dashboard.html", total=total, monthly_total=monthly_total, average_monthly=average_monthly, wallet_balance=wallet_balance, categories=categories, recent_expenses=expenses[:5])

@app.route("/home")
@login_required
def home():
    return render_template("home.html")

@app.route("/expenses", methods=["GET"])
@login_required
def expenses_page():
    user_id = session["user_id"]
    with connect_db() as db:
        expenses = db.execute("SELECT * FROM expenses WHERE user_id = ? ORDER BY date DESC", (user_id,)).fetchall()
    return render_template("expenses.html", expenses=expenses)

@app.route("/add_expense", methods=["POST"])
@login_required
def add_expense():
    user_id = session["user_id"]
    title = request.form.get("title")
    category = request.form.get("category")
    amount = request.form.get("amount")
    exp_date = request.form.get("date")

    try:
        amt = float(amount)
    except (ValueError, TypeError):
        flash("Invalid amount.")
        return redirect(url_for("expenses_page"))

    with connect_db() as db:
        db.execute("INSERT INTO expenses (user_id, title, category, amount, date) VALUES (?, ?, ?, ?, ?)", (user_id, title, category, amt, exp_date))

    flash("Expense added successfully!")
    return redirect(url_for("expenses_page"))

@app.route("/delete_expense/<int:expense_id>", methods=["POST"])
@login_required
def delete_expense(expense_id):
    user_id = session["user_id"]
    with connect_db() as db:
        db.execute("DELETE FROM expenses WHERE id = ? AND user_id = ?", (expense_id, user_id))
    flash("Expense deleted.")
    return redirect(url_for("expenses_page"))

@app.route("/export_expenses")
@login_required
def export_expenses():
    user_id = session["user_id"]
    with connect_db() as db:
        expenses = db.execute("SELECT date, title, category, amount FROM expenses WHERE user_id = ?", (user_id,)).fetchall()

    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(["Date", "Title", "Category", "Amount"])
    for e in expenses:
        cw.writerow([e["date"], e["title"], e["category"], e["amount"]])

    output = io.BytesIO()
    output.write(si.getvalue().encode("utf-8"))
    output.seek(0)
    return send_file(output, mimetype="text/csv", as_attachment=True, download_name="expenses.csv")

@app.route("/wallet", methods=["GET", "POST"])
@login_required
def wallet_page():
    user_id = session["user_id"]
    if request.method == "POST":
        tx_type = request.form.get("type")
        amount = float(request.form.get("amount", 0))
        note = request.form.get("note", "")
        today = date.today().isoformat()

        with connect_db() as db:
            db.execute("INSERT INTO wallet (user_id, type, amount, note, date) VALUES (?, ?, ?, ?, ?)", (user_id, tx_type, amount, note, today))
        flash("Wallet transaction recorded!")
        return redirect(url_for("wallet_page"))

    with connect_db() as db:
        txs = db.execute("SELECT * FROM wallet WHERE user_id = ? ORDER BY id DESC", (user_id,)).fetchall()

    balance = sum(t["amount"] if "Deposit" in t["type"] or "Add" in t["type"] else -t["amount"] for t in txs)
    return render_template("wallet.html", transactions=txs, balance=balance, wallet_balance=balance)

@app.route("/budget", methods=["GET", "POST"])
@login_required
def budget_page():
    user_id = session["user_id"]
    current_month = date.today().isoformat()[:7]

    if request.method == "POST":
        category = request.form.get("category")
        amount = float(request.form.get("amount", 0))
        with connect_db() as db:
            db.execute("INSERT INTO budgets (user_id, category, amount, month) VALUES (?, ?, ?, ?)", (user_id, category, amount, current_month))
        flash("Budget saved!")
        return redirect(url_for("budget_page"))

    with connect_db() as db:
        budgets = db.execute("SELECT * FROM budgets WHERE user_id = ? AND month = ?", (user_id, current_month)).fetchall()
    return render_template("budget.html", budgets=budgets, current_month=current_month)

@app.route("/savings_goals", methods=["GET", "POST"])
@login_required
def savings_goals():
    user_id = session["user_id"]
    if request.method == "POST":
        goal_name = request.form.get("goal_name")
        target_amount = float(request.form.get("target_amount", 0))
        saved_amount = float(request.form.get("saved_amount", 0) or 0)

        with connect_db() as db:
            db.execute("INSERT INTO savings_goals (user_id, goal_name, target_amount, saved_amount) VALUES (?, ?, ?, ?)", (user_id, goal_name, target_amount, saved_amount))
        flash("Savings goal created!")
        return redirect(url_for("savings_goals"))

    with connect_db() as db:
        goals = db.execute("SELECT * FROM savings_goals WHERE user_id = ?", (user_id,)).fetchall()
    return render_template("savings_goals.html", goals=goals)

@app.route("/update_goal/<int:goal_id>", methods=["POST"])
@login_required
def update_goal(goal_id):
    user_id = session["user_id"]
    add_amount = float(request.form.get("add_amount", 0))
    with connect_db() as db:
        db.execute("UPDATE savings_goals SET saved_amount = saved_amount + ? WHERE id = ? AND user_id = ?", (add_amount, goal_id, user_id))
    flash("Goal updated successfully!")
    return redirect(url_for("savings_goals"))

@app.route("/recurring")
@login_required
def recurring_expenses():
    user_id = session["user_id"]
    with connect_db() as db:
        items = db.execute("SELECT * FROM recurring WHERE user_id = ?", (user_id,)).fetchall()
    return render_template("recurring.html", items=items)

@app.route("/split_bills")
@login_required
def split_bills():
    user_id = session["user_id"]
    with connect_db() as db:
        bills = db.execute("SELECT * FROM split_bills WHERE user_id = ?", (user_id,)).fetchall()
    return render_template("split_bills.html", bills=bills)

@app.route("/debts", methods=["GET", "POST"])
@login_required
def debt_tracker():
    user_id = session["user_id"]
    if request.method == "POST":
        friend_name = request.form.get("friend_name")
        amount = float(request.form.get("amount", 0))
        dtype = request.form.get("type")
        note = request.form.get("note", "")

        with connect_db() as db:
            db.execute("INSERT INTO debts (user_id, friend_name, amount, type, note) VALUES (?, ?, ?, ?, ?)", (user_id, friend_name, amount, dtype, note))
        flash("Debt record added!")
        return redirect(url_for("debt_tracker"))

    with connect_db() as db:
        debts = db.execute("SELECT * FROM debts WHERE user_id = ?", (user_id,)).fetchall()
    return render_template("debts.html", debts=debts)

@app.route("/settle_debt/<int:debt_id>", methods=["POST"])
@login_required
def settle_debt(debt_id):
    user_id = session["user_id"]
    with connect_db() as db:
        db.execute("DELETE FROM debts WHERE id = ? AND user_id = ?", (debt_id, user_id))
    flash("Debt settled!")
    return redirect(url_for("debt_tracker"))

@app.route("/insights")
@login_required
def spending_insights():
    return render_template("insights.html")

@app.route("/categories")
@login_required
def manage_categories():
    user_id = session["user_id"]
    with connect_db() as db:
        cats = db.execute("SELECT * FROM categories WHERE user_id = ?", (user_id,)).fetchall()
    return render_template("categories.html", categories=cats)

@app.route("/emergency_fund")
@login_required
def emergency_fund():
    user_id = session["user_id"]
    with connect_db() as db:
        fund = db.execute("SELECT * FROM emergency_fund WHERE user_id = ?", (user_id,)).fetchone()
    return render_template("emergency_fund.html", fund=fund)

@app.route("/subscriptions", methods=["GET", "POST"])
@login_required
def subscriptions():
    user_id = session["user_id"]
    if request.method == "POST":
        service_name = request.form.get("service_name", "").strip()
        amount_text = request.form.get("amount", "")
        renewal_date = request.form.get("renewal_date", "")

        try:
            amount = float(amount_text)
            parsed_date = date.fromisoformat(renewal_date)
        except (ValueError, TypeError):
            flash("Enter valid details.")
            return redirect(url_for("subscriptions"))

        with connect_db() as db:
            db.execute("INSERT INTO subscriptions (user_id, service_name, amount, renewal_date) VALUES (?, ?, ?, ?)", (user_id, service_name, amount, parsed_date.isoformat()))
        flash("Subscription added!")
        return redirect(url_for("subscriptions"))

    with connect_db() as db:
        rows = db.execute("SELECT * FROM subscriptions WHERE user_id = ?", (user_id,)).fetchall()
    return render_template("subscriptions.html", subs=rows)

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user_id = session["user_id"]
    if request.method == "POST":
        file = request.files.get("profile_pic")
        if file and file.filename != '':
            filename = f"user_{user_id}_{file.filename}"
            upload_folder = os.path.join(BASE_DIR, "static", "uploads")
            os.makedirs(upload_folder, exist_ok=True)
            file.save(os.path.join(upload_folder, filename))

            with connect_db() as db:
                db.execute("UPDATE users SET profile_pic = ? WHERE id = ?", (filename, user_id))
            flash("Profile picture updated!")
            return redirect(url_for("profile"))

    with connect_db() as db:
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return render_template("profile.html", user=user)

init_db()

if __name__ == "__main__":
    app.run(debug=True)
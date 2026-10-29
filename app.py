
import os
import csv
import math
import hmac
import secrets
import sqlite3
from functools import wraps
from datetime import date, datetime

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    abort,
)
from werkzeug.security import generate_password_hash, check_password_hash


# --------------------------------------------------
# APP CONFIGURATION
# --------------------------------------------------

app = Flask(__name__)

app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "CHANGE-THIS-TO-A-LONG-RANDOM-SECRET-BEFORE-DEPLOYING",
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "expenses.db")
CSV_FILE = os.path.join(BASE_DIR, "expenses.csv")
WALLET_FILE = os.path.join(BASE_DIR, "wallet.csv")


# --------------------------------------------------
# DATABASE
# --------------------------------------------------

def connect_db():
    db = sqlite3.connect(DB_FILE)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db():
    with connect_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                amount REAL NOT NULL CHECK(amount > 0),
                FOREIGN KEY(user_id) REFERENCES users(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS wallet_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                type TEXT NOT NULL
                    CHECK(type IN ('Deposit', 'Withdraw')),
                note TEXT NOT NULL,
                amount REAL NOT NULL CHECK(amount > 0),
                FOREIGN KEY(user_id) REFERENCES users(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                month TEXT NOT NULL,
                amount REAL NOT NULL CHECK(amount > 0),
                UNIQUE(user_id, category, month),
                FOREIGN KEY(user_id) REFERENCES users(id)
                    ON DELETE CASCADE
            );
        """)


# --------------------------------------------------
# IMPORT OLD CSV DATA FOR FIRST ACCOUNT
# --------------------------------------------------

def import_old_csv_data(user_id):
    """Import old CSV records into the first account."""

    with connect_db() as db:

        if os.path.exists(CSV_FILE):
            with open(
                CSV_FILE, newline="", encoding="utf-8"
            ) as file:
                for item in csv.DictReader(file):
                    try:
                        amount = float(item["amount"])
                        expense_date = date.fromisoformat(
                            item["date"]
                        )
                        title = item["title"].strip()
                        category = item["category"].strip()

                        if (
                            not math.isfinite(amount)
                            or amount <= 0
                            or not title
                            or not category
                        ):
                            continue

                        db.execute("""
                            INSERT INTO expenses
                            (user_id, date, title, category, amount)
                            VALUES (?, ?, ?, ?, ?)
                        """, (
                            user_id,
                            expense_date.isoformat(),
                            title,
                            category,
                            amount,
                        ))

                    except (ValueError, KeyError, TypeError):
                        continue

        if os.path.exists(WALLET_FILE):
            with open(
                WALLET_FILE, newline="", encoding="utf-8"
            ) as file:
                for item in csv.DictReader(file):
                    try:
                        amount = float(item["amount"])
                        transaction_type = item["type"]
                        transaction_date = item["date"]
                        note = item.get("note", "")

                        if (
                            not math.isfinite(amount)
                            or amount <= 0
                            or transaction_type
                            not in ("Deposit", "Withdraw")
                        ):
                            continue

                        db.execute("""
                            INSERT INTO wallet_transactions
                            (user_id, date, type, note, amount)
                            VALUES (?, ?, ?, ?, ?)
                        """, (
                            user_id,
                            transaction_date,
                            transaction_type,
                            note,
                            amount,
                        ))

                    except (ValueError, KeyError, TypeError):
                        continue


# --------------------------------------------------
# CSRF PROTECTION
# --------------------------------------------------

@app.before_request
def security_checks():
    if request.method == "POST":
        sent_token = request.form.get("csrf_token", "")
        saved_token = session.get("csrf_token", "")

        if (
            not saved_token
            or not hmac.compare_digest(sent_token, saved_token)
        ):
            abort(
                400,
                description=(
                    "Invalid form token. Refresh the page and try again."
                ),
            )


@app.context_processor
def template_helpers():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)

    return {"csrf_token": session["csrf_token"]}


# --------------------------------------------------
# LOGIN REQUIRED DECORATOR
# --------------------------------------------------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue.")
            return redirect(url_for("login"))

        return view(*args, **kwargs)

    return wrapped


# --------------------------------------------------
# REGISTER
# --------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if len(username) < 3 or len(username) > 40:
            flash("Username must be between 3 and 40 characters.")
            return redirect(url_for("register"))

        if len(password) < 8:
            flash("Password must contain at least 8 characters.")
            return redirect(url_for("register"))

        with connect_db() as db:
            first_user = (
                db.execute(
                    "SELECT COUNT(*) FROM users"
                ).fetchone()[0] == 0
            )

            try:
                cursor = db.execute("""
                    INSERT INTO users
                    (username, password_hash, created_at)
                    VALUES (?, ?, ?)
                """, (
                    username,
                    generate_password_hash(password),
                    datetime.now().isoformat(timespec="seconds"),
                ))

                user_id = cursor.lastrowid

            except sqlite3.IntegrityError:
                flash("That username is already taken.")
                return redirect(url_for("register"))

        if first_user:
            import_old_csv_data(user_id)

        session.clear()
        session["user_id"] = user_id
        session["username"] = username
        session["csrf_token"] = secrets.token_urlsafe(32)

        flash("Account created successfully!")
        return redirect(url_for("index"))

    return render_template("register.html")


# --------------------------------------------------
# LOGIN
# --------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        with connect_db() as db:
            user = db.execute(
                "SELECT * FROM users WHERE username = ?",
                (username,),
            ).fetchone()

        if user and check_password_hash(
            user["password_hash"], password
        ):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["csrf_token"] = secrets.token_urlsafe(32)

            flash("Welcome back!")
            return redirect(url_for("index"))

        flash("Invalid username or password.")
        return redirect(url_for("login"))

    return render_template("login.html")


# --------------------------------------------------
# LOGOUT
# --------------------------------------------------

@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("You have logged out.")
    return redirect(url_for("login"))


# --------------------------------------------------
# DATABASE HELPERS
# --------------------------------------------------

def get_expenses(user_id):
    with connect_db() as db:
        rows = db.execute("""
            SELECT * FROM expenses
            WHERE user_id = ?
            ORDER BY date DESC, id DESC
        """, (user_id,)).fetchall()

    return [dict(row) for row in rows]


def get_transactions(user_id):
    with connect_db() as db:
        rows = db.execute("""
            SELECT * FROM wallet_transactions
            WHERE user_id = ?
            ORDER BY id DESC
        """, (user_id,)).fetchall()

    return [dict(row) for row in rows]


def calculate_wallet_balance(transactions):
    balance = 0.0

    for transaction in transactions:
        amount = float(transaction["amount"])

        if transaction["type"] == "Deposit":
            balance += amount
        elif transaction["type"] == "Withdraw":
            balance -= amount

    return balance


# --------------------------------------------------
# DASHBOARD - FIRST PAGE AFTER LOGIN
# --------------------------------------------------


@app.route("/")
@login_required
def index():
    user_id = session["user_id"]

    expenses = get_expenses(user_id)
    transactions = get_transactions(user_id)
    today = date.today()

    # Overall expenses
    total = sum(float(e["amount"]) for e in expenses)

    # Current month expenses
    current_month = today.strftime("%Y-%m")

    monthly_total = sum(
        float(e["amount"])
        for e in expenses
        if e["date"][:7] == current_month
    )

    # Category-wise expenses
    categories = {}

    for expense in expenses:
        category = expense["category"]
        categories[category] = (
            categories.get(category, 0)
            + float(expense["amount"])
        )

    # Last 6 months chart data
    monthly_labels = []
    monthly_values = []

    for offset in range(5, -1, -1):
        month_index = today.year * 12 + today.month - 1 - offset
        year = month_index // 12
        month = month_index % 12 + 1

        month_date = date(year, month, 1)
        month_key = month_date.strftime("%Y-%m")

        monthly_labels.append(month_date.strftime("%b %Y"))

        month_sum = sum(
            float(e["amount"])
            for e in expenses
            if e["date"][:7] == month_key
        )

        monthly_values.append(round(month_sum, 2))

    # Average monthly spending over the displayed 6 months
    average_monthly = round(sum(monthly_values) / 6, 2)

    # Wallet balance
    wallet_balance = calculate_wallet_balance(transactions)

    return render_template(
        "dashboard.html",
        expenses=expenses,
        total=total,
        monthly_total=monthly_total,
        categories=categories,
        today=today.isoformat(),
        wallet_balance=wallet_balance,
        transactions=transactions,
        monthly_labels=monthly_labels,
        monthly_values=monthly_values,
        average_monthly=average_monthly,
        category_labels=list(categories.keys()),
        category_values=[
            round(value, 2) for value in categories.values()
        ],
    )


# --------------------------------------------------
# HOME PAGE
# --------------------------------------------------

@app.route("/home")
@login_required
def home():
    return render_template("home.html")


# --------------------------------------------------
# EXPENSES PAGE
# --------------------------------------------------

@app.route("/expenses")
@login_required
def expenses_page():
    expenses = get_expenses(session["user_id"])

    return render_template(
        "expenses.html",
        expenses=expenses,
    )


# --------------------------------------------------
# ADD EXPENSE
# --------------------------------------------------

@app.route("/add", methods=["POST"])
@login_required
def add_expense():
    title = request.form.get("title", "").strip()
    category = request.form.get("category", "").strip()
    expense_date = request.form.get("date", "")
    amount_text = request.form.get("amount", "")

    try:
        amount = float(amount_text)

        if not math.isfinite(amount) or amount <= 0:
            raise ValueError

        parsed_date = date.fromisoformat(expense_date)

    except (ValueError, TypeError):
        flash("Enter a valid date and an amount greater than zero.")
        return redirect(url_for("expenses_page"))

    if not title or not category:
        flash("Enter an expense name and choose a category.")
        return redirect(url_for("expenses_page"))

    with connect_db() as db:
        db.execute("""
            INSERT INTO expenses
            (user_id, date, title, category, amount)
            VALUES (?, ?, ?, ?, ?)
        """, (
            session["user_id"],
            parsed_date.isoformat(),
            title,
            category,
            amount,
        ))

    flash("Expense added successfully!")
    return redirect(url_for("expenses_page"))


# --------------------------------------------------
# DELETE EXPENSE
# --------------------------------------------------

@app.route("/delete/<int:expense_id>", methods=["POST"])
@login_required
def delete_expense(expense_id):
    with connect_db() as db:
        cursor = db.execute("""
            DELETE FROM expenses
            WHERE id = ? AND user_id = ?
        """, (
            expense_id,
            session["user_id"],
        ))

    if cursor.rowcount == 0:
        flash("Expense not found.")
    else:
        flash("Expense deleted.")

    return redirect(url_for("expenses_page"))


# --------------------------------------------------
# WALLET PAGE
# --------------------------------------------------

@app.route("/wallet-page")
@login_required
def wallet_page():
    transactions = get_transactions(session["user_id"])
    balance = calculate_wallet_balance(transactions)

    return render_template(
        "wallet.html",
        transactions=transactions,
        wallet_balance=balance,
    )


# --------------------------------------------------
# WALLET DEPOSIT / WITHDRAW ACTION
# --------------------------------------------------

@app.route("/wallet", methods=["POST"])
@login_required
def wallet_action():
    transaction_type = request.form.get("type", "")
    note = request.form.get("note", "").strip()
    amount_text = request.form.get("amount", "")

    if transaction_type not in ("Deposit", "Withdraw"):
        flash("Choose Deposit or Withdraw.")
        return redirect(url_for("wallet_page"))

    try:
        amount = float(amount_text)

        if not math.isfinite(amount) or amount <= 0:
            raise ValueError

    except (ValueError, TypeError):
        flash("Enter a valid wallet amount greater than zero.")
        return redirect(url_for("wallet_page"))

    user_id = session["user_id"]

    with connect_db() as db:
        rows = db.execute("""
            SELECT type, amount
            FROM wallet_transactions
            WHERE user_id = ?
        """, (user_id,)).fetchall()

        balance = calculate_wallet_balance(
            [dict(row) for row in rows]
        )

        if transaction_type == "Withdraw" and amount > balance:
            flash("Insufficient demo wallet balance.")
            return redirect(url_for("wallet_page"))

        db.execute("""
            INSERT INTO wallet_transactions
            (user_id, date, type, note, amount)
            VALUES (?, ?, ?, ?, ?)
        """, (
            user_id,
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            transaction_type,
            note or (
                "Demo deposit"
                if transaction_type == "Deposit"
                else "Demo withdrawal"
            ),
            amount,
        ))

    flash(
        f"Demo {transaction_type.lower()} recorded successfully."
    )
    return redirect(url_for("wallet_page"))


# --------------------------------------------------
# PROFILE PAGE
# --------------------------------------------------

@app.route("/profile")
@login_required
def profile():
    return render_template(
        "profile.html",
        username=session.get("username", ""),
    )

# --------------------------------------------------
# MONTHLY BUDGET PAGE
# --------------------------------------------------

@app.route("/budget", methods=["GET", "POST"])
@login_required
def budget_page():
    user_id = session["user_id"]
    current_month = date.today().strftime("%Y-%m")

    if request.method == "POST":
        category = request.form.get("category", "").strip()
        amount_text = request.form.get("amount", "")

        try:
            amount = float(amount_text)

            if (
                not math.isfinite(amount)
                or amount <= 0
                or amount > 1000000000
            ):
                raise ValueError

        except (ValueError, TypeError):
            flash("Enter a valid budget amount greater than zero.")
            return redirect(url_for("budget_page"))

        if not category or len(category) > 50:
            flash("Enter a category name (maximum 50 characters).")
            return redirect(url_for("budget_page"))

        with connect_db() as db:
            db.execute("""
                INSERT INTO budgets (user_id, category, month, amount)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, category, month)
                DO UPDATE SET amount = excluded.amount
            """, (user_id, category, current_month, amount))

        flash(f"Budget saved for {category}!")
        return redirect(url_for("budget_page"))

    # Current month's expenses grouped by category
    expenses = get_expenses(user_id)
    category_spending = {}

    for expense in expenses:
        if expense["date"][:7] == current_month:
            category = expense["category"]
            category_spending[category] = (
                category_spending.get(category, 0)
                + float(expense["amount"])
            )

    # Only this user's budgets for the current month
    with connect_db() as db:
        rows = db.execute("""
            SELECT category, amount
            FROM budgets
            WHERE user_id = ? AND month = ?
            ORDER BY category
        """, (user_id, current_month)).fetchall()

    budgets = []

    for row in rows:
        category = row["category"]
        limit_amount = float(row["amount"])
        spent = category_spending.get(category, 0.0)

        percent = (spent / limit_amount) * 100
        remaining = limit_amount - spent

        if percent >= 100:
            status = "over"
        elif percent >= 80:
            status = "warning"
        else:
            status = "safe"

        budgets.append({
            "category": category,
            "amount": limit_amount,
            "spent": spent,
            "remaining": remaining,
            "percent": round(percent, 1),
            "bar_percent": min(round(percent, 1), 100),
            "status": status,
        })

    return render_template(
        "budgets.html",
        budgets=budgets,
        current_month=current_month,
        category_spending=category_spending,
    )


   init_db()
# --------------------------------------------------
# START APPLICATION
# IMPORTANT: Keep this block at the very bottom.
# --------------------------------------------------

if __name__ == "__main__":
    init_db()
    app.run(debug=True)


import csv
import math
import os
from datetime import date, datetime

from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = "student-expense-tracker-key"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, "expenses.csv")
WALLET_FILE = os.path.join(BASE_DIR, "wallet.csv")

EXPENSE_FIELDS = ["id", "date", "title", "category", "amount"]
WALLET_FIELDS = ["id", "date", "type", "note", "amount"]


def setup_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=EXPENSE_FIELDS)
            writer.writeheader()


def setup_wallet():
    if not os.path.exists(WALLET_FILE):
        with open(WALLET_FILE, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=WALLET_FIELDS)
            writer.writeheader()


def read_expenses():
    setup_csv()
    with open(CSV_FILE, "r", newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def save_expenses(expenses):
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=EXPENSE_FIELDS)
        writer.writeheader()
        writer.writerows(expenses)


def read_wallet():
    setup_wallet()
    with open(WALLET_FILE, "r", newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def wallet_balance(transactions):
    balance = 0.0
    for transaction in transactions:
        amount = float(transaction["amount"])
        if transaction["type"] == "Deposit":
            balance += amount
        elif transaction["type"] == "Withdraw":
            balance -= amount
    return balance


@app.route("/")
def index():
    expenses = read_expenses()
    transactions = read_wallet()
    today = date.today()

    total = sum(float(e["amount"]) for e in expenses)
    monthly_total = sum(
        float(e["amount"])
        for e in expenses
        if e["date"][:7] == today.strftime("%Y-%m")
    )

    categories = {}
    for expense in expenses:
        category = expense["category"]
        categories[category] = (
            categories.get(category, 0) + float(expense["amount"])
        )

    return render_template(
        "index.html",
        expenses=expenses,
        total=total,
        monthly_total=monthly_total,
        categories=categories,
        today=today.isoformat(),
        wallet_balance=wallet_balance(transactions),
        transactions=transactions
    )


@app.route("/add", methods=["POST"])
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
        flash("Please enter a valid date and an amount greater than zero.")
        return redirect(url_for("index"))

    if not title or not category:
        flash("Please enter an expense name and choose a category.")
        return redirect(url_for("index"))

    expenses = read_expenses()
    next_id = max((int(e["id"]) for e in expenses), default=0) + 1

    expenses.append({
        "id": str(next_id),
        "date": parsed_date.isoformat(),
        "title": title,
        "category": category,
        "amount": f"{amount:.2f}"
    })
    save_expenses(expenses)
    flash("Expense added successfully!")
    return redirect(url_for("index"))


@app.route("/delete/<int:expense_id>", methods=["POST"])
def delete_expense(expense_id):
    expenses = read_expenses()
    updated = [e for e in expenses if int(e["id"]) != expense_id]

    if len(updated) == len(expenses):
        flash("Expense not found.")
    else:
        save_expenses(updated)
        flash("Expense deleted.")

    return redirect(url_for("index"))


@app.route("/wallet", methods=["POST"])
def wallet_action():
    transaction_type = request.form.get("type", "")
    note = request.form.get("note", "").strip()
    amount_text = request.form.get("amount", "")

    if transaction_type not in ("Deposit", "Withdraw"):
        flash("Please choose Deposit or Withdraw.")
        return redirect(url_for("index"))

    try:
        amount = float(amount_text)
        if not math.isfinite(amount) or amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        flash("Enter a valid wallet amount greater than zero.")
        return redirect(url_for("index"))

    transactions = read_wallet()
    balance = wallet_balance(transactions)

    if transaction_type == "Withdraw" and amount > balance:
        flash("Insufficient wallet balance. Please deposit first.")
        return redirect(url_for("index"))

    next_id = max(
        (int(t["id"]) for t in transactions), default=0
    ) + 1

    transactions.append({
        "id": str(next_id),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "type": transaction_type,
        "note": note or (
            "Savings deposit" if transaction_type == "Deposit"
            else "Wallet withdrawal"
        ),
        "amount": f"{amount:.2f}"
    })

    with open(WALLET_FILE, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=WALLET_FIELDS)
        writer.writeheader()
        writer.writerows(transactions)

    flash(f"{transaction_type} recorded successfully!")
    return redirect(url_for("index"))


if __name__ == "__main__":
    setup_csv()
    setup_wallet()
    app.run(debug=True)

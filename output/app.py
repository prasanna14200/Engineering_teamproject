```python
import gradio as gr
import datetime
import accounts

class Transaction:
    def __init__(self, date, symbol, quantity, price, type):
        self.date = date
        self.symbol = symbol
        self.quantity = quantity
        self.price = price
        self.type = type

class Account:
    def __init__(self):
        self.account_id = 0
        self.balance = 0.0
        self.holdings = {}
        self.transactions = []

    @classmethod
    def create_account(cls):
        account = cls()
        account.account_id += 1
        return account

    def deposit(self, amount):
        self.balance += amount

    def withdraw(self, amount):
        if self.balance >= amount:
            self.balance -= amount
        else:
            raise ValueError("Insufficient balance")

    def buy_shares(self, symbol, quantity):
        price = get_share_price(symbol)
        if self.balance >= price * quantity:
            if symbol in self.holdings:
                self.holdings[symbol] += quantity
            else:
                self.holdings[symbol] = quantity
            self.transactions.append(Transaction(datetime.date.today(), symbol, quantity, price, "buy"))
            self.balance -= price * quantity
        else:
            raise ValueError("Insufficient balance")

    def sell_shares(self, symbol, quantity):
        if symbol in self.holdings and self.holdings[symbol] >= quantity:
            price = get_share_price(symbol)
            self.holdings[symbol] -= quantity
            self.transactions.append(Transaction(datetime.date.today(), symbol, quantity, price, "sell"))
            self.balance += price * quantity
        else:
            raise ValueError("Insufficient shares")

    def get_portfolio_value(self):
        portfolio_value = 0.0
        for symbol, quantity in self.holdings.items():
            price = get_share_price(symbol)
            portfolio_value += price * quantity
        return portfolio_value

    def get_profit_loss(self):
        return self.get_portfolio_value() - self.balance

    def get_holdings(self):
        return self.holdings

    def get_transactions(self):
        return self.transactions

def get_share_price(symbol):
    share_prices = {
        "AAPL": 150.0,
        "TSLA": 2000.0,
        "GOOGL": 3000.0
    }
    return share_prices.get(symbol, None)

account = accounts.Account.create_account()

def create_account():
    global account
    account = accounts.Account.create_account()
    return account

def deposit(amount):
    account.deposit(amount)
    return "Deposit successful"

def withdraw(amount):
    try:
        account.withdraw(amount)
        return "Withdrawal successful"
    except ValueError as e:
        return str(e)

def buy_shares(symbol, quantity):
    try:
        account.buy_shares(symbol, quantity)
        return "Buy successful"
    except ValueError as e:
        return str(e)

def sell_shares(symbol, quantity):
    try:
        account.sell_shares(symbol, quantity)
        return "Sell successful"
    except ValueError as e:
        return str(e)

def get_portfolio_value():
    return account.get_portfolio_value()

def get_profit_loss():
    return account.get_profit_loss()

def get_holdings():
    return account.get_holdings()

def get_transactions():
    return account.get_transactions()

demo = gr.Blocks()
with demo:
    gr.Markdown("Account Management System")
    gr.HTML("<h2>Account Information</h2>")
    account_info = grAccordion(label="Account Info")
    with account_info:
        gr.Textbox(label="Account ID", value=str(account.account_id))
        gr.Textbox(label="Balance", value=str(account.balance))
    gr.HTML("<h2>Transactions</h2>")
    transaction_button = gr.Button("Deposit")
    transaction_button.click(create_account)
    with gr.Accordion("Transactions"):
        with gr.Group():
            with gr.Row():
                with gr.Column():
                    gr.Textbox(label="Amount", placeholder="Enter amount to deposit")
                    deposit_button = gr.Button("Deposit")
                    deposit_button.click(lambda x: gr.update(value=deposit(gr.inputs["Amount"])))
                with gr.Column():
                    gr.Textbox(label="Amount", placeholder="Enter amount to withdraw")
                    withdraw_button = gr.Button("Withdraw")
                    withdraw_button.click(lambda x: gr.update(value=withdraw(gr.inputs["Amount"])))
            with gr.Row():
                with gr.Column():
                    gr.Textbox(label="Symbol", placeholder="AAPL, TSLA, GOOGL")
                    gr.Textbox(label="Quantity", placeholder="Enter quantity to buy")
                    buy_button = gr.Button("Buy")
                    buy_button.click(lambda x: gr.update(value=buy_shares(gr.inputs["Symbol"], gr.inputs["Quantity"])))
                with gr.Column():
                    gr.Textbox(label="Symbol", placeholder="AAPL, TSLA, GOOGL")
                    gr.Textbox(label="Quantity", placeholder="Enter quantity to sell")
                    sell_button = gr.Button("Sell")
                    sell_button.click(lambda x: gr.update(value=sell_shares(gr.inputs["Symbol"], gr.inputs["Quantity"])))
            with gr.Row():
                with gr.Column():
                    gr.Textbox(label="Portfolio Value", value=str(get_portfolio_value()))
                with gr.Column():
                    gr.Textbox(label="Profit/Loss", value=str(get_profit_loss()))
                with gr.Column():
                    gr.Textbox(label="Holdings", value=str(get_holdings()))
                with gr.Column():
                    gr.Textbox(label="Transactions", value=str(get_transactions()))
demo.launch()
```
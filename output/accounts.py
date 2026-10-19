import datetime
import gradio as gr


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

account = Account.create_account()
account.deposit(2000.0)
account.buy_shares("AAPL", 10)
account.sell_shares("AAPL", 5)
print("Portfolio Value: ", account.get_portfolio_value())
print("Profit/Loss: ", account.get_profit_loss())
print("Holdings: ", account.get_holdings())
print("Transactions: ", account.get_transactions())
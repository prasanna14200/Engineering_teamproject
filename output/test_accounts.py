```python
import unittest
import sys
sys.path.insert(0, './')
from accounts import Account

class TestAccount(unittest.TestCase):

    def setUp(self):
        self.account = Account.create_account()

    def test_deposit(self):
        self.account.deposit(1000.0)
        self.assertEqual(self.account.balance, 1000.0)

    def test_withdraw(self):
        self.account.deposit(1000.0)
        self.account.withdraw(500.0)
        self.assertEqual(self.account.balance, 500.0)

    def test_buy_shares(self):
        self.account.deposit(15000.0)
        self.account.buy_shares('AAPL', 10)
        self.assertEqual(self.account.holdings['AAPL'], 10)

    def test_sell_shares(self):
        self.account.deposit(15000.0)
        self.account.buy_shares('AAPL', 10)
        self.account.sell_shares('AAPL', 5)
        self.assertEqual(self.account.holdings['AAPL'], 5)

    def test_get_portfolio_value(self):
        self.account.deposit(15000.0)
        self.account.buy_shares('AAPL', 10)
        self.assertAlmostEqual(self.account.get_portfolio_value(), 15000.0)

    def test_get_profit_loss(self):
        self.account.deposit(15000.0)
        self.account.buy_shares('AAPL', 10)
        self.assertAlmostEqual(self.account.get_profit_loss(), -12000.0)

    def test_get_holdings(self):
        self.account.deposit(15000.0)
        self.account.buy_shares('AAPL', 10)
        self.assertEqual(self.account.get_holdings(), {'AAPL': 10})

    def test_get_transactions(self):
        self.account.deposit(15000.0)
        self.account.buy_shares('AAPL', 10)
        self.assertEqual(len(self.account.get_transactions()), 1)

if __name__ == '__main__':
    unittest.main()
```
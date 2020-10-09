import csv
import json
import logging
import os
import requests
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
from typing import List

TRANSFERWISE_BASE_URI = 'https://api.transferwise.com'
FIREFLY_BASE_URI = 'https://firefly-iii-a.herokuapp.com'


def main():
    load_dotenv('.env')
    validate_dotenv()

    if not os.path.exists('categories-map.json'):
        logging.error("categories-map.json not found, exiting.")
        exit(1)
    with open('categories-map.json', 'r') as fp:
        category_map = json.load(fp)

    if not os.path.exists('accounts.json'):
        logging.error("accounts.json not found, exiting.")
        exit(1)
    with open('accounts.json', 'r') as fp:
        currency_accounts = json.load(fp)

    user_id = get_user_id()
    account_id = get_account_id()
    start = datetime.utcnow() - timedelta(days=14)
    today = datetime.utcnow()

    for currency in currency_accounts:
        transactions = fetch_txs_from_transferwise(user_id, account_id, currency, start, today, category_map,
                                                   currency_accounts)
        for transaction in transactions:
            if transaction.currency_code not in currency_accounts:
                logging.error(f"{transaction.currency_code} not found in accounts.json")
                exit(1)

            account_id = currency_accounts[transaction.currency_code]
            post_tx_to_firefly(transaction, account_id)


def validate_dotenv():
    """
    Check that either the .env or ENV contains the required values.
    :return:
    """

    def check_string(key: str, expected_type: str):
        try:
            if os.environ[key] is None or os.environ[key] == '':
                raise KeyError()
            if expected_type == 'str':
                str(os.environ[key])
            if expected_type == 'int':
                int(os.environ[key])
            if expected_type == 'bool':
                if str(os.environ[key]).lower() not in ['true', 'false']:
                    raise ValueError
        except (KeyError, ValueError) as e:
            logging.error(f"{key} was not set correctly in .env or ENV, please provide a valid {expected_type}.")
            exit(1)

    check_string('TRANSFERWISE_TOKEN', 'str')
    check_string('FIREFLY_TOKEN', 'str')
    check_string('FETCH_PERIOD', 'int')
    check_string('FETCH_CURRENCIES', 'str')
    check_string('CONVERT_AMOUNTS', 'bool')
    check_string('BASE_CURRENCY', 'GBP')


class Transaction:
    id: str
    tx_type: str
    date: datetime
    amount: float
    currency_code: str
    category_name: str
    foreign_code: str
    foreign_amount: float
    raw_category: str
    budget_name: str
    description: str
    notes: str
    source_id: str
    destination_id: str
    reconciled: bool

    def __init__(self, id: str, tx_type: str, date: datetime, amount: float, currency_code: str, foreign_code: str,
                 foreign_amount: float, raw_category: str, description: str, notes: str, category_map: {},
                 accounts_map: {}):
        self.id = id
        self.tx_type = tx_type
        self.date = date.replace(microsecond=0)
        self.amount = amount
        self.currency_code = currency_code
        self.foreign_code = foreign_code
        self.foreign_amount = foreign_amount
        self.description = description
        self.notes = notes
        self.source_id = self.determine_account(accounts_map) if type == 'DEBIT' else None
        self.destination_id = None if type == 'DEBIT' else self.determine_account(accounts_map)
        self.reconciled = True
        self.raw_category = raw_category
        self.category_name = self.determine_category(category_map)
        self.budget_name = self.determine_budget(category_map)

    def determine_category(self, category_map: {}):
        if self.raw_category in category_map:
            return category_map[self.raw_category]['category']
        if 'Converted' in self.description or self.description == 'Sent money to Homerental Nordic AB':
            return None
        return 'Other'

    def determine_budget(self, category_map: {}):
        if self.category_name in category_map:
            return category_map[self.raw_category]['budget']
        if 'Converted' in self.description or self.description == 'Sent money to Homerental Nordic AB':
            return None
        return 'Other'

    def determine_account(self, account_map: {}):
        return account_map[self.currency_code]


def get_user_id() -> str:
    return "3750372"


def get_account_id() -> str:
    return "4067808"


def fetch_txs_from_transferwise(user_id: str, account_id: str, currency: str, start: datetime, end: datetime,
                                category_map: {}, accounts: {}) -> \
        List[Transaction]:
    """
    Fetch transactions from TransferWise
    :param user_id:
    :param account_id:
    :param currency:
    :param start:
    :param end:
    :return:
    """
    start = start.replace(microsecond=0)
    end = end.replace(microsecond=0)
    uri = f"/v3/profiles/{user_id}/borderless-accounts/{account_id}/statement.json?intervalStart={start.isoformat()}Z&intervalEnd={end.isoformat()}Z&currency={currency}"
    res = requests.get(TRANSFERWISE_BASE_URI + uri, headers={
        'Authorization': 'Bearer ' + os.environ['TRANSFERWISE_TOKEN']
    })
    if res.status_code == 401:
        logging.error('Unauthorized response fetching transactions, check API token.')
        exit()
    if res.status_code != 200:
        logging.error(f'Failed to fetch transactions for a non-auth reason. {res.status_code}: {res.content.decode()}')
        exit()

    body = json.loads(res.content.decode("utf-8"))
    transactions = []
    for row in body['transactions']:
        reference = row['referenceNumber']
        amount = abs(row['amount']['value'])
        currency_code = row['amount']['currency']
        tx_type = row['type']
        category = row['details']['category'] if 'category' in row['details'] else ''
        date = datetime.strptime(row['date'], '%Y-%m-%dT%H:%M:%S.%fZ')
        description = row['details']['description'].replace("Card transaction of ", '')
        raw = json.dumps(row)
        foreign_code = None
        foreign_amount = 0.0
        if bool(os.environ['CONVERT_AMOUNTS']) is True:
            foreign_code = os.environ['BASE_CURRENCY']
            rate = fetch_exchange_rate_from_yahoo(from_code=currency_code, to_code=foreign_code, date=date)
            foreign_amount = round(rate * amount, 2)
        tx = Transaction(id=reference, amount=amount, tx_type=tx_type, raw_category=category, date=date,
                         description=description, currency_code=currency_code, foreign_code=foreign_code,
                         foreign_amount=foreign_amount, notes=raw, category_map=category_map, accounts_map=accounts)
        transactions.append(tx)

    return transactions


def fetch_exchange_rate_from_yahoo(from_code: str, to_code: str, date: datetime, retry=0) -> float:
    """
    Fetch a closing exchange rate from Yahoo Finance.
    :param from_code:
    :param to_code:
    :param date:
    :param retry:
    :return:
    """
    if retry > 4:
        logging.error("Failed to fetch from Yahoo after 5 attempts, giving up.")
    start = int(date.timestamp())
    end = int((date + timedelta(days=2)).timestamp())
    res = requests.get(
        f'https://query1.finance.yahoo.com/v7/finance/download/{from_code}{to_code}=X?period1={start}&period2={end}&interval=1d&events=history')
    if res.status_code != 200:
        time.sleep(5)
        return fetch_exchange_rate_from_yahoo(from_code, to_code, date, retry + 1)

    reader = csv.reader(res.content.decode().split("\n"))
    for row in list(reader)[1:]:
        if row[1] == 'null':
            continue
        return float(row[4])

    logging.error("Failed to fetch from Yahoo due to null results. Refusing to convert this transaction.")
    return 0.0


def post_tx_to_firefly(tx: Transaction, account_id: str) -> bool:
    """
    Form the Transaction object ready for ingestion by Firefly and post.
    :param tx:
    :param account_id:
    :return:
    """
    tx_body = {
        "external_id": tx.id,
        "type": "deposit" if tx.tx_type in 'CREDIT' else 'withdrawal',
        "date": tx.date.isoformat()+"Z",
        "amount": str(tx.amount),
        "currency_code": tx.currency_code,
        "category_name": tx.category_name,
        "budget_name": tx.budget_name,
        "description": tx.description,
        "notes": tx.notes,
        "source_id": account_id if tx.tx_type == 'DEBIT' else None,
        "destination_id": None if tx.tx_type == 'DEBIT' else account_id,
        "reconciled": True,
    }

    # Even if these were attempted, if the amount is 0.0 then we failed the Yahoo fetch, don't attempt it.
    if tx.foreign_code != '' and tx.foreign_amount != 0.0:
        pass
        tx_body['foreign_currency_code'] = tx.foreign_code
        tx_body['foreign_amount'] = str(tx.foreign_amount)

    payload = {
        "error_if_duplicate_hash": True,
        "apply_rules": False,
        "group_title": "Spending",
        "transactions": [tx_body]
    }

    res = requests.post(FIREFLY_BASE_URI + "/api/v1/transactions", json.dumps(payload), headers={
        'Authorization': 'Bearer ' + os.environ['FIREFLY_TOKEN'],
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    })
    if res.status_code == 422:
        # Duplicate
        return True
    if res.status_code == 401:
        logging.error('Unauthorized response posting transactions, check API token.')
        exit()
    if res.status_code != 200:
        logging.error(f'Failed to post transactions for a non-auth reason. {res.status_code}: {res.content.decode()}')
        exit()
    return True


if __name__ == '__main__':
    main()

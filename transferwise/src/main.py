import csv
import json
import logging
import os
import urllib3
import time
from datetime import datetime, timedelta
from typing import List

# Globals
TRANSFERWISE_BASE_URI = None
FIREFLY_BASE_URI = None
category_map = {}
currency_accounts = {}

logging.getLogger().setLevel(logging.INFO)
http = urllib3.PoolManager()


def main():
    global TRANSFERWISE_BASE_URI
    global FIREFLY_BASE_URI
    global category_map
    global currency_accounts

    validate_env()

    TRANSFERWISE_BASE_URI = os.environ['TRANSFERWISE_BASE_URI']
    FIREFLY_BASE_URI = os.environ['FIREFLY_BASE_URI']

    if not os.path.exists('config/categories-map.json'):
        logging.error("categories-map.json not found, exiting.")
        exit(1)
    with open('config/categories-map.json', 'r') as fp:
        category_map = json.load(fp)

    if not os.path.exists('config/accounts.json'):
        logging.error("accounts.json not found, exiting.")
        exit(1)
    with open('config/accounts.json', 'r') as fp:
        currency_accounts = json.load(fp)

    tranferwise_user_id = get_user_id()
    tranferwise_account_id = get_account_id()

    # Calculate the difference in days, batch it by 180 if larger
    end = datetime.utcnow()
    start = datetime.utcnow() - timedelta(days=int(os.environ['FETCH_PERIOD'])) - timedelta(seconds=1)
    while (end - start).days > 0:
        period_length = min((end - start).days % 180, 180)
        period_end = start + timedelta(days=period_length)
        for currency in currency_accounts:
            logging.info(
                f"Fetching {currency} transactions between {start.strftime('%Y-%m-%d')} and {period_end.strftime('%Y-%m-%d')}")
            transactions = fetch_txs_from_transferwise(tranferwise_user_id, tranferwise_account_id, currency, start,
                                                       period_end)

            logging.info(f"Writing {len(transactions)} transactions.")
            for transaction in transactions:
                if transaction.currency_code not in currency_accounts:
                    logging.error(f"{transaction.currency_code} not found in accounts.json")
                    exit(1)

                account_id = currency_accounts[transaction.currency_code]
                post_tx_to_firefly(transaction, account_id)

        start = start + timedelta(days=period_length + 1)


def validate_env():
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

    check_string('TRANSFERWISE_BASE_URI', 'str')
    check_string('FIREFLY_BASE_URI', 'str')
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
                 foreign_amount: float, raw_category: str, description: str, notes: str):
        self.id = id
        self.tx_type = tx_type
        self.date = date.replace(microsecond=0)
        self.amount = amount
        self.currency_code = currency_code
        self.foreign_code = foreign_code
        self.foreign_amount = foreign_amount
        self.description = description
        self.notes = notes
        self.source_id = self.determine_account() if type == 'DEBIT' else None
        self.destination_id = None if type == 'DEBIT' else self.determine_account()
        self.reconciled = True
        self.raw_category = raw_category
        self.category_name = self.determine_category()
        self.budget_name = self.determine_budget()

    def determine_category(self):
        global category_map

        if self.raw_category == '':
            return None

        if self.raw_category in category_map:
            return category_map[self.raw_category]['category']

        logging.error(f"Category seen in transaction but not in category_map: '{self.raw_category}'.")

        if 'Converted' in self.description or 'Received' in self.description:
            return None
        if self.description == 'Sent money to Homerental Nordic AB':
            return None

        return 'Other'

    def determine_budget(self):
        global category_map

        if self.raw_category == '':
            return None

        if self.raw_category in category_map:
            return category_map[self.raw_category]['budget']

        logging.error(f"Category seen in transaction but not in category_map: '{self.raw_category}'.")

        if 'Converted' in self.description or 'Received' in self.description:
            return None
        if self.description == 'Sent money to Homerental Nordic AB':
            return None

        return 'Other'

    def determine_account(self):
        global currency_accounts
        return currency_accounts[self.currency_code]


def get_user_id() -> str:
    return "3750372"


def get_account_id() -> str:
    return "4067808"


def fetch_exchange_rate_from_yahoo(from_code: str, to_code: str, start: datetime, end: datetime, retry=0) -> \
        {str: float}:
    """
    Fetch exchange rates from Yahoo Finance between two dates.
    Little bit tricky, as some pairs don't trade over the weekend.
    If any day between `start` and `end` was a non-trading day, use the previous or next rate seen.
    :param from_code:
    :param to_code:
    :param start:
    :param end:
    :param retry:
    :return:
    """
    if retry > 4:
        logging.error("Failed to fetch from Yahoo after 5 attempts, giving up.")

    res = http.request('GET', f"https://query1.finance.yahoo.com/v7/finance/download/{from_code}{to_code}=X?period1={int(start.timestamp())}&period2={int(end.timestamp())}&interval=1d&events=history")  # noqa E401
    if res.status != 200:
        time.sleep(5)
        return fetch_exchange_rate_from_yahoo(from_code, to_code, start, end, retry + 1)

    rates = {}
    last_seen = None

    rows = list(csv.reader(res.data.decode().split("\n")))[1:]
    results = {row[0]: row[4] for row in rows}
    end = end + timedelta(days=1)
    for date in [start + timedelta(days=n) for n in range((end - start).days)]:
        formatted_date = date.strftime("%Y-%m-%d")
        if formatted_date not in results:
            rates[formatted_date] = rows[0][4] if last_seen is None else last_seen
            continue

        rates[formatted_date] = results[formatted_date]
        last_seen = results[formatted_date]

    return {date: float(rate) for date, rate in rates.items()}


def fetch_txs_from_transferwise(user_id: str, account_id: str, currency: str, start: datetime, end: datetime) -> \
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
    global TRANSFERWISE_BASE_URI
    global category_map
    global currency_accounts

    start = start.replace(microsecond=0)
    end = end.replace(microsecond=0)
    uri = f"/v3/profiles/{user_id}/borderless-accounts/{account_id}/statement.json?intervalStart={start.isoformat()}Z&intervalEnd={end.isoformat()}Z&currency={currency}"
    res = http.request("GET", f"{TRANSFERWISE_BASE_URI}{uri}", headers={
        'Authorization': 'Bearer ' + os.environ['TRANSFERWISE_TOKEN']
    })
    if res.status == 401:
        logging.error('Unauthorized response fetching transactions, check API token.')
        exit()
    if res.status != 200:
        logging.error(f'Failed to fetch transactions for a non-auth reason. {res.status}: {res.content.decode()}')
        exit()

    fx_rates = {}
    convert_amounts = bool(os.environ['CONVERT_AMOUNTS'])
    if convert_amounts and currency != os.environ['BASE_CURRENCY']:
        fx_rates = fetch_exchange_rate_from_yahoo(from_code=currency, to_code=os.environ['BASE_CURRENCY'], start=start,
                                                  end=end)

    body = json.loads(res.data.decode("utf-8"))
    transactions = []
    for row in body['transactions']:
        currency_code = row['amount']['currency']
        reference = row['referenceNumber']
        amount = abs(row['amount']['value'])
        tx_type = row['type']
        category = row['details']['category'] if 'category' in row['details'] else ''
        date = datetime.strptime(row['date'], '%Y-%m-%dT%H:%M:%S.%fZ')
        description = row['details']['description'].replace("Card transaction of ", '')
        raw = row

        foreign_amount = 0.0
        if convert_amounts and currency != os.environ['BASE_CURRENCY']:
            fx_date = date.strftime("%Y-%m-%d")
            foreign_amount = round(fx_rates[fx_date] * amount, 2)
            raw['foreignAmount'] = foreign_amount
            raw['foreignFxRate'] = fx_rates[fx_date]

        tx = Transaction(id=reference, amount=amount, tx_type=tx_type, raw_category=category, date=date,
                         description=description, currency_code=currency_code, foreign_code=os.environ['BASE_CURRENCY'],
                         foreign_amount=foreign_amount, notes=json.dumps(raw))
        transactions.append(tx)

    return transactions


def search_for_existing_tx(tx: Transaction) -> int:
    """
    Searches Firefly for a Transaction with a description LIKE TransferWiseID-{currency}
    Fails if it finds > 1, returns 0 if it finds 0, ID if it finds 1.
    :param tx:
    :return:
    """
    res = http.request("GET", FIREFLY_BASE_URI + "/api/v1/search/transactions",
                       fields={'query': f'{tx.id}-{tx.currency_code}'}, headers={
            'Authorization': 'Bearer ' + os.environ['FIREFLY_TOKEN'],
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })
    if res.status == 401:
        logging.error('Unauthorized response posting transactions, check API token.')
        exit()
    if res.status != 200:
        logging.error(f'Failed to search transactions for a non-auth reason. {res.status}: {res.data.decode()}')
        exit()

    body = json.loads(res.data)
    if len(body['data']) > 1:
        ids = [x['id'] for x in body['data']]
        logging.error(f"Received more than one transaction like {tx.id}, IDs: {ids}. Please fix / report bug.")
        exit(1)
    if len(body['data']) == 1:
        return int(body['data'][0]['id'])

    return 0


def post_tx_to_firefly(tx: Transaction, account_id: str) -> bool:
    """
    Form the Transaction object ready for ingestion by Firefly and post.
    :param tx:
    :param account_id:
    :return:
    """
    global FIREFLY_BASE_URI

    tx_body = {
        "external_id": tx.id,
        "type": "deposit" if tx.tx_type in 'CREDIT' else 'withdrawal',
        "date": tx.date.isoformat() + "Z",
        "amount": str(tx.amount),
        "currency_code": tx.currency_code,
        "foreign_currency_code": None,
        "foreign_amount": str(0.0),
        "category_name": tx.category_name,
        "budget_name": tx.budget_name,
        "description": f"{tx.description} ({tx.id}-{tx.currency_code})",
        "notes": tx.notes,
        "source_id": account_id if tx.tx_type == 'DEBIT' else None,
        "destination_id": None if tx.tx_type == 'DEBIT' else account_id,
        "reconciled": True,
    }

    # Even if these were attempted, if the amount is 0.0 then we failed the Yahoo fetch, don't attempt it.
    if tx.foreign_code != '' and tx.foreign_amount != 0.0:
        # If you want to set this in Firefly, remove the pass and uncomment
        pass
        # tx_body['foreign_currency_code'] = tx.foreign_code
        # tx_body['foreign_amount'] = str(tx.foreign_amount)

    payload = {
        "error_if_duplicate_hash": False,
        "apply_rules": False,
        "group_title": "TW",
        "transactions": [tx_body]
    }

    existing_id = search_for_existing_tx(tx)

    if existing_id != 0:
        res = http.request("PUT", f"{FIREFLY_BASE_URI}/api/v1/transactions/{existing_id}", body=json.dumps(payload), headers={
            'Authorization': 'Bearer ' + os.environ['FIREFLY_TOKEN'],
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })
    else:
        res = http.request("POST", f"{FIREFLY_BASE_URI}/api/v1/transactions", body=json.dumps(payload), headers={
            'Authorization': 'Bearer ' + os.environ['FIREFLY_TOKEN'],
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })

    if res.status == 422:
        logging.error(f'Failed to put transaction {tx.id}: {res.data.decode()}')
        return True
    if res.status == 401:
        logging.error('Unauthorized response posting transactions, check API token.')
        exit()
    if res.status != 200:
        logging.error(f'Failed to post transactions for a non-auth reason. {res.status}: {res.data.decode()}')
        exit()

    return True


if __name__ == '__main__':
    main()

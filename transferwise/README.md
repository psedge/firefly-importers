## TransferWise Importer

TransferWise allows a user to hold multiple currencies transferring value between them. This tool
does the following:

1. Fetches the User ID and Account ID against your API Token
2. Fetches transactions from the `/transactions` endpoint
3. Formats data, unifying types with Firefly III
4. Posts transactions to the provided Firefly III API

There's a few points in here which are interesting quirks of either side:

* TransferWise allows you to retrieve a maximum of 9 months at a time, so this tool chunks your request time if larger
* TransferWise is *made* for multiple currencies, so the tool imports both the native currency of the transaction
and if enabled by the `CONVERT_AMOUNTS` .env setting, attempts to convert the currencies at the time of transaction using
the Yahoo Finance API. You'll need an API key to do that, which you should set in `YAHOO_FINANCE_API_TOKEN` in .env
* The importer hashes the body of a transaction, and stores a SHA256 in the `external_reference_id`, so that transactions
are updated, not duplicated on subsequent runs.


### Setup

You'll need an API token to use this tool, which you can grab from 
[transferwise.com/user/settings](https://transferwise.com/user/settings). Scroll down to 'API Tokens' and create a new 
read-only token, then add it into your .env file using the example format contained in .env.example. Alternatively, if
you'd like to deploy this tool to AWS using Terraform, see the section below.

```python
pip install --r requirements.txt
python setup.py
```

In an attempt to make this as flexible as possible, there's some additional (optional) config files you can set up:

#### `.env`

```
TRANSFERWISE_TOKEN=         # Your TransferWise API token
FETCH_PERIOD=720            # Time in days to fetch transactions back from today
FETCH_CURRENCIES=GBP,EUR    # A CSV of currencies to fetch. All defined must have a matching entry in accounts.json
CONVERT_AMOUNTS=true        # Whether to attempt transaction amount conversions using Yahoo Finance API
BASE_CURRENCY=GBP           # Currency to convert others to
```

#### `categories-map.json`

TransferWise provides a set of categories against a transaction, presumably based on some internal categorisation process.
It's great that they expose this data, as it allows us to more accurately set which budget a transaction should be set
to. This mapping between TransferWise category (key/left) and Firefly category (value/right) can be set in this file. eg.

```json
{
  // TransferWise: Firefly
  "Bars, Cocktail Lounges, Discothe": {"category": "Alcohol", "budget": "Recreation"}
}
```

There may be other custom logic you want to run during this categorisation, which you can add in the `determine_category`
function.

#### `accounts.json`

In Firefly you typically have multiple accounts, so this tool requires you to map between TransferWise currencies and
FireFly accounts. The tool will produce an error if it finds transactions with a currency code which do not have
a corresponding entry in this file.

```json
{
  // Currency code: Firefly account ID
  "GBP": 1,
  "EUR": 2
}
```

### Terraform

This tool can be deployed using various AWS products, which makes the whole operation/maintainance of it *super* minimal
. By default, the Terraform module at [./terraform/main.tf](./terraform/main.tf) uses the following services:

1. Lambda; for execution of the main code.
2. CloudWatch; for runtime log storage and cron scheduling

module "transferwise" {
  source = "./transferwise/terraform"

  # Required params
  TRANSFERWISE_BASE_URI = ""
  FIREFLY_BASE_URI      = ""
  TRANSFERWISE_TOKEN    = ""
  FIREFLY_TOKEN         = ""
  FETCH_PERIOD          = 90
  FETCH_CURRENCIES      = "GBP,EUR"
  CONVERT_AMOUNTS       = true
  BASE_CURRENCY         = "GBP"

  # Options for CloudWatch Event -> Lambda trigger
  CRON_ENABLED  = 0
  CRON_SCHEDULE = "0 0 * * *"
}
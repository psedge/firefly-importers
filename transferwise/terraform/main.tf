data "archive_file" "source" {
  type        = "zip"

  source {
    content  = file("${path.module}/../src/__init__.py")
    filename = "__init__.py"
  }
  source {
    content  = file("${path.module}/../src/lambda.py")
    filename = "lambda.py"
  }
  source {
    content  = file("${path.module}/../src/main.py")
    filename = "main.py"
  }
  source {
    content  = file("${path.module}/../config/accounts.json")
    filename = "config/accounts.json"
  }
  source {
    content  = file("${path.module}/../config/categories-map.json")
    filename = "config/categories-map.json"
  }

  output_path = "${path.module}/terraform.zip"
}

resource "aws_lambda_function" "lambda" {
  filename         = data.archive_file.source.output_path
  source_code_hash = data.archive_file.source.output_base64sha256

  function_name = "transferwiseLambda"
  description   = "Syncs a TransferWise account with a Firefly III instance"
  runtime       = "python3.8"
  handler       = "lambda.lambda_handler"
  timeout       = 600
  role          = aws_iam_role.role.arn

  environment {
    variables = {
      TRANSFERWISE_BASE_URI = var.TRANSFERWISE_BASE_URI
      FIREFLY_BASE_URI      = var.FIREFLY_BASE_URI
      TRANSFERWISE_TOKEN    = var.TRANSFERWISE_TOKEN
      FIREFLY_TOKEN         = var.FIREFLY_TOKEN
      FETCH_PERIOD          = var.FETCH_PERIOD
      FETCH_CURRENCIES      = var.FETCH_CURRENCIES
      CONVERT_AMOUNTS       = var.CONVERT_AMOUNTS
      BASE_CURRENCY         = var.BASE_CURRENCY
    }
  }
}

data "aws_iam_policy_document" "assume_policy_doc" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type = "Service"
      identifiers = [
      "lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "policy_doc" {
  statement {
    actions = [
      "logs:CreateLogStream",
      "logs:CreateLogGroup",
      "logs:PutLogEvents"
    ]

    resources = [
      "arn:aws:logs:*:*:*"
    ]
  }
}

resource "aws_iam_policy" "policy" {
  name_prefix = "transferwise-"
  policy      = data.aws_iam_policy_document.policy_doc.json
}

resource "aws_iam_role" "role" {
  name               = "transferwise"
  assume_role_policy = data.aws_iam_policy_document.assume_policy_doc.json
}

resource "aws_iam_role_policy_attachment" "policy_attachment" {
  role       = aws_iam_role.role.name
  policy_arn = aws_iam_policy.policy.arn
}

resource "aws_cloudwatch_event_rule" "cloudwatch_event" {
  name                = "transferwise-cron"
  description         = "Triggers a TransferWise -> Firefly III sync."
  schedule_expression = var.CRON_SCHEDULE
}

resource "aws_cloudwatch_event_target" "cloudwatch_target" {
  rule      = aws_cloudwatch_event_rule.cloudwatch_event.name
  target_id = "lambda"
  arn       = aws_lambda_function.lambda.arn
}

resource "aws_lambda_permission" "cloudwatch_lambda_permission" {
  statement_id  = "CloudWatchTransferWise"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.cloudwatch_event.arn
}

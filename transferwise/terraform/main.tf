data "archive_file" "source" {
  type = "zip"
  output_path = "${path.module}/terraform.zip"
  source_dir = "../src"
}

resource "aws_lambda_function" "lambda" {
  file = data.archive_file.source.output_path
  source_code_hash = data.archive_file.source.output_base64sha256

  function_name = "lambda"
  description = "Syncs a TransferWise account with a Firefly III instance"
  runtime = "python3.8"
  handler = "lambda.lambda_handler"
  timeout = 600
  role = aws_iam_role.role.arn

  environment {
    variables = {
      TRANSFERWISE_TOKEN = var.TRANSFERWISE_TOKEN
      FIREFLY_TOKEN = var.FIREFLY_TOKEN
      FETCH_PERIOD = var.FETCH_PERIOD
      FETCH_CURRENCIES = var.FETCH_CURRENCIES
      CONVERT_AMOUNTS = var.CONVERT_AMOUNTS
      BASE_CURRENCY = var.BASE_CURRENCY
    }
  }
}

data "aws_iam_policy_document" "assume_policy_doc" {
  statement {
    actions = "sts:AssumeRole"

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
  policy = data.aws_iam_policy_document.policy_doc.json
}

resource "aws_iam_role" "role" {
  name = "transferwise"
  assume_role_policy = data.aws_iam_policy_document.assume_policy_doc.json
}

resource "aws_iam_role_policy_attachment" "policy_attachment" {
  role = aws_iam_role.role.name
  policy_arn = aws_iam_policy.policy.arn
}

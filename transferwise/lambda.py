import json
from . import main as transferwise


def lambda_handler(event, context):
    try:
        transferwise.main()
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'status': 'Failed', 'error': e.__str__()})
        }
    return {
        'statusCode': 200,
        'body': 0
    }
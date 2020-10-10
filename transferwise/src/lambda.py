import json
from . import main as transferwise


def lambda_handler(event, context):
    """
    Handle the event from Lambda, starting the import.
    :param event:
    :param context:
    :return: Lambda formatted response.
    """
    try:
        transferwise.main()
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'status': 'Failed', 'error': e.__str__()})
        }
    return {
        'statusCode': 200,
        'body': "Successfully ran TransferWise import."
    }

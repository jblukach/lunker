import json

def handler(event, context):

    print(json.dumps(event, indent=4))

    return {
        'statusCode': 200,
        'body': json.dumps('Action Completed!')
    }
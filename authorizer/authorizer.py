import os

def handler(event, context):
    
    print(event)

    print(context)

    return {
        'statusCode': 200,
        'body': 'authorizer',
        'headers': {
            'Content-Type': 'text/plain'
        }
    }
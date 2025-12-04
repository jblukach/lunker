import os

def handler(event, context):
    
    print(event)

    return {
        'statusCode': 200,
        'body': 'Authorized!',
        'headers': {
            'Content-Type': 'text/plain'
        }
    }
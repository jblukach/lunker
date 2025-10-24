import os

def handler(event, context):
    
    print(event)

    return {
        'statusCode': 200,
        'body': 'Hello, World!',
        'headers': {
            'Content-Type': 'text/plain'
        }
    }
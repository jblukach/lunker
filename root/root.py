import os

def handler(event, context):
    
    print(event)

    return {
        'statusCode': 200,
        'body': os.environ['AWS_REGION'],
        'headers': {
            'Content-Type': 'text/plain'
        }
    }
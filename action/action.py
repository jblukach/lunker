import boto3
import json
import os

def handler(event, context):

    print(event)

    for record in event.get('Records', []):
        if record.get('eventName') == 'INSERT':
            new_image = record.get('dynamodb', {}).get('NewImage', {})
            if new_image and 'sld' in new_image:

                print(new_image['sld']['S'])

                payload = {
                    'Status': new_image['sld']['S']
                }

                lambda_client = boto3.client('lambda')

                lambda_client.invoke(
                    FunctionName = os.environ['PERMUTATION_FUNCTION_NAME'],
                    InvocationType = 'Event',
                    Payload = json.dumps(payload)
                )
                
                lambda_client.invoke(
                    FunctionName = os.environ['FUNCTION_NAME'],
                    InvocationType = 'Event',
                    Payload = json.dumps(payload)
                )

    return {
        'statusCode': 200,
        'body': json.dumps('Action Completed!')
    }

import base64
import os
import requests

def handler(event, context):

    if 'rawQueryString' in event and event['rawQueryString'].startswith('code='):

        b64 = base64.b64encode(f"{os.environ['CLIENT_ID']}:{os.environ['CLIENT_SECRET']}".encode()).decode()

        url = 'https://hello.lukach.net/oauth2/token'
        headers = {
            'Authorization': f'Basic {b64}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        data = {
            'code': event['rawQueryString'].split('=')[1],
            'grant_type': 'authorization_code',
            'redirect_uri': 'https://lunker.lukach.net/auth'
        }

        response = requests.post(url, headers=headers, data=data)

        return {
            'statusCode': 302,
            'headers': {
                'Location': f"https://lunker.lukach.net/home?token={response.json().get('access_token','')}"
            }
        }
 
    else:

        html = '''<HTML>
        <HEAD>
            <TITLE>No Fishing!</TITLE>
        </HEAD>
        <BODY>
            <CENTER>
                <IMAGE SRC="https://lukach.net/images/no-fishing.png" ALT="No Fishing Logo">
                <H2>No Fishing!</H2>
            </CENTER>
        </BODY>
        </HTML>'''

    return {
        'statusCode': 403,
        'body': html,
        'headers': {
            'Content-Type': 'text/html'
        }
    }
import base64
import os
import requests

def handler(event, context):

    code = 401
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

    if 'rawQueryString' in event and event['rawQueryString'].startswith('code='):
        if not all(c.isalnum() or c in ['=','-'] for c in event['rawQueryString']):
            code = 400
        else:
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
            if response.status_code == 200 and 'id_token' in response.json():
                code = 200
                tokens = response.json()
                html = html = '''<HTML>
                <HEAD>
                    <TITLE>Happy Fishing!</TITLE>
                    <SCRIPT>
                        const headers = { 'Authorization': 'Bearer ''' + tokens['access_token'] + '''' };
                        fetch('https://lunker.lukach.net/home', { headers: headers })
                            .then(response => response.text())
                            .then(data => { document.write(data); });
                    </SCRIPT>
                </HEAD>
                <BODY>
                    <CENTER>
                        <IMAGE SRC="https://lukach.net/images/lunker.png" ALT="Lunker Logo">
                        <H2>Happy Fishing!</H2>
                    </CENTER>
                </BODY>
                </HTML>'''

    return {
        'statusCode': code,
        'body': html,
        'headers': {
            'Content-Type': 'text/html'
        }
    }
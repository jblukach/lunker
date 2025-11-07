import os

def handler(event, context):

    clientid = os.environ['CLIENT_ID']

    html = '''<HTML>
    <HEAD>
        <TITLE>Gone Fishing!</TITLE>
    </HEAD>
    <BODY>
        <CENTER>
            <IMAGE SRC="https://lukach.net/images/lunker.png" ALT="Lunker Logo">
            <H2><A HREF="https://hello.lukach.net/login?client_id='''+clientid+'''&response_type=code&scope=openid&redirect_uri=https://lunker.lukach.net/auth" style="text-decoration:none">Gone Fishing!</A></H2>
        </CENTER>
    </BODY>
    </HTML>'''

    return {
        'statusCode': 200,
        'body': html,
        'headers': {
            'Content-Type': 'text/html'
        }
    }
import os

def handler(event, context):
    
    print(event)

    html = '''<HTML>
    <HEAD>
        <TITLE>Fish On!</TITLE>
    </HEAD>
    <BODY>
        <CENTER>
            <IMAGE SRC="https://lukach.net/images/lunker.png" ALT="Lunker Logo">
            <H2>Fish On!</H2>
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
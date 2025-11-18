import os

def handler(event, context):

    print(event)

    print(context)

    if 'rawQueryString' in event and event['rawQueryString'].startswith('code='):

        status = 200
        html = '''<HTML>
        <HEAD>
            <TITLE>Happy Fishing!</TITLE>
        </HEAD>
        <BODY>
            <CENTER>
                <IMAGE SRC="https://lukach.net/images/lunker.png" ALT="Lunker Logo">
                <H2>Happy Fishing!</H2>
            </CENTER>
        </BODY>
        </HTML>'''
 
    else:

        status = 403
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
        'statusCode': status,
        'body': html,
        'headers': {
            'Content-Type': 'text/html'
        }
    }
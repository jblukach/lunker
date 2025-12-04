import requests

def handler(event, context):

    url = 'https://hello.lukach.net/oauth2/userInfo'
    headers = {
        'Authorization': str(event['headers']['authorization'])
    }
    response = requests.get(url, headers=headers)

    if response.status_code != 200 or 'email' not in response.json():

        authorized = {
            "isAuthorized": False
        }

    else:

        authorized = {
            "isAuthorized": True,
            "context": {
                "sub": response.json().get('sub'),
                "email_verified": response.json().get('email_verified'),
                "email": response.json().get('email'),
                "username": response.json().get('username')
            }
        }

    return authorized
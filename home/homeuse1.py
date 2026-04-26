from home_shared import create_handler


handler = create_handler(
    api_endpoint='https://use1.api.lukach.io/home',
    logout_endpoint='https://use1.api.lukach.io/auth?action=logout',
    user_info_endpoint='https://hello-use1.lukach.io/oauth2/userInfo',
)
def handler(event, context):
    
    print(event)

    html = """<!DOCTYPE html>
	<html>
  		<head>
			<script src="https://descopecdn.com/npm/@descope/web-component@3.21.0/dist/index.js"></script>
			<script src="https://descopecdn.com/npm/@descope/web-js-sdk@1.16.0/dist/index.umd.js"></script>
			<script>
                const sdk = Descope({ projectId: "P34YxCrt7m3gXk5YJSHcwwZjyFIh", persistTokens: true, autoRefresh: true });
                const sessionToken = sdk.getSessionToken();
                if (sessionToken) {
  					if(isJwtExpired(sessionToken)) {
						console.log('Session token has expired.');
  					} else {
						console.log('Session token is valid.');
  					}                    
                } else {
				    const wcElement = document.getElementsByTagName('descope-wc')[0];
				    const onSuccess = (e) => {
					    console.log(e.detail.user.email);
				    };
				    const onError = (err) => console.log(err);
				    wcElement.addEventListener('success', onSuccess);
				    wcElement.addEventListener('error', onError);
                }
			</script>
        </head>
  		<body>
    		<p id="container"></p>
			<descope-wc project-id="P34YxCrt7m3gXk5YJSHcwwZjyFIh" flow-id="sign-in" theme="os"/>        
		</body>
	</html>"""

    return {
        'statusCode': 200,
        'body': html,
        'headers': {
            'Content-Type': 'text/html'
        }
    }
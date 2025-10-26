def handler(event, context):
    
    print(event)

    html = """<!DOCTYPE html>
	<html>
  		<head>
			<script src="https://descopecdn.com/npm/@descope/web-js-sdk@1.16.0/dist/index.umd.js"></script>
  		</head>
  		<body>
			<script>
                sdk.refresh()
			</script>
            <h1>Hello from Root!</h1>
		</body>
	</html>"""

    return {
        'statusCode': 200,
        'body': html,
        'headers': {
            'Content-Type': 'text/html'
        }
    }
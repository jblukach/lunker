def handler(event, context):
    
    print(event)

    html = """<!DOCTYPE html>
	<html>
  		<body>
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
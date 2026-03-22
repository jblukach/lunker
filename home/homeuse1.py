import base64
import html
import json

API_ENDPOINT = 'http://use1.api.lukach.io/home'

def _get_method(event):
    request_context = event.get('requestContext') or {}
    http_context = request_context.get('http') or {}
    return (http_context.get('method') or event.get('httpMethod') or 'GET').upper()


def _get_body(event):
    body = event.get('body') or ''
    if event.get('isBase64Encoded') and body:
        body = base64.b64decode(body).decode('utf-8')
    return body


def _get_authorization(event):
    authorization = event.get('authorization')
    if isinstance(authorization, str) and authorization:
        return authorization

    headers = event.get('headers') or {}
    return headers.get('authorization') or headers.get('Authorization') or ''


def _render_form(authorization_header):
    auth_header_json = json.dumps(authorization_header)
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Fish On!</title>
    <style>
        body {{
            font-family: sans-serif;
            margin: 0;
            background: #f4f7fb;
            color: #10233c;
        }}

        main {{
            max-width: 540px;
            margin: 48px auto;
            padding: 32px;
            background: #ffffff;
            border-radius: 16px;
            box-shadow: 0 18px 40px rgba(16, 35, 60, 0.12);
        }}

        img {{
            display: block;
            margin: 0 auto 16px;
            max-width: 220px;
        }}

        h1 {{
            margin: 0 0 8px;
            text-align: center;
        }}

        p {{
            margin: 0 0 24px;
            text-align: center;
        }}

        label {{
            display: block;
            font-weight: 600;
            margin-bottom: 8px;
        }}

        input[type="text"],
        input[type="password"] {{
            width: 100%;
            padding: 12px;
            margin-bottom: 18px;
            border: 1px solid #c6d3e1;
            border-radius: 10px;
            box-sizing: border-box;
        }}

        .options {{
            display: flex;
            gap: 18px;
            margin-bottom: 24px;
        }}

        .actions {{
            text-align: center;
        }}

        button {{
            border: 0;
            border-radius: 999px;
            background: #0e7490;
            color: #ffffff;
            cursor: pointer;
            font-size: 1rem;
            padding: 12px 28px;
        }}
    </style>
</head>
<body>
    <main>
        <img src="https://cdn.lukach.io/lunker.png" alt="Lunker Logo">

        <form id="home-form">
            <label for="entry">Domain</label>
            <input id="entry" name="entry" type="text" required>

            <div class="options">
                <label><input type="radio" name="action" value="Add" checked> Add</label>
                <label><input type="radio" name="action" value="Remove"> Remove</label>
            </div>

            <p id="entry-print"></p>

            <div class="actions">
                <button type="button" onclick="submitHomeForm()">Submit</button>
            </div>
        </form>
    </main>

    <script>
        async function submitHomeForm() {{
            const form = document.getElementById('home-form');
            const formData = new FormData(form);
            const action = formData.get('action');
            const entry = formData.get('entry');
            const entryPrint = document.getElementById('entry-print');
            const authHeader = {auth_header_json};

            entryPrint.textContent = `Text entered: ${{entry}}`;

            const response = await fetch('{API_ENDPOINT}', {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/json',
                    'Authorization': authHeader
                }},
                body: JSON.stringify({{ action, entry }})
            }});

            const responseHtml = await response.text();
            document.open();
            document.write(responseHtml);
            document.close();
        }}
    </script>
</body>
</html>'''


def _render_result(action, entry):
    safe_action = html.escape(action)
    safe_entry = html.escape(entry)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Fish On!</title>
    <style>
        body {{
            font-family: sans-serif;
            margin: 0;
            background: #f4f7fb;
            color: #10233c;
        }}

        main {{
            max-width: 540px;
            margin: 48px auto;
            padding: 32px;
            background: #ffffff;
            border-radius: 16px;
            box-shadow: 0 18px 40px rgba(16, 35, 60, 0.12);
            text-align: center;
        }}

        img {{
            display: block;
            margin: 0 auto 16px;
            max-width: 220px;
        }}

        dl {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            text-align: left;
            margin-top: 24px;
        }}

        dt {{
            font-weight: 700;
        }}

        a {{
            display: inline-block;
            margin-top: 24px;
            color: #0e7490;
        }}
    </style>
</head>
<body>
    <main>
        <img src="https://cdn.lukach.io/lunker.png" alt="Lunker Logo">
        <h1>Submission Received</h1>
        <dl>
            <dt>Option</dt>
            <dd>{safe_action}</dd>
            <dt>Text</dt>
            <dd>{safe_entry}</dd>
        </dl>
        <a href="{API_ENDPOINT}">Back to form</a>
    </main>
</body>
</html>'''


def handler(event, _context):
    print(event)

    method = _get_method(event)

    if method == 'POST':
        try:
            payload = json.loads(_get_body(event) or '{}')
        except json.JSONDecodeError:
            payload = {}
        response_html = _render_result(payload.get('action', ''), payload.get('entry', ''))
    else:
        response_html = _render_form(_get_authorization(event))

    return {
        'statusCode': 200,
        'body': response_html,
        'headers': {
            'Content-Type': 'text/html; charset=utf-8'
        }
    }
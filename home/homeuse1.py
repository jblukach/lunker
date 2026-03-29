import base64
import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import BotoCoreError, ClientError
import html
import json
import os
import requests

API_ENDPOINT = 'https://use1.api.lukach.io/home'
USER_INFO_ENDPOINT = 'https://hello-use1.lukach.io/oauth2/userInfo'

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


def _normalize_authorization(authorization_header):
    if not authorization_header:
        return ''

    value = authorization_header.strip()
    if not value:
        return ''

    if value.lower().startswith('bearer '):
        return value

    return f'Bearer {value}'


def _fetch_user_identity(authorization_header):
    default_region = os.getenv('AWS_REGION', 'unknown')
    identity = {
        'email': 'unknown',
        'region': default_region,
    }

    normalized_authorization = _normalize_authorization(authorization_header)
    if not normalized_authorization:
        return identity

    try:
        response = requests.get(
            USER_INFO_ENDPOINT,
            headers={
                'Authorization': normalized_authorization,
                'Accept': 'application/json',
            },
            timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return identity

    identity['email'] = (
        payload.get('email')
        or payload.get('username')
        or payload.get('cognito:username')
        or 'unknown'
    )
    identity['region'] = (
        payload.get('region')
        or payload.get('custom:region')
        or payload.get('zoneinfo')
        or default_region
    )
    return identity


def _normalize_domain(entry):
    if not isinstance(entry, str):
        return ''

    return entry.strip().lower().rstrip('.')


def _validate_domain(domain):
    if not domain:
        return False, 'Domain is required.'

    labels = domain.split('.')
    if len(labels) < 2 or (len(labels) == 2 and labels[1] == ''):
        return False, 'Domain must include a single dot (e.g. example.com).'
    if len(labels) != 2:
        return False, 'Domain must contain exactly one dot (no subdomains allowed).'

    return True, ''


def _tld_exists(table, tld):
    response = table.get_item(
        Key={
            'pk': 'TLD#',
            'sk': tld,
        },
        ProjectionExpression='sk',
    )
    return 'Item' in response


def _split_domain(domain):
    sld, tld = domain.split('.')
    return sld, tld


def _put_lunker_domain(table, email, domain):
    sld, tld = _split_domain(domain)
    table.put_item(
        Item={
            'pk': 'LUNKER#',
            'sk': f'LUNKER#{email}#{domain}',
            'domain': domain,
            'email': email,
            'sld': sld,
            'tld': tld,
        }
    )


def _delete_lunker_domain(table, email, domain):
    table.delete_item(
        Key={
            'pk': 'LUNKER#',
            'sk': f'LUNKER#{email}#{domain}',
        }
    )


def _list_lunker_domains(table, email):
    if not email or email == 'unknown':
        return []

    domains = []
    query_kwargs = {
        'KeyConditionExpression': Key('pk').eq('LUNKER#') & Key('sk').begins_with(f'LUNKER#{email}#'),
        'ProjectionExpression': '#domain',
        'ExpressionAttributeNames': {
            '#domain': 'domain',
        },
    }

    try:
        while True:
            response = table.query(**query_kwargs)
            for item in response.get('Items', []):
                normalized_domain = _normalize_domain(item.get('domain'))
                if normalized_domain:
                    domains.append(normalized_domain)

            last_evaluated_key = response.get('LastEvaluatedKey')
            if not last_evaluated_key:
                break
            query_kwargs['ExclusiveStartKey'] = last_evaluated_key
    except (BotoCoreError, ClientError, KeyError, TypeError):
        return []

    return sorted(set(domains))


def _process_submission(raw_domain, email, action):
    normalized_domain = _normalize_domain(raw_domain)
    is_valid, validation_message = _validate_domain(normalized_domain)
    if not is_valid:
        return normalized_domain, False, validation_message

    if not email or email == 'unknown':
        return normalized_domain, False, 'Unable to resolve user email from token.'

    dynamodb = boto3.resource('dynamodb')
    tld_table = dynamodb.Table(os.environ['TLD_TABLE'])
    lunker_table = dynamodb.Table(os.environ['LUNKER_TABLE'])

    _, top_level_domain = _split_domain(normalized_domain)
    if not _tld_exists(tld_table, top_level_domain):
        return normalized_domain, False, f'Invalid top-level domain: .{top_level_domain}'

    normalized_action = (action or '').strip().lower()
    if normalized_action == 'deleteitem':
        _delete_lunker_domain(lunker_table, email, normalized_domain)
        return normalized_domain, True, normalized_domain

    _put_lunker_domain(lunker_table, email, normalized_domain)
    return normalized_domain, True, 'Domain saved to lunker table.'


def _table_name_from_env(value):
    if not isinstance(value, str):
        return ''

    normalized = value.strip()
    if not normalized:
        return ''

    marker = ':table/'
    if marker in normalized:
        return normalized.split(marker, 1)[1]

    return normalized


def _resolve_table_identifiers(*env_keys):
    identifiers = []
    for key in env_keys:
        raw_value = os.getenv(key, '').strip()
        if not raw_value:
            continue

        parsed_name = _table_name_from_env(raw_value)
        if raw_value not in identifiers:
            identifiers.append(raw_value)
        if parsed_name and parsed_name not in identifiers:
            identifiers.append(parsed_name)

    return identifiers


def _extract_domain_value(item, sld):
    if not isinstance(item, dict):
        return ''

    for key in ('domain', 'fqdn', 'host', 'name'):
        normalized_domain = _normalize_domain(item.get(key))
        if normalized_domain:
            return normalized_domain

    sk_value = item.get('sk')
    if isinstance(sk_value, str):
        for token in sk_value.split('#'):
            normalized_token = _normalize_domain(token)
            if normalized_token.startswith(f'{sld}.'):
                return normalized_token

    return ''


def _query_with_prefix(dynamodb_client, table_identifier, sld, sk_prefix):
    domains = []
    expression_values = {
        ':pk': {'S': 'LUNKER#'},
        ':sk': {'S': sk_prefix},
    }
    query_kwargs = {
        'TableName': table_identifier,
        'KeyConditionExpression': 'pk = :pk AND begins_with(sk, :sk)',
        'ExpressionAttributeValues': expression_values,
    }

    while True:
        response = dynamodb_client.query(**query_kwargs)
        for item in response.get('Items', []):
            normalized_item = {
                key: next(iter(value.values())) if isinstance(value, dict) and value else value
                for key, value in item.items()
            }
            normalized_domain = _extract_domain_value(normalized_item, sld)
            if normalized_domain:
                domains.append(normalized_domain)

        last_evaluated_key = response.get('LastEvaluatedKey')
        if not last_evaluated_key:
            break
        query_kwargs['ExclusiveStartKey'] = last_evaluated_key

    return domains


def _query_paginated_domains(dynamodb_client, table_identifier, sld):
    prefixes = [
        f'LUNKER#{sld}#',
        f'LUNKER#{sld}',
    ]
    all_domains = []

    for prefix in prefixes:
        try:
            all_domains.extend(_query_with_prefix(dynamodb_client, table_identifier, sld, prefix))
        except (BotoCoreError, ClientError, KeyError, TypeError) as exc:
            print(f'WM query failed for prefix {prefix} on table {table_identifier}: {exc}')
            continue

    return sorted(set(all_domains))


def _load_section_domains(dynamodb_client, sld, *env_keys):
    table_identifiers = _resolve_table_identifiers(*env_keys)
    if not table_identifiers:
        return []

    for table_identifier in table_identifiers:
        domains = _query_paginated_domains(dynamodb_client, table_identifier, sld)
        if domains:
            return domains

    return []


def _get_domain_sections(domain):
    normalized_domain = _normalize_domain(domain)
    is_valid, _ = _validate_domain(normalized_domain)
    if not is_valid:
        return {}

    sld, _ = _split_domain(normalized_domain)
    dynamodb_client = boto3.client('dynamodb')

    return {
        'suspect': {
            'openSourceIntelligence': _load_section_domains(dynamodb_client, sld, 'WM_OSINT'),
            'domainsMonitorSubscription': _load_section_domains(dynamodb_client, sld, 'WM_MALWARE'),
        },
        'newRegistrations': {
            'daily': _load_section_domains(dynamodb_client, sld, 'WM_DAILYUPDATE'),
            'weekly': _load_section_domains(dynamodb_client, sld, 'WM_WEEKLYUPDATE'),
            'monthly': _load_section_domains(dynamodb_client, sld, 'WM_MONTHLY', 'WM_MONTHLYUPDATE'),
            'quarterly': _load_section_domains(dynamodb_client, sld, 'WM_QUARTERLYUPDATE'),
        },
        'expiredRegistrations': {
            'daily': _load_section_domains(dynamodb_client, sld, 'WM_DAILYREMOVE'),
            'weekly': _load_section_domains(dynamodb_client, sld, 'WM_WEEKLYREMOVE'),
            'monthly': _load_section_domains(dynamodb_client, sld, 'WM_MONTHLYREMOVE'),
            'quarterly': _load_section_domains(dynamodb_client, sld, 'WM_QUARTERLYREMOVE'),
        },
        'allDomains': _load_section_domains(dynamodb_client, sld, 'WM_FULL'),
    }


def _render_form(authorization_header, identity, domains=None):
    auth_header_json = json.dumps(authorization_header)
    safe_email = html.escape(identity.get('email', 'unknown'))
    safe_region = html.escape(identity.get('region', 'unknown'))
    domains = domains or []
    if domains:
        domain_list_html = ''.join(
            '<li><a href="#" onclick="showDomain(\'{d}\'); return false;">{d}</a></li>'.format(
                d=html.escape(domain)
            )
            for domain in domains
        )
        domains_section = f'''
            <section class="domains">
                <h2>Domains</h2>
                <ol>
                    {domain_list_html}
                </ol>
            </section>
        '''
    else:
        domains_section = '''
            <section class="domains">
                <h2>Domains</h2>
                <ul>
                    <li>Empty!</li>
                </ul>
            </section>
        '''
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Gone Fishing!</title>
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

        .identity {{
            margin: 0 0 24px;
            padding: 12px 14px;
            border: 1px solid #c6d3e1;
            border-radius: 10px;
            background: #f8fbff;
            text-align: left;
            line-height: 1.5;
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

        .domains {{
            margin-top: 24px;
            text-align: left;
            border-top: 1px solid #dbe5f0;
            padding-top: 16px;
        }}

        .domains h2 {{
            margin: 0 0 10px;
            font-size: 1rem;
        }}

        .domains ul {{
            margin: 0;
            padding-left: 20px;
        }}

        .domains li {{
            margin-bottom: 6px;
        }}

        .domains a {{
            color: #0e7490;
            text-decoration: none;
        }}

        .domains a:hover {{
            text-decoration: underline;
        }}

        .domains-empty {{
            margin: 0;
            text-align: left;
        }}

        .domain-sections {{
            margin-top: 24px;
            border-top: 1px solid #dbe5f0;
            padding-top: 16px;
            text-align: left;
        }}

        .domain-sections h3 {{
            margin: 16px 0 8px;
            font-size: 1rem;
            color: #10233c;
        }}

        .domain-sections h3:first-child {{
            margin-top: 0;
        }}

        .domain-sections h4 {{
            margin: 12px 0 8px;
            font-size: 0.95rem;
            font-weight: 400;
            color: #10233c;
            text-decoration: underline;
        }}

        .domain-sections ul {{
            margin: 0;
            padding-left: 20px;
        }}

        .domain-sections ol {{
            margin: 0;
            padding-left: 20px;
        }}

        .domain-sections li {{
            margin-bottom: 6px;
        }}

        .btn-primary {{
            display: inline-block;
            margin-top: 16px;
            border: 0;
            border-radius: 999px;
            background: #0e7490;
            color: #ffffff;
            cursor: pointer;
            font-size: 1rem;
            padding: 12px 28px;
            text-decoration: none;
        }}

        .actions .btn-primary {{
            margin-top: 0;
        }}
    </style>
</head>
<body>
    <main>
        <img src="https://cdn.lukach.io/lunker.png" alt="Lunker Logo">

        <div class="identity">
            <strong>Email:</strong> {safe_email}<br>
            <strong>Region:</strong> {safe_region}
        </div>

        <form id="home-form">
            <label for="entry">Domain</label>
            <input id="entry" name="entry" type="text" required>

            <div class="options">
                <label><input type="radio" name="action" value="PutItem" checked> Add</label>
                <label><input type="radio" name="action" value="DeleteItem"> Remove</label>
            </div>

            <p id="entry-print"></p>

            <div class="actions">
                <button class="btn-primary" type="button" onclick="submitHomeForm()">Submit</button>
            </div>

            {domains_section}
        </form>
    </main>

    <script>
        function validateDomain(domain) {{
            const issues = [];
            if (!domain) {{
                issues.push('Domain is required.');
                return issues;
            }}

            const labels = domain.split('.');
            if (labels.length < 2 || (labels.length === 2 && labels[1] === '')) {{
                issues.push('Domain must include a single dot (e.g. example.com).');
                return issues;
            }}
            if (labels.length !== 2) {{
                issues.push('Domain must contain exactly one dot (no subdomains allowed).');
                return issues;
            }}

            const sldPattern = /^[a-z0-9](?:[a-z0-9-]{{0,61}}[a-z0-9])?$/;
            const tldPattern = /^[a-z0-9-]{{2,63}}$/;
            const sld = labels[0];
            const tld = labels[1];

            if (!sldPattern.test(sld)) {{
                issues.push('Invalid second-level domain.');
            }}

            if (!tldPattern.test(tld)) {{
                issues.push('Invalid top-level domain format.');
            }}

            return issues;
        }}

        async function submitHomeForm() {{
            const form = document.getElementById('home-form');
            const formData = new FormData(form);
            const action = formData.get('action');
            const entry = formData.get('entry');
            const normalizedEntry = (entry || '').trim().toLowerCase();
            const entryPrint = document.getElementById('entry-print');
            const authHeader = {auth_header_json};

            document.getElementById('entry').value = normalizedEntry;
            const issues = validateDomain(normalizedEntry);
            if (issues.length > 0) {{
                entryPrint.style.color = '#b42318';
                entryPrint.innerHTML = issues.join('<br>');
                return;
            }}

            entryPrint.style.color = '#166534';
            entryPrint.textContent = 'Submitting…';

            try {{
                const response = await fetch('{API_ENDPOINT}', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json',
                        'Authorization': authHeader || ''
                    }},
                    body: JSON.stringify({{ action, entry: normalizedEntry }})
                }});

                if (!response.ok) {{
                    entryPrint.style.color = '#b42318';
                    entryPrint.textContent = 'Submission failed: HTTP ' + response.status;
                    return;
                }}

                const responseHtml = await response.text();
                document.open();
                document.write(responseHtml);
                document.close();
            }} catch (err) {{
                entryPrint.style.color = '#b42318';
                entryPrint.textContent = 'Submission failed: ' + err.message;
            }}
        }}

        function goHome() {{
            fetch('{API_ENDPOINT}', {{
                method: 'GET',
                headers: {{ 'Authorization': {auth_header_json} || '' }}
            }})
            .then(r => r.text())
            .then(h => {{ document.open(); document.write(h); document.close(); }})
            .catch(() => {{ window.location.href = '{API_ENDPOINT}'; }});
        }}

        function escapeHtml(value) {{
            return String(value || '')
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');
        }}

        function renderNumberedList(items) {{
            if (!Array.isArray(items) || items.length === 0) {{
                return '<ul><li>Empty!</li></ul>';
            }}

            const rows = items.map(item => '<li>' + escapeHtml(item) + '</li>').join('');
            return '<ol>' + rows + '</ol>';
        }}

        function getEmptySections() {{
            return {{
                suspect: {{
                    openSourceIntelligence: [],
                    domainsMonitorSubscription: []
                }},
                newRegistrations: {{
                    daily: [],
                    weekly: [],
                    monthly: [],
                    quarterly: []
                }},
                expiredRegistrations: {{
                    daily: [],
                    weekly: [],
                    monthly: [],
                    quarterly: []
                }},
                allDomains: []
            }};
        }}

        async function fetchDomainSections(domain) {{
            const authHeader = {auth_header_json};
            const fallback = getEmptySections();

            try {{
                const response = await fetch('{API_ENDPOINT}', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json',
                        'Authorization': authHeader || ''
                    }},
                    body: JSON.stringify({{ action: 'GetDomainSections', entry: domain }})
                }});

                if (!response.ok) {{
                    return fallback;
                }}

                const payload = await response.json();
                return payload.sections || fallback;
            }} catch (_err) {{
                return fallback;
            }}
        }}

        function renderDomainView(domain, sections) {{
            const safeDomain = escapeHtml(domain);
            const safeSections = sections || getEmptySections();

            document.querySelector('main').innerHTML =
                '<img src="https://cdn.lukach.io/lunker.png" alt="Lunker Logo">' +
                '<p><strong>Domain:</strong> ' + safeDomain + '</p>' +
                '<div style="text-align:center;">' +
                '<a class="btn-primary" href="#" onclick="goHome(); return false;">Back</a>' +
                '</div>' +
                '<div class="domain-sections">' +
                '<h3>Suspect Domains</h3>' +
                '<h4>Open Source Intelligence</h4>' +
                renderNumberedList(safeSections.suspect?.openSourceIntelligence || []) +
                '<h4>Domains Monitor Subscription</h4>' +
                renderNumberedList(safeSections.suspect?.domainsMonitorSubscription || []) +
                '<h3>New Registrations</h3>' +
                '<h4>Daily</h4>' +
                renderNumberedList(safeSections.newRegistrations?.daily || []) +
                '<h4>Weekly</h4>' +
                renderNumberedList(safeSections.newRegistrations?.weekly || []) +
                '<h4>Monthly</h4>' +
                renderNumberedList(safeSections.newRegistrations?.monthly || []) +
                '<h4>Quarterly</h4>' +
                renderNumberedList(safeSections.newRegistrations?.quarterly || []) +
                '<h3>Expired Registrations</h3>' +
                '<h4>Daily</h4>' +
                renderNumberedList(safeSections.expiredRegistrations?.daily || []) +
                '<h4>Weekly</h4>' +
                renderNumberedList(safeSections.expiredRegistrations?.weekly || []) +
                '<h4>Monthly</h4>' +
                renderNumberedList(safeSections.expiredRegistrations?.monthly || []) +
                '<h4>Quarterly</h4>' +
                renderNumberedList(safeSections.expiredRegistrations?.quarterly || []) +
                '<h3>All Domains</h3>' +
                renderNumberedList(safeSections.allDomains || []) +
                '</div>';
        }}

        async function showDomain(domain) {{
            const sections = await fetchDomainSections(domain);
            renderDomainView(domain, sections);
        }}
    </script>
</body>
</html>'''


def _render_result(action, entry, message, success=True, authorization_header='', operation='submission'):
    safe_message = html.escape(message)
    if operation == 'deletion':
        heading = 'Deletion Successful' if success else 'Deletion Failed'
    else:
        heading = 'Submission Successful' if success else 'Submission Failed'
    message_color = '#166534' if success else '#b42318'
    auth_header_json = json.dumps(authorization_header)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Gone Fishing!</title>
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
            border: 0;
            border-radius: 999px;
            background: #0e7490;
            color: #ffffff;
            cursor: pointer;
            font-size: 1rem;
            padding: 12px 28px;
            text-decoration: none;
        }}
    </style>
</head>
<body>
    <main>
        <img src="https://cdn.lukach.io/lunker.png" alt="Lunker Logo">
        <h1>{heading}</h1>
        <p style="color:{message_color}; white-space: pre-line;">{safe_message}</p>
        <a href="#" onclick="goHome(); return false;">Back</a>
    </main>
    <script>
        async function goHome() {{
            try {{
                const response = await fetch('{API_ENDPOINT}', {{
                    method: 'GET',
                    headers: {{
                        'Authorization': {auth_header_json} || ''
                    }}
                }});
                const responseHtml = await response.text();
                document.open();
                document.write(responseHtml);
                document.close();
            }} catch (err) {{
                window.location.href = '{API_ENDPOINT}';
            }}
        }}
    </script>
</body>
</html>'''


def handler(event, _context):
    print(event)

    method = _get_method(event)
    authorization_header = _get_authorization(event)

    if method == 'POST':
        try:
            payload = json.loads(_get_body(event) or '{}')
        except json.JSONDecodeError:
            payload = {}

        action = payload.get('action', 'PutItem')
        normalized_action = (action or '').strip().lower()

        if normalized_action == 'getdomainsections':
            try:
                sections = _get_domain_sections(payload.get('entry', ''))
            except Exception as exc:
                print(f'GetDomainSections failed: {exc}')
                sections = {}
            return {
                'statusCode': 200,
                'body': json.dumps({'sections': sections}),
                'headers': {
                    'Content-Type': 'application/json; charset=utf-8'
                }
            }

        identity = _fetch_user_identity(authorization_header)
        domain, success, message = _process_submission(
            payload.get('entry', ''),
            identity.get('email', 'unknown'),
            action,
        )

        operation = 'deletion' if normalized_action == 'deleteitem' else 'submission'
        if normalized_action == 'putitem':
            if success:
                message = domain
            else:
                message = f'{domain}\n\n{message}'
        elif normalized_action == 'deleteitem' and success:
            message = domain

        if not success:
            action = f'{action} (Not Saved)'.strip()
        response_html = _render_result(action, domain, message, success, authorization_header, operation)
    else:
        identity = _fetch_user_identity(authorization_header)
        dynamodb = boto3.resource('dynamodb')
        lunker_table = dynamodb.Table(os.environ['LUNKER_TABLE'])
        domains = _list_lunker_domains(lunker_table, identity.get('email', 'unknown'))
        response_html = _render_form(authorization_header, identity, domains)

    return {
        'statusCode': 200,
        'body': response_html,
        'headers': {
            'Content-Type': 'text/html; charset=utf-8'
        }
    }
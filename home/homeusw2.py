import base64
import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
import html
import json
import os
import time
import requests

API_ENDPOINT = 'https://usw2.api.lukach.io/home'
LOGOUT_ENDPOINT = 'https://usw2.api.lukach.io/auth?action=logout'
USER_INFO_ENDPOINT = 'https://hello-usw2.lukach.io/oauth2/userInfo'

HTTP_SESSION = requests.Session()
IDENTITY_CACHE = {}
IDENTITY_CACHE_TTL_SECONDS = 300
IDENTITY_CACHE_MAX_ENTRIES = 256
MATCHED_SLD_CACHE = {}
MATCHED_SLD_CACHE_TTL_SECONDS = 60
MATCHED_SLD_CACHE_MAX_ENTRIES = 256
SEARCH_FIELDS_CACHE = {}
SEARCH_FIELDS_CACHE_TTL_SECONDS = 60
SEARCH_FIELDS_CACHE_MAX_ENTRIES = 32

DYNAMODB_CONFIG = Config(
    retries={
        'max_attempts': 4,
        'mode': 'adaptive',
    },
    max_pool_connections=50,
    connect_timeout=2,
    read_timeout=5,
    tcp_keepalive=True,
)
DYNAMODB_RESOURCE = boto3.resource('dynamodb', config=DYNAMODB_CONFIG)
DYNAMODB_CLIENT = boto3.client('dynamodb', config=DYNAMODB_CONFIG)
TABLE_CACHE = {}


def _get_table(table_name):
    table = TABLE_CACHE.get(table_name)
    if table is not None:
        return table

    table = DYNAMODB_RESOURCE.Table(table_name)
    TABLE_CACHE[table_name] = table
    return table


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


def _decode_jwt_payload(authorization_header):
    normalized_authorization = _normalize_authorization(authorization_header)
    if not normalized_authorization:
        return {}

    token = normalized_authorization.split(' ', 1)[1].strip()
    token_parts = token.split('.')
    if len(token_parts) < 2:
        return {}

    payload_segment = token_parts[1]
    payload_segment += '=' * (-len(payload_segment) % 4)

    try:
        decoded_payload = base64.urlsafe_b64decode(payload_segment.encode('utf-8')).decode('utf-8')
        payload = json.loads(decoded_payload)
    except (ValueError, json.JSONDecodeError):
        return {}

    return payload if isinstance(payload, dict) else {}


def _build_identity(payload, default_region):
    return {
        'email': (
            payload.get('email')
            or payload.get('username')
            or payload.get('cognito:username')
            or 'unknown'
        ),
        'region': (
            payload.get('region')
            or payload.get('custom:region')
            or payload.get('zoneinfo')
            or default_region
        ),
    }


def _get_cached_identity(normalized_authorization):
    cached_entry = IDENTITY_CACHE.get(normalized_authorization)
    if not cached_entry:
        return None

    cached_at, identity = cached_entry
    if (time.time() - cached_at) > IDENTITY_CACHE_TTL_SECONDS:
        IDENTITY_CACHE.pop(normalized_authorization, None)
        return None

    return dict(identity)


def _cache_identity(normalized_authorization, identity):
    if not normalized_authorization or not identity or identity.get('email') == 'unknown':
        return

    if len(IDENTITY_CACHE) >= IDENTITY_CACHE_MAX_ENTRIES:
        oldest_key = min(IDENTITY_CACHE, key=lambda key: IDENTITY_CACHE[key][0])
        IDENTITY_CACHE.pop(oldest_key, None)

    IDENTITY_CACHE[normalized_authorization] = (time.time(), dict(identity))


def _fetch_user_identity(authorization_header):
    default_region = os.getenv('AWS_REGION', 'unknown')
    default_identity = {
        'email': 'unknown',
        'region': default_region,
    }
    normalized_authorization = _normalize_authorization(authorization_header)
    if not normalized_authorization:
        return default_identity

    cached_identity = _get_cached_identity(normalized_authorization)
    if cached_identity:
        return cached_identity

    try:
        response = HTTP_SESSION.get(
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
        payload = _decode_jwt_payload(authorization_header)
        return {
            'email': 'unknown',
            'region': (
                payload.get('region')
                or payload.get('custom:region')
                or payload.get('zoneinfo')
                or default_region
            ),
        }

    identity = _build_identity(payload, default_region)
    _cache_identity(normalized_authorization, identity)
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
            'tk': f'LUNKER#{sld}#{email}#{domain}',
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
    index_query_kwargs = {
        'IndexName': 'email-domain-index',
        'KeyConditionExpression': Key('email').eq(email),
        'ProjectionExpression': '#domain',
        'ExpressionAttributeNames': {
            '#domain': 'domain',
        },
    }

    def _collect_from_query(query_kwargs):
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

    fallback_query_kwargs = {
        'KeyConditionExpression': Key('pk').eq('LUNKER#') & Key('sk').begins_with(f'LUNKER#{email}#'),
        'ProjectionExpression': '#domain',
        'ExpressionAttributeNames': {
            '#domain': 'domain',
        },
    }

    try:
        _collect_from_query(index_query_kwargs)
    except ClientError as exc:
        error_code = exc.response.get('Error', {}).get('Code', '')
        if error_code not in ('ValidationException', 'ResourceNotFoundException'):
            return []
    except (BotoCoreError, KeyError, TypeError):
        return []

    if not domains:
        try:
            _collect_from_query(fallback_query_kwargs)
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

    tld_table = _get_table(os.environ['TLD_TABLE'])
    lunker_table = _get_table(os.environ['LUNKER_TABLE'])

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
        'ProjectionExpression': '#sk, #domain, #fqdn, #host, #name',
        'ExpressionAttributeNames': {
            '#sk': 'sk',
            '#domain': 'domain',
            '#fqdn': 'fqdn',
            '#host': 'host',
            '#name': 'name',
        },
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


def _normalize_search_field(value):
    normalized_value = _normalize_domain(value)
    if not normalized_value:
        return ''

    if '.' in normalized_value:
        return normalized_value.split('.', 1)[0]

    return normalized_value


def _extract_search_field_value(item):
    if not isinstance(item, dict):
        return ''

    for key in ('search', 'searchField', 'searchfield', 'sld'):
        normalized_value = _normalize_search_field(item.get(key))
        if normalized_value:
            return normalized_value

    return ''


def _query_search_fields(dynamodb_client, table_identifier):
    search_fields = []
    expression_values = {
        ':pk': {'S': 'LUNKER#'},
        ':sk': {'S': 'LUNKER#'},
    }
    query_kwargs = {
        'TableName': table_identifier,
        'KeyConditionExpression': 'pk = :pk AND begins_with(sk, :sk)',
        'ExpressionAttributeValues': expression_values,
        'ProjectionExpression': '#sk, #search, #searchField, #searchfield, #sld',
        'ExpressionAttributeNames': {
            '#sk': 'sk',
            '#search': 'search',
            '#searchField': 'searchField',
            '#searchfield': 'searchfield',
            '#sld': 'sld',
        },
    }

    while True:
        response = dynamodb_client.query(**query_kwargs)
        for item in response.get('Items', []):
            normalized_item = {
                key: next(iter(value.values())) if isinstance(value, dict) and value else value
                for key, value in item.items()
            }
            search_field = _extract_search_field_value(normalized_item)
            if search_field:
                search_fields.append(search_field)

        last_evaluated_key = response.get('LastEvaluatedKey')
        if not last_evaluated_key:
            break
        query_kwargs['ExclusiveStartKey'] = last_evaluated_key

    return sorted(set(search_fields))


def _get_search_field_matches(domains):
    normalized_slds = set()
    for domain in domains or []:
        normalized_domain = _normalize_domain(domain)
        is_valid, _ = _validate_domain(normalized_domain)
        if not is_valid:
            continue

        sld, _ = _split_domain(normalized_domain)
        normalized_slds.add(sld)

    if not normalized_slds:
        return set()

    search_fields = set()

    for env_key in ('WM_DAILYUPDATE', 'WM_DAILYREMOVE', 'WM_MALWARE', 'WM_OSINT'):
        for table_identifier in _resolve_table_identifiers(env_key):
            try:
                search_fields.update(_get_cached_search_fields(DYNAMODB_CLIENT, table_identifier))
            except (BotoCoreError, ClientError, KeyError, TypeError) as exc:
                print(f'Search-field query failed on table {table_identifier}: {exc}')

    return normalized_slds.intersection(search_fields)


def _normalize_domain_list(domains):
    normalized_domains = []
    for domain in domains or []:
        normalized_domain = _normalize_domain(domain)
        if normalized_domain:
            normalized_domains.append(normalized_domain)

    return sorted(set(normalized_domains))


def _get_cached_matched_slds(cache_key):
    cached_entry = MATCHED_SLD_CACHE.get(cache_key)
    if not cached_entry:
        return None

    cached_at, matched_slds = cached_entry
    if (time.time() - cached_at) > MATCHED_SLD_CACHE_TTL_SECONDS:
        MATCHED_SLD_CACHE.pop(cache_key, None)
        return None

    return set(matched_slds)


def _cache_matched_slds(cache_key, matched_slds):
    if len(MATCHED_SLD_CACHE) >= MATCHED_SLD_CACHE_MAX_ENTRIES:
        oldest_key = min(MATCHED_SLD_CACHE, key=lambda key: MATCHED_SLD_CACHE[key][0])
        MATCHED_SLD_CACHE.pop(oldest_key, None)

    MATCHED_SLD_CACHE[cache_key] = (time.time(), sorted(set(matched_slds)))


def _get_cached_search_fields_entry(table_identifier):
    cached_entry = SEARCH_FIELDS_CACHE.get(table_identifier)
    if not cached_entry:
        return None

    cached_at, search_fields = cached_entry
    if (time.time() - cached_at) > SEARCH_FIELDS_CACHE_TTL_SECONDS:
        SEARCH_FIELDS_CACHE.pop(table_identifier, None)
        return None

    return set(search_fields)


def _cache_search_fields(table_identifier, search_fields):
    if len(SEARCH_FIELDS_CACHE) >= SEARCH_FIELDS_CACHE_MAX_ENTRIES:
        oldest_key = min(SEARCH_FIELDS_CACHE, key=lambda key: SEARCH_FIELDS_CACHE[key][0])
        SEARCH_FIELDS_CACHE.pop(oldest_key, None)

    SEARCH_FIELDS_CACHE[table_identifier] = (time.time(), sorted(set(search_fields)))


def _get_cached_search_fields(dynamodb_client, table_identifier):
    cached_search_fields = _get_cached_search_fields_entry(table_identifier)
    if cached_search_fields is not None:
        return cached_search_fields

    search_fields = set(_query_search_fields(dynamodb_client, table_identifier))
    _cache_search_fields(table_identifier, search_fields)
    return search_fields


def _get_matched_slds(domains):
    normalized_domains = _normalize_domain_list(domains)
    if not normalized_domains:
        return set()

    cache_key = tuple(normalized_domains)
    cached_match = _get_cached_matched_slds(cache_key)
    if cached_match is not None:
        return cached_match

    matched_slds = _get_search_field_matches(normalized_domains)
    _cache_matched_slds(cache_key, matched_slds)
    return matched_slds


def _get_domain_sections(domain):
    normalized_domain = _normalize_domain(domain)
    is_valid, _ = _validate_domain(normalized_domain)
    if not is_valid:
        return {}

    sld, _ = _split_domain(normalized_domain)
    dynamodb_client = DYNAMODB_CLIENT

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
        }
    }


def _get_permutation_count(domain):
    normalized_domain = _normalize_domain(domain)
    is_valid, _ = _validate_domain(normalized_domain)
    if not is_valid:
        return 0

    sld, _ = _split_domain(normalized_domain)
    permutation_table_name = os.getenv('PERMUTATION_TABLE', 'permutation')
    table = _get_table(permutation_table_name)

    try:
        response = table.get_item(
            Key={
                'pk': 'LUNKER#',
                'sk': f'LUNKER#{sld}',
            },
            ProjectionExpression='#count',
            ExpressionAttributeNames={
                '#count': 'count',
            },
        )
    except (BotoCoreError, ClientError, KeyError, TypeError) as exc:
        print(f'Permutation count lookup failed for {normalized_domain}: {exc}')
        return 0

    item = response.get('Item') or {}
    count = item.get('count', 0)
    try:
        return int(count)
    except (TypeError, ValueError, ArithmeticError):
        if isinstance(count, str):
            try:
                return int(float(count))
            except (TypeError, ValueError, ArithmeticError):
                return 0
        return 0


def _get_domain_permutations(domain):
    normalized_domain = _normalize_domain(domain)
    is_valid, _ = _validate_domain(normalized_domain)
    if not is_valid:
        return []

    sld, _ = _split_domain(normalized_domain)
    permutation_table_name = os.getenv('PERMUTATION_TABLE', 'permutation')
    table = _get_table(permutation_table_name)

    try:
        response = table.get_item(
            Key={
                'pk': 'LUNKER#',
                'sk': f'LUNKER#{sld}',
            },
            ProjectionExpression='#perm',
            ExpressionAttributeNames={
                '#perm': 'perm',
            },
        )
    except (BotoCoreError, ClientError, KeyError, TypeError) as exc:
        print(f'Permutation lookup failed for {normalized_domain}: {exc}')
        return []

    item = response.get('Item') or {}
    permutations = item.get('perm', [])
    if not isinstance(permutations, list):
        return []

    normalized_permutations = []
    for permutation in permutations:
        if permutation is None:
            continue
        normalized_permutations.append(str(permutation))
    return normalized_permutations


def _render_form(authorization_header, identity, domains=None, matched_slds=None):
    auth_header_json = json.dumps(authorization_header)
    safe_email = html.escape(identity.get('email', 'unknown'))
    safe_region = html.escape(identity.get('region', 'unknown'))
    domains = domains or []
    matched_slds = matched_slds or set()
    domains_json = json.dumps(domains)
    if domains:
        domain_items = []
        for domain in domains:
            css_class = ''
            normalized_domain = _normalize_domain(domain)
            is_valid, _ = _validate_domain(normalized_domain)
            if is_valid:
                sld, _ = _split_domain(normalized_domain)
                if sld in matched_slds:
                    css_class = ' class="matched-domain"'

            safe_domain = html.escape(domain)
            domain_items.append(
                '<li><a data-domain="{d}"{css_class} href="#" onclick="showDomain(\'{d}\'); return false;">{d}</a></li>'.format(
                    d=safe_domain,
                    css_class=css_class
                )
            )

        domain_list_html = ''.join(domain_items)
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

        body.modal-open {{
            overflow: hidden;
        }}

        main {{
            position: relative;
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

        .domains a.matched-domain {{
            color: #ff0000;
            font-weight: 700;
        }}

        .domains a:hover {{
            text-decoration: underline;
        }}

        .inline-link {{
            color: #0e7490;
            text-decoration: none;
        }}

        .inline-link:hover {{
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

        .domain-sections .attention-text {{
            color: #ff0000;
            font-weight: 700;
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

        .card-actions {{
            position: absolute;
            top: 16px;
            right: 16px;
            display: flex;
            gap: 8px;
        }}

        .help-button {{
            width: 34px;
            height: 34px;
            border: 1px solid #cbd5e1;
            border-radius: 50%;
            background: #ffffff;
            color: #10233c;
            font-size: 1rem;
            font-weight: 700;
            line-height: 1;
            cursor: pointer;
        }}

        .help-button:hover {{
            background: #f8fafc;
        }}

        .logoff-button {{
            width: 34px;
            height: 34px;
            border: 1px solid #cbd5e1;
            border-radius: 50%;
            background: #ffffff;
            color: #10233c;
            font-size: 0.95rem;
            font-weight: 700;
            line-height: 1;
            cursor: pointer;
        }}

        .logoff-button:hover {{
            background: #f8fafc;
        }}

        .help-modal-overlay {{
            position: fixed;
            inset: 0;
            display: none;
            align-items: center;
            justify-content: center;
            background: rgba(16, 35, 60, 0.45);
            padding: 16px;
            z-index: 1000;
        }}

        .help-modal-overlay.open {{
            display: flex;
        }}

        .help-modal {{
            width: min(420px, 100%);
            padding: 18px 18px 14px;
            border: 1px solid #dbe4ee;
            border-radius: 14px;
            background: #ffffff;
            box-shadow: 0 18px 36px rgba(16, 35, 60, 0.2);
            text-align: left;
            max-height: 80vh;
            overflow-y: auto;
        }}

        .help-modal h2 {{
            margin: 0 0 12px;
            font-size: 1rem;
        }}

        .help-modal h3 {{
            margin: 14px 0 8px;
            font-size: 0.98rem;
            color: #10233c;
        }}

        .help-modal h4 {{
            margin: 12px 0 8px;
            font-size: 0.92rem;
            color: #10233c;
        }}

        .help-steps {{
            margin: 0;
            padding-left: 20px;
            color: #486581;
            font-size: 0.92rem;
        }}

        .help-rules {{
            margin: 0;
            padding-left: 20px;
            color: #486581;
            font-size: 0.9rem;
        }}

        .help-rules li {{
            margin-bottom: 8px;
        }}

        .help-steps li {{
            margin-bottom: 12px;
        }}

        .help-steps span {{
            display: block;
            margin-bottom: 6px;
            font-weight: 600;
            color: #10233c;
        }}

        .help-steps img {{
            display: block;
            max-width: 100%;
            border-radius: 8px;
            border: 1px solid #dbe4ee;
            margin: 0;
        }}

        .help-close {{
            display: inline-block;
            margin-top: 12px;
            border: 0;
            border-radius: 999px;
            background: #0e7490;
            color: #ffffff;
            font-size: 1rem;
            padding: 12px 28px;
            cursor: pointer;
        }}
    </style>
</head>
<body>
    <section id="lunker-help" class="help-modal-overlay" aria-hidden="true" aria-live="polite">
        <div class="help-modal" role="dialog" aria-modal="true" aria-label="Lunker Help">
            <h2 style="text-align:center">Lunker Help</h2>

            <h3>Add Domain</h3>
            <ol class="help-steps">
                <li>
                    <span>Step 1: Enter a Domain</span>
                    In the Domain field, enter a second-level domain (for example: example.com), keep <b>Add</b> selected, then click <b>Submit</b>.
                    <img src="https://cdn.lukach.io/help/add-domain.png" alt="Add Domain">
                </li>
                <li>
                    <span>Step 2: Domain Validation Runs</span>
                    Client-side validation runs before submit continues.
                    <img src="https://cdn.lukach.io/help/domain-validation.png" alt="Domain Validation">
                </li>
                <li>
                    <span>Step 3: Submission Failed Case</span>
                    If backend validation fails, the app shows a failed submission result.
                    <img src="https://cdn.lukach.io/help/submission-failed.png" alt="Submission Failed">
                </li>
                <li>
                    <span>Step 4: Successful Add</span>
                    If all checks pass, the domain is stored and success is shown.
                    <img src="https://cdn.lukach.io/help/successful-add.png" alt="Successful Add">
                </li>
            </ol>

            <h4>Domain Validation On Submit</h4>
            <ul class="help-rules">
                <li>Domain is required (cannot be empty).</li>
                <li>Must include one dot and exactly two labels (example.com format).</li>
                <li>No subdomains are allowed.</li>
                <li>Second-level label regex: starts/ends alphanumeric, dashes allowed only inside.</li>
                <li>Top-level label regex: 2-63 chars using alphanumeric or dash.</li>
                <li>Entry is normalized to lowercase and trimmed.</li>
            </ul>

            <h4>Validation That Produces Submission Failed</h4>
            <ul class="help-rules">
                <li>Client-side validation rules above fail.</li>
                <li>User email cannot be resolved from token (unknown identity).</li>
                <li>Top-level domain is not found in the TLD table.</li>
                <li>POST request returns non-OK HTTP status.</li>
                <li>Network or runtime fetch error during submit.</li>
            </ul>

            <h3>Remove Domain</h3>
            <ol class="help-steps">
                <li>
                    <span>Step 1: Select Remove and Submit</span>
                    Enter an existing domain, select <b>Remove</b>, then click <b>Submit</b>.
                    <img src="https://cdn.lukach.io/help/remove-domain.png" alt="Remove Domain">
                </li>
                <li>
                    <span>Step 2: Successful Delete</span>
                    If the request succeeds, the domain is removed and a success result is shown.
                    <img src="https://cdn.lukach.io/help/successful-delete.png" alt="Successful Delete">
                </li>
            </ol>
            <div style="text-align:center">
                <button class="help-close" type="button" onclick="closeHelp()">Close</button>
            </div>
        </div>
    </section>
    <main>
        <div class="card-actions">
            <button class="help-button" type="button" title="Lunker Help" onclick="toggleHelp()">?</button>
            <button class="logoff-button" type="button" title="Cognito Log Off" onclick="logOff()">X</button>
        </div>
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

        const initialDomains = {domains_json};

        function applyMatchedDomainHighlights(matchedSlds) {{
            const highlightSet = new Set((matchedSlds || []).map(value => String(value || '').toLowerCase()));
            document.querySelectorAll('.domains a[data-domain]').forEach(link => {{
                const domain = (link.getAttribute('data-domain') || '').toLowerCase();
                const sld = domain.includes('.') ? domain.split('.')[0] : domain;
                link.classList.toggle('matched-domain', highlightSet.has(sld));
            }});
        }}

        async function loadMatchedDomains() {{
            const authHeader = {auth_header_json};
            if (!Array.isArray(initialDomains) || initialDomains.length === 0) {{
                return;
            }}

            try {{
                const response = await fetch('{API_ENDPOINT}', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json',
                        'Authorization': authHeader || ''
                    }},
                    body: JSON.stringify({{ action: 'GetMatchedSlds', domains: initialDomains }})
                }});

                if (!response.ok) {{
                    return;
                }}

                const payload = await response.json();
                applyMatchedDomainHighlights(payload.matchedSlds || []);
            }} catch (_err) {{
                // Ignore highlight refresh failures so the page stays responsive.
            }}
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

        function renderNumberedList(items, emphasize = false) {{
            if (!Array.isArray(items) || items.length === 0) {{
                return '<ul><li>Empty!</li></ul>';
            }}

            const rows = items
                .map(item => '<li>' + (emphasize ? '<span class="attention-text">' + escapeHtml(item) + '</span>' : escapeHtml(item)) + '</li>')
                .join('');
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
                }}
            }};
        }}

        async function fetchDomainSections(domain) {{
            const authHeader = {auth_header_json};
            const fallback = {{
                sections: getEmptySections(),
                permutations: 0
            }};

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
                const permutations = Number(payload.permutations);
                return {{
                    sections: payload.sections || fallback.sections,
                    permutations: Number.isFinite(permutations) ? permutations : 0
                }};
            }} catch (_err) {{
                return fallback;
            }}
        }}

        async function fetchDomainPermutations(domain) {{
            const authHeader = {auth_header_json};

            try {{
                const response = await fetch('{API_ENDPOINT}', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json',
                        'Authorization': authHeader || ''
                    }},
                    body: JSON.stringify({{ action: 'GetDomainPermutations', entry: domain }})
                }});

                if (!response.ok) {{
                    return [];
                }}

                const payload = await response.json();
                return Array.isArray(payload.permutations) ? payload.permutations : [];
            }} catch (_err) {{
                return [];
            }}
        }}

        const domainDetailsCache = new Map();
        const domainPermutationsCache = new Map();

        function renderDomainView(domain, domainDetails) {{
            const safeDomain = escapeHtml(domain);
            const domainLiteral = JSON.stringify(String(domain || '')).replace(/"/g, '&quot;');
            const safeSections = domainDetails?.sections || getEmptySections();
            const safePermutations = Number.isFinite(domainDetails?.permutations)
                ? domainDetails.permutations
                : 0;

            domainDetailsCache.set(domain, {{
                sections: safeSections,
                permutations: safePermutations
            }});

            document.querySelector('main').innerHTML =
                '<div class="card-actions">' +
                '<button class="help-button" type="button" title="Lunker Help" onclick="toggleHelp()">?</button>' +
                '<button class="logoff-button" type="button" title="Cognito Log Off" onclick="logOff()">X</button>' +
                '</div>' +
                '<img src="https://cdn.lukach.io/lunker.png" alt="Lunker Logo">' +
                '<div style="text-align:center; margin: 8px 0 12px; line-height: 1.4;">' +
                '<p style="margin:0;"><strong>Domain:</strong> ' + safeDomain + '</p>' +
                '<p style="margin:4px 0 0;"><strong>Permutations:</strong> <a class="inline-link" href="#" onclick="showPermutations(' + domainLiteral + '); return false;">' + String(safePermutations) + '</a></p>' +
                '</div>' +
                '<div style="text-align:center;">' +
                '<a class="btn-primary" href="#" onclick="goHome(); return false;">Back</a>' +
                '</div>' +
                '<div class="domain-sections">' +
                '<h3>Suspect Domains</h3>' +
                '<h4>Open Source Intelligence</h4>' +
                renderNumberedList(safeSections.suspect?.openSourceIntelligence || [], true) +
                '<h4>Domains Monitor Subscription</h4>' +
                renderNumberedList(safeSections.suspect?.domainsMonitorSubscription || [], true) +
                '<h3>New Domains</h3>' +
                '<h4>Daily</h4>' +
                renderNumberedList(safeSections.newRegistrations?.daily || [], true) +
                '<h4>Weekly</h4>' +
                renderNumberedList(safeSections.newRegistrations?.weekly || []) +
                '<h4>Monthly</h4>' +
                renderNumberedList(safeSections.newRegistrations?.monthly || []) +
                '<h4>Quarterly</h4>' +
                renderNumberedList(safeSections.newRegistrations?.quarterly || []) +
                '<h3>Expired Domains</h3>' +
                '<h4>Daily</h4>' +
                renderNumberedList(safeSections.expiredRegistrations?.daily || [], true) +
                '<h4>Weekly</h4>' +
                renderNumberedList(safeSections.expiredRegistrations?.weekly || []) +
                '<h4>Monthly</h4>' +
                renderNumberedList(safeSections.expiredRegistrations?.monthly || []) +
                '<h4>Quarterly</h4>' +
                renderNumberedList(safeSections.expiredRegistrations?.quarterly || []) +
                '</div>';
        }}

        function renderPermutationsView(domain, permutations) {{
            const safeDomain = escapeHtml(domain);
            const domainLiteral = JSON.stringify(String(domain || '')).replace(/"/g, '&quot;');

            document.querySelector('main').innerHTML =
                '<div class="card-actions">' +
                '<button class="help-button" type="button" title="Lunker Help" onclick="toggleHelp()">?</button>' +
                '<button class="logoff-button" type="button" title="Cognito Log Off" onclick="logOff()">X</button>' +
                '</div>' +
                '<img src="https://cdn.lukach.io/lunker.png" alt="Lunker Logo">' +
                '<div style="text-align:center; margin: 8px 0 12px; line-height: 1.4;">' +
                '<p style="margin:0;"><strong>Domain:</strong> ' + safeDomain + '</p>' +
                '<p style="margin:4px 0 0;"><strong>Permutations:</strong> ' + String(Array.isArray(permutations) ? permutations.length : 0) + '</p>' +
                '</div>' +
                '<div style="text-align:center; margin: 0 0 12px;">' +
                '<a class="btn-primary" href="#" onclick="showDomain(' + domainLiteral + '); return false;">Back</a>' +
                '</div>' +
                '<div class="domain-sections">' +
                '<h3>Permutations</h3>' +
                renderNumberedList(permutations || []) +
                '</div>';
        }}

        async function showDomain(domain) {{
            const domainDetails = domainDetailsCache.get(domain) || await fetchDomainSections(domain);
            renderDomainView(domain, domainDetails);
        }}

        async function showPermutations(domain) {{
            let permutations = domainPermutationsCache.get(domain);
            if (!permutations) {{
                permutations = await fetchDomainPermutations(domain);
                domainPermutationsCache.set(domain, permutations);
            }}

            renderPermutationsView(domain, permutations);
        }}

        function toggleHelp() {{
            const modal = document.getElementById('lunker-help');
            modal.classList.toggle('open');
            document.body.classList.toggle('modal-open', modal.classList.contains('open'));
        }}

        function closeHelp() {{
            const modal = document.getElementById('lunker-help');
            modal.classList.remove('open');
            document.body.classList.remove('modal-open');
        }}

        function logOff() {{
            window.location.href = '{LOGOUT_ENDPOINT}';
        }}

        if (window.requestIdleCallback) {{
            window.requestIdleCallback(() => loadMatchedDomains());
        }} else {{
            window.setTimeout(loadMatchedDomains, 0);
        }}

        window.addEventListener('click', function(event) {{
            const modal = document.getElementById('lunker-help');
            if (event.target === modal) {{
                closeHelp();
            }}
        }});
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
            position: relative;
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

        .card-actions {{
            position: absolute;
            top: 16px;
            right: 16px;
            display: flex;
            gap: 8px;
        }}

        .help-button {{
            width: 34px;
            height: 34px;
            border: 1px solid #cbd5e1;
            border-radius: 50%;
            background: #ffffff;
            color: #10233c;
            font-size: 1rem;
            font-weight: 700;
            line-height: 1;
            cursor: pointer;
        }}

        .help-button:hover {{
            background: #f8fafc;
        }}

        .logoff-button {{
            width: 34px;
            height: 34px;
            border: 1px solid #cbd5e1;
            border-radius: 50%;
            background: #ffffff;
            color: #10233c;
            font-size: 0.95rem;
            font-weight: 700;
            line-height: 1;
            cursor: pointer;
        }}

        .logoff-button:hover {{
            background: #f8fafc;
        }}

        .help-modal-overlay {{
            position: fixed;
            inset: 0;
            display: none;
            align-items: center;
            justify-content: center;
            background: rgba(16, 35, 60, 0.45);
            padding: 16px;
            z-index: 1000;
        }}

        .help-modal-overlay.open {{
            display: flex;
        }}

        .help-modal {{
            width: min(420px, 100%);
            padding: 18px 18px 14px;
            border: 1px solid #dbe4ee;
            border-radius: 14px;
            background: #ffffff;
            box-shadow: 0 18px 36px rgba(16, 35, 60, 0.2);
            text-align: left;
            max-height: 80vh;
            overflow-y: auto;
        }}

        .help-modal h2 {{
            margin: 0 0 12px;
            font-size: 1rem;
        }}

        .help-modal h3 {{
            margin: 14px 0 8px;
            font-size: 0.98rem;
            color: #10233c;
        }}

        .help-modal h4 {{
            margin: 12px 0 8px;
            font-size: 0.92rem;
            color: #10233c;
        }}

        .help-steps {{
            margin: 0;
            padding-left: 20px;
            color: #486581;
            font-size: 0.92rem;
        }}

        .help-rules {{
            margin: 0;
            padding-left: 20px;
            color: #486581;
            font-size: 0.9rem;
        }}

        .help-rules li {{
            margin-bottom: 8px;
        }}

        .help-steps li {{
            margin-bottom: 12px;
        }}

        .help-steps span {{
            display: block;
            margin-bottom: 6px;
            font-weight: 600;
            color: #10233c;
        }}

        .help-steps img {{
            display: block;
            max-width: 100%;
            border-radius: 8px;
            border: 1px solid #dbe4ee;
            margin: 0;
        }}

        .help-close {{
            display: inline-block;
            margin-top: 12px;
            border: 0;
            border-radius: 999px;
            background: #0e7490;
            color: #ffffff;
            font-size: 1rem;
            padding: 12px 28px;
            cursor: pointer;
        }}
    </style>
</head>
<body>
    <section id="lunker-help" class="help-modal-overlay" aria-hidden="true" aria-live="polite">
        <div class="help-modal" role="dialog" aria-modal="true" aria-label="Lunker Help">
            <h2 style="text-align:center">Lunker Help</h2>

            <h3>Add Domain</h3>
            <ol class="help-steps">
                <li>
                    <span>Step 1: Enter a Domain</span>
                    In the Domain field, enter a second-level domain (for example: example.com), keep <b>Add</b> selected, then click <b>Submit</b>.
                    <img src="https://cdn.lukach.io/help/add-domain.png" alt="Add Domain">
                </li>
                <li>
                    <span>Step 2: Domain Validation Runs</span>
                    Client-side validation runs before submit continues.
                    <img src="https://cdn.lukach.io/help/domain-validation.png" alt="Domain Validation">
                </li>
                <li>
                    <span>Step 3: Submission Failed Case</span>
                    If backend validation fails, the app shows a failed submission result.
                    <img src="https://cdn.lukach.io/help/submission-failed.png" alt="Submission Failed">
                </li>
                <li>
                    <span>Step 4: Successful Add</span>
                    If all checks pass, the domain is stored and success is shown.
                    <img src="https://cdn.lukach.io/help/successful-add.png" alt="Successful Add">
                </li>
            </ol>

            <h4>Domain Validation On Submit</h4>
            <ul class="help-rules">
                <li>Domain is required (cannot be empty).</li>
                <li>Must include one dot and exactly two labels (example.com format).</li>
                <li>No subdomains are allowed.</li>
                <li>Second-level label regex: starts/ends alphanumeric, dashes allowed only inside.</li>
                <li>Top-level label regex: 2-63 chars using alphanumeric or dash.</li>
                <li>Entry is normalized to lowercase and trimmed.</li>
            </ul>

            <h4>Validation That Produces Submission Failed</h4>
            <ul class="help-rules">
                <li>Client-side validation rules above fail.</li>
                <li>User email cannot be resolved from token (unknown identity).</li>
                <li>Top-level domain is not found in the TLD table.</li>
                <li>POST request returns non-OK HTTP status.</li>
                <li>Network or runtime fetch error during submit.</li>
            </ul>

            <h3>Remove Domain</h3>
            <ol class="help-steps">
                <li>
                    <span>Step 1: Select Remove and Submit</span>
                    Enter an existing domain, select <b>Remove</b>, then click <b>Submit</b>.
                    <img src="https://cdn.lukach.io/help/remove-domain.png" alt="Remove Domain">
                </li>
                <li>
                    <span>Step 2: Successful Delete</span>
                    If the request succeeds, the domain is removed and a success result is shown.
                    <img src="https://cdn.lukach.io/help/successful-delete.png" alt="Successful Delete">
                </li>
            </ol>
            <div style="text-align:center">
                <button class="help-close" type="button" onclick="closeHelp()">Close</button>
            </div>
        </div>
    </section>
    <main>
        <div class="card-actions">
            <button class="help-button" type="button" title="Lunker Help" onclick="toggleHelp()">?</button>
            <button class="logoff-button" type="button" title="Cognito Log Off" onclick="logOff()">X</button>
        </div>
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

        function toggleHelp() {{
            const modal = document.getElementById('lunker-help');
            modal.classList.toggle('open');
            document.body.classList.toggle('modal-open', modal.classList.contains('open'));
        }}

        function closeHelp() {{
            const modal = document.getElementById('lunker-help');
            modal.classList.remove('open');
            document.body.classList.remove('modal-open');
        }}

        function logOff() {{
            window.location.href = '{LOGOUT_ENDPOINT}';
        }}

        window.addEventListener('click', function(event) {{
            const modal = document.getElementById('lunker-help');
            if (event.target === modal) {{
                closeHelp();
            }}
        }});
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
                permutations = _get_permutation_count(payload.get('entry', ''))
            except Exception as exc:
                print(f'GetDomainSections failed: {exc}')
                sections = {}
                permutations = 0
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'sections': sections,
                    'permutations': permutations,
                }),
                'headers': {
                    'Content-Type': 'application/json; charset=utf-8'
                }
            }

        if normalized_action == 'getdomainpermutations':
            try:
                permutations = _get_domain_permutations(payload.get('entry', ''))
            except Exception as exc:
                print(f'GetDomainPermutations failed: {exc}')
                permutations = []
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'permutations': permutations,
                }),
                'headers': {
                    'Content-Type': 'application/json; charset=utf-8'
                }
            }

        if normalized_action == 'getmatchedslds':
            requested_domains = payload.get('domains', [])
            if not isinstance(requested_domains, list):
                requested_domains = []

            try:
                matched_slds = sorted(_get_matched_slds(requested_domains))
            except Exception as exc:
                print(f'GetMatchedSlds failed: {exc}')
                matched_slds = []

            return {
                'statusCode': 200,
                'body': json.dumps({'matchedSlds': matched_slds}),
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
        lunker_table = _get_table(os.environ['LUNKER_TABLE'])
        domains = _list_lunker_domains(lunker_table, identity.get('email', 'unknown'))
        matched_slds = _get_matched_slds(domains)
        response_html = _render_form(authorization_header, identity, domains, matched_slds)

    return {
        'statusCode': 200,
        'body': response_html,
        'headers': {
            'Content-Type': 'text/html; charset=utf-8'
        }
    }
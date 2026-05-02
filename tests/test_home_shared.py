import os
import unittest
from unittest.mock import patch
import json
import time


# Prevent boto3 from attempting metadata lookups during import in test environments.
os.environ.setdefault('AWS_EC2_METADATA_DISABLED', 'true')
os.environ.setdefault('AWS_DEFAULT_REGION', 'us-east-1')
os.environ.setdefault('AWS_REGION', 'us-east-1')

from home import home_shared


GET_DOMAIN_SECTIONS = getattr(home_shared, '_get_domain_sections')


class WebUiHandlerTests(unittest.TestCase):
    def setUp(self):
        os.environ['LUNKER_TABLE'] = 'lunker-table'
        home_shared.IDENTITY_CACHE.clear()
        home_shared.MATCHED_SLD_CACHE.clear()
        home_shared.SEARCH_FIELDS_CACHE.clear()
        home_shared.TABLE_CACHE.clear()

    def test_get_request_renders_form(self):
        event = {
            'requestContext': {
                'http': {
                    'method': 'GET'
                }
            },
            'headers': {
                'Authorization': 'test-token'
            },
        }

        with patch.object(home_shared, '_fetch_user_identity', return_value={'email': 'user@example.com', 'region': 'use1'}) as fetch_identity, \
                patch.object(home_shared, '_get_table', return_value=object()), \
                patch.object(home_shared, '_list_lunker_domains', return_value=['example.com']), \
                patch.object(home_shared, '_get_matched_slds', return_value={'example'}):
            response = home_shared._handle_request(event, None)

        self.assertEqual(response['statusCode'], 200)
        self.assertEqual(response['headers']['Content-Type'], 'text/html; charset=utf-8')
        self.assertIn('Gone Fishing!', response['body'])
        self.assertIn('example.com', response['body'])
        fetch_identity.assert_called_once_with('test-token')

    def test_post_get_domain_sections_success(self):
        event = {
            'requestContext': {
                'http': {
                    'method': 'POST'
                }
            },
            'body': json.dumps({'action': 'GetDomainSections', 'entry': 'example.com'}),
        }

        expected_sections = {'suspect': {'openSourceIntelligence': [], 'domainsMonitorSubscription': []}}

        with patch.object(home_shared, '_get_domain_sections', return_value=expected_sections), \
                patch.object(home_shared, '_get_permutation_count', return_value=7):
            response = home_shared._handle_request(event, None)

        payload = json.loads(response['body'])
        self.assertEqual(response['statusCode'], 200)
        self.assertEqual(response['headers']['Content-Type'], 'application/json; charset=utf-8')
        self.assertEqual(payload['sections'], expected_sections)
        self.assertEqual(payload['permutations'], 7)

    def test_post_get_domain_sections_failure_falls_back(self):
        event = {
            'requestContext': {
                'http': {
                    'method': 'POST'
                }
            },
            'body': json.dumps({'action': 'GetDomainSections', 'entry': 'example.com'}),
        }

        with patch.object(home_shared, '_get_domain_sections', side_effect=ValueError('boom')):
            response = home_shared._handle_request(event, None)

        payload = json.loads(response['body'])
        self.assertEqual(payload['sections'], {})
        self.assertEqual(payload['permutations'], 0)

    def test_post_get_domain_permutations_success(self):
        event = {
            'requestContext': {
                'http': {
                    'method': 'POST'
                }
            },
            'body': json.dumps({'action': 'GetDomainPermutations', 'entry': 'example.com'}),
        }

        with patch.object(home_shared, '_get_domain_permutations', return_value=['a.com', 'b.com']):
            response = home_shared._handle_request(event, None)

        payload = json.loads(response['body'])
        self.assertEqual(payload['permutations'], ['a.com', 'b.com'])

    def test_post_get_domain_permutations_failure_falls_back(self):
        event = {
            'requestContext': {
                'http': {
                    'method': 'POST'
                }
            },
            'body': json.dumps({'action': 'GetDomainPermutations', 'entry': 'example.com'}),
        }

        with patch.object(home_shared, '_get_domain_permutations', side_effect=TypeError('boom')):
            response = home_shared._handle_request(event, None)

        payload = json.loads(response['body'])
        self.assertEqual(payload['permutations'], [])

    def test_post_get_matched_slds_with_non_list_domains(self):
        event = {
            'requestContext': {
                'http': {
                    'method': 'POST'
                }
            },
            'body': json.dumps({'action': 'GetMatchedSlds', 'domains': 'not-a-list'}),
        }

        with patch.object(home_shared, '_get_matched_slds', return_value={'zeta', 'alpha'}) as get_matched_slds:
            response = home_shared._handle_request(event, None)

        payload = json.loads(response['body'])
        get_matched_slds.assert_called_once_with([])
        self.assertEqual(payload['matchedSlds'], ['alpha', 'zeta'])

    def test_post_put_item_success_renders_submission_result(self):
        event = {
            'requestContext': {
                'http': {
                    'method': 'POST'
                }
            },
            'headers': {
                'Authorization': 'token'
            },
            'body': json.dumps({'action': 'PutItem', 'entry': 'example.com'}),
        }

        with patch.object(home_shared, '_fetch_user_identity', return_value={'email': 'user@example.com'}), \
                patch.object(home_shared, '_process_submission', return_value=('example.com', True, 'saved')), \
                patch.object(home_shared, '_render_result', return_value='<html>ok</html>') as render_result:
            response = home_shared._handle_request(event, None)

        self.assertEqual(response['body'], '<html>ok</html>')
        render_result.assert_called_once_with('example.com', True, 'token', 'submission')

    def test_post_put_item_failure_renders_failure_message(self):
        event = {
            'requestContext': {
                'http': {
                    'method': 'POST'
                }
            },
            'headers': {
                'Authorization': 'token'
            },
            'body': json.dumps({'action': 'PutItem', 'entry': 'bad'}),
        }

        with patch.object(home_shared, '_fetch_user_identity', return_value={'email': 'user@example.com'}), \
                patch.object(home_shared, '_process_submission', return_value=('bad', False, 'Invalid domain')), \
                patch.object(home_shared, '_render_result', return_value='<html>fail</html>') as render_result:
            response = home_shared._handle_request(event, None)

        self.assertEqual(response['body'], '<html>fail</html>')
        render_result.assert_called_once_with('bad\n\nInvalid domain', False, 'token', 'submission')

    def test_post_delete_item_success_renders_deletion_result(self):
        event = {
            'requestContext': {
                'http': {
                    'method': 'POST'
                }
            },
            'headers': {
                'Authorization': 'token'
            },
            'body': json.dumps({'action': 'DeleteItem', 'entry': 'example.com'}),
        }

        with patch.object(home_shared, '_fetch_user_identity', return_value={'email': 'user@example.com'}), \
                patch.object(home_shared, '_process_submission', return_value=('example.com', True, 'deleted')), \
                patch.object(home_shared, '_render_result', return_value='<html>deleted</html>') as render_result:
            response = home_shared._handle_request(event, None)

        self.assertEqual(response['body'], '<html>deleted</html>')
        render_result.assert_called_once_with('example.com', True, 'token', 'deletion')

    def test_post_invalid_json_defaults_to_put_item(self):
        event = {
            'requestContext': {
                'http': {
                    'method': 'POST'
                }
            },
            'headers': {
                'Authorization': 'token'
            },
            'body': '{invalid-json',
        }

        with patch.object(home_shared, '_fetch_user_identity', return_value={'email': 'user@example.com'}), \
                patch.object(home_shared, '_process_submission', return_value=('example.com', True, 'saved')) as process_submission, \
                patch.object(home_shared, '_render_result', return_value='<html>ok</html>'):
            home_shared._handle_request(event, None)

        process_submission.assert_called_once_with('', 'user@example.com', 'PutItem')


class CreateHandlerTests(unittest.TestCase):
    def test_create_handler_applies_configured_endpoints(self):
        configured_handler = home_shared.create_handler('api-url', 'logout-url', 'user-info-url')
        captured = {}

        def fake_handle_request(_event, _context):
            captured['endpoints'] = (
                home_shared.API_ENDPOINT,
                home_shared.LOGOUT_ENDPOINT,
                home_shared.USER_INFO_ENDPOINT,
            )
            return {'statusCode': 200, 'body': 'ok', 'headers': {}}

        with patch.object(home_shared, '_handle_request', side_effect=fake_handle_request):
            configured_handler({}, None)

        self.assertEqual(captured['endpoints'], ('api-url', 'logout-url', 'user-info-url'))

    def test_create_handler_restores_endpoints_after_exception(self):
        old_api = home_shared.API_ENDPOINT
        old_logout = home_shared.LOGOUT_ENDPOINT
        old_user_info = home_shared.USER_INFO_ENDPOINT
        configured_handler = home_shared.create_handler('api-url', 'logout-url', 'user-info-url')

        with patch.object(home_shared, '_handle_request', side_effect=RuntimeError('fail')):
            with self.assertRaises(RuntimeError):
                configured_handler({}, None)

        self.assertEqual(home_shared.API_ENDPOINT, old_api)
        self.assertEqual(home_shared.LOGOUT_ENDPOINT, old_logout)
        self.assertEqual(home_shared.USER_INFO_ENDPOINT, old_user_info)


class DomainSectionsTests(unittest.TestCase):
    def test_invalid_domain_returns_empty_sections(self):
        self.assertEqual(GET_DOMAIN_SECTIONS('invalid-domain'), {})

    def test_suspect_sections_are_loaded_independently(self):
        osint_domains = ['phreeesia.com']
        malware_domains = ['evil-phreeesia.net']

        with patch.object(home_shared, '_load_section_domains') as load_sections:
            load_sections.side_effect = [
                osint_domains,
                malware_domains,
                [],
                [],
                [],
                [],
                [],
                [],
                [],
                [],
            ]

            sections = GET_DOMAIN_SECTIONS('phreeesia.com')

        self.assertEqual(sections['suspect']['openSourceIntelligence'], osint_domains)
        self.assertEqual(sections['suspect']['domainsMonitorSubscription'], malware_domains)

    def test_domain_in_both_tables_appears_in_both_sections(self):
        overlap_domain = ['phreeesia.com']

        with patch.object(home_shared, '_load_section_domains') as load_sections:
            load_sections.side_effect = [
                overlap_domain,
                overlap_domain,
                [],
                [],
                [],
                [],
                [],
                [],
                [],
                [],
            ]

            sections = GET_DOMAIN_SECTIONS('phreeesia.com')

        self.assertEqual(sections['suspect']['openSourceIntelligence'], overlap_domain)
        self.assertEqual(sections['suspect']['domainsMonitorSubscription'], overlap_domain)


class DomainNormalizationTests(unittest.TestCase):
    def test_normalize_domain_strips_whitespace(self):
        self.assertEqual(home_shared._normalize_domain('  Example.COM  '), 'example.com')

    def test_normalize_domain_removes_trailing_dot(self):
        self.assertEqual(home_shared._normalize_domain('example.com.'), 'example.com')

    def test_normalize_domain_empty_string_returns_empty(self):
        self.assertEqual(home_shared._normalize_domain(''), '')

    def test_normalize_domain_non_string_returns_empty(self):
        self.assertEqual(home_shared._normalize_domain(None), '')
        self.assertEqual(home_shared._normalize_domain(123), '')
        self.assertEqual(home_shared._normalize_domain([]), '')

    def test_normalize_domain_multiple_dots(self):
        self.assertEqual(home_shared._normalize_domain('sub.example.com'), 'sub.example.com')


class DomainValidationTests(unittest.TestCase):
    def test_validate_domain_valid_format(self):
        is_valid, msg = home_shared._validate_domain('example.com')
        self.assertTrue(is_valid)
        self.assertEqual(msg, '')

    def test_validate_domain_empty_string(self):
        is_valid, msg = home_shared._validate_domain('')
        self.assertFalse(is_valid)
        self.assertIn('required', msg.lower())

    def test_validate_domain_no_dot(self):
        is_valid, msg = home_shared._validate_domain('example')
        self.assertFalse(is_valid)
        self.assertIn('single dot', msg.lower())

    def test_validate_domain_trailing_dot_format(self):
        is_valid, msg = home_shared._validate_domain('example.')
        self.assertFalse(is_valid)

    def test_validate_domain_subdomain(self):
        is_valid, msg = home_shared._validate_domain('sub.example.com')
        self.assertFalse(is_valid)
        self.assertIn('exactly one dot', msg.lower())

    def test_validate_domain_multiple_subdomains(self):
        is_valid, msg = home_shared._validate_domain('a.b.c.example.com')
        self.assertFalse(is_valid)


class JwtDecodingTests(unittest.TestCase):
    def test_decode_jwt_payload_no_authorization(self):
        payload = home_shared._decode_jwt_payload('')
        self.assertEqual(payload, {})

    def test_decode_jwt_payload_invalid_format(self):
        payload = home_shared._decode_jwt_payload('invalid-token')
        self.assertEqual(payload, {})

    def test_decode_jwt_payload_valid_jwt(self):
        token_payload = {'email': 'user@example.com', 'region': 'us-east-1'}
        import base64
        encoded_payload = base64.urlsafe_b64encode(json.dumps(token_payload).encode()).decode().rstrip('=')
        token = f'Bearer header.{encoded_payload}.signature'

        payload = home_shared._decode_jwt_payload(token)
        self.assertEqual(payload['email'], 'user@example.com')
        self.assertEqual(payload['region'], 'us-east-1')

    def test_decode_jwt_payload_non_dict_payload(self):
        import base64
        encoded_payload = base64.urlsafe_b64encode(b'"not a dict"').decode().rstrip('=')
        token = f'Bearer header.{encoded_payload}.signature'

        payload = home_shared._decode_jwt_payload(token)
        self.assertEqual(payload, {})

    def test_decode_jwt_payload_malformed_json(self):
        import base64
        encoded_payload = base64.urlsafe_b64encode(b'{invalid json}').decode().rstrip('=')
        token = f'Bearer header.{encoded_payload}.signature'

        payload = home_shared._decode_jwt_payload(token)
        self.assertEqual(payload, {})


class IdentityBuildingTests(unittest.TestCase):
    def test_build_identity_with_email_field(self):
        payload = {'email': 'test@example.com', 'region': 'us-west-2'}
        identity = home_shared._build_identity(payload, 'default-region')
        self.assertEqual(identity['email'], 'test@example.com')
        self.assertEqual(identity['region'], 'us-west-2')

    def test_build_identity_fallback_to_username(self):
        payload = {'username': 'testuser', 'region': 'us-east-1'}
        identity = home_shared._build_identity(payload, 'default-region')
        self.assertEqual(identity['email'], 'testuser')

    def test_build_identity_fallback_to_cognito_username(self):
        payload = {'cognito:username': 'cognito-user', 'zoneinfo': 'UTC'}
        identity = home_shared._build_identity(payload, 'default-region')
        self.assertEqual(identity['email'], 'cognito-user')
        self.assertEqual(identity['region'], 'UTC')

    def test_build_identity_fallback_to_custom_region(self):
        payload = {'email': 'user@example.com', 'custom:region': 'ap-southeast-1'}
        identity = home_shared._build_identity(payload, 'default-region')
        self.assertEqual(identity['region'], 'ap-southeast-1')

    def test_build_identity_all_unknown(self):
        payload = {}
        identity = home_shared._build_identity(payload, 'default-region')
        self.assertEqual(identity['email'], 'unknown')
        self.assertEqual(identity['region'], 'default-region')


class AuthorizationNormalizationTests(unittest.TestCase):
    def test_normalize_authorization_with_bearer_prefix(self):
        result = home_shared._normalize_authorization('Bearer token123')
        self.assertEqual(result, 'Bearer token123')

    def test_normalize_authorization_without_prefix(self):
        result = home_shared._normalize_authorization('token123')
        self.assertEqual(result, 'Bearer token123')

    def test_normalize_authorization_empty_string(self):
        result = home_shared._normalize_authorization('')
        self.assertEqual(result, '')

    def test_normalize_authorization_whitespace_only(self):
        result = home_shared._normalize_authorization('   ')
        self.assertEqual(result, '')

    def test_normalize_authorization_case_insensitive_prefix(self):
        result = home_shared._normalize_authorization('bearer token123')
        self.assertEqual(result, 'bearer token123')


class ProcessSubmissionTests(unittest.TestCase):
    def setUp(self):
        os.environ['TLD_TABLE'] = 'tld-table'
        os.environ['LUNKER_TABLE'] = 'lunker-table'

    def test_process_submission_invalid_domain_format(self):
        domain, success, msg = home_shared._process_submission('invalid', 'user@example.com', 'PutItem')
        self.assertFalse(success)
        self.assertIn('single dot', msg.lower())

    def test_process_submission_unknown_email(self):
        domain, success, msg = home_shared._process_submission('example.com', 'unknown', 'PutItem')
        self.assertFalse(success)
        self.assertIn('email', msg.lower())

    def test_process_submission_empty_email(self):
        domain, success, msg = home_shared._process_submission('example.com', '', 'PutItem')
        self.assertFalse(success)

    def test_process_submission_tld_not_found(self):
        mock_tld_table = object()
        mock_lunker_table = object()

        with patch.object(home_shared, '_get_table', side_effect=[mock_tld_table, mock_lunker_table]), \
                patch.object(home_shared, '_tld_exists', return_value=False):
            domain, success, msg = home_shared._process_submission('example.com', 'user@example.com', 'PutItem')

        self.assertFalse(success)
        self.assertIn('Invalid top-level domain', msg)

    def test_process_submission_put_item_success(self):
        mock_tld_table = object()
        mock_lunker_table = object()

        with patch.object(home_shared, '_get_table', side_effect=[mock_tld_table, mock_lunker_table]), \
                patch.object(home_shared, '_tld_exists', return_value=True), \
                patch.object(home_shared, '_put_lunker_domain') as put_domain:
            domain, success, msg = home_shared._process_submission('example.com', 'user@example.com', 'PutItem')

        self.assertTrue(success)
        self.assertEqual(domain, 'example.com')
        put_domain.assert_called_once_with(mock_lunker_table, 'user@example.com', 'example.com')

    def test_process_submission_delete_item_success(self):
        mock_tld_table = object()
        mock_lunker_table = object()

        with patch.object(home_shared, '_get_table', side_effect=[mock_tld_table, mock_lunker_table]), \
                patch.object(home_shared, '_tld_exists', return_value=True), \
                patch.object(home_shared, '_delete_lunker_domain') as delete_domain:
            domain, success, msg = home_shared._process_submission('example.com', 'user@example.com', 'DeleteItem')

        self.assertTrue(success)
        self.assertEqual(domain, 'example.com')
        delete_domain.assert_called_once_with(mock_lunker_table, 'user@example.com', 'example.com')


class RenderFormTests(unittest.TestCase):
    def test_render_form_with_empty_domains(self):
        html = home_shared._render_form('token', {'email': 'user@example.com', 'region': 'us-east-1'}, [], set())
        self.assertIn('Gone Fishing!', html)
        self.assertIn('user@example.com', html)
        self.assertIn('us-east-1', html)
        self.assertIn('Empty!', html)

    def test_render_form_with_domains(self):
        html = home_shared._render_form('token', {'email': 'user@example.com', 'region': 'us-east-1'}, ['example.com'], set())
        self.assertIn('example.com', html)

    def test_render_form_with_matched_slds_highlights(self):
        html = home_shared._render_form('token', {'email': 'user@example.com', 'region': 'us-east-1'}, ['example.com', 'test.com'], {'example'})
        self.assertIn('matched-domain', html)

    def test_render_form_html_escaping(self):
        html = home_shared._render_form('token', {'email': '<script>alert("xss")</script>', 'region': 'us-east-1'}, [], set())
        # Check that malicious script is properly escaped in the identity div
        self.assertIn('<strong>Email:</strong> &lt;script&gt;', html)
        # Verify the escaped version exists
        self.assertIn('&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;', html)

    def test_render_form_none_domains_defaults_to_empty(self):
        html = home_shared._render_form('token', {'email': 'user@example.com', 'region': 'us-east-1'}, None, None)
        self.assertIn('Gone Fishing!', html)
        self.assertIn('Empty!', html)

    def test_render_form_uses_contains_for_sld_matches(self):
        html = home_shared._render_form('token', {'email': 'user@example.com', 'region': 'us-east-1'}, ['example.com'], {'example'})
        self.assertIn('function containsSldMatch(item, matchSld)', html)
        self.assertIn('return normalizedItem.includes(normalizedMatch);', html)

    def test_render_form_header_highlight_checks_sld_before_permutations(self):
        html = home_shared._render_form('token', {'email': 'user@example.com', 'region': 'us-east-1'}, ['example.com'], {'example'})
        self.assertIn('const hasExactSldMatch = safeItems.some(item => containsSldMatch(item, matchSld));', html)
        self.assertIn('if (hasExactSldMatch) {', html)
        self.assertIn("return 'alert';", html)
        self.assertIn('const hasPermutationMatch = safeItems.some(item => containsPermutationMatch(item, permutationTerms));', html)
        self.assertIn("return 'warning';", html)
        self.assertTrue(
            html.index('const hasExactSldMatch = safeItems.some(item => containsSldMatch(item, matchSld));') <
            html.index('const hasPermutationMatch = safeItems.some(item => containsPermutationMatch(item, permutationTerms));')
        )


class RenderResultTests(unittest.TestCase):
    def test_render_result_success_submission(self):
        html = home_shared._render_result('Domain saved', success=True, authorization_header='token', operation='submission')
        self.assertIn('Submission Successful', html)
        self.assertIn('Domain saved', html)
        self.assertIn('#166534', html)  # green color

    def test_render_result_failure_submission(self):
        html = home_shared._render_result('Invalid domain', success=False, authorization_header='token', operation='submission')
        self.assertIn('Submission Failed', html)
        self.assertIn('Invalid domain', html)
        self.assertIn('#b42318', html)  # red color

    def test_render_result_success_deletion(self):
        html = home_shared._render_result('example.com', success=True, authorization_header='token', operation='deletion')
        self.assertIn('Deletion Successful', html)

    def test_render_result_failure_deletion(self):
        html = home_shared._render_result('Error', success=False, authorization_header='token', operation='deletion')
        self.assertIn('Deletion Failed', html)

    def test_render_result_html_escaping(self):
        html = home_shared._render_result('<script>alert("xss")</script>', success=True, authorization_header='token')
        # Check that the malicious script in the message content is properly escaped
        self.assertIn('&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;', html)


class FetchUserIdentityTests(unittest.TestCase):
    def setUp(self):
        os.environ['AWS_REGION'] = 'us-east-1'
        home_shared.IDENTITY_CACHE.clear()

    def test_fetch_user_identity_no_authorization(self):
        identity = home_shared._fetch_user_identity('')
        self.assertEqual(identity['email'], 'unknown')
        self.assertEqual(identity['region'], 'us-east-1')

    def test_fetch_user_identity_cached_entry(self):
        token = 'Bearer test-token'
        cached_identity = {'email': 'cached@example.com', 'region': 'us-west-2'}
        home_shared.IDENTITY_CACHE['Bearer Bearer test-token'] = (time.time(), cached_identity)

        with patch.object(home_shared, '_normalize_authorization', return_value='Bearer Bearer test-token'):
            identity = home_shared._fetch_user_identity(token)

        self.assertEqual(identity['email'], 'cached@example.com')

    def test_fetch_user_identity_expired_cache(self):
        token = 'Bearer test-token'
        old_time = time.time() - (home_shared.IDENTITY_CACHE_TTL_SECONDS + 10)
        home_shared.IDENTITY_CACHE['Bearer Bearer test-token'] = (old_time, {'email': 'old@example.com'})

        with patch.object(home_shared, '_normalize_authorization', return_value='Bearer Bearer test-token'), \
                patch.object(home_shared, '_decode_jwt_payload', return_value={}):
            identity = home_shared._fetch_user_identity(token)

        self.assertEqual(identity['email'], 'unknown')

    def test_fetch_user_identity_http_request_success(self):
        token = 'Bearer test-token'
        normalized_token = 'Bearer test-token'

        mock_response = type('Response', (), {
            'json': lambda self: {'email': 'http@example.com', 'region': 'eu-west-1'},
            'raise_for_status': lambda self: None
        })()

        with patch.object(home_shared, '_normalize_authorization', return_value=normalized_token), \
                patch.object(home_shared.HTTP_SESSION, 'get', return_value=mock_response):
            home_shared.USER_INFO_ENDPOINT = 'https://userinfo'
            identity = home_shared._fetch_user_identity(token)

        self.assertEqual(identity['email'], 'http@example.com')
        self.assertEqual(identity['region'], 'eu-west-1')

    def test_fetch_user_identity_http_request_failure_falls_back_to_jwt(self):
        import requests
        token = 'Bearer test-token'
        normalized_token = 'Bearer test-token'

        with patch.object(home_shared, '_normalize_authorization', return_value=normalized_token), \
                patch.object(home_shared.HTTP_SESSION, 'get', side_effect=requests.RequestException('Network error')), \
                patch.object(home_shared, '_decode_jwt_payload', return_value={'region': 'ap-south-1'}):
            home_shared.USER_INFO_ENDPOINT = 'https://userinfo'
            identity = home_shared._fetch_user_identity(token)

        self.assertEqual(identity['email'], 'unknown')
        self.assertEqual(identity['region'], 'ap-south-1')


class TableNameResolutionTests(unittest.TestCase):
    def test_table_name_from_env_arn_format(self):
        result = home_shared._table_name_from_env('arn:aws:dynamodb:us-east-1:123456789012:table/my-table')
        self.assertEqual(result, 'my-table')

    def test_table_name_from_env_plain_name(self):
        result = home_shared._table_name_from_env('my-table')
        self.assertEqual(result, 'my-table')

    def test_table_name_from_env_empty_string(self):
        result = home_shared._table_name_from_env('')
        self.assertEqual(result, '')

    def test_table_name_from_env_non_string(self):
        result = home_shared._table_name_from_env(None)
        self.assertEqual(result, '')
        result = home_shared._table_name_from_env(123)
        self.assertEqual(result, '')

    def test_resolve_table_identifiers_single_env_key(self):
        with patch.dict(os.environ, {'TABLE_NAME': 'my-table'}):
            result = home_shared._resolve_table_identifiers('TABLE_NAME')
        self.assertIn('my-table', result)

    def test_resolve_table_identifiers_multiple_env_keys(self):
        with patch.dict(os.environ, {'TABLE1': 'table-one', 'TABLE2': 'table-two'}):
            result = home_shared._resolve_table_identifiers('TABLE1', 'TABLE2')
        self.assertIn('table-one', result)
        self.assertIn('table-two', result)

    def test_resolve_table_identifiers_nonexistent_env_key(self):
        result = home_shared._resolve_table_identifiers('NONEXISTENT_KEY')
        self.assertEqual(result, [])


class SanitizationTests(unittest.TestCase):
    def test_sanitize_event_for_logging_removes_authorization(self):
        event = {'authorization': 'Bearer secret-token', 'body': 'data'}
        sanitized = home_shared._sanitize_event_for_logging(event)
        self.assertEqual(sanitized['authorization'], '***')
        self.assertEqual(sanitized['body'], 'data')

    def test_sanitize_event_for_logging_removes_authorization_header(self):
        event = {'headers': {'Authorization': 'Bearer secret', 'Content-Type': 'application/json'}}
        sanitized = home_shared._sanitize_event_for_logging(event)
        self.assertEqual(sanitized['headers']['Authorization'], '***')
        self.assertEqual(sanitized['headers']['Content-Type'], 'application/json')

    def test_sanitize_event_for_logging_non_dict_ignored(self):
        result = home_shared._sanitize_event_for_logging('not-a-dict')
        self.assertEqual(result, 'not-a-dict')


class GetMethodTests(unittest.TestCase):
    def test_get_method_from_http_context(self):
        event = {'requestContext': {'http': {'method': 'GET'}}}
        method = home_shared._get_method(event)
        self.assertEqual(method, 'GET')

    def test_get_method_from_http_method(self):
        event = {'httpMethod': 'POST'}
        method = home_shared._get_method(event)
        self.assertEqual(method, 'POST')

    def test_get_method_default_to_get(self):
        event = {'requestContext': {}}
        method = home_shared._get_method(event)
        self.assertEqual(method, 'GET')


class GetAuthorizationTests(unittest.TestCase):
    def test_get_authorization_prefers_event_level_value(self):
        event = {
            'authorization': 'event-token',
            'headers': {
                'Authorization': 'header-token'
            }
        }
        self.assertEqual(home_shared._get_authorization(event), 'event-token')

    def test_get_authorization_falls_back_to_authorization_header(self):
        event = {
            'headers': {
                'Authorization': 'header-token'
            }
        }
        self.assertEqual(home_shared._get_authorization(event), 'header-token')

    def test_get_authorization_supports_lowercase_header(self):
        event = {
            'headers': {
                'authorization': 'header-token'
            }
        }
        self.assertEqual(home_shared._get_authorization(event), 'header-token')

    def test_get_authorization_returns_empty_without_values(self):
        self.assertEqual(home_shared._get_authorization({}), '')


class GetBodyTests(unittest.TestCase):
    def test_get_body_plain_text(self):
        event = {'body': 'plain text'}
        body = home_shared._get_body(event)
        self.assertEqual(body, 'plain text')

    def test_get_body_base64_encoded(self):
        original = 'hello world'
        encoded = 'aGVsbG8gd29ybGQ='
        event = {'body': encoded, 'isBase64Encoded': True}
        body = home_shared._get_body(event)
        self.assertEqual(body, original)

    def test_get_body_none_body(self):
        event = {}
        body = home_shared._get_body(event)
        self.assertEqual(body, '')

    def test_get_body_base64_encoded_malformed_payload(self):
        event = {'body': '!!!not-base64!!!', 'isBase64Encoded': True}
        body = home_shared._get_body(event)
        self.assertEqual(body, '')


if __name__ == '__main__':
    unittest.main()
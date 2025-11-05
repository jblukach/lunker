from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    aws_apigatewayv2 as _api,
    aws_apigatewayv2_authorizers as _authorizers,
    aws_apigatewayv2_integrations as _integrations,
    aws_certificatemanager as _acm,
    aws_cognito as _cognito,
    aws_iam as _iam,
    aws_lambda as _lambda,
    aws_logs as _logs,
    aws_route53 as _route53,
    aws_route53_targets as _r53targets,
    aws_ssm as _ssm
)

from constructs import Construct

class LunkerUI(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        account = Stack.of(self).account
        region = Stack.of(self).region

    ### HOSTZONE ###

        hostzoneid = _ssm.StringParameter.from_string_parameter_attributes(
            self, 'hostzoneid',
            parameter_name = '/network/hostzone'
        )

        hostzone = _route53.HostedZone.from_hosted_zone_attributes(
             self, 'hostzone',
             hosted_zone_id = hostzoneid.string_value,
             zone_name = 'lukach.net'
        )

    ### COGNITO USER POOL ###

        userpool = _cognito.UserPool(
            self, 'userpool',
            user_pool_name = 'lunker',
            deletion_protection = True,
            removal_policy = RemovalPolicy.RETAIN,
            feature_plan = _cognito.FeaturePlan.PLUS,
            standard_threat_protection_mode = _cognito.StandardThreatProtectionMode.AUDIT_ONLY,
            custom_threat_protection_mode = _cognito.CustomThreatProtectionMode.AUDIT_ONLY,
            self_sign_up_enabled = False,
            sign_in_aliases = _cognito.SignInAliases(
                email = True
            ),
            sign_in_case_sensitive = False,
            sign_in_policy = _cognito.SignInPolicy(
                allowed_first_auth_factors = _cognito.AllowedFirstAuthFactors(
                    password = True,
                    email_otp = True,
                    passkey = True
                )
            ),
            auto_verify = _cognito.AutoVerifiedAttrs(
                email = False,
                phone = False
            ),
            account_recovery = _cognito.AccountRecovery.NONE,
            device_tracking = _cognito.DeviceTracking(
                challenge_required_on_new_device = True,
                device_only_remembered_on_user_prompt = False
            ),
            passkey_user_verification = _cognito.PasskeyUserVerification.PREFERRED,
            mfa = _cognito.Mfa.OFF
        )

    ### COGNITO RESOURCE SERVER ###

        scope = _cognito.ResourceServerScope(
            scope_name = 'read',
            scope_description = 'read-only access for lunker'
        )

        server = userpool.add_resource_server(
            'server',
            identifier = 'lunker',
            user_pool_resource_server_name = 'lunker',
            scopes = [
                _cognito.ResourceServerScope(
                    scope_name = 'read',
                    scope_description = 'read-only access for lunker'
                )
            ]
        )

    ### COGNITO APP CLIENT ###

        appclient = userpool.add_client(
            'appclient',
            user_pool_client_name = 'lunker',
            prevent_user_existence_errors = True,
            enable_propagate_additional_user_context_data = True,
            auth_flows = _cognito.AuthFlow(
                user = True,
                user_srp = True
            ),
            o_auth = _cognito.OAuthSettings(
                default_redirect_uri = 'https://lunker.lukach.net',
                callback_urls = [
                    'https://hello.lukach.net',
                    'https://lunker.lukach.net'
                ],
                flows = _cognito.OAuthFlows(
                    authorization_code_grant = True
                ),
                scopes = [
                    _cognito.OAuthScope.resource_server(server, scope)
                ]
            ),
            generate_secret = True
        )

    #### COGNITO BRANDING ###

        branding = _cognito.CfnManagedLoginBranding(
            self, 'branding',
            user_pool_id = userpool.user_pool_id,
            client_id = appclient.user_pool_client_id,
            use_cognito_provided_values = True,
        )

    ### COGNITO ACM ###

        cognitoacm = _acm.Certificate(
            self, 'cognitoacm',
            domain_name = 'hello.lukach.net',
            validation = _acm.CertificateValidation.from_dns(hostzone)
        )

    ### COGNITO DOMAIN ###

        cognitodomain = userpool.add_domain(
            'hellodomain',
            custom_domain = _cognito.CustomDomainOptions(
                domain_name = 'hello.lukach.net',
                certificate = cognitoacm
            ),
            managed_login_version = _cognito.ManagedLoginVersion.NEWER_MANAGED_LOGIN
        )

    ### COGNITO DNS ###

        cognitofour = _route53.ARecord(
            self, 'cognitofour',
            zone = hostzone,
            record_name = 'hello.lukach.net',
            target = _route53.RecordTarget.from_alias(
                _r53targets.UserPoolDomainTarget(cognitodomain)
            )
        )

        cognitofsix = _route53.AaaaRecord(
            self, 'cognitofsix',
            zone = hostzone,
            record_name = 'hello.lukach.net',
            target = _route53.RecordTarget.from_alias(
                _r53targets.UserPoolDomainTarget(cognitodomain)
            )
        )

    ### COGNITO LOGS ###

        authenticationlogs = _logs.LogGroup(
            self, 'authenticationlogs',
            log_group_name = '/aws/cognito/lunker/authentication',
            retention = _logs.RetentionDays.THIRTEEN_MONTHS,
            removal_policy = RemovalPolicy.DESTROY
        )

        authenticationlogsdelivery = _cognito.CfnLogDeliveryConfiguration(
            self, 'authenticationlogsdelivery',
            user_pool_id = userpool.user_pool_id,
            log_configurations = [
                _cognito.CfnLogDeliveryConfiguration.LogConfigurationProperty(
                    cloud_watch_logs_configuration = _cognito.CfnLogDeliveryConfiguration.CloudWatchLogsConfigurationProperty(
                        log_group_arn = 'arn:aws:logs:'+region+':'+account+':log-group:/aws/cognito/lunker/authentication'
                    ),
                    event_source = 'userAuthEvents',
                    log_level = 'INFO'
                )
            ]
        )

    ### IAM ROLE ###

        role = _iam.Role(
            self, 'role',
            assumed_by = _iam.ServicePrincipal(
                'lambda.amazonaws.com'
            )
        )

        role.add_managed_policy(
            _iam.ManagedPolicy.from_aws_managed_policy_name(
                'service-role/AWSLambdaBasicExecutionRole'
            )
        )

        role.add_to_policy(
            _iam.PolicyStatement(
                actions = [
                    'apigateway:GET'
                ],
                resources = [
                    '*'
                ]
            )
        )

    ### LAMBDA FUNCTION ###

        root = _lambda.Function(
            self, 'root',
            runtime = _lambda.Runtime.PYTHON_3_13,
            architecture = _lambda.Architecture.ARM_64,
            code = _lambda.Code.from_asset('root'),
            handler = 'root.handler',
            timeout = Duration.seconds(7),
            memory_size = 128,
            role = role
        )

        rootlogs = _logs.LogGroup(
            self, 'rootlogs',
            log_group_name = '/aws/lambda/'+root.function_name,
            retention = _logs.RetentionDays.THIRTEEN_MONTHS,
            removal_policy = RemovalPolicy.DESTROY
        )

    ### ACM CERTIFICATE ###

        acm = _acm.Certificate(
            self, 'acm',
            domain_name = 'lunker.lukach.net',
            validation = _acm.CertificateValidation.from_dns(hostzone)
        )

        domain = _api.DomainName(
            self, 'domain',
            domain_name = 'lunker.lukach.net',
            certificate = acm,
            endpoint_type = _api.EndpointType.REGIONAL,
            ip_address_type = _api.IpAddressType.DUAL_STACK
        )

    ### API LOG ROLE ###

        apirole = _iam.Role(
            self, 'apirole', 
            assumed_by = _iam.ServicePrincipal(
                'apigateway.amazonaws.com'
            )
        )

        apirole.add_managed_policy(
            _iam.ManagedPolicy.from_aws_managed_policy_name(
                'service-role/AmazonAPIGatewayPushToCloudWatchLogs'
            )
        )

    ### API AUTHORIZER ###

        authorizer = _authorizers.HttpJwtAuthorizer(
            'authorizer',
            authorizer_name = 'lunker',
            identity_source = [
                '$request.header.Authorization'
            ],
            jwt_issuer = userpool.user_pool_provider_url,
            jwt_audience = [
                appclient.user_pool_client_id
            ]
        )

    ### API GATEWAY ###

        api = _api.HttpApi(
            self, 'api',
            api_name = 'lunker',
            default_domain_mapping = _api.DomainMappingOptions(
                domain_name = domain
            ),
            ip_address_type = _api.IpAddressType.DUAL_STACK,
            cors_preflight = _api.CorsPreflightOptions(
                allow_credentials = True,
                allow_headers = [
                    'Authorization'
                ],
                allow_methods = [
                    _api.CorsHttpMethod.GET
                ],
                allow_origins = [
                    'https://hello.lukach.net'
                ]
            )
        )

    ### API ROOT ###

        integration = _integrations.HttpLambdaIntegration(
            'integration', root
        )

        api.add_routes(
            path = '/',
            methods = [
                _api.HttpMethod.GET
            ],
            integration = integration,
            authorizer = authorizer
        )

    ### DNS RECORDS

        ipv4dns = _route53.ARecord(
            self, 'ipv4dns',
            zone = hostzone,
            record_name = 'lunker.lukach.net',
            target = _route53.RecordTarget.from_alias(
                _r53targets.ApiGatewayv2DomainProperties(
                    domain.regional_domain_name,
                    domain.regional_hosted_zone_id
                )
            )
        )

        ipv6dns = _route53.AaaaRecord(
            self, 'ipv6dns',
            zone = hostzone,
            record_name = 'lunker.lukach.net',
            target = _route53.RecordTarget.from_alias(
                _r53targets.ApiGatewayv2DomainProperties(
                    domain.regional_domain_name,
                    domain.regional_hosted_zone_id
                )
            )
        )

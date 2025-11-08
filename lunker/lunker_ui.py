from aws_cdk import (
    Duration,
    RemovalPolicy,
    SecretValue,
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

    ### LAMBDA LAYER ###

        pkgrequests = _ssm.StringParameter.from_string_parameter_arn(
            self, 'pkgrequests',
            'arn:aws:ssm:us-east-1:070176467818:parameter/pkg/requests'
        )

        requests = _lambda.LayerVersion.from_layer_version_arn(
            self, 'requests',
            layer_version_arn = pkgrequests.string_value
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

    ### COGNITO APP CLIENT ###

        appclient = userpool.add_client(
            'appclient',
            user_pool_client_name = 'lunker',
            prevent_user_existence_errors = True,
            auth_flows = _cognito.AuthFlow(
                user = True,
                user_srp = True
            ),
            o_auth = _cognito.OAuthSettings(
                default_redirect_uri = 'https://lunker.lukach.net/auth',
                callback_urls = [
                    'https://lunker.lukach.net/auth'
                ],
                flows = _cognito.OAuthFlows(
                    authorization_code_grant = True
                ),
                scopes = [
                    _cognito.OAuthScope.OPENID
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

    ### AUTH LAMBDA FUNCTION ###

        auth = _lambda.Function(
            self, 'auth',
            runtime = _lambda.Runtime.PYTHON_3_13,
            architecture = _lambda.Architecture.ARM_64,
            code = _lambda.Code.from_asset('auth'),
            handler = 'auth.handler',
            environment = dict(
                CLIENT_ID = appclient.user_pool_client_id,
                CLIENT_SECRET = SecretValue.unsafe_unwrap(appclient.user_pool_client_secret)
            ),
            timeout = Duration.seconds(7),
            memory_size = 128,
            role = role,
            layers = [
                requests
            ]
        )

        authlogs = _logs.LogGroup(
            self, 'authlogs',
            log_group_name = '/aws/lambda/'+auth.function_name,
            retention = _logs.RetentionDays.THIRTEEN_MONTHS,
            removal_policy = RemovalPolicy.DESTROY
        )

    ### HOME LAMBDA FUNCTION ###

        home = _lambda.Function(
            self, 'home',
            runtime = _lambda.Runtime.PYTHON_3_13,
            architecture = _lambda.Architecture.ARM_64,
            code = _lambda.Code.from_asset('home'),
            handler = 'home.handler',
            timeout = Duration.seconds(7),
            memory_size = 128,
            role = role
        )

        homelogs = _logs.LogGroup(
            self, 'homelogs',
            log_group_name = '/aws/lambda/'+home.function_name,
            retention = _logs.RetentionDays.THIRTEEN_MONTHS,
            removal_policy = RemovalPolicy.DESTROY
        )

    ### ROOT LAMBDA FUNCTION ###

        root = _lambda.Function(
            self, 'root',
            runtime = _lambda.Runtime.PYTHON_3_13,
            architecture = _lambda.Architecture.ARM_64,
            code = _lambda.Code.from_asset('root'),
            handler = 'root.handler',
            environment = dict(
                CLIENT_ID = appclient.user_pool_client_id
            ),
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

        authorizer = _authorizers.HttpLambdaAuthorizer(
            'authorizer',
            auth,
            response_types = [
                _authorizers.HttpLambdaResponseType.SIMPLE
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

    ### API LOGS ###

        apilogs = _logs.LogGroup(
            self, 'apilogs',
            log_group_name = '/aws/apigateway/lunker',
            retention = _logs.RetentionDays.THIRTEEN_MONTHS,
            removal_policy = RemovalPolicy.DESTROY
        )

    ### API STAGE ###




    ### AUTH API ###

        authintegration = _integrations.HttpLambdaIntegration(
            'authintegration', auth
        )

        api.add_routes(
            path = '/auth',
            methods = [
                _api.HttpMethod.GET
            ],
            integration = authintegration
        )

    ### HOME API ###

        homeintegration = _integrations.HttpLambdaIntegration(
            'homeintegration', home
        )

        api.add_routes(
            path = '/home',
            methods = [
                _api.HttpMethod.GET
            ],
            integration = homeintegration,
            authorizer = authorizer
        )

    ### ROOT API ###

        rootintegration = _integrations.HttpLambdaIntegration(
            'rootintegration', root
        )

        api.add_routes(
            path = '/',
            methods = [
                _api.HttpMethod.GET
            ],
            integration = rootintegration
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

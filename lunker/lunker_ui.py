from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    aws_apigatewayv2 as _api,
    aws_apigatewayv2_authorizers as _authorizers,
    aws_apigatewayv2_integrations as _integrations,
    aws_certificatemanager as _acm,
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

    ### SSM PARAMETER ###

        projectid = _ssm.StringParameter.from_string_parameter_attributes(
            self, 'projectid',
            parameter_name = '/descope/projectid'
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

    ### AUTH LAMBDA ###

        auth = _lambda.Function(
            self, 'auth',
            runtime = _lambda.Runtime.PYTHON_3_13,
            architecture = _lambda.Architecture.ARM_64,
            code = _lambda.Code.from_asset('auth'),
            handler = 'auth.handler',
            environment = {
                'PROJECT_ID': projectid.string_value
            },
            timeout = Duration.seconds(7),
            memory_size = 128,
            role = role
        )

        authlogs = _logs.LogGroup(
            self, 'authlogs',
            log_group_name = '/aws/lambda/'+auth.function_name,
            retention = _logs.RetentionDays.THIRTEEN_MONTHS,
            removal_policy = RemovalPolicy.DESTROY
        )

    ### ROOT LAMBDA ###

        root = _lambda.Function(
            self, 'root',
            runtime = _lambda.Runtime.PYTHON_3_13,
            architecture = _lambda.Architecture.ARM_64,
            code = _lambda.Code.from_asset('root'),
            handler = 'root.handler',
            environment = {
                'PROJECT_ID': projectid.string_value
            },
            timeout = Duration.seconds(7),
            memory_size = 128,
            role = role
        )

        logs = _logs.LogGroup(
            self, 'logs',
            log_group_name = '/aws/lambda/'+root.function_name,
            retention = _logs.RetentionDays.THIRTEEN_MONTHS,
            removal_policy = RemovalPolicy.DESTROY
        )

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

    ### ACM CERTIFICATE ###

        acm = _acm.Certificate(
            self, 'acm',
            domain_name = 'lunker.lukach.net',
            validation = _acm.CertificateValidation.from_dns(hostzone)
        )

    ### DOMAIN NAME ###

        domain = _api.DomainName(
            self, 'domain',
            domain_name = 'lunker.lukach.net',
            certificate = acm
        )

    ### AUTH INTEGRATION ###

        authintegration = _integrations.HttpLambdaIntegration(
            'authintegration', auth
        )

    ### ROOT INTEGRATION ###

        integration = _integrations.HttpLambdaIntegration(
            'integration', root
        )

    ### API GATEWAY ###

        api = _api.HttpApi(
            self, 'api',
            description = 'lunker.lukach.net',
            default_domain_mapping = _api.DomainMappingOptions(
                domain_name = domain
            )
        )

    ### API AUTHORIZER ###

        descope = _authorizers.HttpJwtAuthorizer(
            'descope',
            jwt_issuer = 'https://api.descope.com/'+projectid.string_value,
            jwt_audience = [
                projectid.string_value
            ]
        )

    ### AUTH ROUTE ###

        api.add_routes(
            path = '/auth',
            methods = [
                _api.HttpMethod.GET
            ],
            integration = authintegration,
        )

    ### ROOT ROUTE ###

        api.add_routes(
            path = '/',
            methods = [
                _api.HttpMethod.GET
            ],
            integration = integration,
            authorizer = descope
        )

    ### DNS RECORDS ###

        dns4 = _route53.ARecord(
            self, 'dns4',
            zone = hostzone,
            record_name = 'lunker.lukach.net',
            target = _route53.RecordTarget.from_alias(
                _r53targets.ApiGatewayv2DomainProperties(
                    domain.regional_domain_name,
                    domain.regional_hosted_zone_id
                )
            )
        )

        dns6 = _route53.AaaaRecord(
            self, 'dns6',
            zone = hostzone,
            record_name = 'lunker.lukach.net',
            target = _route53.RecordTarget.from_alias(
                _r53targets.ApiGatewayv2DomainProperties(
                    domain.regional_domain_name,
                    domain.regional_hosted_zone_id
                )
            )
        )

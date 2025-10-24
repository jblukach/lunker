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

class LunkerAPI(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

    ### SSM PARAMETER ###

        clientid = _ssm.StringParameter.from_string_parameter_attributes(
            self, 'clientid',
            parameter_name = '/frontegg/clientid'
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

    ### LAMBDA FUNCTIONS ###

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

    ### API INTEGRATIONS ###

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

        authorizer = _authorizers.HttpJwtAuthorizer(
            'authorizer',
            jwt_issuer = 'https://lunker.us.frontegg.com',
            jwt_audience = [
                clientid.string_value
            ]
        )

    ### API ROUTES ###

        api.add_routes(
            path = '/',
            methods = [
                _api.HttpMethod.GET
            ],
            integration = integration,
            authorizer = authorizer
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

        cnameacm = _route53.CnameRecord(
            self, 'cnameacm',
            record_name = '_2002d7fc0bdbfe39431fd9a68d036f72.login.lukach.net.',
            zone = hostzone,
            domain_name = '_37a6a6096b5abdb6e5d414268b538b81.xlfgrmvvlj.acm-validations.aws.',
            ttl = Duration.seconds(300)
        )

        cnamecdn = _route53.CnameRecord(
            self, 'cnamecdn',
            record_name = 'login.lukach.net',
            zone = hostzone,
            domain_name = 'di6hvr0bdm7km.cloudfront.net',
            ttl = Duration.seconds(300)
        )

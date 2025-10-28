from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    aws_apigateway as _api,
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

        domain = _api.CfnDomainName(
            self, 'domain',
            certificate_arn = acm.certificate_arn,
            domain_name = 'lunker.lukach.net',
            endpoint_configuration = _api.CfnDomainName.EndpointConfigurationProperty(
                ip_address_type = 'dualstack',
                types = [
                    'EDGE'
                ]
            )
        )

    ### API INTEGRATION ###

        rootintegration = _api.LambdaIntegration(
            root,
            proxy = True, 
            integration_responses = [
                _api.IntegrationResponse(
                    status_code = '200',
                    response_parameters = {
                        'method.response.header.Access-Control-Allow-Origin': "'*'"
                    }
                )
            ]
        )

    ### API GATEWAY ###

        api = _api.RestApi(
            self, 'api',
            description = 'lunker.lukach.net',
            cloud_watch_role = True,
            cloud_watch_role_removal_policy = RemovalPolicy.DESTROY,
            deploy_options = _api.StageOptions(
                access_log_destination = _api.LogGroupLogDestination(
                    _logs.LogGroup(
                        self, 'apigwlogs',
                        log_group_name = '/aws/apigateway/lunker',
                        retention = _logs.RetentionDays.THIRTEEN_MONTHS,
                        removal_policy = RemovalPolicy.DESTROY
                    )
                ),
                access_log_format = _api.AccessLogFormat.clf(),
                logging_level = _api.MethodLoggingLevel.INFO,
                data_trace_enabled = True
            ),
            endpoint_configuration = _api.EndpointConfiguration(
                types = [
                    _api.EndpointType.EDGE
                ],
                ip_address_type = _api.IpAddressType.DUAL_STACK
            )
        )

        api.root.add_method(
            'GET',
            rootintegration,
            method_responses = [
                _api.MethodResponse(
                    status_code = '200',
                    response_parameters = {
                        'method.response.header.Access-Control-Allow-Origin': True
                    }
                )
            ]
        )

    ### BASE PATH MAPPING ###

        basepath = _api.BasePathMapping(
            self, 'basepath',
            domain_name = domain,
            rest_api = api
        )

    ### DNS RECORDS ### attr_distribution_domain_name

        dnsfour = _route53.ARecord(
            self, 'dnsfour',
            zone = hostzone,
            record_name = 'lunker.lukach.net',
            target = _route53.RecordTarget.from_alias(
                _r53targets.ApiGatewayv2DomainProperties(
                    domain.attr_distribution_domain_name,
                    domain.attr_distribution_hosted_zone_id
                )
            )
        )

        dnssix = _route53.AaaaRecord(
            self, 'dnssix',
            zone = hostzone,
            record_name = 'lunker.lukach.net',
            target = _route53.RecordTarget.from_alias(
                _r53targets.ApiGatewayv2DomainProperties(
                    domain.attr_distribution_domain_name,
                    domain.attr_distribution_hosted_zone_id
                )
            )
        )

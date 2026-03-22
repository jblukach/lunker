import datetime

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    aws_dynamodb as _dynamodb,
    aws_events as _events,
    aws_events_targets as _targets,
    aws_iam as _iam,
    aws_lambda as _lambda,
    aws_logs as _logs,
    aws_s3 as _s3,
    aws_ssm as _ssm
)

from constructs import Construct

class LunkerStackUsw2(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        year = datetime.datetime.now().strftime('%Y')
        month = datetime.datetime.now().strftime('%m')
        day = datetime.datetime.now().strftime('%d')

    ### S3 BUCKETS ###

        bucket = _s3.Bucket.from_bucket_name(
            self, 'bucket',
            bucket_name = 'packages-usw2-lukach-io'
        )

    ### LAMBDA LAYER ###

        requests = _lambda.LayerVersion(
            self, 'requests',
            layer_version_name = 'requests',
            description = str(year)+'-'+str(month)+'-'+str(day)+' deployment',
            code = _lambda.Code.from_bucket(
                bucket = bucket,
                key = 'requests.zip'
            ),
            compatible_architectures = [
                _lambda.Architecture.ARM_64
            ],
            compatible_runtimes = [
                _lambda.Runtime.PYTHON_3_13
            ],
            removal_policy = RemovalPolicy.DESTROY
        )

    ### DATABASE ###

        table = _dynamodb.Table(
            self, 'table',
            table_name = 'tld',
            partition_key = {
                'name': 'pk',
                'type': _dynamodb.AttributeType.STRING
            },
            sort_key = {
                'name': 'sk',
                'type': _dynamodb.AttributeType.STRING
            },
            billing_mode = _dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy = RemovalPolicy.DESTROY,
                        point_in_time_recovery_specification = _dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled = True
            ),
            deletion_protection = True
        )

    ### PARAMETER ###

        organization = _ssm.StringParameter.from_string_parameter_attributes(
            self, 'organization',
            parameter_name = '/organization/id'
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

        role.add_to_policy(
            _iam.PolicyStatement(
                actions = [
                    'dynamodb:DeleteItem',
                    'dynamodb:PutItem',
                    'dynamodb:Query'
                ],
                resources = [
                    '*'
                ]
            )
        )

        composite = _iam.CompositePrincipal(
            _iam.OrganizationPrincipal(organization.string_value),
            _iam.ServicePrincipal('apigateway.amazonaws.com')
        )

    ### HOME LAMBDA FUNCTION ###

        home = _lambda.Function(
            self, 'home',
            function_name = 'home',
            runtime = _lambda.Runtime.PYTHON_3_13,
            architecture = _lambda.Architecture.ARM_64,
            code = _lambda.Code.from_asset('home'),
            handler = 'homeusw2.handler',
            environment = dict(
                LUNKER_TABLE = 'lunker',
                TLD_TABLE = table.table_name
            ),
            timeout = Duration.seconds(7),
            memory_size = 128,
            role = role,
            layers = [
                requests
            ]
        )

        home.grant_invoke_composite_principal(composite)

        homelogs = _logs.LogGroup(
            self, 'homelogs',
            log_group_name = '/aws/lambda/'+home.function_name,
            retention = _logs.RetentionDays.THIRTEEN_MONTHS,
            removal_policy = RemovalPolicy.DESTROY
        )

    ### TLD LAMBDA FUNCTION ###

        tld = _lambda.Function(
            self, 'tld',
            function_name = 'tld',
            runtime = _lambda.Runtime.PYTHON_3_13,
            architecture = _lambda.Architecture.ARM_64,
            code = _lambda.Code.from_asset('tld'),
            timeout = Duration.seconds(900),
            handler = 'tld.handler',
            environment = dict(
                TLD_TABLE = table.table_name
            ),
            memory_size = 256,
            role = role,
            layers = [
                requests
            ]
        )

        logs = _logs.LogGroup(
            self, 'logs',
            log_group_name = '/aws/lambda/'+tld.function_name,
            retention = _logs.RetentionDays.ONE_DAY,
            removal_policy = RemovalPolicy.DESTROY
        )

        event = _events.Rule(
            self, 'event',
            schedule = _events.Schedule.cron(
                minute = '0',
                hour = '10',
                month = '*',
                week_day = '*',
                year = '*'
            )
        )

        event.add_target(
            _targets.LambdaFunction(tld)
        )

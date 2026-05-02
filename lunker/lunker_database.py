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
    aws_lambda_event_sources as _sources,
    aws_logs as _logs,
    aws_s3 as _s3,
    aws_ssm as _ssm
)

from constructs import Construct

class LunkerDatabase(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        region = Stack.of(self).region
        account = Stack.of(self).account

        year = datetime.datetime.now().strftime('%Y')
        month = datetime.datetime.now().strftime('%m')
        day = datetime.datetime.now().strftime('%d')

    ### S3 BUCKETS ###

        bucket = _s3.Bucket.from_bucket_name(
            self, 'bucket',
            bucket_name = 'packages-use2-lukach-io'
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

    ### PARAMETER ###

        organization = _ssm.StringParameter.from_string_parameter_attributes(
            self, 'organization',
            parameter_name = '/organization/id'
        )

        webmonitor = _ssm.StringParameter.from_string_parameter_attributes(
            self, 'webmonitor',
            parameter_name = '/account/webmonitor'
        )

    ### DATABASE ###

        table = _dynamodb.TableV2(
            self, 'table',
            table_name = 'lunker',
            partition_key = {
                'name': 'pk',
                'type': _dynamodb.AttributeType.STRING
            },
            sort_key = {
                'name': 'sk',
                'type': _dynamodb.AttributeType.STRING
            },
            billing = _dynamodb.Billing.on_demand(),
            removal_policy = RemovalPolicy.DESTROY,
            point_in_time_recovery_specification = _dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled = True
            ),
            deletion_protection = True,
            dynamo_stream = _dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
            replicas = [
                _dynamodb.ReplicaTableProps(region = 'us-east-1'),
                _dynamodb.ReplicaTableProps(region = 'us-west-2'),
            ]
        )

        permutation = _dynamodb.TableV2(
            self, 'permutation',
            table_name = 'permutation',
            partition_key = {
                'name': 'pk',
                'type': _dynamodb.AttributeType.STRING
            },
            sort_key = {
                'name': 'sk',
                'type': _dynamodb.AttributeType.STRING
            },
            billing = _dynamodb.Billing.on_demand(),
            removal_policy = RemovalPolicy.DESTROY,
            point_in_time_recovery_specification = _dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled = True
            ),
            deletion_protection = True,
            time_to_live_attribute = 'ttl',
            replicas = [
                _dynamodb.ReplicaTableProps(region = 'us-east-1'),
                _dynamodb.ReplicaTableProps(region = 'us-west-2'),
            ]
        )

        table.add_global_secondary_index(
            index_name = 'pk-tk-index',
            partition_key = {
                'name': 'pk',
                'type': _dynamodb.AttributeType.STRING
            },
            sort_key = {
                'name': 'tk',
                'type': _dynamodb.AttributeType.STRING
            }
        )

        table.add_global_secondary_index(
            index_name = 'email-domain-index',
            partition_key = {
                'name': 'email',
                'type': _dynamodb.AttributeType.STRING
            },
            sort_key = {
                'name': 'domain',
                'type': _dynamodb.AttributeType.STRING
            }
        )

        tld = _dynamodb.TableV2(
            self, 'tld',
            table_name = 'tld',
            partition_key = {
                'name': 'pk',
                'type': _dynamodb.AttributeType.STRING
            },
            sort_key = {
                'name': 'sk',
                'type': _dynamodb.AttributeType.STRING
            },
            billing = _dynamodb.Billing.on_demand(),
            removal_policy = RemovalPolicy.DESTROY,
            point_in_time_recovery_specification = _dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled = True
            ),
            deletion_protection = True,
            replicas = [
                _dynamodb.ReplicaTableProps(region = 'us-east-1'),
                _dynamodb.ReplicaTableProps(region = 'us-west-2'),
            ]
        )

    ### RESOURCE POLICY ###

        table.add_to_resource_policy(
            _iam.PolicyStatement(
                sid = 'AllowOrganizationGetItemAndQuery',
                effect = _iam.Effect.ALLOW,
                principals = [
                    _iam.OrganizationPrincipal(organization_id = organization.string_value)
                ],
                actions = [
                    'dynamodb:DescribeTable',
                    'dynamodb:GetItem',
                    'dynamodb:Query'
                ],
                resources = [
                    self.format_arn(
                        service = 'dynamodb',
                        resource = 'table',
                        resource_name = 'lunker'
                    ),
                    self.format_arn(
                        service = 'dynamodb',
                        resource = 'table',
                        resource_name = 'lunker/index/*'
                    )
                ]
            )
        )

        permutation.add_to_resource_policy(
            _iam.PolicyStatement(
                sid = 'AllowOrganizationGetItemAndQueryPermutation',
                effect = _iam.Effect.ALLOW,
                principals = [
                    _iam.OrganizationPrincipal(organization_id = organization.string_value)
                ],
                actions = [
                    'dynamodb:DescribeTable',
                    'dynamodb:GetItem',
                    'dynamodb:Query'
                ],
                resources = [
                    self.format_arn(
                        service = 'dynamodb',
                        resource = 'table',
                        resource_name = 'permutation'
                    ),
                    self.format_arn(
                        service = 'dynamodb',
                        resource = 'table',
                        resource_name = 'permutation/index/*'
                    )
                ]
            )
        )

        tld.add_to_resource_policy(
            _iam.PolicyStatement(
                sid = 'AllowOrganizationGetItemAndQueryTld',
                effect = _iam.Effect.ALLOW,
                principals = [
                    _iam.OrganizationPrincipal(organization_id = organization.string_value)
                ],
                actions = [
                    'dynamodb:DescribeTable',
                    'dynamodb:GetItem',
                    'dynamodb:Query'
                ],
                resources = [
                    self.format_arn(
                        service = 'dynamodb',
                        resource = 'table',
                        resource_name = 'tld'
                    ),
                    self.format_arn(
                        service = 'dynamodb',
                        resource = 'table',
                        resource_name = 'tld/index/*'
                    )
                ]
            )
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
                    'lambda:InvokeFunction'
                ],
                resources = [
                    '*'
                ]
            )
        )

    ### ACTION LAMBDA ###

        action = _lambda.Function(
            self, 'action',
            function_name = 'action',
            runtime = _lambda.Runtime.PYTHON_3_13,
            architecture = _lambda.Architecture.ARM_64,
            code = _lambda.Code.from_asset('action'),
            handler = 'action.handler',
            environment = dict(
                FUNCTION_NAME = 'arn:aws:lambda:'+region+':'+webmonitor.string_value+':function:searchlist',
                PERMUTATION_FUNCTION_NAME = 'arn:aws:lambda:'+region+':'+account+':function:permutation'
            ),
            timeout = Duration.seconds(7),
            memory_size = 128,
            role = role
        )

        actionlogs = _logs.LogGroup(
            self, 'actionlogs',
            log_group_name = '/aws/lambda/'+action.function_name,
            retention = _logs.RetentionDays.THIRTEEN_MONTHS,
            removal_policy = RemovalPolicy.DESTROY
        )

        action.add_event_source(
            _sources.DynamoEventSource(
                table,
                starting_position = _lambda.StartingPosition.TRIM_HORIZON,
                batch_size = 1,
                retry_attempts = 3
            )
        )

    ### TLD LAMBDA ROLE ###

        tldrole = _iam.Role(
            self, 'tldrole',
            assumed_by = _iam.ServicePrincipal(
                'lambda.amazonaws.com'
            )
        )

        tldrole.add_managed_policy(
            _iam.ManagedPolicy.from_aws_managed_policy_name(
                'service-role/AWSLambdaBasicExecutionRole'
            )
        )

        tldrole.add_to_policy(
            _iam.PolicyStatement(
                actions = [
                    'dynamodb:GetItem',
                    'dynamodb:DeleteItem',
                    'dynamodb:PutItem',
                    'dynamodb:Query'
                ],
                resources = [
                    '*'
                ]
            )
        )

    ### TLD LAMBDA FUNCTION ###

        tldlambda = _lambda.Function(
            self, 'tldlambda',
            function_name = 'tld',
            runtime = _lambda.Runtime.PYTHON_3_13,
            architecture = _lambda.Architecture.ARM_64,
            code = _lambda.Code.from_asset('tld'),
            timeout = Duration.seconds(900),
            handler = 'tld.handler',
            environment = dict(
                TLD_TABLE = tld.table_name
            ),
            memory_size = 256,
            role = tldrole,
            layers = [
                requests
            ]
        )

        tldlogs = _logs.LogGroup(
            self, 'tldlogs',
            log_group_name = '/aws/lambda/'+tldlambda.function_name,
            retention = _logs.RetentionDays.ONE_DAY,
            removal_policy = RemovalPolicy.DESTROY
        )

        tldevent = _events.Rule(
            self, 'tldevent',
            schedule = _events.Schedule.cron(
                minute = '0',
                hour = '10',
                month = '*',
                week_day = '*',
                year = '*'
            )
        )

        tldevent.add_target(
            _targets.LambdaFunction(tldlambda)
        )

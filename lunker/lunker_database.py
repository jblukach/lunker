from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    aws_dynamodb as _dynamodb,
    aws_iam as _iam,
    aws_lambda as _lambda,
    aws_lambda_event_sources as _sources,
    aws_logs as _logs,
)

from constructs import Construct

class LunkerDatabase(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

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

    ### ACTION LAMBDA ###

        action = _lambda.Function(
            self, 'action',
            function_name = 'action',
            runtime = _lambda.Runtime.PYTHON_3_13,
            architecture = _lambda.Architecture.ARM_64,
            code = _lambda.Code.from_asset('action'),
            handler = 'action.handler',
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

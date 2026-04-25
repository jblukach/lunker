from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    aws_events as _events,
    aws_events_targets as _targets,
    aws_iam as _iam,
    aws_lambda as _lambda,
    aws_logs as _logs,
)

from constructs import Construct

class LunkerPermutation(Stack):

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
                    'dynamodb:GetItem',
                    'dynamodb:PutItem',
                    'dynamodb:UpdateItem',
                    'dynamodb:DeleteItem',
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
                    ),
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

    ### PERMUTATION LAMBDA FUNCTION ###

        permutation = _lambda.Function(
            self, 'permutation',
            function_name = 'permutation',
            runtime = _lambda.Runtime.PYTHON_3_13,
            architecture = _lambda.Architecture.ARM_64,
            code = _lambda.Code.from_asset('permutation'),
            handler = 'permutation.handler',
            environment = dict(
                LUNKER_TABLE = 'lunker',
                PERMUTATION_TABLE = 'permutation'
            ),
            timeout = Duration.seconds(900),
            memory_size = 512,
            role = role
        )

        _logs.LogGroup(
            self, 'logs',
            log_group_name = '/aws/lambda/'+permutation.function_name,
            retention = _logs.RetentionDays.ONE_WEEK,
            removal_policy = RemovalPolicy.DESTROY
        )

        event = _events.Rule(
            self, 'event',
            schedule = _events.Schedule.cron(
                minute = '0',
                hour = '11',
                month = '*',
                week_day = '*',
                year = '*'
            )
        )

        event.add_target(
            _targets.LambdaFunction(permutation)
        )

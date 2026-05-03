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

        region = Stack.of(self).region

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

    ### PARAMETER ###

        apigateway = _ssm.StringParameter.from_string_parameter_attributes(
            self, 'apigateway',
            parameter_name = '/account/api'
        )

        cognito = _ssm.StringParameter.from_string_parameter_attributes(
            self, 'cognito',
            parameter_name = '/account/cognito'
        )

        webmonitor = _ssm.StringParameter.from_string_parameter_attributes(
            self, 'webmonitor',
            parameter_name = '/account/webmonitor'
        )

        webdb = _ssm.StringParameter.from_string_parameter_attributes(
            self, 'webdb',
            parameter_name = '/account/webdb'
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

        role.add_to_policy(
            _iam.PolicyStatement(
                actions = [
                    'secretsmanager:GetSecretValue'
                ],
                resources = [
                    'arn:aws:secretsmanager:us-east-1:'+cognito.string_value+':secret:clientid*'
                ]
            )
        )

        composite = _iam.CompositePrincipal(
            _iam.AccountPrincipal(apigateway.string_value),
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
                PERMUTATION_TABLE = 'permutation',
                POSSIBILITIES_TABLE = 'arn:aws:dynamodb:'+region+':'+webdb.string_value+':table/possibilities',
                TLD_TABLE = 'tld',
                CLIENTID_SECRET_ARN = 'arn:aws:secretsmanager:us-east-1:'+cognito.string_value+':secret:clientid',
                WM_OSINT = 'arn:aws:dynamodb:'+region+':'+webmonitor.string_value+':table/osint',
                WM_MALWARE = 'arn:aws:dynamodb:'+region+':'+webmonitor.string_value+':table/malware',
                WM_DAILYUPDATE = 'arn:aws:dynamodb:'+region+':'+webmonitor.string_value+':table/dailyupdate',
                WM_WEEKLYUPDATE = 'arn:aws:dynamodb:'+region+':'+webmonitor.string_value+':table/weeklyupdate',
                WM_MONTHLYUPDATE = 'arn:aws:dynamodb:'+region+':'+webmonitor.string_value+':table/monthlyupdate',
                WM_DAILYREMOVE = 'arn:aws:dynamodb:'+region+':'+webmonitor.string_value+':table/dailyremove',
                WM_WEEKLYREMOVE = 'arn:aws:dynamodb:'+region+':'+webmonitor.string_value+':table/weeklyremove',
                WM_MONTHLYREMOVE = 'arn:aws:dynamodb:'+region+':'+webmonitor.string_value+':table/monthlyremove'
            ),
            timeout = Duration.seconds(30),
            memory_size = 256,
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

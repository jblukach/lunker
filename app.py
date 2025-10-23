#!/usr/bin/env python3
import os

import aws_cdk as cdk

from lunker.lunker_api import LunkerAPI
from lunker.lunker_tld import LunkerTLD

app = cdk.App()

LunkerAPI(
    app, 'LunkerAPI',
    env = cdk.Environment(
        account = os.getenv('CDK_DEFAULT_ACCOUNT'),
        region = 'us-east-1'
    ),
    synthesizer = cdk.DefaultStackSynthesizer(
        qualifier = '4n6ir'
    )
)

LunkerTLD(
    app, 'LunkerTLD',
    env = cdk.Environment(
        account = os.getenv('CDK_DEFAULT_ACCOUNT'),
        region = 'us-east-1'
    ),
    synthesizer = cdk.DefaultStackSynthesizer(
        qualifier = '4n6ir'
    )
)

cdk.Tags.of(app).add('Alias','lukach.net')
cdk.Tags.of(app).add('GitHub','https://github.com/jblukach/lunker')

app.synth()
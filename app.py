#!/usr/bin/env python3
import os

import aws_cdk as cdk

from lunker.lunker_stackuse1 import LunkerStackUse1
from lunker.lunker_stackuse2 import LunkerStackUse2
from lunker.lunker_stackusw2 import LunkerStackUsw2
from lunker.lunker_topleveldomain import LunkerTopLevelDomain
from lunker.lunker_watchlist import LunkerWatchList

app = cdk.App()

LunkerStackUse1(
    app, 'LunkerStackUse1',
    env = cdk.Environment(
        account = os.getenv('CDK_DEFAULT_ACCOUNT'),
        region = 'us-east-1'
    ),
    synthesizer = cdk.DefaultStackSynthesizer(
        qualifier = 'lukach'
    )
)

LunkerStackUse2(
    app, 'LunkerStackUse2',
    env = cdk.Environment(
        account = os.getenv('CDK_DEFAULT_ACCOUNT'),
        region = 'us-east-2'
    ),
    synthesizer = cdk.DefaultStackSynthesizer(
        qualifier = 'lukach'
    )
)

LunkerStackUsw2(
    app, 'LunkerStackUsw2',
    env = cdk.Environment(
        account = os.getenv('CDK_DEFAULT_ACCOUNT'),
        region = 'us-west-2'
    ),
    synthesizer = cdk.DefaultStackSynthesizer(
        qualifier = 'lukach'
    )
)

LunkerTopLevelDomain(
    app, 'LunkerTopLevelDomain',
    env = cdk.Environment(
        account = os.getenv('CDK_DEFAULT_ACCOUNT'),
        region = 'us-east-2'
    ),
    synthesizer = cdk.DefaultStackSynthesizer(
        qualifier = 'lukach'
    )
)

LunkerWatchList(
    app, 'LunkerWatchList',
    env = cdk.Environment(
        account = os.getenv('CDK_DEFAULT_ACCOUNT'),
        region = 'us-east-2'
    ),
    synthesizer = cdk.DefaultStackSynthesizer(
        qualifier = 'lukach'
    )
)

cdk.Tags.of(app).add('Alias','lunker')
cdk.Tags.of(app).add('GitHub','https://github.com/jblukach/lunker')
cdk.Tags.of(app).add('Org','lukach.io')

app.synth()
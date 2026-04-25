# Lunker

Lunker is a multi-region AWS CDK application for registering second-level domains for threat intelligence monitoring. Users authenticate with Amazon Cognito, manage a personal watchlist, and review related results sourced from the [webmonitor](https://github.com/jblukach/webmonitor) service.

## Features

- **Amazon Cognito authentication** for the hosted sign-in flow
- **Domain management** — add or remove second-level domains such as `example.com`
- **TLD validation** using the official [IANA TLD list](https://data.iana.org/TLD/tlds-alpha-by-domain.txt), refreshed daily
- **Threat intelligence enrichment** triggered automatically when a domain is registered
- **Saved-domain insights** — clicking a saved domain loads related sections such as suspect domains, new registrations, expired registrations, and all known domains
- **Matched-domain highlighting** — domains with matching search-field hits are emphasized in red on the home page
- **Multi-region deployment** across `us-east-1`, `us-east-2`, and `us-west-2`
- **GitHub Actions CI/CD via OIDC** with no long-lived AWS credentials

## Architecture

The application is deployed as four CDK stacks:

| Stack | Region | Purpose |
| --- | --- | --- |
| `LunkerDatabase` | `us-east-2` | Creates the global `lunker` DynamoDB table, stream processing, and the `action` Lambda |
| `LunkerStackUse1` | `us-east-1` | Creates the regional `tld` table plus the `home` and `tld` Lambdas for `us-east-1` |
| `LunkerStackUse2` | `us-east-2` | Creates the GitHub OIDC provider and IAM role used for CI/CD |
| `LunkerStackUsw2` | `us-west-2` | Creates the regional `tld` table plus the `home` and `tld` Lambdas for `us-west-2` |

### Lambda functions

- **`action`** — triggered by DynamoDB Streams on new domain inserts and invokes the `searchlist` Lambda in the webmonitor account
- **`home`** — renders the HTML UI and handles domain listing, add/remove actions, domain section lookups, and matched-domain highlighting
- **`tld`** — runs daily at **10:00 UTC** to refresh the IANA TLD list in the regional `tld` table

### DynamoDB tables

- **`lunker`** — global DynamoDB table with its primary region in `us-east-2` and replicas in `us-east-1` and `us-west-2`; stores user-to-domain mappings and enables PITR and deletion protection
- **`tld`** — regional DynamoDB table used to validate top-level domains during submission
- **`permutation`** — DynamoDB table in `us-east-2` with key pattern `pk = LUNKER#` and `sk = LUNKER#<sld>#`; stores `sld`, `perm`, and TTL via `ttl`

## Prerequisites

- [AWS CDK](https://docs.aws.amazon.com/cdk/v2/guide/getting_started.html) v2
- Python **3.13**
- An AWS environment bootstrapped with the CDK qualifier `lukach`:

  ```bash
  cdk bootstrap --qualifier lukach
  ```

- The following SSM parameters available to the stacks:
  - `/organization/id` — AWS Organizations ID
  - `/account/api` — API Gateway account identifier used for invocation permissions
  - `/account/cognito` — Cognito account identifier used for secret access
  - `/account/webmonitor` — AWS account ID that owns the webmonitor service
- S3 buckets containing the `requests.zip` Lambda layer:
  - `packages-use1-lukach-io` in `us-east-1`
  - `packages-usw2-lukach-io` in `us-west-2`

## Deployment

```bash
# Optional: create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Deploy all stacks
cdk deploy --profile lunker --all --require-approval never

# Deploy a single stack
cdk deploy --profile lunker LunkerDatabase --require-approval never
```

`CDK_DEFAULT_ACCOUNT` must be set, or resolvable from the active AWS CLI profile, before deployment.

## Home page behavior

After sign-in, the home page:

1. lists the domains saved for the current user
2. highlights matched domains in **red** when related search-field data is present
3. lets the user add or remove a domain
4. loads detailed domain sections on demand when a saved domain is clicked

To keep the page responsive, the home handlers reuse HTTP connections and cache short-lived identity and highlight lookups during warm Lambda invocations.

## Project structure

```text
app.py                    # CDK app entry point
requirements.txt          # Python dependencies
cdk.json                  # CDK configuration
lunker/
  lunker_database.py      # LunkerDatabase stack (us-east-2)
  lunker_stackuse1.py     # LunkerStackUse1 stack (us-east-1)
  lunker_stackuse2.py     # LunkerStackUse2 stack (us-east-2, CI/CD)
  lunker_stackusw2.py     # LunkerStackUsw2 stack (us-west-2)
action/
  action.py               # DynamoDB Streams Lambda handler
home/
  homeuse1.py             # Home API Lambda handler for us-east-1
  homeusw2.py             # Home API Lambda handler for us-west-2
tld/
  tld.py                  # IANA TLD sync Lambda handler
```

## License

[LICENSE](LICENSE)

# Lunker

Lunker is a multi-region AWS CDK application for registering second-level domains for threat intelligence monitoring. Users authenticate with Amazon Cognito, manage a personal watchlist, and review related results sourced from the [webmonitor](https://github.com/jblukach/webmonitor) service.

## Features

- **Amazon Cognito authentication** for the hosted sign-in flow
- **Domain management** — add or remove second-level domains such as `example.com`
- **TLD validation** using the official [IANA TLD list](https://data.iana.org/TLD/tlds-alpha-by-domain.txt), stored in the centralized `tld` table
- **Threat intelligence enrichment** triggered automatically when a domain is registered
- **Saved-domain insights** — clicking a saved domain loads related suspect, new-registration, and expired-registration sections
- **Matched-domain highlighting** — exact SLD matches are emphasized in red and permutation-based matches in orange
- **Multi-region deployment** across `us-east-1`, `us-east-2`, and `us-west-2`
- **GitHub Actions CI/CD via OIDC** with no long-lived AWS credentials

## Architecture

The application is deployed as five CDK stacks:

| Stack | Region | Purpose |
| --- | --- | --- |
| `LunkerDatabase` | `us-east-2` | Creates the global `lunker`, `permutation`, and `tld` DynamoDB tables (with replicas), org-wide resource policies, stream processing, and the `action` and `tld` Lambdas |
| `LunkerPermutation` | `us-east-2` | Creates the `permutation` Lambda, scheduled daily at **11:00 UTC** |
| `LunkerStackUse1` | `us-east-1` | Creates the regional `home` Lambda and related IAM/logging resources for `us-east-1` |
| `LunkerStackUse2` | `us-east-2` | Creates the GitHub OIDC provider and IAM role used for CI/CD |
| `LunkerStackUsw2` | `us-west-2` | Creates the regional `home` Lambda and related IAM/logging resources for `us-west-2` |

### Lambda functions

- **`action`** — triggered by DynamoDB Streams on new domain inserts; asynchronously invokes both the `searchlist` Lambda in the webmonitor account and the local `permutation` Lambda
- **`home`** — renders the HTML UI and handles domain listing, add/remove actions, domain section lookups, and matched-domain highlighting
- **`permutation`** — runs daily at **11:00 UTC**; reads domains from the `lunker` table, generates permutations, and writes results to the `permutation` table with a TTL
- **`tld`** — deployed in `LunkerDatabase` (us-east-2), runs daily at **10:00 UTC**, and writes to the centralized `tld` table

### DynamoDB tables

- **`lunker`** — global DynamoDB table with its primary region in `us-east-2` and replicas in `us-east-1` and `us-west-2`; stores user-to-domain mappings; enables PITR and deletion protection; includes a `pk-tk-index` GSI used by the permutation Lambda and an `email-domain-index` GSI used by the home workflow; org-wide read access (`DescribeTable`, `GetItem`, `Query`) is granted via a resource policy
- **`tld`** — global DynamoDB table with its primary region in `us-east-2` and replicas in `us-east-1` and `us-west-2`; used by home and tld workflows for top-level-domain validation data; enables PITR and deletion protection; org-wide read access (`DescribeTable`, `GetItem`, `Query`) is granted via a resource policy
- **`permutation`** — global DynamoDB table with its primary region in `us-east-2` and replicas in `us-east-1` and `us-west-2`; key pattern `pk = LUNKER#` and `sk = LUNKER#<sld>`; stores `sld`, `perm`, `count`, and TTL via `ttl`; enables PITR and deletion protection; org-wide read access is granted via a resource policy

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
  - `packages-use2-lukach-io` in `us-east-2`
  - `packages-usw2-lukach-io` in `us-west-2`

## Deployment

```bash
# Optional: create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Synthesize templates
cdk synth

# Review infrastructure changes
cdk diff --profile lunker

# Deploy all stacks
cdk deploy --profile lunker --all --require-approval never

# Deploy a single stack
cdk deploy --profile lunker LunkerDatabase --require-approval never
```

`CDK_DEFAULT_ACCOUNT` must be set, or resolvable from the active AWS CLI profile, before deployment.

## Post-deploy verification

Use these commands to validate that the core scheduled and event-driven workflows are healthy.

```bash
# Confirm all stacks are up to date
cdk diff --profile lunker

# Trigger a one-off TLD sync
aws lambda invoke \
  --profile lunker \
  --region us-east-2 \
  --function-name tld \
  --payload '{}' \
  /tmp/lunker-tld.json && cat /tmp/lunker-tld.json

# Trigger a one-off full permutation refresh
aws lambda invoke \
  --profile lunker \
  --region us-east-2 \
  --function-name permutation \
  --payload '{}' \
  /tmp/lunker-permutation-full.json && cat /tmp/lunker-permutation-full.json

# Trigger a targeted permutation run for one SLD
aws lambda invoke \
  --profile lunker \
  --region us-east-2 \
  --function-name permutation \
  --payload '{"sld":"example"}' \
  /tmp/lunker-permutation-single.json && cat /tmp/lunker-permutation-single.json

# Tail action/permutation logs while testing inserts
aws logs tail /aws/lambda/action --profile lunker --region us-east-2 --follow
aws logs tail /aws/lambda/permutation --profile lunker --region us-east-2 --follow
```

## Local testing

Unit tests currently focus on shared home-handler behavior.

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

## Runtime configuration

The stacks set most Lambda environment variables automatically at deploy time. The values below are useful when troubleshooting behavior.

| Function | Key environment variables |
| --- | --- |
| `action` | `FUNCTION_NAME`, `PERMUTATION_FUNCTION_NAME` |
| `home` | `LUNKER_TABLE`, `PERMUTATION_TABLE`, `TLD_TABLE`, `CLIENTID_SECRET_ARN`, `WM_OSINT`, `WM_MALWARE`, `WM_DAILYUPDATE`, `WM_WEEKLYUPDATE`, `WM_MONTHLYUPDATE`, `WM_DAILYREMOVE`, `WM_WEEKLYREMOVE`, `WM_MONTHLYREMOVE` |
| `permutation` | `LUNKER_TABLE`, `PERMUTATION_TABLE`, `LUNKER_INDEX` (defaults to `pk-tk-index`), `PERMUTATION_TTL_DAYS` (defaults to `30`) |
| `tld` | `TLD_TABLE` |

## Permutation strategies

For each unique second-level domain (SLD) found in the `lunker` table, the `permutation` Lambda generates candidate look-alike domains.

- For SLDs shorter than 5 characters, it applies a conservative subset: **Homoglyph** and **Transposition**.
- For SLDs with length 5 or greater, it applies the full strategy set below.

| Strategy | Description |
| --- | --- |
| **Homoglyph** | Replaces visually similar characters — e.g. `o`↔`0`, `i`↔`1`↔`l`, `s`↔`5`, `a`↔`4`, `e`↔`3`, `g`↔`9` |
| **Omission** | Removes one character at a time from the SLD |
| **Repetition** | Inserts a duplicate of each existing character adjacent to its original position |
| **Transposition** | Swaps each pair of adjacent, non-identical characters |
| **Hyphenation** | Inserts a hyphen at every possible position within the SLD |
| **Replacement** | Substitutes each character with its QWERTY keyboard neighbors |
| **Insertion** | Inserts a QWERTY keyboard neighbor of each character before or after it |
| **Addition** | Prepends or appends every alphanumeric character (`a–z`, `0–9`) to the SLD |
| **Bitsquatting** | Flips individual bits in each character's ASCII code, keeping only alphanumeric or hyphen results |
| **Vowel Swap** | Replaces each vowel (`a e i o u`) with every other vowel |

All candidates are lower-cased, must be at least two characters long, may only contain alphanumeric characters or hyphens, and must not contain the original SLD as a substring. Results are deduplicated before being written to the `permutation` table with a configurable TTL (default **30 days**).

## Home page behavior

After sign-in, the home page:

1. lists the domains saved for the current user
2. highlights exact SLD matches in **red** and permutation-based matches in **orange**
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
  lunker_permutation.py   # LunkerPermutation stack (us-east-2)
  lunker_stackuse1.py     # LunkerStackUse1 stack (us-east-1, home)
  lunker_stackuse2.py     # LunkerStackUse2 stack (us-east-2, CI/CD)
  lunker_stackusw2.py     # LunkerStackUsw2 stack (us-west-2, home)
action/
  action.py               # DynamoDB Streams Lambda handler
home/
  home_shared.py          # Shared home API logic and HTML rendering helpers
  homeuse1.py             # Home API Lambda handler for us-east-1
  homeusw2.py             # Home API Lambda handler for us-west-2
permutation/
  permutation.py          # Domain permutation Lambda handler
tests/
  test_home_shared.py     # Unit tests for shared home logic
tld/
  tld.py                  # IANA TLD sync Lambda handler
```

## License

[LICENSE](LICENSE)

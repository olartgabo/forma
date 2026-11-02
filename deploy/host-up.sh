#!/usr/bin/env bash
# Run as root on the EC2 host: rebuild deploy/.env from SSM Parameter Store,
# then build and (re)start the stack. Secrets never enter git or shell history.
set -euo pipefail
cd "$(dirname "$0")"

imds_token=$(curl -sf -X PUT http://169.254.169.254/latest/api/token \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
export AWS_DEFAULT_REGION=$(curl -sf -H "X-aws-ec2-metadata-token: $imds_token" \
  http://169.254.169.254/latest/meta-data/placement/region)

required() {
  aws ssm get-parameter --with-decryption --name "$1" \
    --query Parameter.Value --output text
}
# get-parameters reports a missing name instead of failing, so an unset
# provider key deploys with Muse actions disabled.
optional() {
  aws ssm get-parameters --with-decryption --names "$1" \
    --query 'Parameters[0].Value' --output text | sed 's/^None$//'
}

host=$(required /forma/host)
tokens=$(required /forma/api-tokens)
model_key=$(optional /forma/model-api-key)

umask 077
printf "FORMA_HOST=%s\nFORMA_API_TOKENS='%s'\nMODEL_API_KEY='%s'\n" \
  "$host" "$tokens" "$model_key" >.env

docker compose up -d --build --remove-orphans
docker image prune -f

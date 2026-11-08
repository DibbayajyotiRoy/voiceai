#!/usr/bin/env bash
# Deploy the DEMO stack: package the control Lambda, create/update the CloudFormation stack,
# build the amd64 app image and push it to ECR. Safe to re-run.
# Prereq: Secrets Manager secret voiceai/vercel-token exists (see deploy/aws/README.md).
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
STACK="${STACK_NAME:-voiceai-demo}"
REPO_NAME="voiceai-demo"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEMPLATE="$ROOT/deploy/aws/demo.yaml"

if ! command -v aws >/dev/null 2>&1; then
  aws() { uvx --from awscli aws "$@"; }
fi

TAG="${IMAGE_TAG:-$(git -C "$ROOT" rev-parse --short=12 HEAD 2>/dev/null || echo latest)}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
ARTIFACTS="voiceai-demo-artifacts-$ACCOUNT"
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT

# A deploy replaces the running task, which cuts any live call. Refuse unless FORCE=1.
DEMO_URL="${DEMO_URL:-https://demo-api.dibbayajyoti.com}"
ACTIVE="$(curl -fsS --max-time 5 "$DEMO_URL/api/demo/idle-seconds" 2>/dev/null \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("active", 0))' 2>/dev/null || echo 0)"
if [ "${ACTIVE:-0}" -gt 0 ] && [ "${FORCE:-0}" != "1" ]; then
  echo "!! $ACTIVE live call(s) on the demo. Deploying now would cut them. Retry later or set FORCE=1." >&2
  exit 1
fi

echo "==> Artifacts bucket s3://$ARTIFACTS (control Lambda code)"
if ! aws s3api head-bucket --bucket "$ARTIFACTS" >/dev/null 2>&1; then
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$ARTIFACTS" --region "$REGION" >/dev/null
  else
    aws s3api create-bucket --bucket "$ARTIFACTS" --region "$REGION" \
      --create-bucket-configuration "LocationConstraint=$REGION" >/dev/null
  fi
  aws s3api put-public-access-block --bucket "$ARTIFACTS" \
    --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
fi

echo "==> Package template (uploads deploy/aws/control)"
aws cloudformation package --region "$REGION" --template-file "$TEMPLATE" \
  --s3-bucket "$ARTIFACTS" --output-template-file "$BUILD_DIR/packaged.yaml" >/dev/null

output() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}
deploy_stack() {
  echo "==> Deploy stack $STACK (image tag $TAG)"
  aws cloudformation deploy --region "$REGION" --stack-name "$STACK" \
    --template-file "$BUILD_DIR/packaged.yaml" --capabilities CAPABILITY_IAM \
    --parameter-overrides "ImageTag=$TAG" "VercelTeamId=${VERCEL_TEAM_ID:-}" --no-fail-on-empty-changeset
}
push_image() {
  REPO_URI="$(output EcrRepositoryUri)"
  echo "==> Build linux/amd64 image and push $REPO_URI:$TAG"
  aws ecr get-login-password --region "$REGION" \
    | docker login --username AWS --password-stdin "${REPO_URI%%/*}" >/dev/null
  BUILDER="voiceai-demo-builder"
  docker buildx inspect "$BUILDER" >/dev/null 2>&1 \
    || docker buildx create --name "$BUILDER" --driver docker-container >/dev/null
  docker buildx build --builder "$BUILDER" --platform linux/amd64 \
    --tag "$REPO_URI:$TAG" --push "$ROOT"
}

# Push the image BEFORE the task definition points at it; otherwise a task started in
# between fails with "image not found". Only the very first deploy (no ECR repo yet)
# must create the stack first.
if aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" >/dev/null 2>&1; then
  push_image
  deploy_stack
else
  deploy_stack
  push_image
fi

echo "==> Done"
echo "Control URL: $(output ControlUrl)"
echo "Start:  curl -X POST $(output ControlUrl)start"
echo "Status: curl $(output ControlUrl)status"

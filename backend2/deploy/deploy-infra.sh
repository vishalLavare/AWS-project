#!/usr/bin/env bash
# ==============================================================================
# Deploy script for Backend 2 AWS Infrastructure using CloudFormation
# ==============================================================================

set -euo pipefail

STACK_NAME=${1:-"backend2-infra-stack"}
AWS_REGION=$(aws configure get region 2>/dev/null || echo "us-east-1")

echo "========================================================"
echo "Starting CloudFormation Deployment"
echo "Stack Name: $STACK_NAME"
echo "AWS Region: $AWS_REGION"
echo "========================================================"

# Detect Default VPC and Subnets if not custom specified
echo "Detecting default network configuration..."
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=is-default,Values=true" --query "Vpcs[0].VpcId" --output text 2>/dev/null || echo "")

if [ -z "$VPC_ID" ] || [ "$VPC_ID" == "None" ]; then
    echo "❌ Error: Could not find a default VPC. Please create resources manually or customize the script to supply VPC parameters."
    exit 1
fi

SUBNETS=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" --query "Subnets[*].SubnetId" --output text 2>/dev/null | tr '\t' ',' || echo "")

if [ -z "$SUBNETS" ] || [ "$SUBNETS" == "None" ]; then
    echo "❌ Error: Could not find subnets for VPC $VPC_ID."
    exit 1
fi

echo "✅ Found Default VPC: $VPC_ID"
echo "✅ Found Subnets: $SUBNETS"

TEMPLATE_FILE="$(dirname "$0")/infrastructure.yaml"

echo "Deploying CloudFormation stack..."
aws cloudformation deploy \
  --stack-name "$STACK_NAME" \
  --template-file "$TEMPLATE_FILE" \
  --parameter-overrides \
      VpcId="$VPC_ID" \
      Subnets="$SUBNETS" \
  --capabilities CAPABILITY_NAMED_IAM \
  --region "$AWS_REGION"

echo "========================================================"
echo "✅ CloudFormation Stack Deployed Successfully!"
echo "========================================================"

# Query and display outputs
aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs" \
  --output table \
  --region "$AWS_REGION"

# ==============================================================================
# Deploy script for Backend 2 AWS Infrastructure using CloudFormation (PowerShell)
# ==============================================================================

$StackName = if ($args[0]) { $args[0] } else { "backend2-infra-stack" }
$AwsRegion = aws configure get region
if (-not $AwsRegion) { $AwsRegion = "us-east-1" }

Write-Host "========================================================"
Write-Host "Starting CloudFormation Deployment"
Write-Host "Stack Name: $StackName"
Write-Host "AWS Region: $AwsRegion"
Write-Host "========================================================"

# Detect Default VPC
Write-Host "Detecting default network configuration..."
$VpcId = aws ec2 describe-vpcs --filters "Name=is-default,Values=true" --query "Vpcs[0].VpcId" --output text

if ($VpcId -eq "None" -or -not $VpcId) {
    Write-Error "Could not find a default VPC. Please create resources manually or customize the script to supply VPC parameters."
    exit 1
}

# Detect Default Subnets
$SubnetsRaw = aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VpcId" --query "Subnets[*].SubnetId" --output text
# Replace tabs or spaces with commas for CloudFormation list format
$Subnets = ($SubnetsRaw -split "\s+") -join ","
# Remove any trailing or leading commas
$Subnets = $Subnets.Trim(',')

if ($Subnets -eq "None" -or -not $Subnets) {
    Write-Error "Could not find subnets for VPC $VpcId."
    exit 1
}

Write-Host "✅ Found Default VPC: $VpcId"
Write-Host "✅ Found Subnets: $Subnets"

$TemplateFile = Join-Path $PSScriptRoot "infrastructure.yaml"

Write-Host "Deploying CloudFormation stack..."
aws cloudformation deploy `
  --stack-name $StackName `
  --template-file $TemplateFile `
  --parameter-overrides VpcId=$VpcId Subnets=$Subnets `
  --capabilities CAPABILITY_NAMED_IAM `
  --region $AwsRegion

Write-Host "========================================================"
Write-Host "✅ CloudFormation Stack Deployed Successfully!"
Write-Host "========================================================"

# Query and display outputs
aws cloudformation describe-stacks `
  --stack-name $StackName `
  --query "Stacks[0].Outputs" `
  --output table `
  --region $AwsRegion

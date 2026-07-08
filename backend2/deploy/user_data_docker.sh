#!/usr/bin/env bash
# ==============================================================================
# AWS EC2 User Data script for Backend 2 (Dockerized via ECR)
# Configured in the AWS Launch Template for the Auto Scaling Group.
# This script runs on boot to install Docker, fetch the container image from ECR,
# and run it.
# ==============================================================================

# Exit immediately if a command exits with a non-zero status
set -e

echo "Updating packages and installing Docker / AWS CLI..."
apt-get update -y
apt-get install -y docker.io awscli

# Start and enable Docker service
systemctl start docker
systemctl enable docker

# Configuration variables
# Note: Ensure the EC2 Instance Profile IAM Role has ECR read permissions:
# ecr:GetAuthorizationToken, ecr:BatchCheckLayerAvailability, ecr:GetDownloadUrlForLayer, ecr:BatchGetImage
AWS_REGION="us-east-1"
ECR_REGISTRY="YOUR_ECR_REGISTRY_URL" # e.g. <account-id>.dkr.ecr.us-east-1.amazonaws.com
ECR_REPOSITORY="backend2"
IMAGE_TAG="latest"

FULL_IMAGE_URI="${ECR_REGISTRY}/${ECR_REPOSITORY}:${IMAGE_TAG}"

echo "Authenticating Docker with Amazon ECR..."
# Log in to ECR (retries if credentials helper or network is initially slow on boot)
for i in {1..5}; do
    aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_REGISTRY" && break || sleep 5
done

echo "Pulling image from ECR: $FULL_IMAGE_URI..."
docker pull "$FULL_IMAGE_URI"

echo "Running Backend 2 Container..."
# Stop and remove any existing container with the same name to prevent naming conflicts
docker stop backend2-container || true
docker rm backend2-container || true

# Run container exposing port 8001
# Note: We pass environment variables so that the app knows it is running in AWS
# and which Auto Scaling Group it belongs to for self-termination.
docker run -d \
  --name backend2-container \
  --restart always \
  -p 8001:8001 \
  -e AWS_DEPLOYMENT=true \
  -e AWS_REGION="$AWS_REGION" \
  -e BACKEND2_ASG_NAME="backend2-asg" \
  -e IDLE_TIMEOUT_SECONDS="600" \
  "$FULL_IMAGE_URI"

echo "Backend 2 container deployment complete and running on port 8001!"

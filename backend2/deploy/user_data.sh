#!/usr/bin/env bash
# ==============================================================================
# AWS EC2 User Data script for Backend 2 (Dockerized via ECR)
# Configured in the AWS Launch Template for the Auto Scaling Group.
# This script runs on boot to install Docker, pull the backend image from ECR,
# and run the Docker container.
# ==============================================================================

# Exit immediately if a command exits with a non-zero status
set -e

echo "Updating packages and installing Docker / AWS CLI..."
apt-get update -y
apt-get install -y docker.io awscli

# Start and enable Docker service
systemctl start docker
systemctl enable docker

# ==============================================================================
# CONFIGURATION VARIABLES
# Replace these values as needed for your AWS environment.
# Ensure the EC2 Instance Profile (IAM Role) attached to the instances has:
# 1. ECR read permissions (AmazonEC2ContainerRegistryReadOnly)
# 2. Auto Scaling update permission (to scale itself down to 0 when idle)
# ==============================================================================
AWS_REGION="ap-south-1"
ECR_REGISTRY="142166253229.dkr.ecr.ap-south-1.amazonaws.com"
ECR_REPOSITORY="backend2"
IMAGE_TAG="latest"
BACKEND2_ASG_NAME="backend2-asg"
IDLE_TIMEOUT_SECONDS="600" # 10 minutes

FULL_IMAGE_URI="${ECR_REGISTRY}/${ECR_REPOSITORY}:${IMAGE_TAG}"

echo "Authenticating Docker with Amazon ECR..."
# Retry logic in case network is not fully up or IAM credentials aren't ready immediately
for i in {1..5}; do
    aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_REGISTRY" && break || sleep 5
done

echo "Pulling image from ECR: $FULL_IMAGE_URI..."
docker pull "$FULL_IMAGE_URI"

echo "Running Backend 2 Container..."
# Stop and remove any existing container with the same name to prevent conflicts
docker stop backend2-container || true
docker rm backend2-container || true

# Run container exposing port 8001
docker run -d \
  --name backend2-container \
  --restart always \
  -p 8001:8001 \
  -e AWS_DEPLOYMENT=true \
  -e AWS_REGION="$AWS_REGION" \
  -e BACKEND2_ASG_NAME="$BACKEND2_ASG_NAME" \
  -e IDLE_TIMEOUT_SECONDS="$IDLE_TIMEOUT_SECONDS" \
  "$FULL_IMAGE_URI"

echo "Backend 2 container deployment complete and running on port 8001!"


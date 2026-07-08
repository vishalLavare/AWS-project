#!/usr/bin/env bash
# ==============================================================================
# AWS EC2 User Data script for Backend 2
# Configured in the AWS Launch Template for the Auto Scaling Group.
# This script runs on boot to fetch the latest code from S3 and start the app.
# ==============================================================================

# Exit immediately if a command exits with a non-zero status
set -e

# Update and install system dependencies
echo "Updating packages and installing system requirements..."
apt-get update -y
apt-get install -y python3 python3-pip python3-venv unzip awscli

# Configuration variables
DEPLOY_DIR="/home/ubuntu/backend2"
S3_BUCKET="YOUR_S3_BUCKET_NAME" # Will be updated/replaced or read dynamically
S3_KEY="backend2.zip"

# Create application directory
mkdir -p "$DEPLOY_DIR"
cd "$DEPLOY_DIR"

# Download the latest artifact from S3
# Note: Ensure the EC2 instance has an IAM Role attached that permits S3 Read Access for the bucket.
echo "Downloading backend2 from S3..."
aws s3 cp "s3://$S3_BUCKET/$S3_KEY" ./backend2.zip

# Unzip and clean archive
echo "Extracting deployment package..."
unzip -o backend2.zip
rm backend2.zip

# Setup Python Virtual Environment
echo "Setting up Python virtual environment..."
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
else
    # Fallback default dependencies
    pip install fastapi uvicorn[standard] requests
fi

# Fix ownership
chown -R ubuntu:ubuntu "$DEPLOY_DIR"

# Create systemd service unit file for Backend 2
echo "Configuring systemd service..."
cat > /etc/systemd/system/backend2.service <<EOF
[Unit]
Description=Backend 2 Node FastAPI Service
After=network.target

[Service]
User=ubuntu
WorkingDirectory=$DEPLOY_DIR
ExecStart=$DEPLOY_DIR/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8001
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Reload daemon, enable and start service
echo "Starting Backend 2 service..."
systemctl daemon-reload
systemctl enable backend2.service
systemctl restart backend2.service

echo "Backend 2 deployment complete and running on port 8001!"

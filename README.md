# Multi-Service Auto-Start Control Center (AWS Serverless + ASG)

This repository implements an on-demand backend activation system. It scales an AWS Auto Scaling Group (ASG) from **0 to 1 nodes** only when a user requests it (via UI click, API request, or curl), monitors the server until it becomes healthy, forwards requests, and scales back down to **0 nodes** after a period of inactivity (10 minutes) to minimize AWS costs.

It supports two main execution modes and components:
1. **FastAPI Web Dashboard Control Center ([backend1/](AWS project/backend1))**: An EC2-based controller app that polls the status of Backend 2, triggers its scaling via API Gateway, and acts as the administrative portal.
2. **On-Demand Worker Node ([backend2/](AWS project/backend2))**: An EC2-hosted application in an Auto Scaling Group, containerized with Docker, pulling from ECR, and exposing port 8001.

---

## 📐 System Architecture

### User Flow & Request Routing
```
                +-------------------+
                |   Frontend / UI   |
                |   (Start Button)  |
                +---------+---------+
                          |
                          | (POST /start)
                          ▼
                API Gateway (HTTP API)
                          |
                          ▼
                     AWS Lambda
                          |
             +------------+------------+
             |                         |
             ▼                         ▼
    Auto Scaling Group          Target Group
    (Desired: 0 -> 1)           (Health Check)
             |                         |
             +------------+------------+
                          |
                          ▼
              Application Load Balancer (ALB)
                          |
                          ▼
                  EC2 Instance (Backend 2)
                          |
                          ▼
                  Docker Container
```

### Overall Service Map
```
                  ┌──────────────────────────────┐
                  │          Web Browser         │
                  └──────────────┬───────────────┘
                                 │ HTTP / API
                                 ▼
                     ┌───────────────────────┐
                     │       Backend 1       │ (FastAPI Dashboard / Controller)
                     │    (EC2 Instance)     │
                     └─────┬───────────┬─────┘
            AWS Auto Scale │           │ Health Probe
            (boto3 API)    │           │ (HTTP port 8001 via ALB)
                           ▼           ▼
                     ┌───────────────────────┐
                     │       Backend 2       │ (Auto Scaling Group)
                     │  (ASG: 0 -> 1 Nodes)  │
                     └───────────────────────┘
```

---

## 📂 Repository Structure

*   **[`backend1/`](AWS project/backend1)**: The controller application.
    *   Serves the Web Dashboard.
    *   Handles status monitoring, starting, and stopping of Backend 2 by invoking the AWS API Gateway start endpoint.
    *   **CI/CD**: Deploys via SSH to an EC2 instance and runs within a Docker container.
*   **[`backend2/`](AWS project/backend2)**: The worker node application.
    *   An on-demand service running behind an Auto Scaling Group.
    *   Exposes a `/health` endpoint and automatically terminates/scales itself down if idle.
    *   **CI/CD**: Packages application in a Docker container, pushes to Amazon ECR, and triggers an ASG Instance Refresh.
*   **[`lambda_function.py`](AWS project/lambda_function.py)**: The serverless orchestrator that manages Target Group health checks, ASG capacity adjustment, and polling.

---

## 🚀 Setup & Deployment Guide

Follow these steps sequentially to configure the AWS serverless auto-start infrastructure:

### Step 1: Create & Push Docker Image (Backend 2)
Build the container image for Backend 2 and push it to Amazon Elastic Container Registry (ECR).

1. Create a repository in Amazon ECR named `backend2`.
2. Run the following commands to build, tag, and push the image:
```bash
# Build docker image
docker build -t backend2 ./backend2

# Tag image with ECR URI
docker tag backend2:latest <ACCOUNT_ID>.dkr.ecr.ap-south-1.amazonaws.com/backend2:latest

# Log in to ECR
aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.ap-south-1.amazonaws.com

# Push Image to registry
docker push <ACCOUNT_ID>.dkr.ecr.ap-south-1.amazonaws.com/backend2:latest
```

---

### Step 2: Create IAM Roles

#### 1. Backend 1 EC2 Role (FastAPI Controller)
Attach this role to the Backend 1 EC2 instance to allow it to monitor and manually scale down the ASG:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "autoscaling:DescribeAutoScalingGroups",
        "autoscaling:UpdateAutoScalingGroup",
        "ec2:DescribeInstances"
      ],
      "Resource": "*"
    }
  ]
}
```

#### 2. Backend 2 Launch Template Role (Worker EC2)
Attach this role to the EC2 instances created by the Launch Template. It permits the instance to pull the docker image from ECR, and allows the container to update the ASG desired capacity to 0 when idle:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:DescribeRepositories",
        "ecr:ListImages"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "autoscaling:DescribeAutoScalingGroups",
        "autoscaling:SetDesiredCapacity",
        "autoscaling:UpdateAutoScalingGroup"
      ],
      "Resource": "*"
    }
  ]
}
```

---

### Step 3: Create Launch Template (Backend 2)
Create a Launch Template named `backend2-launch-template` with:
- **AMI**: Ubuntu Server (Latest LTS)
- **Instance Type**: `t2.micro`
- **Security Group**: Open port `8001` (for app health checks/traffic) and `22` (optional SSH).
- **IAM Instance Profile**: Attach the Backend 2 Launch Template Role created in Step 2.
- **Key Pair**: Select your preferred SSH key pair.
- **User Data**: Paste the contents of [`backend2/deploy/user_data.sh`](AWS project/backend2/deploy/user_data.sh) in the Advanced Details:

```bash
#!/usr/bin/env bash
set -e

# Update and install Docker + AWS CLI
apt-get update -y
apt-get install -y docker.io awscli

systemctl start docker
systemctl enable docker

# Configuration
AWS_REGION="ap-south-1"
ECR_REGISTRY="<YOUR_ACCOUNT_ID>.dkr.ecr.ap-south-1.amazonaws.com"
ECR_REPOSITORY="backend2"
IMAGE_TAG="latest"
BACKEND2_ASG_NAME="backend2-asg"
IDLE_TIMEOUT_SECONDS="600" # 10 Minutes

FULL_IMAGE_URI="${ECR_REGISTRY}/${ECR_REPOSITORY}:${IMAGE_TAG}"

# Authenticate with ECR
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_REGISTRY"

# Pull image
docker pull "$FULL_IMAGE_URI"

# Stop existing container if any
docker stop backend2-container || true
docker rm backend2-container || true

# Run Backend 2 container
docker run -d \
  --restart always \
  --name backend2-container \
  -p 8001:8001 \
  -e AWS_DEPLOYMENT=true \
  -e AWS_REGION="$AWS_REGION" \
  -e BACKEND2_ASG_NAME="$BACKEND2_ASG_NAME" \
  -e IDLE_TIMEOUT_SECONDS="$IDLE_TIMEOUT_SECONDS" \
  "$FULL_IMAGE_URI"
```

---

### Step 4: Create Target Group
Create an Application Load Balancer Target Group named `backend2-tg`:
- **Target Type**: Instances
- **Protocol**: `HTTP`
- **Port**: `8001` (corresponds to Docker container port)
- **Health Check Path**: `/health` (or `/` according to your application)
- **Healthy/Unhealthy Thresholds**: set to `2` for fast registration response times.

---

### Step 5: Create Application Load Balancer (ALB)
Create a public-facing Application Load Balancer:
- **Listeners**: `HTTP : 80`
- **Default Action**: Forward to Target Group `backend2-tg`
- **Security Group**: Allow public HTTP port 80 traffic.

---

### Step 6: Create Auto Scaling Group (ASG)
Create an Auto Scaling Group named `backend2-asg`:
- **Launch Template**: Choose `backend2-launch-template`.
- **Target Group**: Attach the Target Group `backend2-tg` under Load Balancing settings.
- **Group Size Capacities**:
  - Minimum Capacity: `0`
  - Desired Capacity: `0`
  - Maximum Capacity: `1`

---

### Step 7: Create Lambda Function
Create a Lambda function to orchestrate the start sequence:
- **Runtime**: `Python 3.x`
- **Timeout**: `300 Seconds` (Crucial: gives EC2 enough time to boot and start Docker)
- **Environment Variables**:
  - `ASG_NAME`: `backend2-asg`
  - `TARGET_GROUP_ARN`: `<your_target_group_arn>`
  - `ALB_DNS`: `<your_alb_public_dns_url>`
- **IAM Permission Policy**: Attach the following custom policy to the Lambda execution role:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "autoscaling:DescribeAutoScalingGroups",
        "autoscaling:SetDesiredCapacity",
        "autoscaling:UpdateAutoScalingGroup",
        "elasticloadbalancing:DescribeTargetHealth"
      ],
      "Resource": "*"
    }
  ]
}
```
- **Lambda Code**: Paste the contents of [`lambda_function.py`](AWS project/lambda_function.py) into the editor:
[View complete Lambda Source Code (lambda_function.py)](AWS project/lambda_function.py)

---

### Step 8: Create HTTP API Gateway
Create an HTTP API Gateway to expose the start function:
1. Create a new **HTTP API**.
2. Create an Integration pointing to your **Lambda Function** from Step 7.
3. Configure the Route:
   - Method: `POST`
   - Path: `/start`
4. Deploy the API Gateway stage.
5. Note the generated Invoke URL (e.g., `https://xxxxx.execute-api.ap-south-1.amazonaws.com/start`).

---

### Step 9: Connect the Start Trigger (Client Examples)

#### Python Integration
```python
import requests

response = requests.post("https://xxxxx.execute-api.ap-south-1.amazonaws.com/start")
print(response.status_code)
print(response.json())
```

#### JavaScript Integration
```javascript
fetch("https://xxxxx.execute-api.ap-south-1.amazonaws.com/start", {
    method: "POST"
})
.then(res => res.json())
.then(data => console.log(data));
```

#### Curl CLI
```bash
curl -X POST https://xxxxx.execute-api.ap-south-1.amazonaws.com/start
```

---

## 📋 Full Request Flow

```
[Start Trigger / POST] ➔ [API Gateway] ➔ [AWS Lambda]
                                               │
                                       ┌───────┴───────┐
                                       ▼               ▼
                              [Check TG Health]  [If Unhealthy: Scale ASG (Desired 0→1)]
                                       │               │
                                       ▼               ▼
                                 [If Healthy]     [EC2 Instance Boot up]
                                       │               │
                                       │               ▼
                                       │          [Docker Pulls & Runs Backend 2]
                                       │               │
                                       │               ▼
                                       │          [Instance registers to Target Group]
                                       │               │
                                       ▼               ▼
                            [Return ALB DNS] ◄─── [Wait/Poll until Target is Healthy]
```

---

## 🕒 Inactivity Auto Scale-Down (10 Minutes)

Backend 2 runs a background monitoring task that terminates the host instance to save cost when idle:
*   **Request Tracker**: Backend 2 tracks the timestamp of the last active request using a FastAPI HTTP middleware.
*   **Excluded Endpoints**: Background automated health checks (such as `/health` or static assets) are excluded and **do not** reset the idle timer.
*   **Scale Down Trigger**: If no business requests are received for 10 minutes (`IDLE_TIMEOUT_SECONDS` environment variable, default `600`), Backend 2 invokes the Auto Scaling boto3 client to update its ASG Desired Capacity back to `0`.
*   **Local Fallback**: In local development, the service automatically terminates its own process when idle.

---

## 🚀 GitHub Actions Pipelines (CI/CD)

The repository provides automated deployment pipelines located in `.github/workflows/`. Add the following Secrets under your repository settings:

### Shared Config Secrets
- `AWS_ACCESS_KEY_ID`: AWS Access Key ID.
- `AWS_SECRET_ACCESS_KEY`: AWS Secret Access Key.
- `AWS_REGION`: Target region (default: `ap-south-1`).

### Backend 1 Deploy Secrets (EC2)
- `EC2_HOST`: Public IP/DNS of the Backend 1 controller host.
- `EC2_USERNAME`: SSH username (e.g., `ubuntu`).
- `SSH_PRIVATE_KEY`: Private SSH Key matching the controller EC2.
- `DEPLOY_PATH`: Target directory path on EC2 (e.g., `/home/ubuntu/backend1`).
- `API_GATEWAY_URL`: HTTP API Gateway Invoke URL from Step 8.

### Backend 2 Deploy Secrets (ECR)
- `ECR_REPOSITORY`: Name of ECR repository (default: `backend2`).
- `ASG_NAME`: Name of the worker Auto Scaling Group (e.g., `backend2-asg`).
- `LAUNCH_TEMPLATE_NAME`: Name of Launch Template (default: `backend2-launch-template`).

---

## 💻 Local Development Fallback

Both backends are configured to function locally without active AWS configurations:
1. Start Backend 1:
   ```bash
   cd backend1
   pip install -r requirements.txt
   uvicorn main:app --port 8000
   ```
2. Open `http://127.0.0.1:8000` in your browser. Clicking **Start** will launch Backend 2 as a subprocess on port `8001` on your local machine. It will automatically shut down if idle for 10 minutes.

---

## 🔧 Troubleshooting & Common Issues

### 1. AWS Credentials & IMDSv2 in Docker
*   **Issue**: Running containerised worker application throws `AWS Error: Unable to locate credentials`.
*   **Cause**: Docker containers run in a bridged network (one hop away from host). By default, IMDSv2 uses a HTTP response hop limit of `1`, dropping credentials before they reach the container.
*   **Solutions**:
    *   **Option A**: Run Docker container using host network:
        ```bash
        docker run --network host ...
        ```
    *   **Option B (Recommended)**: Modify the EC2 Metadata Options to allow a hop limit of `2`:
        ```bash
        aws ec2 modify-instance-metadata-options --instance-id <instance-id> --http-put-response-hop-limit 2
        ```

### 2. Lambda Timeout (202 / 504 Gateway Timeout)
*   **Solution**: Ensure your Lambda function configuration timeout is set to `300 Seconds` (5 minutes). EC2 boot times and ECR pulling take ~1-2 minutes.

### 3. ASG Scaling Failures
*   **Solution**: Double check that the ASG configuration permits scaling up to `1` (Maximum Capacity = `1`).

### 4. Docker ECR Authorization Failures
*   **Solution**: Ensure the IAM role assigned to the EC2 Launch Template has ECR read access, and the User Data is logging in using the correct AWS Account ID and region.

### 5. Target Group Remains Unhealthy
*   **Solution**: Check that your container runs on port `8001` and is listening on `0.0.0.0` (not just `127.0.0.1`), and your target group is pointing to Port `8001`.

---

## 🛠️ Useful Debugging Commands

*   Check running containers: `docker ps`
*   View container logs: `docker logs backend2-container`
*   View instance initialization progress logs: `sudo cat /var/log/cloud-init-output.log`
*   Verify Docker daemon status: `sudo systemctl status docker`
*   Inspect ALB Target Health from CLI:
    ```bash
    aws elbv2 describe-target-health --target-group-arn <TARGET_GROUP_ARN>
    ```

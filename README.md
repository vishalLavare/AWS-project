# Multi-Service Control Center (AWS Deployments)

This project contains two distinct microservices, **Backend 1** and **Backend 2**, built to show how an EC2-hosted controller app can dynamically scale a separate backend from 0 to 1 nodes in an AWS Auto Scaling Group (ASG) upon a user trigger.

```
                  ┌──────────────────────────────┐
                  │          Web Browser         │
                  └──────────────┬───────────────┘
                                 │ HTTP / API
                                 ▼
                     ┌───────────────────────┐
                     │       Backend 1       │ (FastAPI Controller)
                     │    (EC2 Instance)     │
                     └─────┬───────────┬─────┘
            AWS Auto Scale │           │ Health Probe
            (boto3 API)    │           │ (HTTP port 8001)
                           ▼           ▼
                     ┌───────────────────────┐
                     │       Backend 2       │ (Auto Scaling Group)
                     │  (ASG: 0 -> 1 Nodes)  │
                     └───────────────────────┘
```

---

## 📂 Repository Structure

*   **`backend1/`**: The controller application.
    *   Serves the Web Dashboard.
    *   Handles status monitoring, starting, and stopping of Backend 2 via AWS ASG APIs.
    *   **CI/CD**: Deploys via SSH to an EC2 instance.
*   **`backend2/`**: The worker node application.
    *   An on-demand service running behind an Auto Scaling Group.
    *   **CI/CD**: Packages application in a Docker container, pushes to Amazon ECR, and triggers an ASG Instance Refresh.

---

## 🛠️ Infrastructure Configuration

To deploy this setup successfully in AWS, follow the guide below:

### 1. Amazon ECR Registry
Create an Amazon Elastic Container Registry (ECR) repository named `backend2` to host the Backend 2 container images.

### 2. IAM Roles
*   **Backend 1 EC2 Role**: Attach an IAM role to the Backend 1 EC2 instance with the following permissions so it can scale and inspect Backend 2:
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
*   **Backend 2 Launch Template Role**: Attach an IAM role to the Launch Template used by Backend 2 with ECR read permissions (so the instances can authenticate and pull the image):
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
            "ecr:BatchGetImage"
          ],
          "Resource": "*"
        }
      ]
    }
    ```

### 3. Backend 2 Auto Scaling Group
1. Set up a **Launch Template** using an Ubuntu or Amazon Linux AMI.
2. In the **User Data** section under **Advanced Details**, paste the contents of `backend2/deploy/user_data_docker.sh`. Make sure to replace `YOUR_ECR_REGISTRY_URL` with your actual ECR Registry URL (e.g. `<aws_account_id>.dkr.ecr.<region>.amazonaws.com`).
3. Create an **Auto Scaling Group** named `backend2-asg` with:
   *   Minimum Capacity: `0`
   *   Maximum Capacity: `1`
   *   Desired Capacity: `0`

---

## 🚀 GitHub Actions Pipelines

Both microservices are deployed from this single repository using path-based workflow triggers in `.github/workflows/`. Add the following secrets in your GitHub Repository settings:

### Shared Secrets
*   `AWS_ACCESS_KEY_ID`: AWS credentials access key.
*   `AWS_SECRET_ACCESS_KEY`: AWS credentials secret key.
*   `AWS_REGION`: AWS Region of your ASG and ECR registry (e.g. `us-east-1`).

### Backend 1 Secrets (EC2 Deploy)
*   `EC2_HOST`: Public IP/DNS of the Backend 1 EC2 instance.
*   `EC2_USERNAME`: SSH Username (e.g. `ubuntu`).
*   `SSH_PRIVATE_KEY`: Private Key matching the EC2 instance key pair.
*   `DEPLOY_PATH`: Target directory path on EC2 (e.g., `/home/ubuntu/backend1`).

### Backend 2 Secrets (ECR Deploy)
*   `ECR_REPOSITORY`: The name of your ECR repository (defaults to `backend2` if not set).
*   `ASG_NAME`: The name of your Backend 2 Auto Scaling Group (e.g. `backend2-asg`).

---

## 🕒 Inactivity Auto Scale-Down (10 Minutes)

Backend 2 features an automatic self-scaling mechanism that scales the infrastructure down from 1 to 0 nodes after a period of inactivity:
*   **Request Tracker**: Backend 2 tracks the timestamp of the last incoming request.
*   **Excluded Endpoints**: Background health checks (specifically `/health` and static assets) are excluded, meaning the server's idle timer is **not** reset by automated system status checks.
*   **Scale Down Trigger**: If no business requests are received for 10 minutes (600 seconds, customizable via the `IDLE_TIMEOUT_SECONDS` environment variable), Backend 2 automatically calls the AWS Auto Scaling API to set the Desired Capacity of its ASG to `0`. 
*   **Local Fallback**: In local development, the server will automatically shut down its subprocess when idle.

---

## 💻 Local Development

Both applications are configured with a local fallback mode. If no AWS environment variables are set, they execute Backend 2 as a local subprocess.

To run locally:
1. Start Backend 1:
   ```bash
   cd backend1
   pip install -r requirements.txt
   uvicorn main:app --port 8000
   ```
2. Navigate to `http://127.0.0.1:8000` in your web browser. Clicking the **Start** button will spawn Backend 2 as a subprocess on port `8001` locally.

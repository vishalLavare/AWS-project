import os
import sys
import subprocess
import requests
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

# AWS configuration and initialization
AWS_DEPLOYMENT = os.getenv("AWS_DEPLOYMENT", "false").lower() == "true"
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
BACKEND2_ASG_NAME = os.getenv("BACKEND2_ASG_NAME", "backend2-asg")
BACKEND2_URL = os.getenv("BACKEND2_URL", "").strip() or "http://demoLB-1135950361.ap-south-1.elb.amazonaws.com" # Optional ALB or custom Route53 DNS for Backend 2
API_GATEWAY_URL = os.getenv("API_GATEWAY_URL", "https://abc123.execute-api.ap-south-1.amazonaws.com/start")

BOTO3_AVAILABLE = False
as_client = None
ec2_client = None
elbv2_client = None

if AWS_DEPLOYMENT:
    try:
        import boto3
        as_client = boto3.client('autoscaling', region_name=AWS_REGION)
        ec2_client = boto3.client('ec2', region_name=AWS_REGION)
        try:
            elbv2_client = boto3.client('elbv2', region_name=AWS_REGION)
        except Exception as e_elb:
            print(f"Failed to initialize elbv2 client: {e_elb}")
        BOTO3_AVAILABLE = (as_client is not None) and (ec2_client is not None)
    except Exception as e:
        print(f"Failed to initialize AWS clients: {e}")
        as_client = None
        ec2_client = None
        elbv2_client = None
        BOTO3_AVAILABLE = False

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    global backend2_process
    if backend2_process and backend2_process.poll() is None:
        backend2_process.terminate()
        try:
            backend2_process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            backend2_process.kill()

app = FastAPI(title="Backend 1 Controller", lifespan=lifespan)

# Allow CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Reference to the backend 2 subprocess (for local mode)
backend2_process = None

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
BACKEND2_SCRIPT = os.path.join(BASE_DIR, "backend2", "main.py")

# Mount static files (style.css, index.html)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
async def get_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.get("/api/status")
async def get_status():
    global backend2_process
    
    # 1. AWS ASG Mode
    if AWS_DEPLOYMENT:
        if not BOTO3_AVAILABLE or as_client is None or ec2_client is None:
            return {
                "backend1": "running",
                "backend2": "error",
                "message": "AWS_DEPLOYMENT is enabled, but AWS clients (boto3) are not initialized. Check server logs."
            }
        try:
            response = as_client.describe_auto_scaling_groups(
                AutoScalingGroupNames=[BACKEND2_ASG_NAME]
            )
            asg_list = response.get("AutoScalingGroups", [])
            if not asg_list:
                return {"backend1": "running", "backend2": "stopped", "message": f"ASG {BACKEND2_ASG_NAME} not found"}
            
            asg = asg_list[0]
            desired_capacity = asg.get("DesiredCapacity", 0)
            instances = asg.get("Instances", [])
            
            if desired_capacity == 0:
                return {"backend1": "running", "backend2": "stopped"}
            
            # Check for InService and Healthy instances
            inservice_instances = [
                inst for inst in instances 
                if inst.get("LifecycleState") == "InService" and inst.get("HealthStatus") == "Healthy"
            ]
            
            if not inservice_instances:
                return {"backend1": "running", "backend2": "starting", "backend2_url": BACKEND2_URL}
            
            # If a public/private ALB or custom URL is defined, check its health endpoint
            if BACKEND2_URL:
                try:
                    res = requests.get(f"{BACKEND2_URL.rstrip('/')}/health", timeout=2.0)
                    if res.status_code == 200:
                        try:
                            if res.json().get("status") == "running":
                                return {"backend1": "running", "backend2": "running", "backend2_url": BACKEND2_URL}
                        except ValueError:
                            pass
                    elif res.status_code in (502, 503, 504):
                        # The load balancer is reached but not routing to targets yet (propagating status)
                        return {"backend1": "running", "backend2": "starting", "backend2_url": BACKEND2_URL}
                except requests.RequestException:
                    pass


            # Fallback 1: Query Target Group health via the AWS API
            if elbv2_client is not None:
                target_group_arns = asg.get("TargetGroupARNs", [])
                for tg_arn in target_group_arns:
                    try:
                        health_resp = elbv2_client.describe_target_health(TargetGroupArn=tg_arn)
                        for target_desc in health_resp.get("TargetHealthDescriptions", []):
                            if target_desc.get("TargetHealth", {}).get("State") == "healthy":
                                return {"backend1": "running", "backend2": "running", "backend2_url": BACKEND2_URL}
                    except Exception as e_tg:
                        print(f"Failed to check target health for {tg_arn}: {e_tg}")
            
            # Fallback 2: Fetch dynamic instance IPs and check their ports directly
            try:
                instance_ids = [inst["InstanceId"] for inst in inservice_instances]
                ec2_response = ec2_client.describe_instances(InstanceIds=instance_ids)
                
                ips = []
                for reservation in ec2_response.get("Reservations", []):
                    for instance in reservation.get("Instances", []):
                        ip = instance.get("PrivateIpAddress") or instance.get("PublicIpAddress")
                        if ip:
                            ips.append(ip)
                
                for ip in ips:
                    try:
                        res = requests.get(f"http://{ip}:8001/health", timeout=1.0)
                        if res.status_code == 200 and res.json().get("status") == "running":
                            return {"backend1": "running", "backend2": "running", "backend2_url": BACKEND2_URL}
                    except requests.RequestException:
                        pass
            except Exception as e_ip:
                print(f"Failed to check individual instance IPs: {e_ip}")
            
            return {"backend1": "running", "backend2": "starting", "backend2_url": BACKEND2_URL}
            
        except Exception as e:
            return {"backend1": "running", "backend2": "error", "message": f"AWS Error: {str(e)}"}
            
    # 2. Local Fallback Mode
    else:
        try:
            response = requests.get("http://127.0.0.1:8001/health", timeout=1.0)
            if response.status_code == 200 and response.json().get("status") == "running":
                return {"backend1": "running", "backend2": "running", "backend2_url": "http://127.0.0.1:8001/"}
        except requests.RequestException:
            pass

        if backend2_process and backend2_process.poll() is not None:
            backend2_process = None

        return {"backend1": "running", "backend2": "stopped"}

@app.post("/api/start")
async def start_backend2():
    global backend2_process
    
    # 1. AWS ASG Mode via API Gateway
    if AWS_DEPLOYMENT:
        if not API_GATEWAY_URL:
            return {"status": "failed", "message": "AWS_DEPLOYMENT is enabled, but API_GATEWAY_URL is not configured."}
        if not (API_GATEWAY_URL.startswith("http://") or API_GATEWAY_URL.startswith("https://")):
            return {"status": "failed", "message": f"AWS_DEPLOYMENT is enabled, but API_GATEWAY_URL '{API_GATEWAY_URL}' is invalid. It must start with http:// or https://"}
        try:
            response = requests.post(API_GATEWAY_URL, timeout=300)
            return Response(
                content=response.text,
                status_code=response.status_code,
                media_type="application/json"
            )
        except Exception as e:
            return {"status": "failed", "message": f"Failed to call API Gateway: {str(e)}"}
            
    # 2. Local Fallback Mode
    else:
        try:
            response = requests.get("http://127.0.0.1:8001/health", timeout=1.0)
            if response.status_code == 200:
                return {"status": "running", "message": "Backend 2 is already running"}
        except requests.RequestException:
            pass
            
        if not backend2_process or backend2_process.poll() is not None:
            try:
                backend2_process = subprocess.Popen(
                    [sys.executable, BACKEND2_SCRIPT],
                    cwd=os.path.dirname(BACKEND2_SCRIPT),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                return {"status": "starting", "message": "Backend 2 is starting"}
            except Exception as e:
                return {"status": "failed", "message": f"Failed to start Backend 2: {str(e)}"}
                
        return {"status": "running", "message": "Backend 2 process active"}

@app.post("/api/stop")
async def stop_backend2():
    global backend2_process
    
    # 1. AWS ASG Mode
    if AWS_DEPLOYMENT:
        if not BOTO3_AVAILABLE or as_client is None:
            return {"status": "failed", "message": "AWS_DEPLOYMENT is enabled, but AWS clients (boto3) are not initialized."}
        try:
            as_client.update_auto_scaling_group(
                AutoScalingGroupName=BACKEND2_ASG_NAME,
                DesiredCapacity=0,
                MinSize=0,
                MaxSize=1
            )
            return {"status": "stopped", "message": "Triggered ASG scale down from 1 to 0 for Backend 2"}
        except Exception as e:
            return {"status": "failed", "message": f"Failed to scale down ASG: {str(e)}"}
            
    # 2. Local Fallback Mode
    else:
        try:
            requests.post("http://127.0.0.1:8001/shutdown", timeout=1.0)
        except requests.RequestException:
            pass
            
        if backend2_process:
            if backend2_process.poll() is None:
                backend2_process.terminate()
                try:
                    backend2_process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    backend2_process.kill()
            backend2_process = None
            
        return {"status": "stopped", "message": "Backend 2 stopped successfully"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)


import os
import sys
import time
import asyncio
import platform
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

# Idle timeout configuration
# Default: 10 minutes (600 seconds)
IDLE_TIMEOUT_SECONDS = int(os.getenv("IDLE_TIMEOUT_SECONDS", "600"))
LAST_REQUEST_TIME = time.time()

# AWS configurations for self-termination/scaling down
AWS_DEPLOYMENT = os.getenv("AWS_DEPLOYMENT", "false").lower() == "true"
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
BACKEND2_ASG_NAME = os.getenv("BACKEND2_ASG_NAME", "backend2-asg")

async def idle_timeout_monitor():
    global LAST_REQUEST_TIME
    while True:
        await asyncio.sleep(10)  # Check every 10 seconds
        elapsed = time.time() - LAST_REQUEST_TIME
        if elapsed > IDLE_TIMEOUT_SECONDS:
            print(f"Backend 2 idle for {elapsed:.1f}s. Initiating scale down to 0...")
            if AWS_DEPLOYMENT:
                try:
                    import boto3
                    as_client = boto3.client('autoscaling', region_name=AWS_REGION)
                    # Scale down the ASG containing this instance to 0
                    as_client.update_auto_scaling_group(
                        AutoScalingGroupName=BACKEND2_ASG_NAME,
                        DesiredCapacity=0
                    )
                    print(f"Successfully requested scaling down ASG {BACKEND2_ASG_NAME} to 0 desired capacity.")
                except Exception as e:
                    print(f"Failed to scale down ASG via boto3: {str(e)}")
            else:
                # Local fallback - shutdown process
                print("Local mode: Shutting down process locally.")
                os._exit(0)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start monitor task
    monitor_task = asyncio.create_task(idle_timeout_monitor())
    yield
    # Cancel monitor task
    monitor_task.cancel()

app = FastAPI(title="Backend 2 Node", lifespan=lifespan)

# Allow CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def update_last_request_time(request: Request, call_next):
    # Update last request time for non-health/non-static routes
    path = request.url.path
    # We exclude /health and /static paths from resetting the idle timer
    # as Backend 1 polls /health to check service availability.
    if path != "/health" and not path.startswith("/static"):
        global LAST_REQUEST_TIME
        LAST_REQUEST_TIME = time.time()
    response = await call_next(request)
    return response

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# Mount static files (style.css, index.html)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
async def get_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.get("/health")
def health():
    return {"status": "running"}

@app.get("/api/info")
def get_info():
    return {
        "pid": os.getpid(),
        "platform": f"{platform.system()} {platform.release()}",
        "uptime_seconds": int(time.time() - START_TIME)
    }

# Record start time for uptime statistics
START_TIME = time.time()

@app.post("/shutdown")
async def shutdown():
    async def stop_server():
        await asyncio.sleep(0.5)
        # Terminate backend 2 process
        os._exit(0)
    
    asyncio.create_task(stop_server())
    return {"message": "Backend 2 shutdown initiated"}

if __name__ == "__main__":
    # pyrefly: ignore [missing-import]
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)


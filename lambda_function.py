import os
import time
import json
import boto3

def lambda_handler(event, context):
    """
    AWS Lambda function that:
    1. Checks the health of the Application Load Balancer (ALB) Target Group.
    2. If there are no healthy targets, scales the Auto Scaling Group (ASG) from 0 to 1.
    3. Polls the Target Group health until the backend container becomes healthy.
    4. Returns a success response once the target is healthy, or a starting/timeout response.
    """
    asg_name = os.environ.get("ASG_NAME")
    target_group_arn = os.environ.get("TARGET_GROUP_ARN")
    alb_dns = os.environ.get("ALB_DNS")
    
    if not asg_name or not target_group_arn:
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({
                "status": "error",
                "message": "Missing environment variables: ASG_NAME and TARGET_GROUP_ARN must be set."
            })
        }
    
    elbv2 = boto3.client("elbv2")
    autoscaling = boto3.client("autoscaling")
    
    # 1. Check Target Group Health
    try:
        health_resp = elbv2.describe_target_health(TargetGroupArn=target_group_arn)
        target_health_descriptions = health_resp.get("TargetHealthDescriptions", [])
    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({
                "status": "error",
                "message": f"Failed to describe target health: {str(e)}"
            })
        }
        
    healthy_targets = [
        t for t in target_health_descriptions 
        if t.get("TargetHealth", {}).get("State") == "healthy"
    ]
    
    if healthy_targets:
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({
                "status": "healthy",
                "message": "Backend is already running and healthy.",
                "alb_dns": alb_dns
            })
        }
        
    # 2. No healthy target found. Scale ASG (0 -> 1)
    try:
        asg_resp = autoscaling.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])
        asgs = asg_resp.get("AutoScalingGroups", [])
        if not asgs:
            return {
                "statusCode": 404,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*"
                },
                "body": json.dumps({
                    "status": "error",
                    "message": f"Auto Scaling Group {asg_name} not found."
                })
            }
        
        asg = asgs[0]
        desired_capacity = asg.get("DesiredCapacity", 0)
        
        if desired_capacity == 0:
            print(f"Desired capacity is 0. Scaling ASG {asg_name} to 1...")
            autoscaling.set_desired_capacity(
                AutoScalingGroupName=asg_name,
                DesiredCapacity=1,
                HonorCooldown=False
            )
        else:
            print(f"ASG {asg_name} desired capacity is already {desired_capacity}. Waiting for target to register and become healthy...")
            
    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({
                "status": "error",
                "message": f"Failed to inspect or scale Auto Scaling Group: {str(e)}"
            })
        }
        
    # 3. Wait until instance becomes healthy
    # Lambda execution timeout is configured for up to 300s.
    # We will poll for up to 260 seconds to respond safely before a Lambda timeout.
    start_time = time.time()
    max_wait_seconds = 260
    poll_interval = 8
    
    while time.time() - start_time < max_wait_seconds:
        print(f"Polling target group health ({int(time.time() - start_time)}s elapsed)...")
        try:
            health_resp = elbv2.describe_target_health(TargetGroupArn=target_group_arn)
            target_health_descriptions = health_resp.get("TargetHealthDescriptions", [])
            
            healthy_targets = [
                t for t in target_health_descriptions 
                if t.get("TargetHealth", {}).get("State") == "healthy"
            ]
            
            if healthy_targets:
                print("Success: Target registered and healthy!")
                return {
                    "statusCode": 200,
                    "headers": {
                        "Content-Type": "application/json",
                        "Access-Control-Allow-Origin": "*"
                    },
                    "body": json.dumps({
                        "status": "healthy",
                        "message": "Backend successfully started and target is now healthy.",
                        "alb_dns": alb_dns
                    })
                }
                
            if target_health_descriptions:
                states = [t.get("TargetHealth", {}).get("State") for t in target_health_descriptions]
                print(f"Targets detected, but not yet healthy. Current states: {states}")
            else:
                print("No targets registered yet in the target group.")
                
        except Exception as e:
            print(f"Error checking target health: {str(e)}")
            
        time.sleep(poll_interval)
        
    # 4. Timeout fallback response
    return {
        "statusCode": 202,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps({
            "status": "starting",
            "message": "Auto Scaling Group scaled up, but the backend target is still registering or launching. Please check status again shortly.",
            "alb_dns": alb_dns
        })
    }

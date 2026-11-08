#!/usr/bin/env bash
# Start what pause-platform.sh stopped. The NAT gateway, load balancer and
# EKS cluster are not restarted here: recreate them from Posts 4, 11 and 12.
set -uo pipefail
export AWS_DEFAULT_REGION=${REGION:-us-east-1}

echo "== RDS: start plat-meta"
aws rds start-db-instance --db-instance-identifier plat-meta \
  --query 'DBInstance.DBInstanceStatus' --output text

echo "== EC2: start instances tagged project=plat"
IDS=$(aws ec2 describe-instances \
  --filters Name=tag:project,Values=plat Name=instance-state-name,Values=stopped \
  --query 'Reservations[].Instances[].InstanceId' --output text)
if [ -n "$IDS" ]; then aws ec2 start-instances --instance-ids $IDS --query 'StartingInstances[].InstanceId' --output text; else echo "   none stopped"; fi

echo "== Wait for the database, then scale the API back up"
aws rds wait db-instance-available --db-instance-identifier plat-meta
aws ecs update-service --cluster plat-cluster --service plat-api-svc \
  --desired-count 2 --query 'service.desiredCount' --output text

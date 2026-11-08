#!/usr/bin/env bash
# Stop the billable parts of the Platform Lab that are safe to stop, and
# list the ones that must be deleted or stopped by hand.
set -uo pipefail
REGION=${REGION:-us-east-1}
export AWS_DEFAULT_REGION=$REGION

echo "== ECS: scale plat-api-svc to 0"
aws ecs update-service --cluster plat-cluster --service plat-api-svc \
  --desired-count 0 --query 'service.desiredCount' --output text 2>&1 | sed 's/^/   desired=/'

echo "== RDS: stop plat-meta (AWS restarts it after 7 days)"
aws rds stop-db-instance --db-instance-identifier plat-meta \
  --query 'DBInstance.DBInstanceStatus' --output text 2>&1 | sed 's/^/   status=/'

echo "== EC2: stop running instances tagged project=plat"
IDS=$(aws ec2 describe-instances \
  --filters Name=tag:project,Values=plat Name=instance-state-name,Values=running \
  --query 'Reservations[].Instances[].InstanceId' --output text)
if [ -n "$IDS" ]; then aws ec2 stop-instances --instance-ids $IDS --query 'StoppingInstances[].InstanceId' --output text; else echo "   none running"; fi

echo "== SageMaker: delete endpoint plat-churn if it exists"
if aws sagemaker describe-endpoint --endpoint-name plat-churn >/dev/null 2>&1; then
  aws sagemaker delete-endpoint --endpoint-name plat-churn && echo "   deleted"
else
  echo "   not present"
fi

echo
echo "== STILL BILLING: delete these by hand if you are done for the day"
echo "-- NAT gateways (available):"
aws ec2 describe-nat-gateways --filter Name=state,Values=available \
  --query 'NatGateways[].[NatGatewayId,Tags[?Key==`Name`]|[0].Value]' --output text
echo "-- Load balancers:"
aws elbv2 describe-load-balancers --query 'LoadBalancers[].[LoadBalancerName,Type]' --output text
echo "-- EKS clusters:"
aws eks list-clusters --query 'clusters' --output text
echo "-- Unattached Elastic IPs:"
aws ec2 describe-addresses --query 'Addresses[?AssociationId==null].[PublicIp,AllocationId]' --output text
echo "-- Studio spaces still running (stop in the Studio console):"
aws sagemaker list-apps --query 'Apps[?Status==`InService`].[SpaceName,AppType]' --output text

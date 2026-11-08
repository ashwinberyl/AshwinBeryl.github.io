import os

import boto3

ddb = boto3.client("dynamodb")
sns = boto3.client("sns")
TOPIC = os.environ["ALERT_TOPIC_ARN"]


def handler(event, context):
    jobs, rows, token = 0, 0, None
    while True:
        kwargs = dict(
            TableName="plat-jobs",
            IndexName="status-created_idx",
            KeyConditionExpression="#s = :d",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":d": {"S": "DONE"}},
        )
        if token:
            kwargs["ExclusiveStartKey"] = token
        page = ddb.query(**kwargs)
        for item in page["Items"]:
            jobs += 1
            rows += int(item.get("rows", {}).get("N", "0"))
        token = page.get("LastEvaluatedKey")
        if not token:
            break

    message = f"Platform report: {jobs} completed jobs, {rows} rows ingested in total."
    sns.publish(TopicArn=TOPIC, Subject="plat report", Message=message)
    return {"jobs": jobs, "rows": rows}

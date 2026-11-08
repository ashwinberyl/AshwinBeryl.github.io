import hashlib
import json
import logging
import os
import urllib.parse
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger()
log.setLevel(logging.INFO)

# Created once per execution environment, reused while it stays warm.
s3 = boto3.client("s3")
table = boto3.resource("dynamodb").Table(os.environ["JOBS_TABLE"])


def extract(record):
    """Yield (bucket, key) pairs from an S3 notification, whether it arrived
    directly from S3 or wrapped in an SNS envelope inside an SQS message."""
    if record.get("eventSource") == "aws:sqs":
        body = json.loads(record["body"])
        if "Message" in body:                     # SNS envelope
            body = json.loads(body["Message"])
        for inner in body.get("Records", []):
            yield from extract(inner)
    elif "s3" in record:
        yield (record["s3"]["bucket"]["name"],
               urllib.parse.unquote_plus(record["s3"]["object"]["key"]))


def ingest(bucket, key):
    if not (key.startswith("raw/") and key.endswith(".csv")):
        log.info("skipping %s", key)
        return

    head = s3.head_object(Bucket=bucket, Key=key)
    etag = head["ETag"].strip('"')
    # One object version always gives the same job id, so a redelivered
    # notification for it is harmless.
    job_id = "ingest-" + hashlib.sha1(f"{bucket}/{key}/{etag}".encode()).hexdigest()[:12]

    body = s3.get_object(Bucket=bucket, Key=key)["Body"]
    rows = sum(1 for _ in body.iter_lines()) - 1       # minus the header line

    item = {
        "job_id": job_id,
        "status": "DONE",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rows": rows,
        "s3_key": key,
        "bytes": head["ContentLength"],
    }
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(job_id)")
        log.info("recorded %s rows=%d key=%s", job_id, rows, key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            log.info("duplicate delivery ignored job=%s key=%s", job_id, key)
        else:
            raise


def handler(event, context):
    failures = []
    for record in event.get("Records", []):
        try:
            for bucket, key in extract(record):
                ingest(bucket, key)
        except Exception:
            log.exception("record failed")
            if record.get("eventSource") == "aws:sqs":
                failures.append({"itemIdentifier": record["messageId"]})  # retry only this one
            else:
                raise                                                      # let async retry handle it
    return {"batchItemFailures": failures}

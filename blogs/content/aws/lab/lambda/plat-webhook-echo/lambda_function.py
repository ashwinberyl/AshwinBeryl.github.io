import base64
import hashlib
import hmac
import json
import logging
import os

import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)

sm = boto3.client("secretsmanager")
_secret = None


def secret():
    global _secret
    if _secret is None:
        _secret = sm.get_secret_value(SecretId=os.environ["SECRET_ID"])["SecretString"].encode()
    return _secret


def handler(event, context):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    raw = event.get("body") or ""
    body = base64.b64decode(raw) if event.get("isBase64Encoded") else raw.encode()

    sent = headers.get("x-hub-signature-256", "")
    expected = "sha256=" + hmac.new(secret(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sent, expected):
        log.warning("rejected delivery=%s", headers.get("x-github-delivery"))
        return {"statusCode": 401, "body": "invalid signature"}

    kind = headers.get("x-github-event", "unknown")
    delivery = headers.get("x-github-delivery")
    if kind == "ping":
        log.info(json.dumps({"event": "ping", "delivery": delivery}))
        return {"statusCode": 200, "body": "pong"}

    payload = json.loads(body)
    if kind == "push":
        log.info(json.dumps({
            "event": "push",
            "delivery": delivery,
            "repo": payload["repository"]["full_name"],
            "ref": payload["ref"],
            "head": payload["after"][:7],
            "commits": len(payload.get("commits", [])),
            "pusher": payload["pusher"]["name"],
        }))
    else:
        log.info(json.dumps({"event": kind, "delivery": delivery, "action": payload.get("action")}))
    return {"statusCode": 202, "body": "accepted"}

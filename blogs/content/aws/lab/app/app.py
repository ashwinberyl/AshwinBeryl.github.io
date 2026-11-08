import json
import os
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import boto3

VERSION = os.environ.get("APP_VERSION", "1.0.0")
REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
BUCKET = os.environ.get("DATA_BUCKET")
JOBS_TABLE = os.environ.get("JOBS_TABLE")
DB_HOST = os.environ.get("DB_HOST")
DB_NAME = os.environ.get("DB_NAME", "platmeta")
DB_SECRET_ARN = os.environ.get("DB_SECRET_ARN")

s3 = boto3.client("s3", region_name=REGION)
ddb = boto3.resource("dynamodb", region_name=REGION)
secrets = boto3.client("secretsmanager", region_name=REGION)


def log(**fields):
    print(json.dumps({"ts": time.time(), **fields}), flush=True)


def db_rows():
    import pg8000.native  # imported lazily so the app starts without a database

    secret = json.loads(secrets.get_secret_value(SecretId=DB_SECRET_ARN)["SecretString"])
    con = pg8000.native.Connection(
        user=secret["username"],
        password=secret["password"],
        host=DB_HOST,
        database=DB_NAME,
        ssl_context=True,
        timeout=5,
    )
    try:
        rows = con.run("SELECT id, name, s3_key, row_count FROM datasets ORDER BY id")
    finally:
        con.close()
    return [{"id": r[0], "name": r[1], "s3_key": r[2], "row_count": r[3]} for r in rows]


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        data = json.dumps(body, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        try:
            if path == "/health":
                return self._send(200, {"status": "ok"})
            if path == "/":
                return self._send(200, {"app": "plat-api", "version": VERSION,
                                        "host": socket.gethostname()})
            if path == "/data":
                if not BUCKET:
                    return self._send(503, {"error": "DATA_BUCKET not set"})
                resp = s3.list_objects_v2(Bucket=BUCKET, Prefix="raw/", MaxKeys=100)
                keys = [o["Key"] for o in resp.get("Contents", [])]
                return self._send(200, {"bucket": BUCKET, "raw_objects": keys})
            if path.startswith("/jobs/"):
                if not JOBS_TABLE:
                    return self._send(503, {"error": "JOBS_TABLE not set"})
                job_id = path[len("/jobs/"):]
                item = ddb.Table(JOBS_TABLE).get_item(Key={"job_id": job_id}).get("Item")
                return self._send(200 if item else 404, item or {"error": "not found"})
            if path == "/datasets":
                if not (DB_HOST and DB_SECRET_ARN):
                    return self._send(503, {"error": "database not configured"})
                return self._send(200, db_rows())
            return self._send(404, {"error": "no such route"})
        except Exception as exc:  # report the class, log the detail
            log(level="error", path=path, error=str(exc))
            return self._send(502, {"error": type(exc).__name__})

    def log_message(self, fmt, *args):
        log(level="info", client=self.client_address[0], request=fmt % args)


if __name__ == "__main__":
    log(level="info", msg="starting", version=VERSION)
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()

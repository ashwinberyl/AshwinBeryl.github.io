import json
import os

import joblib
import numpy as np
from flask import Flask, Response, request

MODEL_DIR = os.environ.get("MODEL_DIR", "/opt/ml/model")
FEATURE_COUNT = 4  # sessions_7d, minutes_7d, tickets_30d, plan_pro

app = Flask(__name__)
model = joblib.load(os.path.join(MODEL_DIR, "model.joblib"))  # fails loudly if missing


@app.get("/ping")
def ping():
    return Response("\n", status=200)


@app.post("/invocations")
def invocations():
    content_type = request.content_type or ""
    body = request.get_data(as_text=True)
    try:
        if content_type.startswith("text/csv"):
            rows = [[float(v) for v in line.split(",")]
                    for line in body.strip().splitlines() if line.strip()]
        elif content_type.startswith("application/json"):
            rows = json.loads(body)["instances"]
        else:
            return Response(f"unsupported content type: {content_type}", status=415)
        x = np.array(rows, dtype=float)
        if x.ndim != 2 or x.shape[1] != FEATURE_COUNT:
            return Response(f"expected {FEATURE_COUNT} features per row", status=400)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        return Response(f"bad request: {exc}", status=400)

    proba = model.predict_proba(x)[:, 1]
    return Response("\n".join(f"{p:.6f}" for p in proba), mimetype="text/csv")

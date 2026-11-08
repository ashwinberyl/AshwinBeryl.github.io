import json
import os
import sys
import traceback

import joblib
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

PREFIX = "/opt/ml"
HYPERPARAMETERS = f"{PREFIX}/input/config/hyperparameters.json"
FEATURES = ["sessions_7d", "minutes_7d", "tickets_30d", "plan_pro"]


def load(channel):
    df = pd.read_csv(f"{PREFIX}/input/data/{channel}/{channel}.csv", header=None)
    return df.iloc[:, 1:].to_numpy(), df.iloc[:, 0].to_numpy()  # label is column 0


def main():
    hp = json.load(open(HYPERPARAMETERS)) if os.path.exists(HYPERPARAMETERS) else {}
    c = float(hp.get("C", "1.0"))               # hyperparameters are strings
    max_iter = int(hp.get("max_iter", "200"))

    x_train, y_train = load("train")
    x_val, y_val = load("validation")

    model = make_pipeline(StandardScaler(), LogisticRegression(C=c, max_iter=max_iter))
    model.fit(x_train, y_train)

    proba = model.predict_proba(x_val)[:, 1]
    accuracy = accuracy_score(y_val, proba >= 0.5)
    auc = roc_auc_score(y_val, proba)
    baseline = max(y_val.mean(), 1 - y_val.mean())

    print(f"rows train={len(y_train)} validation={len(y_val)} baseline_accuracy={baseline:.4f}")
    print(f"validation_accuracy={accuracy:.4f}")
    print(f"validation_auc={auc:.4f}")

    os.makedirs(f"{PREFIX}/model", exist_ok=True)
    joblib.dump(model, f"{PREFIX}/model/model.joblib")
    with open(f"{PREFIX}/model/features.json", "w") as f:
        json.dump({"features": FEATURES}, f)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        os.makedirs(f"{PREFIX}/output", exist_ok=True)
        with open(f"{PREFIX}/output/failure", "w") as f:
            f.write(traceback.format_exc())
        traceback.print_exc()
        sys.exit(1)

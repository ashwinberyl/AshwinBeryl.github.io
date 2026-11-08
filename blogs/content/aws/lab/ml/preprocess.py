import os

import pandas as pd

INPUT = "/opt/ml/processing/input/events.csv"
OUT = "/opt/ml/processing"


def main():
    df = pd.read_csv(INPUT)
    rows_in = len(df)

    # Replayed events are exact copies, so they share an event_id.
    df = df.drop_duplicates(subset="event_id")
    unique = len(df)

    missing = int(df["minutes_7d"].isna().sum())
    df["minutes_7d"] = df["minutes_7d"].fillna(df["minutes_7d"].median())
    df["plan_pro"] = (df["plan"] == "pro").astype(int)

    # Label first, no header: the layout the training step expects.
    # user_id and event_id are identifiers, not features, so they are dropped.
    cols = ["churned", "sessions_7d", "minutes_7d", "tickets_30d", "plan_pro"]
    data = df[cols].sample(frac=1.0, random_state=42).reset_index(drop=True)

    cut = int(len(data) * 0.8)
    train, validation = data.iloc[:cut], data.iloc[cut:]

    for name, part in (("train", train), ("validation", validation)):
        os.makedirs(f"{OUT}/{name}", exist_ok=True)
        part.to_csv(f"{OUT}/{name}/{name}.csv", header=False, index=False)

    print(
        f"rows_in={rows_in} unique={unique} missing_minutes={missing} "
        f"train={len(train)} validation={len(validation)} "
        f"churn_rate={data['churned'].mean():.3f}"
    )


if __name__ == "__main__":
    main()

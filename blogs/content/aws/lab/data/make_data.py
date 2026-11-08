import csv
import math
import random

random.seed(42)
ROWS = 5000

with open("events.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["event_id", "user_id", "plan", "sessions_7d",
                "minutes_7d", "tickets_30d", "churned"])
    written = []
    for i in range(1, ROWS + 1):
        plan = random.choices(["free", "pro"], weights=[0.7, 0.3])[0]
        sessions = max(0, int(random.gauss(8 if plan == "pro" else 4, 3)))
        minutes = round(max(0.0, random.gauss(sessions * 14, 25)), 1)
        tickets = max(0, int(random.gauss(1, 1.2)))
        logit = 0.6 + 0.5 * tickets - 0.18 * sessions - (0.8 if plan == "pro" else 0)
        churned = 1 if random.random() < 1 / (1 + math.exp(-logit)) else 0
        # a few rows have no minutes recorded
        minutes_out = "" if random.random() < 0.03 else minutes
        row = [f"e{i:05d}", f"u{random.randint(1, 2000):04d}", plan,
               sessions, minutes_out, tickets, churned]
        w.writerow(row)
        written.append(row)
    # replayed events: exact duplicates of earlier rows
    for row in random.sample(written, 50):
        w.writerow(row)

print("wrote events.csv")

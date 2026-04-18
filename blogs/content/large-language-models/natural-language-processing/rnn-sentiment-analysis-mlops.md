---
title: "End-to-End RNN Sentiment Analysis — From Model to Production MLOps"
date: 2026-03-28
tags: [rnn, sentiment-analysis, mlops, pytorch, dvc, mlflow, fastapi, docker, terraform, github-actions, evidently, ci-cd, data-drift]
description: A complete walkthrough of building an end-to-end MLOps pipeline for RNN-based sentiment analysis — covering project architecture, PyTorch model code, DVC data versioning, MLflow experiment tracking, FastAPI serving, Docker containerization, Terraform infrastructure, CI/CD/CT automation, and Evidently data drift monitoring.
---

# End-to-End RNN Sentiment Analysis — From Model to Production 🚀

In our [previous post](content/large-language-models/natural-language-processing/rnn.md), we explored the theory behind Recurrent Neural Networks — how they process sequences, the math of forward propagation and BPTT, and the vanishing gradient problem that ultimately limits vanilla RNNs. And in our [Fake News Classifier post](content/large-language-models/natural-language-processing/fake-news-classifier-lstm.md), we built a working LSTM model in a Colab notebook.

But building a model in a notebook is only **10% of real-world ML**. The other 90%? That's the engineering — versioning data, tracking experiments, containerizing the model, deploying it behind an API, automating retraining when data drifts, and orchestrating the entire pipeline with CI/CD.

In this post, we're walking through my **[RNN Sentiment Analysis repository](https://github.com/ashwinberyl/rnn)** — a production-grade MLOps pipeline that takes a vanilla Bidirectional RNN from raw data to a live, self-healing system.

![End-to-End RNN MLOps Pipeline — From Raw Data to Automated Deployment](content/large-language-models/natural-language-processing/images/rnn_mlops_pipeline_overview.png)

---

## What Are We Building? 🎯

A **restaurant review sentiment classifier** — you give it a text review, and it predicts whether the sentiment is **positive** or **negative**. Simple on the surface, but the infrastructure powering it is anything but simple.

Here's the full stack:

| Component | Tool | Purpose |
|---|---|---|
| **Model** | PyTorch `nn.RNN` | Bidirectional vanilla RNN for binary classification |
| **Data Versioning** | DVC + LocalStack S3 | Track datasets and model weights like code |
| **Experiment Tracking** | MLflow | Log hyperparameters, metrics, and artifacts |
| **API Serving** | FastAPI + Uvicorn | REST endpoint for real-time predictions |
| **Containerization** | Docker (multi-stage) | Lightweight, reproducible deployment |
| **Infrastructure** | Terraform + LocalStack | Infrastructure-as-Code for S3 buckets |
| **Orchestration** | Docker Compose | Spin up LocalStack + MLflow + API together |
| **CI/CD/CT** | GitHub Actions | Automated lint, test, deploy, and retrain |
| **Drift Detection** | Evidently | Statistical drift monitoring for retraining |

> **Why LocalStack?** We simulate AWS S3 locally using [LocalStack](https://localstack.cloud/) instead of paying for real cloud resources. The Terraform code, S3 paths, and DVC configuration are all *production-identical* — swap out the endpoint URL and everything works on real AWS without changing a single line of application code.

---

## Project Structure — The Blueprint 📁

Before diving into code, let's understand how the repository is organized. Every file serves a specific purpose in the MLOps pipeline:

![Repository Structure — Color-Coded by Purpose](content/large-language-models/natural-language-processing/images/rnn_repo_structure.png)

```
rnn/
├── .dvc/                  # DVC config — S3 remote for data/model versioning
├── .github/workflows/     # CI/CD/CT automation (ci.yml, cd.yml, ct.yml)
├── data/
│   ├── raw/               # Original dataset (reviews.csv) — tracked by DVC
│   └── processed/         # Tokenized train/test splits + vocab.json
├── infra/                 # Terraform IaC — provisions S3 buckets on LocalStack
├── models/                # Saved PyTorch weights (sentiment_rnn.pt)
├── src/
│   ├── train.py           # Data prep + vocabulary building + RNN training loop
│   ├── evaluate.py        # Model evaluation + metrics + quality gate
│   ├── predict.py         # FastAPI inference server
│   └── data_drift.py      # Evidently drift detection (triggers retraining)
├── tests/
│   ├── test_model.py      # Tests: model architecture, forward pass, gradients
│   └── test_preprocessing.py  # Tests: vocab building, tokenization, padding
├── Dockerfile             # Multi-stage build → compressed CPU-only API image
├── docker-compose.yml     # Orchestrates LocalStack + MLflow + API
├── dvc.yaml               # Reproducible pipeline: prepare → train → evaluate
├── dvc.lock               # Deterministic hashes tying code + data + model
├── params.yaml            # Centralized hyperparameters + eval thresholds
├── pyproject.toml         # Ruff / Black / Pytest configuration
└── requirements.txt       # Pinned Python dependencies
```

### How the Pieces Connect

Think of the repository as three concentric layers:

| Layer | Files | What It Does |
|---|---|---|
| **Inner — ML Core** | `src/train.py`, `src/evaluate.py`, `params.yaml` | The actual data science — preprocessing, model architecture, training loop, evaluation metrics |
| **Middle — MLOps** | `dvc.yaml`, `dvc.lock`, `.dvc/`, `src/data_drift.py`, `src/predict.py` | Versioning, reproducibility, drift detection, and serving |
| **Outer — DevOps** | `Dockerfile`, `docker-compose.yml`, `infra/`, `.github/workflows/` | Containerization, infrastructure, and CI/CD/CT automation |

> **Key insight:** The ML code stays clean and focused. It doesn't know or care about Docker, Terraform, or GitHub Actions. The MLOps and DevOps layers wrap around it, providing reliability and automation without polluting the model code.

---

## The Model — Bidirectional Vanilla RNN 🧠

Let's start at the core — the neural network itself. We use a **Bidirectional RNN** built in PyTorch. This means the network processes each review in **both directions**: left-to-right (capturing forward context) and right-to-left (capturing backward context). The final hidden states from both directions are concatenated, giving the classifier a complete view of the sentence.

![Bidirectional RNN Architecture — Forward and Backward Context](content/large-language-models/natural-language-processing/images/bidirectional_rnn_sentiment.png)

### The Architecture (`src/train.py`)

```python
class SentimentRNN(nn.Module):
    """Bidirectional vanilla RNN for binary sentiment classification."""

    def __init__(
        self,
        vocab_size: int,
        embedding_dim: int,
        hidden_dim: int,
        output_dim: int = 1,
        n_layers: int = 2,
        dropout: float = 0.3,
        pad_idx: int = 0,
    ):
        super().__init__()
        self.embedding = nn.Embedding(vocab_size, embedding_dim, padding_idx=pad_idx)
        self.rnn = nn.RNN(
            embedding_dim,
            hidden_dim,
            num_layers=n_layers,
            nonlinearity="tanh",
            bidirectional=True,
            dropout=dropout if n_layers > 1 else 0.0,
            batch_first=True,
        )
        self.fc = nn.Linear(hidden_dim * 2, output_dim)
        self.dropout = nn.Dropout(dropout)

    def forward(self, text: torch.Tensor) -> torch.Tensor:
        embedded = self.dropout(self.embedding(text))
        _, hidden = self.rnn(embedded)
        # Concatenate final forward and backward hidden states
        hidden = torch.cat((hidden[-2, :, :], hidden[-1, :, :]), dim=1)
        return self.fc(self.dropout(hidden))
```

### Breaking Down Every Layer

| Layer | Code | What It Does |
|---|---|---|
| **Embedding** | `nn.Embedding(vocab_size, embedding_dim, padding_idx=pad_idx)` | Converts each word index into a dense 128-dimensional vector. `padding_idx=0` ensures the `<PAD>` token's embedding stays at zero and doesn't contribute to learning. |
| **RNN** | `nn.RNN(..., bidirectional=True, num_layers=2)` | A 2-layer bidirectional RNN. Each layer processes the sequence in both directions. Uses `tanh` activation (the standard for RNNs, as we covered in our [RNN theory post](content/large-language-models/natural-language-processing/rnn.md)). |
| **Dropout** | `nn.Dropout(0.3)` | Applied after embedding and before the final layer — prevents overfitting by randomly disabling 30% of neurons during training. Same concept we used in our [ANN blog](content/large-language-models/deep-learning/your-first-ann.md). |
| **Fully Connected** | `nn.Linear(hidden_dim * 2, 1)` | Maps the concatenated forward+backward hidden state (256×2 = 512 dims) down to a single output logit. |

> **Why `hidden_dim * 2`?** Because `bidirectional=True` doubles the hidden state. The forward RNN produces a 256-dim vector encoding left-to-right context, and the backward RNN produces another 256-dim vector encoding right-to-left context. We concatenate them: 256 + 256 = 512 dimensions fed into the final linear layer.

> **Why `BCEWithLogitsLoss` instead of `BCELoss`?** The model outputs raw logits (no sigmoid in the forward pass). `BCEWithLogitsLoss` combines sigmoid + binary cross-entropy in a single numerically stable operation. During inference, we apply `torch.sigmoid()` manually to get probabilities.

### The Hyperparameters (`params.yaml`)

All hyperparameters are externalized into a single YAML file — never hardcoded in scripts:

```yaml
train:
  epochs: 10
  learning_rate: 0.001
  batch_size: 64
  hidden_dim: 256
  embedding_dim: 128
  dropout: 0.3
  vocab_size: 10000
  max_seq_length: 200

evaluate:
  accuracy_threshold: 0.20
  f1_threshold: 0.20

drift:
  significance_level: 0.05
  reference_data: data/processed/train.csv
```

> **Why externalize hyperparameters?** DVC tracks `params.yaml` as a dependency. When you change `learning_rate` from 0.001 to 0.0005 and run `dvc repro`, DVC knows it needs to re-run the `train` stage (and everything downstream). No more "did I forget to retrain after changing the learning rate?" bugs.

---

## Data Preprocessing — Building the Vocabulary 📖

Before the RNN can process text, every word must become a number. The `train.py` script handles this in two functions:

### Step 1: Build Vocabulary

```python
def build_vocab(texts: list[str], max_size: int = 10000) -> dict[str, int]:
    """Build a word→index vocabulary from a list of texts."""
    from collections import Counter

    counter: Counter = Counter()
    for text in texts:
        counter.update(text.lower().split())
    vocab = {"<PAD>": 0, "<UNK>": 1}
    for word, _ in counter.most_common(max_size - 2):
        vocab[word] = len(vocab)
    return vocab
```

This scans all reviews, counts word frequencies, and keeps only the top 10,000 words (configurable via `params.yaml`). Two special tokens are reserved:
- **`<PAD>` (index 0):** Used to pad shorter sequences to a fixed length.
- **`<UNK>` (index 1):** Replaces any word not in our vocabulary.

### Step 2: Tokenize and Pad

```python
def tokenize_and_pad(texts: list[str], vocab: dict[str, int], max_len: int = 200) -> np.ndarray:
    """Convert texts to padded integer sequences."""
    unk_idx = vocab.get("<UNK>", 1)
    sequences = []
    for text in texts:
        tokens = [vocab.get(w, unk_idx) for w in text.lower().split()]
        if len(tokens) >= max_len:
            tokens = tokens[:max_len]
        else:
            tokens = tokens + [0] * (max_len - len(tokens))
        sequences.append(tokens)
    return np.array(sequences)
```

Every review is converted into a fixed-length integer sequence:
- **Short reviews** → padded with zeros (the `<PAD>` token)
- **Long reviews** → truncated to `max_seq_length` (200 words)

> **Why 200 words?** Most restaurant reviews are well under 200 words. Truncating at 200 captures the overwhelming majority of content without wasting compute on excessively long sequences. This is the same padding concept we covered in our [LSTM Fake News post](content/large-language-models/natural-language-processing/fake-news-classifier-lstm.md).

---

## The Training Loop — PyTorch + MLflow 🏋️

The training function loads the processed data, instantiates the model, and trains it with full experiment tracking:

```python
def train_model():
    params = load_params()["train"]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # Load processed data
    train_df = pd.read_csv(PROCESSED_DIR / "train.csv")
    labels = train_df.pop("label").values
    sequences = train_df.values

    dataset = ReviewDataset(sequences, labels)
    loader = DataLoader(dataset, batch_size=params["batch_size"], shuffle=True)

    # Initialize model
    model = SentimentRNN(
        vocab_size=params["vocab_size"],
        embedding_dim=params["embedding_dim"],
        hidden_dim=params["hidden_dim"],
        dropout=params["dropout"],
    ).to(device)

    criterion = nn.BCEWithLogitsLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=params["learning_rate"])

    # MLflow tracking
    mlflow.set_tracking_uri("http://localhost:5000")
    mlflow.set_experiment("rnn-sentiment-analysis")

    with mlflow.start_run(run_name="train"):
        mlflow.log_params(params)

        for epoch in range(params["epochs"]):
            model.train()
            epoch_loss, correct, total = 0.0, 0, 0

            for batch_seqs, batch_labels in loader:
                batch_seqs = batch_seqs.to(device)
                batch_labels = batch_labels.to(device)

                optimizer.zero_grad()
                predictions = model(batch_seqs).squeeze(1)
                loss = criterion(predictions, batch_labels)
                loss.backward()
                optimizer.step()

                epoch_loss += loss.item()
                predicted = (torch.sigmoid(predictions) >= 0.5).float()
                correct += (predicted == batch_labels).sum().item()
                total += batch_labels.size(0)

            train_acc = correct / total
            avg_loss = epoch_loss / len(loader)
            mlflow.log_metrics({"train_loss": avg_loss, "train_accuracy": train_acc}, step=epoch)

        # Save checkpoint
        torch.save(model.state_dict(), MODELS_DIR / "sentiment_rnn.pt")
        mlflow.log_artifact(str(MODELS_DIR / "sentiment_rnn.pt"))
```

### What MLflow Captures

Every training run automatically logs:
- **Parameters:** epochs, learning_rate, batch_size, hidden_dim, embedding_dim, dropout
- **Metrics:** train_loss and train_accuracy at every epoch
- **Artifacts:** The saved `.pt` model checkpoint

You can view all of this in the MLflow UI at `http://localhost:5000` — compare runs, chart loss curves, and reproduce any past experiment by checking out the corresponding code + data version.

---

## Model Evaluation — Metrics & Quality Gates 📊

After training, `evaluate.py` loads the checkpoint, runs inference on the test set, and computes comprehensive metrics:

```python
def evaluate():
    params = load_params()
    # ... load model and test data ...

    # Compute metrics
    accuracy = accuracy_score(all_labels, all_preds)
    f1 = f1_score(all_labels, all_preds, average="binary")
    precision = precision_score(all_labels, all_preds, average="binary")
    recall = recall_score(all_labels, all_preds, average="binary")

    metrics = {
        "accuracy": round(float(accuracy), 4),
        "f1_score": round(float(f1), 4),
        "precision": round(float(precision), 4),
        "recall": round(float(recall), 4),
    }

    # Quality gate — fail if metrics are below thresholds
    if accuracy < eval_params["accuracy_threshold"]:
        logger.warning("⚠ Accuracy %.4f is below threshold %.4f", accuracy, ...)

    if f1 < eval_params["f1_threshold"]:
        logger.warning("⚠ F1 score %.4f is below threshold %.4f", f1, ...)

    # Write metrics.json (consumed by DVC)
    with open(ROOT_DIR / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    # Save confusion matrix for DVC plots
    cm = confusion_matrix(all_labels, all_preds).tolist()
    with open(PLOTS_DIR / "confusion_matrix.json", "w") as f:
        json.dump({"confusion_matrix": {"labels": ["negative", "positive"], "matrix": cm}}, f)

    # Log everything to MLflow
    with mlflow.start_run(run_name="evaluate"):
        mlflow.log_metrics(metrics)
        mlflow.log_artifact(str(metrics_path))
```

The quality gate is critical — it checks if the model's accuracy and F1 score meet the thresholds defined in `params.yaml`. If they don't, the CI pipeline can block deployment. No subpar models reach production.

---

## DVC Pipeline — Reproducible ML ♻️

**DVC (Data Version Control)** turns our three scripts into a single, reproducible pipeline. Instead of running scripts manually and hoping you remembered the right order, you run one command: `dvc repro`.

![DVC Pipeline Stages — prepare → train → evaluate](content/large-language-models/natural-language-processing/images/dvc_pipeline_stages.png)

### The Pipeline Definition (`dvc.yaml`)

```yaml
stages:
  prepare_data:
    cmd: python -m src.train --stage prepare
    deps:
      - src/train.py
      - data/raw/
    outs:
      - data/processed/train.csv
      - data/processed/test.csv

  train:
    cmd: python -m src.train --stage train
    deps:
      - src/train.py
      - data/processed/train.csv
    outs:
      - models/sentiment_rnn.pt
    params:
      - train.epochs
      - train.learning_rate
      - train.batch_size
      - train.hidden_dim
      - train.embedding_dim

  evaluate:
    cmd: python -m src.evaluate
    deps:
      - src/evaluate.py
      - models/sentiment_rnn.pt
      - data/processed/test.csv
    params:
      - evaluate.accuracy_threshold
      - evaluate.f1_threshold
    metrics:
      - metrics.json:
          cache: false
    plots:
      - plots/confusion_matrix.json:
          cache: false
```

### How DVC Makes This Powerful

Each stage declares its **dependencies** (`deps`), **outputs** (`outs`), and referenced **parameters** (`params`). DVC uses MD5 hashes to track all of these in `dvc.lock`. Here's what happens:

| Scenario | What DVC Does |
|---|---|
| You change `data/raw/reviews.csv` | Re-runs `prepare_data` → `train` → `evaluate` (full pipeline) |
| You change `learning_rate` in `params.yaml` | Re-runs `train` → `evaluate` (skips `prepare_data`) |
| You change `accuracy_threshold` in `params.yaml` | Re-runs only `evaluate` (model hasn't changed) |
| You change nothing | **Skips everything** — "Pipeline is up to date" |

> **DVC + S3 (LocalStack):** The `.dvc/config` file points to a LocalStack S3 bucket as the remote storage. Large files like `reviews.csv` and `sentiment_rnn.pt` are pushed to S3 via `dvc push` and pulled on any machine with `dvc pull`. Git tracks only the lightweight hash files — never the raw data.

```
[core]
    remote = localstack-s3

['remote "localstack-s3"']
    url = s3://rnn-dvc-storage
    endpointurl = http://localhost:4566
```

---

## FastAPI — Serving Predictions 🌐

The trained model is served via a **FastAPI** REST API in `src/predict.py`:

```python
app = FastAPI(
    title="RNN Sentiment Analysis API",
    description="Predict sentiment of restaurant reviews using a bidirectional vanilla RNN.",
    version="0.1.0",
)

class PredictRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Restaurant review text")

class PredictResponse(BaseModel):
    sentiment: str = Field(..., description="'positive' or 'negative'")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Model confidence score")

@app.on_event("startup")
async def load_model():
    """Load model weights and vocabulary at server startup."""
    global MODEL, VOCAB, MAX_SEQ_LENGTH
    # ... loads params, vocab.json, and sentiment_rnn.pt ...

@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint."""
    return HealthResponse(status="ok", model_loaded=MODEL is not None)

@app.post("/predict", response_model=PredictResponse)
async def predict(request: PredictRequest):
    """Predict sentiment for a given restaurant review."""
    if MODEL is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    # Tokenize & pad
    unk_idx = VOCAB.get("<UNK>", 1)
    tokens = [VOCAB.get(w, unk_idx) for w in request.text.lower().split()]
    # ... truncate or pad to max_seq_length ...

    input_tensor = torch.LongTensor([tokens]).to(DEVICE)

    with torch.no_grad():
        logit = MODEL(input_tensor).squeeze()
        probability = torch.sigmoid(logit).item()

    sentiment = "positive" if probability >= 0.5 else "negative"
    confidence = probability if sentiment == "positive" else 1 - probability

    return PredictResponse(sentiment=sentiment, confidence=round(confidence, 4))
```

### The Two Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Health check — returns whether the model is loaded. Used by Docker's `HEALTHCHECK`. |
| `/predict` | POST | Accepts a JSON body `{"text": "The food was incredible!"}` and returns `{"sentiment": "positive", "confidence": 0.9234}`. |

The server starts with `uvicorn src.predict:app --host 0.0.0.0 --port 8000` and automatically loads the model + vocabulary at startup.

> **Why FastAPI?** It's fast (async by default), auto-generates interactive Swagger docs at `/docs`, and validates request/response schemas with Pydantic. Perfect for ML model serving.

---

## Docker — Containerized Deployment 🐳

### Multi-Stage Dockerfile

The `Dockerfile` uses a **multi-stage build** to minimize image size:

```dockerfile
# ── Stage 1: Builder ──────────────────────────
FROM python:3.10-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends gcc g++
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt \
    --extra-index-url https://download.pytorch.org/whl/cpu

# ── Stage 2: Runtime ─────────────────────────
FROM python:3.10-slim AS runtime
COPY --from=builder /install /usr/local

RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser
WORKDIR /app

COPY params.yaml .
COPY src/ ./src/
COPY models/ ./models/
COPY data/processed/vocab.json ./data/processed/

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "src.predict:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Why Multi-Stage?

| Stage | What It Includes | Why |
|---|---|---|
| **Builder** | Full compiler toolchain (gcc, g++) + all pip packages | Needed to compile PyTorch and NumPy C extensions |
| **Runtime** | Only the compiled Python packages + our source code | No compiler, no build artifacts — image shrinks from >9GB to ~200MB |

The `--extra-index-url https://download.pytorch.org/whl/cpu` flag installs the **CPU-only** version of PyTorch, dramatically reducing image size since we don't need GPU drivers in a lightweight inference container.

> **Security:** The container runs as a non-root `appuser` — a best practice that limits the blast radius if the container is compromised.

### Docker Compose — Full Orchestration

![Docker Compose Orchestration — Three Interconnected Services](content/large-language-models/natural-language-processing/images/docker_compose_orchestration.png)

The `docker-compose.yml` spins up the entire development environment with one command:

```yaml
services:
  localstack:
    image: localstack/localstack:3.4
    ports: ["4566:4566"]
    environment:
      - SERVICES=s3

  mlflow:
    image: ghcr.io/mlflow/mlflow:v2.12.1
    ports: ["5000:5000"]
    command: mlflow server --host 0.0.0.0 --port 5000

  api:
    build: .
    ports: ["8000:8000"]
    depends_on:
      localstack:
        condition: service_healthy
```

```bash
docker-compose up -d          # Start everything
# LocalStack → http://localhost:4566
# MLflow UI  → http://localhost:5000
# API Docs   → http://localhost:8000/docs
```

---

## Infrastructure as Code — Terraform 🏗️

The `infra/` directory contains Terraform definitions that provision exactly three S3 buckets on LocalStack:

| Bucket | Purpose |
|---|---|
| `rnn-sentiment-dvc-storage` | DVC pushes large CSV files and model checkpoints here |
| `rnn-sentiment-model-artifacts` | Direct model backup and deployment source |
| `rnn-sentiment-drift-reports` | Evidently data drift JSON reports are archived here |

```bash
cd infra
terraform init
terraform apply -auto-approve
```

Terraform ensures infrastructure is **declarative** and **reproducible**. No clicking through AWS consoles, no "works on my machine" — anyone can recreate the exact same bucket layout by running `terraform apply`.

---

## Data Drift Detection — Evidently 📉

Models degrade over time as real-world data shifts away from the training distribution. The `src/data_drift.py` script uses [Evidently](https://evidentlyai.com/) to detect this:

```python
def detect_drift(reference_path=None, current_path=None) -> dict:
    """Run statistical data drift detection."""
    reference = pd.read_csv(reference_path)
    current = pd.read_csv(current_path)

    # Compare feature distributions using statistical tests
    report = Report(metrics=[DataDriftPreset(stattest_threshold=significance)])
    report.run(reference_data=reference, current_data=current)

    # Parse results
    drift_detected = drift_result.get("dataset_drift", False)
    drift_share = drift_result.get("share_of_drifted_columns", 0.0)

    # Upload report to S3 (LocalStack)
    s3.upload_file(str(report_path), drift_bucket, f"reports/{report_filename}")

    return {
        "drift_detected": drift_detected,
        "drift_share": round(drift_share, 4),
        "num_drifted": int(drift_share * len(reference.columns)),
    }
```

Evidently compares the **statistical distribution** of each feature in the current data against a reference dataset (our training data). If a statistically significant shift is detected (p-value below the `significance_level` from `params.yaml`), the system flags that drift occurred.

> **Why does drift matter?** Imagine training your sentiment model on 2024 restaurant reviews and then deploying it on 2026 reviews. New slang, new restaurant names, different writing styles — the data distribution has shifted. If we don't monitor and retrain, accuracy silently degrades. Drift detection is the **immune system** of your ML pipeline.

---

## CI/CD/CT — Automated Workflows 🔄

The `.github/workflows/` directory contains three GitHub Actions pipelines that automate the entire lifecycle:

![CI/CD/CT Workflows — Three Automated Pipelines](content/large-language-models/natural-language-processing/images/cicdct_workflows.png)

### CI: Continuous Integration (`ci.yml`)

**Trigger:** Every push or pull request to `main` or `develop`.

| Job | What It Does |
|---|---|
| **Lint & Test** | Runs `ruff check` (linting), `black --check` (formatting), and `pytest` (unit tests) |
| **Model Quality Gate** | Pulls data with DVC, runs `dvc repro evaluate`, checks metrics against thresholds in `params.yaml` |
| **Docker Smoke Test** | Builds the Docker image and verifies the container starts successfully |
| **Terraform Validate** | Runs `terraform init` + `terraform validate` + `terraform fmt -check` on the infra code |

```yaml
# Key CI steps:
- name: Lint with ruff
  run: ruff check src/ tests/ --output-format=github

- name: Check formatting with black
  run: black --check --diff src/ tests/

- name: Run unit tests
  run: pytest tests/ -v --tb=short --junitxml=test-results.xml
```

> **Why lint in CI?** As the team grows, consistent code style prevents merge conflicts and makes code reviews faster. Ruff catches bugs (like unused imports and potential security issues), while Black enforces formatting — no more "tabs vs spaces" debates.

---

### CD: Continuous Deployment (`cd.yml`)

**Trigger:** Creating a Git tag matching `v[0-9]+.[0-9]+.[0-9]+*` (e.g., `v1.0.0`).

| Job | What It Does |
|---|---|
| **Provision Infrastructure** | Spins up LocalStack in a service container and runs `terraform apply` |
| **Build & Deploy** | Builds the Docker image, then deploys via `docker-compose up -d api` |

```yaml
on:
  push:
    tags:
      - "v[0-9]+.[0-9]+.[0-9]+*"    # e.g. v1.2.3

  # ... later in the workflow:
  - name: Deploy Local Environment
    run: |
      docker-compose up -d api
      sleep 15
      curl -f http://localhost:8000/health || (docker logs rnn-api && exit 1)
      echo "✅ Successfully deployed API locally!"
```

> **Tag-driven deployment** means nobody can accidentally deploy by pushing to `main`. Deployment is a deliberate act — you create a version tag, and the pipeline handles the rest.

---

### CT: Continuous Training (`ct.yml`)

**Trigger:** Weekly cron schedule (`0 2 * * 0` — every Sunday at 2 AM) or manual dispatch.

This is the most interesting pipeline — it creates a **self-healing loop** for model quality:

| Job | What It Does |
|---|---|
| **1. Drift Detection** | Runs `src/data_drift.py` with Evidently, outputs `drift_detected` as a boolean |
| **2. Retrain** | If drift detected (or forced), retrains the model with `src/train.py` and evaluates with `src/evaluate.py` |
| **3. Promote** | If the new model beats the baseline, pushes a new Git tag → **automatically triggers CD** |

```yaml
retrain:
    if: needs.drift-detection.outputs.drift_detected == 'True' || inputs.force_retrain == true
    # ... retrain model ...

    - name: Compare new model vs baseline
      run: |
        python -c "
        baseline = json.load(open('baseline_metrics.json')).get('accuracy', 0)
        current = json.load(open('metrics.json')).get('accuracy', 0)
        improved = current > baseline
        "

promote:
    if: needs.retrain.outputs.model_improved == 'True'
    # Pushes a new tag → triggers CD pipeline automatically!
    - name: Commit & Push Tag
      run: |
        TAG="v0.0.0-retrain-${TIMESTAMP}"
        git tag -a "${TAG}" -m "Retrained model"
        git push origin "${TAG}"
```

> **The full loop:** Data drifts → Evidently detects it → Model is retrained → If it's better → New tag is pushed → CD deploys the improved model → No human intervention required. This is what **production-grade MLOps** looks like.

---

## Testing — Trust but Verify ✅

The `tests/` directory contains two test suites that validate both the model architecture and the data preprocessing:

### Model Tests (`test_model.py`)

```python
class TestSentimentRNN:
    def test_model_instantiation(self, model, model_params):
        """Model should instantiate with correct structure."""
        assert model.embedding.num_embeddings == model_params["vocab_size"]
        assert model.rnn.bidirectional is True

    def test_forward_pass_shape(self, model, sample_input):
        """Forward pass output should be (batch_size, 1)."""
        output = model(sample_input)
        assert output.shape == (sample_input.size(0), 1)

    def test_output_range_after_sigmoid(self, model, sample_input):
        """After sigmoid, all outputs should be in [0, 1]."""
        output = torch.sigmoid(model(sample_input))
        assert (output >= 0.0).all() and (output <= 1.0).all()

    def test_gradient_flow(self, model, sample_input):
        """Gradients should flow through all parameters."""
        output = model(sample_input).squeeze()
        loss = output.sum()
        loss.backward()
        for name, param in model.named_parameters():
            if param.requires_grad:
                assert param.grad is not None
                assert not torch.all(param.grad == 0)

    def test_different_sequence_lengths(self, model):
        """Model should handle variable-length sequences."""
        for seq_len in [10, 100, 200]:
            input_tensor = torch.randint(0, 1000, (2, seq_len))
            output = model(input_tensor)
            assert output.shape == (2, 1)
```

### Preprocessing Tests (`test_preprocessing.py`)

```python
class TestBuildVocab:
    def test_special_tokens_present(self, vocab):
        assert vocab["<PAD>"] == 0
        assert vocab["<UNK>"] == 1

    def test_vocab_size_limit(self, sample_texts):
        small_vocab = build_vocab(sample_texts, max_size=10)
        assert len(small_vocab) <= 10

    def test_case_insensitive(self, sample_texts):
        vocab = build_vocab(["Hello World", "hello world"], max_size=100)
        assert "hello" in vocab
        assert "Hello" not in vocab

class TestTokenizeAndPad:
    def test_padding(self, vocab):
        result = tokenize_and_pad(["hello"], vocab, max_len=10)
        assert result[0][-1] == 0  # Last position should be PAD

    def test_truncation(self, vocab):
        long_text = " ".join(["word"] * 100)
        result = tokenize_and_pad([long_text], vocab, max_len=10)
        assert result.shape == (1, 10)

    def test_unknown_tokens(self, vocab):
        result = tokenize_and_pad(["supercalifragilistic"], vocab, max_len=5)
        assert result[0][0] == vocab["<UNK>"]
```

> **Why test gradient flow?** This is a surprisingly common failure mode. If gradients don't flow through all parameters, some parts of the model aren't learning — and you won't notice until your accuracy plateaus mysteriously. The `test_gradient_flow` test catches this proactively.

---

## Running It Yourself 🏃

```bash
# 1. Create your environment
python -m venv venv
source venv/Scripts/activate   # or venv/bin/activate on Mac/Linux
pip install -r requirements.txt

# 2. Start infrastructure
docker-compose up -d localstack mlflow

# 3. Provision S3 buckets
cd infra && terraform init && terraform apply -auto-approve && cd ..

# 4. Train the model (add your data to data/raw/reviews.csv first)
dvc repro

# 5. Start the API
docker-compose up -d --build api

# 6. Test it!
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"text": "The pasta was absolutely divine, best meal ever!"}'
# → {"sentiment": "positive", "confidence": 0.9156}
```

---

## Recap — What We Built 🎓

| Concept | Tool | Blog Where We Covered the Theory |
|---|---|---|
| RNN Architecture (Bidirectional) | PyTorch `nn.RNN` | [Recurrent Neural Network](content/large-language-models/natural-language-processing/rnn.md) |
| Word Embeddings | `nn.Embedding` | [Word2Vec](content/large-language-models/natural-language-processing/word-embeddings-word2vec.md) |
| Sequence Padding | `tokenize_and_pad()` | [Fake News Classifier](content/large-language-models/natural-language-processing/fake-news-classifier-lstm.md) |
| Dropout Regularization | `nn.Dropout(0.3)` | [Your First ANN](content/large-language-models/deep-learning/your-first-ann.md) |
| Binary Cross-Entropy | `BCEWithLogitsLoss` | [Loss Functions](content/large-language-models/deep-learning/loss-functions.md) |
| Adam Optimizer | `torch.optim.Adam` | [Optimizers](content/large-language-models/deep-learning/optimizers.md) |
| Feature Scaling / Normalization | `build_vocab` + `tokenize_and_pad` | [Text Preprocessing](content/large-language-models/natural-language-processing/text-preprocessing.md) |
| Data Versioning | DVC + S3 | *This post* |
| Experiment Tracking | MLflow | *This post* |
| Model Serving | FastAPI | *This post* |
| Containerization | Docker (multi-stage) | *This post* |
| Infrastructure as Code | Terraform + LocalStack | *This post* |
| Automated Pipelines | GitHub Actions CI/CD/CT | *This post* |
| Data Drift Detection | Evidently | *This post* |

---

## Key Takeaways 💡

1. **Notebooks are prototypes, not products** — Your Colab notebook proves the model works; the production pipeline ensures it *keeps* working.
2. **Externalize everything** — Hyperparameters in `params.yaml`, infrastructure in Terraform, pipeline stages in DVC. Nothing hardcoded.
3. **Version data like code** — DVC + S3 gives you `git checkout` for your datasets. Every model can be traced back to the exact data it was trained on.
4. **Guard your quality gates** — Automated threshold checks in CI prevent bad models from reaching production.
5. **Monitor for drift** — Models decay silently. Evidently + CT catches degradation before your users do.
6. **Automate the loop** — Drift detected → Retrain → Evaluate → Deploy. The CT→CD chain makes your system self-healing.

---

## What's Next? 🚀

We've now seen the full lifecycle of a production ML system — from raw text to a deployed, self-monitoring API. But our model is still a **vanilla RNN** (albeit bidirectional). As we learned in our [theory post](content/large-language-models/natural-language-processing/rnn.md), vanilla RNNs suffer from vanishing gradients and struggle with long-range dependencies.

The natural next step? Fix the architecture itself. The **LSTM (Long Short-Term Memory)** introduces a "conveyor belt" cell state with **three learned gates** — forget, input, and output — that allow gradients to flow unchanged across hundreds of time steps. No more vanishing gradients, no more forgotten beginnings.

👉 **[Long Short-Term Memory (LSTM) — The Fix for Vanishing Gradients](content/large-language-models/natural-language-processing/lstm.md)**

---

Got questions or suggestions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*


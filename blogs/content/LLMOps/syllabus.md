# LLMOps Syllabus — From Notebook to Production at Scale

> This syllabus bridges the gap between **"making it work in a notebook"** and **"making it work for 10,000 users."** It focuses on **stability**, **scalability**, and **observability** — the three pillars of production-grade LLM systems.

---

## Pre-requisites

Before diving in, learners should be comfortable with:

- Python fundamentals (functions, classes, decorators)
- Basic ML/DL concepts (training, inference, fine-tuning)
- Git version control
- Familiarity with at least one LLM (e.g., GPT, Llama, Mistral)
- Basic command-line / terminal usage

---

## Module 1: Foundations — Python for Production AI

**Goal:** Master the Python programming patterns that separate "notebook code" from "production code."

### 1.1 Asyncio & Concurrency

- **Why it matters:** LLM inference is I/O-bound (waiting for GPU computation). While one request is being processed, the server should accept others — not block.
- **Topics:**
  - Python's `async`/`await` syntax and the event loop
  - `asyncio.gather()` for parallel operations
  - Async generators for streaming responses
  - Thread pools vs. process pools for CPU-bound vs. I/O-bound tasks
- **Key Concepts:** Concurrency vs. parallelism, coroutines, event-driven architecture.

> 📖 **Reference:** [Python asyncio documentation](https://docs.python.org/3/library/asyncio.html)

### 1.2 Pydantic for Data Validation

- **Why it matters:** Every API input (prompts, parameters) and output (responses, metadata) must be validated and structured. You can't let a 200,000-token prompt crash your GPU.
- **Topics:**
  - Pydantic `BaseModel`, field validators, and computed fields
  - Constraining inputs (e.g., `max_length`, `gt=0`, custom validators)
  - Structured output schemas for LLM responses
  - Serialization / deserialization for API contracts
- **Key Concepts:** Schema validation, type safety, API contracts.

> 📖 **Reference:** [Pydantic V2 documentation](https://docs.pydantic.dev/latest/)

### 1.3 FastAPI for AI APIs

- **Why it matters:** FastAPI is the gold standard for serving ML models — it's async-native, uses Pydantic for automatic validation, and generates OpenAPI docs out of the box.
- **Topics:**
  - Creating REST endpoints (`@app.post`, `@app.get`)
  - Dependency injection for loading models once at startup (lifespan events)
  - Background tasks for async post-processing
  - Error handling with `HTTPException` and custom error models
  - Middleware for logging, authentication, and rate limiting
  - WebSockets and Server-Sent Events (SSE) for streaming
- **Key Concepts:** ASGI servers, request lifecycle, dependency injection.

> 📖 **Reference:** [FastAPI official documentation](https://fastapi.tiangolo.com/)

### 🛠️ Hands-on Lab

Build a simple FastAPI application that accepts a text prompt, validates it with Pydantic (max 500 characters, no special injection tokens), and returns a mock response with simulated latency using `asyncio.sleep()`.

---

## Module 2: High-Performance Model Serving

**Goal:** Learn to expose your LLM as a fast, reliable API that handles concurrent requests without crashing.

### 2.1 The Inference Bottleneck

- **Why standard HuggingFace `.generate()` is too slow:**
  - Static batching wastes GPU cycles waiting for the longest sequence to finish
  - Naive KV-cache allocation fragments GPU memory
  - No concurrent request handling out of the box
- **Understanding the inference pipeline:** Prefill phase (prompt processing) vs. Decode phase (token-by-token generation), and why they have different computational profiles.

> 📖 **Reference:** [Efficient Inference on a Single GPU — HuggingFace](https://huggingface.co/docs/transformers/perf_infer_gpu_one)

### 2.2 vLLM — The Production Inference Engine

- **What it is:** An open-source, high-throughput LLM serving engine adopted by Meta, Mistral AI, Cohere, and IBM for production workloads. Achieves **2–24× throughput improvements** over conventional serving frameworks.
- **Core innovations:**
  - **PagedAttention:** Inspired by OS virtual memory, it divides the KV-cache into fixed-size "pages" stored in non-contiguous memory. This reduces GPU memory waste by **60–80%** and enables higher batch sizes.
  - **Continuous Batching:** Dynamically inserts new requests into the batch as soon as GPU resources become available from completed sequences — boosts throughput **2–10×** over static batching.
  - **Prefix Caching:** Reuses KV-cache across requests with shared prompt prefixes (system prompts, few-shot examples).
- **Quantization for serving:** Using AWQ or GPTQ (4-bit / 8-bit) to serve 70B-parameter models on consumer GPUs.
- **OpenAI-compatible API:** Drop-in replacement for OpenAI endpoints.

> 📖 **References:**
> - [vLLM official site](https://vllm.ai/) — Documentation and production stack
> - [PagedAttention paper (Kwon et al., 2023)](https://arxiv.org/abs/2309.06180) — Original research
> - [vLLM Production Stack (Jan 2025)](https://blog.vllm.ai/2025/01/27/vllm-production-stack.html) — Kubernetes-native deployment with KV-cache sharing, autoscaling, and observability

### 2.3 Alternative Serving Engines

- **Text Generation Inference (TGI):** HuggingFace's production serving solution with built-in support for token streaming and quantization.
- **TensorRT-LLM:** NVIDIA's purpose-built engine for maximizing performance on NVIDIA hardware. Best for latency-critical workloads.
- **SGLang:** Emerging alternative using RadixAttention for efficient chat/multi-turn scenarios. Competitive or superior to vLLM in some benchmarks.

> 📖 **References:**
> - [HuggingFace TGI](https://huggingface.co/docs/text-generation-inference/)
> - [TensorRT-LLM GitHub](https://github.com/NVIDIA/TensorRT-LLM)
> - [SGLang GitHub](https://github.com/sgl-project/sglang)

### 2.4 Streaming Responses

- **Server-Sent Events (SSE):** Implementing token-by-token streaming so users see text appearing in real-time (like ChatGPT).
- **Implementation:** FastAPI `StreamingResponse` with async generators connected to vLLM's streaming output.
- **Client-side handling:** Consuming SSE streams in JavaScript / Python clients.

### 2.5 AWS Model Serving

- **Amazon SageMaker Inference Endpoints:**
  - Real-time endpoints for low-latency predictions
  - Serverless inference for intermittent traffic patterns
  - Multi-model endpoints to host multiple models on a single instance
  - Optimized inference containers: vLLM and HuggingFace LLM Deep Learning Containers (DLCs)
  - Hardware Requirements objects for granular GPU resource control
- **Amazon Bedrock — Managed Foundation Model API:**
  - Access to foundation models (Anthropic Claude, Meta Llama, Mistral, Amazon Titan) via a single unified API
  - Inference options: On-Demand, Provisioned Throughput, Latency-Optimized, Cross-Region
  - Custom Model Import: Fine-tune on SageMaker → deploy to Bedrock for managed inference
  - Batch inference for processing large datasets of prompts asynchronously
  - Converse API for unified interaction across model providers

> 📖 **References:**
> - [Amazon SageMaker Inference](https://docs.aws.amazon.com/sagemaker/latest/dg/deploy-model.html)
> - [Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html)
> - [Deploy LLMs on SageMaker with vLLM DLCs — Phil Schmid](https://www.philschmid.de/sagemaker-vllm)

### 🛠️ Hands-on Lab

Build a production-ready API for a **Llama 3** (or **Mistral 7B**) model using **vLLM + FastAPI** that supports SSE streaming and can handle **50 concurrent users**. Benchmark with `locust` or `k6`.

---

## Module 3: Production Architecture — Load Balancing, Caching & Queues

**Goal:** Design the infrastructure layer around your serving engine for reliability and performance.

### 3.1 Load Balancing

- **NGINX / AWS Application Load Balancer (ALB):** Distributing traffic across multiple API workers.
- **Strategies:** Round-robin, least-connections, IP hash.
- **Health checks:** Ensuring traffic is only routed to healthy GPU servers.
- **AWS Elastic Load Balancing:** Application Load Balancer (ALB) for HTTP/HTTPS with path-based routing, Network Load Balancer (NLB) for ultra-low latency TCP.

> 📖 **References:**
> - [NGINX Load Balancing](https://docs.nginx.com/nginx/admin-guide/load-balancer/http-load-balancer/)
> - [AWS Elastic Load Balancing](https://docs.aws.amazon.com/elasticloadbalancing/latest/userguide/what-is-load-balancing.html)

### 3.2 Queue Management

- **The "thundering herd" problem:** When 1,000 users hit your API simultaneously and your GPU can only process 16 at a time.
- **Solutions:**
  - Request queues with **Redis**, **RabbitMQ**, or **Amazon SQS**
  - Backpressure mechanisms: rejecting requests gracefully when the queue is full
  - Priority queues for premium vs. free-tier users
- **AWS Amazon SQS:** Fully managed message queuing for decoupling producers and consumers at scale.

> 📖 **References:**
> - [Redis Streams](https://redis.io/docs/latest/develop/data-types/streams/)
> - [Amazon SQS](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/welcome.html)

### 3.3 Semantic Caching

- **Why cache LLM responses?** LLM inference is expensive ($0.01–$0.10+ per query). If users ask semantically similar questions, return cached results.
- **Implementation:**
  - Embedding-based similarity search (e.g., cosine similarity > 0.95 → return cached response)
  - **Redis** with vector search, or **GPTCache**
  - **Amazon ElastiCache** for managed Redis caching
  - **Amazon OpenSearch** with vector search for semantic similarity
  - Cache invalidation strategies for time-sensitive content

> 📖 **References:**
> - [GPTCache GitHub](https://github.com/zilliztech/GPTCache)
> - [Amazon ElastiCache](https://docs.aws.amazon.com/AmazonElastiCache/latest/red-ug/WhatIs.html)

### 🛠️ Hands-on Lab

Add **NGINX load balancing** across 2 vLLM workers, an **Amazon SQS** (or Redis) queue for request management, and a **semantic cache** layer using Redis vector search. Measure the cache hit rate and latency improvement.

---

## Module 4: LLM Evaluation & Testing

**Goal:** Move from "vibes-based" evaluation ("it looks good to me") to **mathematical confidence**.

### 4.1 Offline Evaluation Frameworks

- **LLM-as-a-Judge:** Using a stronger model (e.g., GPT-4, Claude) to grade the outputs of a smaller deployed model.
- **Ragas Framework (RAG Assessment):**
  - **Faithfulness:** Does the answer come strictly from the retrieved documents? (Breaks answer into claims, verifies each against context.)
  - **Answer Relevancy:** Did the model actually answer the user's question?
  - **Context Precision:** Were the relevant chunks ranked higher than irrelevant ones?
  - **Context Recall:** Did the retrieval step find the right information?
  - Scores range 0–1; lower faithfulness signals hallucination.
- **G-Eval:** Creating custom evaluation criteria (e.g., "Politeness," "Conciseness," "Technical Accuracy") with weighted scoring using LLM judges.
- **DeepEval:** Open-source framework for measuring LLM output quality with metrics like hallucination, toxicity, bias, and answer relevancy.

> 📖 **References:**
> - [Ragas documentation](https://docs.ragas.io/) — Metrics: Faithfulness, Answer Relevancy, Context Precision, Context Recall
> - [Ragas research paper (Es et al., 2023)](https://arxiv.org/abs/2309.15217)
> - [G-Eval paper (Liu et al., 2023)](https://arxiv.org/abs/2303.16634)
> - [DeepEval GitHub](https://github.com/confident-ai/deepeval)

### 4.2 Automated Testing for LLMs

- **Golden Test Sets:** Curating a set of 50–200 test queries with expected outputs. Run automatically on every code push.
- **Regression Testing:** Comparing new model version outputs against baseline to catch degradations.
- **A/B Testing:** Serving two model versions to different user segments and comparing metrics.
- **AWS-specific:** Using **Amazon Bedrock Model Evaluation** for automated and human evaluation of foundation models.

> 📖 **Reference:** [Amazon Bedrock Model Evaluation](https://docs.aws.amazon.com/bedrock/latest/userguide/model-evaluation.html)

### 🛠️ Hands-on Lab

Create an evaluation pipeline using **Ragas** to score your RAG application on "Faithfulness" and "Context Precision." Set up alerts that fire if any metric drops below **0.80**.

---

## Module 5: Observability & Monitoring

**Goal:** Build real-time visibility into your LLM system — because you can't fix what you can't see.

### 5.1 Tracing — Understanding the Full Chain

- **What to trace:** User Query → Retriever → Reranker → LLM → Post-processor → Output
- **Tools:**
  - **LangSmith:** End-to-end tracing for LangChain applications. Captures every prompt, tool call, and model response. Custom dashboards track token usage, latency, error rates, and costs.
  - **Arize Phoenix:** Open-source, OpenTelemetry-based tracing. Framework-agnostic (LangGraph, LlamaIndex, etc.). Supports LLM-based benchmarking, versioned datasets, and experiment tracking.
  - **Langfuse:** Open-source alternative with production-ready tracing and analytics.
- **OpenTelemetry standard:** The emerging standard for interoperable LLM observability — supported by LangSmith, Phoenix, and Langfuse.

> 📖 **References:**
> - [LangSmith documentation](https://docs.smith.langchain.com/) — Tracing, evaluation, monitoring
> - [Arize Phoenix GitHub](https://github.com/Arize-AI/phoenix) — Open-source AI observability
> - [Langfuse documentation](https://langfuse.com/docs) — Open-source LLM engineering platform
> - [OpenTelemetry](https://opentelemetry.io/) — Vendor-neutral observability framework

### 5.2 Guardrails & Safety — Real-Time Protection

- **Hallucination detection:** Catching factually incorrect or fabricated outputs before they reach the user.
- **Tools:**
  - **NeMo Guardrails (NVIDIA):** Open-source toolkit for programmable guardrails. Built-in modules for input/output moderation, fact-checking, hallucination detection, topic control, and jailbreak prevention. Integrates with LangChain, LangGraph, and LlamaIndex.
  - **Guardrails for Amazon Bedrock:** AWS-managed contextual grounding checks — verifies if the model's response is factually accurate based on source context and relevant to the user's query. Also provides content filters for toxicity and PII detection.
  - **Guardrails AI:** Open-source framework for input/output validation with custom validators.

> 📖 **References:**
> - [NeMo Guardrails GitHub](https://github.com/NVIDIA/NeMo-Guardrails)
> - [Guardrails for Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html)
> - [Guardrails AI](https://www.guardrailsai.com/)

### 5.3 Cost Tracking & Token Budget Management

- **Why it matters:** A runaway prompt loop can generate a $10,000 bill overnight.
- **Implementation:**
  - Monitoring token usage per user / tenant / API key
  - Setting hard token limits and budget alerts
  - **AWS Cost Explorer & Budgets** for tracking Bedrock and SageMaker spend
  - **Amazon CloudWatch** custom metrics for token consumption dashboards

> 📖 **References:**
> - [AWS Cost Explorer](https://docs.aws.amazon.com/cost-management/latest/userguide/ce-what-is.html)
> - [Amazon CloudWatch](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/WhatIsCloudWatch.html)

### 5.4 Drift Detection

- **Prompt Drift:** Detecting when user query patterns shift over time (e.g., users start asking about a new product you haven't indexed). Monitor query embedding distributions.
- **Data Drift:** Detecting when retrieval documents become stale or the source knowledge base changes significantly.
- **Model Drift:** Performance degradation over time as the world changes and the model's training data becomes outdated.
- **AWS-specific:** **Amazon SageMaker Model Monitor** for detecting data and model quality drift with automatic alerts.

> 📖 **Reference:** [Amazon SageMaker Model Monitor](https://docs.aws.amazon.com/sagemaker/latest/dg/model-monitor.html)

### 🛠️ Hands-on Lab

Set up **LangSmith** (or **Arize Phoenix**) tracing for your RAG application. Create a **CloudWatch dashboard** that tracks: tokens/minute, p95 latency, error rate, and faithfulness score. Configure alerts for anomalies.

---

## Module 6: Containerization with Docker

**Goal:** Package your application so it runs **exactly the same** on your laptop, a colleague's machine, and the cloud.

### 6.1 Docker for ML — Beyond the Basics

- **Multi-stage builds:** Keeping images small by separating build tools (compilers, pip) from the runtime (just Python + your code). A typical ML image can go from 15GB to 3GB.
- **Layer caching:** Optimizing build times so you don't re-download PyTorch every time you change one line of application code. (Copy `requirements.txt` first, then copy source code.)
- **GPU passthrough:** Configuring the **NVIDIA Container Toolkit** (`nvidia-docker2`) so Docker containers can see and use your GPUs.
- **Environment & secrets management:**
  - Never hardcode API keys in images
  - Use `.env` files, Docker secrets, or **AWS Secrets Manager**
  - Mount volumes for model weights to avoid bloating images

> 📖 **References:**
> - [Docker documentation](https://docs.docker.com/)
> - [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/overview.html)
> - [AWS Secrets Manager](https://docs.aws.amazon.com/secretsmanager/latest/userguide/intro.html)

### 6.2 Container Registries

- **Docker Hub** for public images
- **Amazon Elastic Container Registry (ECR):** AWS-managed private container registry with vulnerability scanning, image signing, and IAM-based access control.

> 📖 **Reference:** [Amazon ECR](https://docs.aws.amazon.com/AmazonECR/latest/userguide/what-is-ecr.html)

### 🛠️ Hands-on Lab

Write a **multi-stage Dockerfile** for your vLLM + FastAPI application. Optimize it so a code-only change rebuilds in <30 seconds (no PyTorch re-download). Push to **Amazon ECR**.

---

## Module 7: Orchestration with Kubernetes

**Goal:** Deploy, scale, and manage your containerized LLM application across a cluster of machines.

### 7.1 Kubernetes Fundamentals

- **Core concepts:**
  - **Pods:** The smallest deployable unit (your container + sidecar containers)
  - **Deployments:** Declarative updates for Pods (rolling updates, rollbacks)
  - **Services:** Stable networking for Pods (ClusterIP, NodePort, LoadBalancer)
  - **Ingress:** HTTP routing rules (path-based, host-based)
  - **ConfigMaps & Secrets:** Configuration and credential management
- **GPU scheduling:** Using the **NVIDIA Device Plugin** to expose GPUs as schedulable resources. Supports time-slicing and Multi-Instance GPU (MIG) for efficient utilization.

> 📖 **References:**
> - [Kubernetes official documentation](https://kubernetes.io/docs/)
> - [NVIDIA GPU Operator for Kubernetes](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/overview.html)

### 7.2 Autoscaling Strategies

- **HPA (Horizontal Pod Autoscaler):** Automatically adding more API server pods when CPU/memory usage spikes. Adequate for general workloads but not GPU-aware.
- **KEDA (Kubernetes Event-driven Autoscaling):** Purpose-built for LLM workloads. Scales based on:
  - **Request queue depth** (Redis, RabbitMQ, SQS queue length)
  - **GPU utilization** (via Prometheus + DCGM metrics)
  - **LLM-specific metrics** (Time To First Token (TTFT), Time Per Output Token (TPOT), token throughput)
  - Supports **scale-to-zero** for cost savings during idle periods
  - KEDA-HTTP add-on buffers requests during scale-up to avoid cold-start failures
- **Karpenter:** Just-in-time node provisioning — automatically selects and provisions the right EC2 instance type (including GPU instances) based on pod requirements.

> 📖 **References:**
> - [KEDA documentation](https://keda.sh/docs/)
> - [KEDA for LLM workloads — Red Hat](https://www.redhat.com/en/blog/scaling-llm-workloads-with-keda)
> - [Karpenter](https://karpenter.sh/)

### 7.3 AWS Kubernetes & Container Services

- **Amazon EKS (Elastic Kubernetes Service):**
  - Managed Kubernetes control plane
  - **EKS Auto Mode:** Automates cluster provisioning, node scaling, and GPU configuration with built-in Karpenter
  - CloudWatch Container Insights for GPU observability (NVIDIA DCGM metrics)
  - Integration with AWS Inferentia and Trainium for cost-effective AI inference
- **Amazon ECS (Elastic Container Service):**
  - Simpler alternative to Kubernetes for container orchestration
  - Service auto scaling with custom metrics (e.g., backlog-per-task)
  - Deep integration with EC2 Auto Scaling Groups and Spot Instances
  - **AWS Fargate** for serverless containers (no GPU support as of 2024)

> 📖 **References:**
> - [Amazon EKS](https://docs.aws.amazon.com/eks/latest/userguide/what-is-eks.html)
> - [Amazon ECS](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/Welcome.html)
> - [Best Practices for Gen AI Inference on EKS — AWS](https://docs.aws.amazon.com/eks/latest/best-practices/generative-ai.html)

### 7.4 Ray Serve

- **What it is:** A specialized framework often used on top of Kubernetes for managing complex multi-model pipelines (e.g., retriever model + reranker model + LLM all orchestrated together).
- **Key features:** Dynamic batching, model multiplexing, fractional GPU allocation.

> 📖 **Reference:** [Ray Serve documentation](https://docs.ray.io/en/latest/serve/index.html)

### 🛠️ Hands-on Lab

Deploy your Dockerized vLLM API on a **local Kubernetes cluster (Minikube or Kind)** with:
- GPU passthrough via NVIDIA Device Plugin
- A **KEDA** autoscaler that activates when the pending request queue exceeds 10
- A **rolling update** deployment strategy

---

## Module 8: CI/CD for LLM Applications

**Goal:** Automate the testing, versioning, and deployment of your LLM application so every change is safe and traceable.

### 8.1 Model Registry & Versioning

- **MLflow Model Registry:**
  - Version control for model weights, prompts, configurations, and evaluation results
  - `LoggedModel` for comprehensive version control of entire LLM applications/agents
  - **Prompt Registry:** Centralized versioning for prompt templates with diff views and commit messages
  - Lineage tracking: linking each model version to training data, hyperparameters, and evaluation metrics
- **HuggingFace Hub:** Community-oriented model hosting with versioning via Git LFS.
- **AWS-specific:** **Amazon SageMaker Model Registry** for tracking model versions, approval workflows, and deployment lineage within AWS.

> 📖 **References:**
> - [MLflow Model Registry](https://mlflow.org/docs/latest/model-registry.html)
> - [MLflow Prompt Registry](https://mlflow.org/docs/latest/llms/prompt-registry/index.html)
> - [Amazon SageMaker Model Registry](https://docs.aws.amazon.com/sagemaker/latest/dg/model-registry.html)

### 8.2 CI/CD Pipelines

- **Automated evaluation on every push:**
  - Run a "golden set" of 50–200 test queries against the model
  - Compare evaluation scores (faithfulness, latency, accuracy) against baseline thresholds
  - Block deployment if any metric regresses beyond tolerance
- **Pipeline stages:**
  1. **Build:** Lint code → run unit tests → build Docker image
  2. **Evaluate:** Deploy candidate model → run Ragas evaluation suite → compare against baseline
  3. **Register:** If evaluation passes → version and register in MLflow Model Registry
  4. **Deploy:** Rolling update to staging → smoke test → promote to production
- **Tools:** GitHub Actions, GitLab CI, **AWS CodePipeline** + **AWS CodeBuild**
- **AWS CodePipeline:** Fully managed CI/CD service for automating build, test, and deploy stages. Integrates natively with ECR, ECS, EKS, and SageMaker.

> 📖 **References:**
> - [GitHub Actions](https://docs.github.com/en/actions)
> - [AWS CodePipeline](https://docs.aws.amazon.com/codepipeline/latest/userguide/welcome.html)
> - [AWS CodeBuild](https://docs.aws.amazon.com/codebuild/latest/userguide/welcome.html)

### 8.3 Infrastructure as Code (IaC)

- **Terraform:** Declarative infrastructure management for multi-cloud deployments.
- **AWS CloudFormation / AWS CDK:** AWS-native IaC for provisioning SageMaker endpoints, EKS clusters, Bedrock configurations, and supporting infrastructure.
- **Helm Charts:** Package manager for Kubernetes — version and deploy your entire application stack (vLLM + FastAPI + Redis + monitoring) as a single Helm release.

> 📖 **References:**
> - [Terraform documentation](https://developer.hashicorp.com/terraform/docs)
> - [AWS CDK](https://docs.aws.amazon.com/cdk/v2/guide/home.html)
> - [Helm](https://helm.sh/docs/)

### 🛠️ Hands-on Lab

Create a **GitHub Actions** (or **AWS CodePipeline**) CI/CD pipeline that:
1. Runs linting and unit tests
2. Builds and pushes a Docker image to ECR
3. Runs the Ragas evaluation suite against 100 test queries
4. Deploys to staging if all evaluation thresholds pass
5. Requires manual approval before production promotion

---

## Module 9: Security, Compliance & Cost Management

**Goal:** Protect your LLM system from abuse and control your cloud spend.

### 9.1 API Security

- **Authentication:** API keys, OAuth 2.0, **AWS IAM** roles and policies
- **Rate Limiting:** Token buckets, sliding window counters (per user / per tenant)
- **Input Sanitization:** Defending against prompt injection attacks
- **PII Detection:** Using **Amazon Comprehend** or NeMo Guardrails to detect and redact personally identifiable information before it reaches the model

> 📖 **References:**
> - [AWS IAM](https://docs.aws.amazon.com/IAM/latest/UserGuide/introduction.html)
> - [Amazon Comprehend PII Detection](https://docs.aws.amazon.com/comprehend/latest/dg/how-pii.html)

### 9.2 Cost Optimization

- **Spot Instances:** Using **EC2 Spot Instances** for fault-tolerant inference workloads — up to 90% cost savings. Combine with Karpenter for automatic fallback to on-demand.
- **Right-sizing:** Using **AWS Compute Optimizer** to get instance type recommendations based on actual usage.
- **Reserved Capacity:** **SageMaker Savings Plans** and **EC2 Reserved Instances** for predictable workloads.
- **Model optimization:** Quantization (4-bit/8-bit) reduces GPU requirements by 2–4×, directly cutting instance costs.
- **Budgets & Alerts:** **AWS Budgets** for spending thresholds, **Cost Anomaly Detection** for unexpected spikes.

> 📖 **References:**
> - [EC2 Spot Instances](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/using-spot-instances.html)
> - [AWS Compute Optimizer](https://docs.aws.amazon.com/compute-optimizer/latest/ug/what-is-compute-optimizer.html)
> - [AWS Budgets](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html)

### 🛠️ Hands-on Lab

Implement **rate limiting** (100 requests/minute per API key) in your FastAPI middleware. Set up **AWS Budgets** with a $50/day threshold and configure SNS alerts.

---

## Capstone Project: "The Enterprise RAG Platform"

**Build a fully deployed Question-Answering system that integrates everything from this syllabus:**

### Architecture

| Component | Technology |
|---|---|
| **Model Serving** | vLLM backend hosting a quantized **Mistral 7B** (AWQ 4-bit) |
| **API Layer** | FastAPI middleware with authentication, rate limiting, input validation |
| **Retrieval** | Vector store (Qdrant / Pinecone / Amazon OpenSearch) + embedding model |
| **Evaluation** | Daily automated job running 100 test queries, scoring with Ragas, logging to dashboard |
| **Guardrails** | NeMo Guardrails for hallucination detection + content safety |
| **Observability** | LangSmith or Arize Phoenix tracing + CloudWatch metrics dashboard |
| **Caching** | Redis semantic cache for frequently asked queries |
| **Infrastructure** | Docker Compose for local dev; Helm on EKS for cloud deployment |
| **CI/CD** | GitHub Actions → ECR → Ragas eval gate → EKS rolling deploy |
| **Cost Controls** | Spot instances + AWS Budgets + token budget per user |

### Deliverables

1. **Source code** — GitHub repository with Dockerfile, Helm chart, CI/CD pipeline
2. **Architecture diagram** — Full system diagram showing all components and data flow
3. **Evaluation report** — Ragas scores (Faithfulness > 0.85, Context Precision > 0.80)
4. **Observability dashboard** — Live CloudWatch / Grafana dashboard with key metrics
5. **Load test results** — Locust or k6 report showing the system handles 100 concurrent users with p95 latency < 5 seconds
6. **Cost analysis** — Estimated monthly AWS cost breakdown with optimization recommendations

---

## Appendix A: Tool & Technology Quick Reference

| Category | Tools | Links |
|---|---|---|
| **Serving Engines** | vLLM, TGI, TensorRT-LLM, SGLang | [vllm.ai](https://vllm.ai), [TGI](https://huggingface.co/docs/text-generation-inference/) |
| **API Frameworks** | FastAPI, LitServe | [fastapi.tiangolo.com](https://fastapi.tiangolo.com) |
| **Evaluation** | Ragas, DeepEval, G-Eval | [ragas.io](https://docs.ragas.io), [deepeval](https://github.com/confident-ai/deepeval) |
| **Observability** | LangSmith, Arize Phoenix, Langfuse | [langchain.com/langsmith](https://www.langchain.com/langsmith), [phoenix](https://github.com/Arize-AI/phoenix) |
| **Guardrails** | NeMo Guardrails, Guardrails AI, Bedrock Guardrails | [NeMo](https://github.com/NVIDIA/NeMo-Guardrails), [Bedrock](https://docs.aws.amazon.com/bedrock/) |
| **Model Registry** | MLflow, HuggingFace Hub, SageMaker Registry | [mlflow.org](https://mlflow.org), [SageMaker](https://docs.aws.amazon.com/sagemaker/) |
| **Containerization** | Docker, NVIDIA Container Toolkit | [docker.com](https://docs.docker.com) |
| **Orchestration** | Kubernetes, Amazon EKS, Amazon ECS | [kubernetes.io](https://kubernetes.io), [EKS](https://docs.aws.amazon.com/eks/) |
| **Autoscaling** | KEDA, Karpenter, HPA | [keda.sh](https://keda.sh), [karpenter.sh](https://karpenter.sh) |
| **CI/CD** | GitHub Actions, AWS CodePipeline, Terraform | [github.com/actions](https://docs.github.com/en/actions), [CodePipeline](https://docs.aws.amazon.com/codepipeline/) |
| **Queueing** | Redis, Amazon SQS, RabbitMQ | [redis.io](https://redis.io), [SQS](https://docs.aws.amazon.com/sqs/) |
| **Caching** | Redis, ElastiCache, GPTCache | [ElastiCache](https://docs.aws.amazon.com/AmazonElastiCache/) |
| **Security** | AWS IAM, AWS Secrets Manager, Amazon Comprehend | [IAM](https://docs.aws.amazon.com/IAM/), [Secrets Manager](https://docs.aws.amazon.com/secretsmanager/) |
| **Cost Management** | AWS Budgets, Cost Explorer, Compute Optimizer | [Budgets](https://docs.aws.amazon.com/cost-management/) |

---

## Appendix B: Recommended Learning Path

```
Week 1–2:  Module 1 (Python Foundations) + Module 2 (Model Serving)
Week 3:    Module 3 (Production Architecture)
Week 4:    Module 4 (Evaluation & Testing)
Week 5:    Module 5 (Observability & Monitoring)
Week 6:    Module 6 (Docker) + Module 7 (Kubernetes)
Week 7:    Module 8 (CI/CD)
Week 8:    Module 9 (Security & Cost) + Capstone Project
Week 9–10: Capstone Project completion and presentation
```

---

*Last updated: March 2026*

---
title: "Transformers"
date: 2026-04-18
tags: [nlp, transformers, attention, positional-encoding, bert, gpt, t5, bart, encoder-decoder, self-attention, multi-head-attention]
description: The architecture that powers every modern LLM — from the "Attention Is All You Need" paper to BERT, GPT, and T5. Covering why Transformers replaced RNNs, positional encoding, the full Transformer block, masked self-attention, and the three variant families (Encoder-Only, Decoder-Only, Encoder-Decoder) with full math and Python code.
---

# Attention Is All You Need 🔥

In our [Attention Mechanism blog](content/large-language-models/natural-language-processing/attention-mechanism.md), we built the tools that let a Decoder *look back* at all Encoder hidden states and dynamically focus on the most relevant parts of the input. Self-Attention let a sequence attend to itself. Multi-Head Attention captured multiple relationship types in parallel.

But we were still using LSTMs as the backbone. The attention mechanism sat *on top of* the LSTM — it improved things, but the sequential bottleneck remained. Word 1 had to be processed before word 2, word 2 before word 3. On a modern GPU with thousands of CUDA cores, this is like having a 12-lane highway but forcing every car to drive in a single lane.

In June 2017, a team at Google published a paper with an unforgettable title: **"Attention Is All You Need"** (Vaswani et al., 2017). Their radical idea?

> **Strip away the RNN entirely. Build the entire model using *nothing but* attention, feed-forward layers, and a clever trick to handle word order.**

The result — the **Transformer** — is the architecture behind GPT, BERT, T5, LLaMA, Claude, Gemini, and every modern Large Language Model. It didn't just improve NLP — it replaced the entire paradigm.

---

## Why Transformers Replaced RNNs — The Three Killers 💀

### Killer 1: Parallelization ⚡

In an LSTM, each time step depends on the previous one — you **cannot** compute h₃ before h₂, because h₃ = LSTM(x₃, h₂). For a 100-word sentence, that's 100 sequential operations.

In a Transformer, **every word attends to every other word simultaneously** — it's a single matrix multiplication: `Attention = softmax(Q·K^T / √d_k) · V`. All 100 words are processed in **one parallel step**. On a GPU, this is dramatically faster.

```
LSTM:        x₁ → h₁ → x₂ → h₂ → x₃ → h₃   (100 sequential steps)
Transformer: [x₁, x₂, x₃, ..., x₁₀₀] → [y₁, y₂, y₃, ..., y₁₀₀]  (1 parallel step!)
```

> **Interview insight — "Why are Transformers faster than RNNs?"** RNNs are inherently sequential — each time step depends on the previous one, making it impossible to parallelize across time steps. Transformers replace recurrence with self-attention, which computes relationships between all positions in a single matrix multiplication. This allows Transformers to fully exploit modern GPU parallelism, reducing training time from weeks to days for equivalent tasks.

### Killer 2: Long-Range Dependencies 🔗

Even with LSTMs and attention, very long sequences (500+ tokens) were challenging. The LSTM still had to propagate information step by step through time.

In a Transformer, the distance between any two words is **always 1** — every word directly attends to every other word. "France" at position 1 is just as accessible as "fluent" at position 30, because both are in the Q·K^T matrix.

### Killer 3: Training Efficiency 📈

Because Transformers can be parallelized, they can be trained on **much more data** in the same wall clock time. This is what enabled the scaling revolution — GPT-3 was trained on 300 billion tokens, something that would be infeasible with LSTMs.

| Feature | LSTM + Attention | Transformer |
|---|---|---|
| **Sequential operations** | O(n) — one per time step | O(1) — all in parallel |
| **Max dependency distance** | O(n) through hidden states | O(1) — direct attention |
| **GPU utilization** | Poor (sequential bottleneck) | Excellent (matrix ops) |
| **Training time** | Weeks for large models | Days for equivalent scale |
| **Scalability** | Hits a wall at ~500M params | Scales to 1T+ parameters |

---

## The Transformer Architecture — Full Blueprint 🏗️

![The Transformer Architecture](content/large-language-models/natural-language-processing/images/transformer_architecture.png)

The original Transformer is an **Encoder-Decoder** model (just like our LSTM-based one from the [Encoder-Decoder blog](content/large-language-models/natural-language-processing/encoder-decoder.md)), but with attention replacing every recurrent component.

### The Big Picture

![Transformer Encoder-Decoder Block Diagram](content/large-language-models/natural-language-processing/images/transformer_encoder_block.png)

Let's break down every component.

---

## Positional Encoding — Teaching Order to a Parallel Model 📍

Here's the first challenge unique to Transformers: since there's no recurrence, **the model has no inherent notion of word order**. To an LSTM, "I love cats" and "cats love I" produce different hidden states because the words arrive in different orders. But to a Transformer's self-attention, both sentences produce the same Q·K^T matrix — the attention scores are the same regardless of order (self-attention is **permutation invariant**).

This is a serious problem. Word order is fundamental to meaning:
- "**Dog** bites **man**" vs "**Man** bites **dog**" — same words, opposite meaning

We need to *inject* positional information into the model. The solution: **add** a position-dependent vector to each word embedding before feeding it into the Transformer.

![Positional Encoding: Adding position information since Transformers have no sense of order](content/large-language-models/natural-language-processing/images/transformer_positional_encoding.png)

### The Sinusoidal Encoding

The original paper uses sine and cosine functions of different frequencies:

```
PE(pos, 2i)   = sin(pos / 10000^(2i/d_model))
PE(pos, 2i+1) = cos(pos / 10000^(2i/d_model))
```

Where:
- **pos** — the position of the word in the sequence (0, 1, 2, ...)
- **i** — the dimension index (0, 1, 2, ..., d_model/2)
- **d_model** — the model dimension (e.g., 512)

Each position gets a unique pattern of sines and cosines — like a fingerprint for where a word sits in the sentence.

### Why Sinusoidal? Why Not Just Use 1, 2, 3...?

You might wonder: why not just add the position number (1 for the first word, 2 for the second, etc.)? Three reasons:

1. **Scale problem** — position 500 would dominate the embedding values, drowning out the actual word meaning
2. **Generalization** — the model couldn't handle sequences longer than what it saw during training
3. **Relative positions** — sinusoidal encodings have a special property: `PE(pos + k)` can be expressed as a linear function of `PE(pos)`, meaning the model can learn to attend to *relative* positions ("3 words ago") rather than absolute positions

> **Interview insight — "Why do Transformers need positional encoding?"** Self-attention is permutation invariant — it computes the same attention scores regardless of the order of inputs. Since Transformers have no recurrence or convolution to capture sequential order, positional encoding must be explicitly added to the input embeddings. Without it, the model would treat "dog bites man" and "man bites dog" identically. Sinusoidal encoding is chosen because it generalizes to unseen sequence lengths and allows the model to learn relative position relationships.

### Code: Positional Encoding

```python
import numpy as np

def positional_encoding(max_len, d_model):
    """
    Generate sinusoidal positional encodings.
    
    max_len: maximum sequence length
    d_model: model dimension (must be even)
    
    Returns: PE matrix of shape [max_len, d_model]
    """
    PE = np.zeros((max_len, d_model))
    
    for pos in range(max_len):
        for i in range(0, d_model, 2):
            denominator = 10000 ** (i / d_model)
            PE[pos, i]     = np.sin(pos / denominator)   # Even dimensions
            PE[pos, i + 1] = np.cos(pos / denominator)   # Odd dimensions
    
    return PE

# Generate positional encodings for 50 positions, 512 dimensions
PE = positional_encoding(50, 512)

# The final input to the Transformer:
# input = word_embedding + positional_encoding
# shape: [T, 512] + [T, 512] = [T, 512]  ← same shape! Just adds position info.

print(f"PE shape: {PE.shape}")          # (50, 512)
print(f"PE[0][:8]: {PE[0][:8].round(4)}")  # Position 0
print(f"PE[1][:8]: {PE[1][:8].round(4)}")  # Position 1 — different pattern!
```

> **Interview insight — "Can we use learned positional encodings instead of sinusoidal?"** Yes! BERT and GPT use *learned* positional embeddings — trainable vectors that the model learns during training. The original Transformer used sinusoidal because it generalizes to sequence lengths unseen during training (extrapolation). In practice, both approaches perform similarly for sequences within the training length. Modern models like RoPE (Rotary Position Embedding) and ALiBi offer even better alternatives for long-context scenarios.

---

## The Transformer Block — Building Brick 🧱

Each Encoder and Decoder layer is a **Transformer Block**. Let's dissect the Encoder block (the Decoder block adds masked attention and cross-attention, which we'll cover after).

### Component 1: Multi-Head Self-Attention

This is exactly what we built in the [Attention blog](content/large-language-models/natural-language-processing/attention-mechanism.md):

```
MultiHead(Q, K, V) = Concat(head₁, ..., headₕ) · W_O

where headᵢ = Attention(X·W_Qᵢ, X·W_Kᵢ, X·W_Vᵢ)
```

Every word attends to every other word. With h=8 heads, 8 different relationship types are captured in parallel.

### Component 2: Add & Layer Normalization (Residual Connection)

After the attention layer, the Transformer uses a **residual connection** followed by **Layer Normalization**:

```
output = LayerNorm(x + MultiHeadAttention(x))
```

Why residual connections? Same reason as ResNets — they let gradients flow directly through the network without degradation. The attention output is *added* to the original input, meaning the model only needs to learn the **delta** (the change), not the entire representation from scratch.

Why Layer Normalization (not Batch Normalization)? In NLP, sequences have variable lengths, making batch statistics unreliable. Layer Norm normalizes across the feature dimension for each individual example, which is more stable for sequences.

> **Interview insight — "What's the purpose of residual connections in Transformers?"** Residual connections (x + sublayer(x)) serve two purposes: (1) They allow gradients to flow unimpeded through the network during backpropagation, preventing vanishing gradients in deep stacks (the original Transformer has 6 layers, modern ones have 100+). (2) They enable the model to learn *incremental refinements* — each layer adds a small modification to the representation rather than creating it from scratch. This is why Transformers can be stacked so deep without training instability.

### Component 3: Position-wise Feed-Forward Network (FFN)

After attention, each position passes through a simple two-layer neural network — **independently and identically** at every position:

```
FFN(x) = ReLU(x · W₁ + b₁) · W₂ + b₂
```

Where:
- W₁ expands the dimension: [512 → 2048] (4× expansion)
- W₂ projects it back: [2048 → 512]

This FFN acts as a "thinking step" — after the attention layer has gathered information from other positions, the FFN processes that gathered information at each position individually.

> **Interview insight — "What does the Feed-Forward Network do in a Transformer?"** The FFN provides non-linear transformation capacity at each position *independently*. While self-attention allows positions to exchange information (inter-position mixing), the FFN processes the aggregated information at each position separately (intra-position processing). Research has shown that the FFN layers act as key-value memories, storing factual knowledge learned during training. The 4× expansion (512 → 2048 → 512) provides a higher-dimensional space for this processing.

### The Complete Encoder Block

```python
def transformer_encoder_block(X, W_Qs, W_Ks, W_Vs, W_O, W1, b1, W2, b2, n_heads):
    """
    One Transformer Encoder Block.
    
    X: shape [T, d_model] — input sequence
    """
    # Step 1: Multi-Head Self-Attention
    attn_output = multi_head_attention(X, W_Qs, W_Ks, W_Vs, W_O, n_heads)
    
    # Step 2: Residual + LayerNorm
    X = layer_norm(X + attn_output)
    
    # Step 3: Feed-Forward Network (applied to each position independently)
    ffn_output = np.maximum(0, X @ W1 + b1) @ W2 + b2   # ReLU activation
    
    # Step 4: Residual + LayerNorm
    X = layer_norm(X + ffn_output)
    
    return X   # shape: [T, d_model] — same as input!

# Stack 6 of these blocks:
# for block in range(6):
#     X = transformer_encoder_block(X, ...)
```

> **Notice:** The input and output shapes are identical — [T, d_model]. This is what makes stacking trivial: the output of block 1 feeds directly into block 2, 3, 4, 5, 6 without any shape changes.

---

## Masked Self-Attention — The Decoder's Secret 🎭

In the Encoder, every word can attend to every other word — past *and* future. But in the Decoder, we're *generating* text word by word. When predicting word 3, the model **must not** be allowed to peek at words 4, 5, 6... because they haven't been generated yet!

The solution: **Masked Self-Attention**. We apply a mask that sets all "future" attention scores to -∞ before the softmax, effectively zeroing them out:

```
                  "I"   "love"  "cats"
"I"             [ 0.8    -inf    -inf  ]     ← can only see itself
"love"          [ 0.3    0.7     -inf  ]     ← can see "I" and itself
"cats"          [ 0.1    0.2     0.7   ]     ← can see everything before it
```

After softmax, the -∞ values become 0 (since e^(-∞) = 0), and the model can only attend to previous positions.

```python
def masked_attention(Q, K, V):
    """
    Masked (Causal) Self-Attention for the Decoder.
    """
    T, d_k = Q.shape
    
    scores = Q @ K.T / np.sqrt(d_k)
    
    # Create causal mask: upper triangle = -inf
    mask = np.triu(np.full((T, T), -np.inf), k=1)
    scores = scores + mask  # Future positions become -inf
    
    # Softmax: e^(-inf) = 0, so future positions get zero attention
    exp_scores = np.exp(scores - scores.max(axis=-1, keepdims=True))
    attn_weights = exp_scores / exp_scores.sum(axis=-1, keepdims=True)
    
    return attn_weights @ V
```

> **Interview insight — "What is masked self-attention and why is it needed?"** Masked (causal) self-attention prevents the decoder from attending to future positions during generation. Without masking, the model could "cheat" during training by looking at the target words it's supposed to predict. The mask sets future attention scores to -∞ before softmax, ensuring e^(-∞) = 0 attention weight. This maintains the autoregressive property: each position can only depend on earlier positions, mirroring the left-to-right generation process at inference time.

---

## The Full Decoder Block

The Decoder block has **three** sub-layers (vs the Encoder's two):

```
1. Masked Multi-Head Self-Attention    ← attends to previous decoder outputs
   + Add & LayerNorm

2. Multi-Head Cross-Attention          ← attends to Encoder outputs (Q from decoder, K/V from encoder)
   + Add & LayerNorm

3. Feed-Forward Network                ← position-wise processing
   + Add & LayerNorm
```

The cross-attention layer is the bridge between Encoder and Decoder — exactly like Bahdanau attention, but now using the Multi-Head Q/K/V framework. The Decoder provides the **Queries** ("what am I looking for?"), and the Encoder provides the **Keys** and **Values** ("here's what I have").

---

## Transformer Configurations — Three Dimensions 📐

The original Transformer uses these hyperparameters (referred to as the "base" model):

```
+-----------------------------------+
|  Transformer Base Configuration   |
+-----------------------------------+
|  d_model  = 512                   |  ← model dimension
|  h        = 8                     |  ← attention heads
|  d_k      = d_model / h = 64     |  ← key/query dim per head
|  d_ff     = 2048                  |  ← FFN inner dimension (4x)
|  N        = 6                     |  ← number of encoder/decoder layers
|  vocab    = ~37000 (BPE tokens)   |  ← vocabulary size
|  dropout  = 0.1                   |  ← regularization
+-----------------------------------+
|  Total parameters ≈ 65 million    |
+-----------------------------------+
```

Compare this to our LSTM-based Seq2Seq model (~27M parameters for a 4-layer stacked LSTM). The Transformer is larger but trains *much* faster due to parallelization, and achieves significantly better translation quality.

---

## The Three Transformer Families 👨‍👩‍👧

After the original Transformer paper, researchers discovered that you don't always need *both* the Encoder and Decoder. Depending on the task, you can use just one side — and this insight led to three distinct families of models.

### 1. Encoder-Only Models — BERT 🟢 "I understand"

**Architecture:** Only the Encoder stack. No Decoder. No text generation.

**Key innovation:** BERT (Bidirectional Encoder Representations from Transformers, 2018) uses the Encoder to build **deep bidirectional representations** — every word can attend to every other word in both directions (no masking).

**Training objective — Masked Language Modeling (MLM):** Randomly mask 15% of input tokens and train the model to predict them:

```
Input:   "The cat [MASK] on the mat"
Target:  "sat"

The model must use BOTH left and right context:
  "The cat" (left) + "on the mat" (right) → predict "sat"
```

This is fundamentally different from left-to-right language modeling (GPT), where the model can only see past words. BERT sees *everything* — making it exceptional at understanding.

**What BERT is great at:**

| Task | Example | Why BERT Excels |
|---|---|---|
| **Text Classification** | "Is this email spam?" | Full context → better understanding |
| **Sentiment Analysis** | "The movie was not bad" (positive!) | Bidirectional catches "not" + "bad" |
| **Named Entity Recognition** | "Apple launched iPhone" → [ORG, O, PRODUCT] | Sees both left and right context of each word |
| **Question Answering** | Context + Question → extract answer span | Attends to all parts of context simultaneously |

**How BERT is used:**

```
Input sentence → BERT Encoder (12 layers) → Contextualized embeddings

Then add a task-specific head:
  Classification:  [CLS] token embedding → Linear → softmax → label
  NER:             Each token embedding → Linear → softmax → entity tag
  QA:              Each token embedding → Linear → start/end position
```

> **Interview insight — "Why can't BERT generate text?"** BERT is an encoder-only model — it uses bidirectional self-attention where every word can see every other word (including future words). This makes it powerful for understanding but prevents autoregressive generation. Text generation requires predicting the *next* word based only on *previous* words (causal masking), which BERT's architecture doesn't enforce. For generation, you need a decoder-only model (GPT) or a full encoder-decoder (T5).

### 2. Decoder-Only Models — GPT 🔵 "I create"

**Architecture:** Only the Decoder stack. No Encoder. No cross-attention.

**Key innovation:** GPT (Generative Pre-trained Transformer, 2018) uses **causal (masked) self-attention** — each word can only attend to previous words, enabling left-to-right text generation.

**Training objective — Next Token Prediction (Causal Language Modeling):**

```
Input:   "The cat sat on"
Target:  "the"

The model predicts the NEXT word using only LEFT context:
  "The cat sat on" → predict "the"
```

This is the training objective that scales to GPT-2, GPT-3, GPT-4, and ChatGPT. The beauty is its simplicity — just predict the next token, over billions of tokens, and emergent abilities appear.

**What GPT is great at:**

| Task | Example | Why GPT Excels |
|---|---|---|
| **Text Generation** | "Once upon a time..." → full story | Autoregressive by design |
| **Chatbots** | User: "Explain gravity" → response | Generate multi-sentence answers |
| **Code Generation** | "def fibonacci(n):" → complete function | Left-to-right code completion |
| **Few-Shot Learning** | Prompt + examples → answer | In-context learning from examples |

**The Scaling Revelation:**

```
GPT-1:    117M params    (2018)  — proved the concept
GPT-2:    1.5B params    (2019)  — surprisingly coherent text
GPT-3:    175B params    (2020)  — few-shot learning emerged
GPT-4:    ~1.8T params   (2023)  — human-level on many benchmarks
```

The key insight: **the same architecture** just gets bigger. No fundamental changes — just more layers, more heads, more data, more compute. This is the scaling law that drives the entire LLM revolution.

> **Interview insight — "What's the difference between BERT and GPT?"** The fundamental difference is the attention pattern: BERT uses *bidirectional* self-attention (every word sees every other word), making it excellent for understanding tasks but incapable of generation. GPT uses *unidirectional/causal* self-attention (each word only sees previous words), enabling autoregressive generation. BERT is pre-trained with Masked Language Modeling (predict masked words), while GPT uses Causal Language Modeling (predict next word). In practice, BERT dominates classification/NER/QA, while GPT dominates generation/chatbots/reasoning.

### 3. Encoder-Decoder Models — T5/BART 🟣 "I transform"

**Architecture:** Full Encoder + Decoder with cross-attention — the complete original Transformer.

**Key innovation:** T5 (Text-to-Text Transfer Transformer, 2019) frames *every* NLP task as a text-to-text problem:

```
Translation:    "translate English to French: I love cats" → "J'aime les chats"
Summarization:  "summarize: <long article>"                → "NASA landed on Mars..."
Classification: "classify: This movie was amazing"         → "positive"
QA:             "question: Who is CEO? context: Tim..."     → "Tim Cook"
```

By converting every task into "input text → output text," the same model handles everything.

**What T5/BART excel at:**

| Task | Why Encoder-Decoder? |
|---|---|
| **Translation** | Encoder understands source language; Decoder generates target language |
| **Summarization** | Encoder reads the full document; Decoder generates a condensed version |
| **Question Answering** | Encoder processes context+question; Decoder generates the answer |
| **Grammar Correction** | Encoder reads broken text; Decoder generates corrected version |

> **Interview insight — "When would you choose T5 over BERT or GPT?"** Use T5/BART when you need to both *understand* an input and *generate* an output that's structurally different — translation (different language), summarization (different length), or transformation (different format). BERT can't generate at all. GPT can generate but processes everything as a single stream — it can't separately encode a source and decode a target. The encoder-decoder architecture lets the encoder build a rich understanding of the input while the decoder focuses entirely on generation.

### The Three Families — Side by Side

![The Three Transformer Families: Encoder-Only (BERT), Decoder-Only (GPT), Encoder-Decoder (T5/BART)](content/large-language-models/natural-language-processing/images/transformer_three_variants.png)

---

## Which Model to Choose? — Decision Framework 🎯

```
Do you need to GENERATE text?
├── NO  → Encoder-Only (BERT)
│         Classification, NER, Sentiment, QA (extractive)
│
├── YES → Do you need to TRANSFORM an input into an output?
│         ├── YES → Encoder-Decoder (T5/BART)
│         │         Translation, Summarization, Grammar Correction
│         │
│         └── NO  → Decoder-Only (GPT)
│                   Open-ended generation, Chatbots, Code, Reasoning
```

---

## Parameter Comparison — The Scale of Things 📊

| Model | Type | Layers | d_model | Heads | Parameters |
|---|---|---|---|---|---|
| BERT-base | Encoder | 12 | 768 | 12 | 110M |
| BERT-large | Encoder | 24 | 1024 | 16 | 340M |
| GPT-2 | Decoder | 48 | 1600 | 25 | 1.5B |
| GPT-3 | Decoder | 96 | 12288 | 96 | 175B |
| T5-base | Enc-Dec | 12+12 | 768 | 12 | 220M |
| T5-11B | Enc-Dec | 24+24 | 1024 | 128 | 11B |

> **Interview insight — "How does the number of parameters relate to model capability?"** More parameters allow a model to store more knowledge and capture more complex patterns. However, it's not just size — the interplay of depth (layers), width (d_model), and heads determines expressivity. Deeper models learn more abstract features. Wider models have richer per-position representations. More heads capture more diverse attention patterns. The scaling laws (Kaplan et al., 2020) showed that model performance scales predictably with the product of parameters, data, and compute.

---

## Summary — What We Learned 🎓

| Concept | Key Takeaway |
|---|---|
| **Why Transformers?** | Parallelizable, better long-range deps, and scales to billions of parameters |
| **No Recurrence** | Self-attention replaces LSTMs — all words processed simultaneously |
| **Positional Encoding** | Sinusoidal patterns added to embeddings to inject word order information |
| **Transformer Block** | Multi-Head Self-Attention → Add & LayerNorm → FFN → Add & LayerNorm |
| **Residual Connections** | Enable deep stacking without vanishing gradients |
| **Masked Self-Attention** | Decoder sees only previous words — enables autoregressive generation |
| **Cross-Attention** | Decoder queries attend to Encoder key/values — the Encoder-Decoder bridge |
| **BERT (Encoder-Only)** | Bidirectional understanding — classification, NER, sentiment, QA |
| **GPT (Decoder-Only)** | Causal generation — text generation, chatbots, code, reasoning |
| **T5/BART (Enc-Dec)** | Full transformation — translation, summarization, text-to-text |
| **Scaling Laws** | Same architecture, more parameters + data + compute = better performance |

---

## The Story So Far — And What Comes Next 🛣️

Let's step back and appreciate the journey:

```
Bag of Words / TF-IDF
  → "Just count words" — no order, no context

Word2Vec / Word Embeddings
  → "Words have meaning in vector space" — but still static

RNNs
  → "Process sequences with memory" — but vanishing gradients

LSTMs
  → "Selective memory with gates" — but sequential

Encoder-Decoder
  → "Read then write for different-length sequences" — but information bottleneck

Attention
  → "Focus on what matters at each step" — but still uses LSTMs

Transformers  ← YOU ARE HERE
  → "Attention is ALL you need" — parallel, scalable, the foundation of everything
```

We've arrived at the architecture that powers the AI revolution. But the Transformer is just the *architecture*. The next question is: **how do we actually train these models to be useful?**

Pre-training a Transformer on vast amounts of text gives us a powerful base — but how do we adapt it to *specific* tasks like your company's customer support, your domain's medical reports, or your application's code generation? We don't retrain from scratch — we **fine-tune**.

Fine-tuning is the art of taking a pre-trained Transformer (BERT, GPT, T5) and adapting it to your specific task with a small amount of labeled data. And that's the next post. 🔥

---

## What's Next? 🚀

```
RNNs → LSTMs → Encoder-Decoder → Attention → Transformers → ???
```

We now understand the architecture that powers every modern LLM. But raw architecture alone isn't enough — BERT fresh out of pre-training doesn't know how to classify your emails, and GPT doesn't know your company's products.

The next step is learning how to take these powerful pre-trained models and adapt them to *your* specific tasks — with techniques like fine-tuning, transfer learning, and prompt engineering.

Stay tuned — we're moving from *how Transformers work* to *how to use them*. ⚡

---

Got questions or suggestions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*

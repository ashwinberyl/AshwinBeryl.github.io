---
title: "Attention Mechanism"
date: 2026-04-18
tags: [nlp, attention, bahdanau, luong, self-attention, multi-head-attention, query-key-value, seq2seq, transformers]
description: From the Encoder-Decoder bottleneck to the Attention revolution — covering Bahdanau (additive) and Luong (multiplicative) attention with full math, Self-Attention with Query-Key-Value intuition, Multi-Head Attention for parallel pattern capture, scaled dot-product, and why Attention is the foundation of every modern LLM.
---

# The Breakthrough — Learning Where to Look 🔦

In our [Encoder-Decoder blog](content/large-language-models/natural-language-processing/encoder-decoder.md), we built a powerful architecture for machine translation. The Encoder read the entire source sentence and compressed it into a **Context Vector** — a single fixed-size vector (e.g., 512 numbers). The Decoder then generated the translation word by word, pulling entirely from that compressed summary.

It worked. Until the sentences got long.

The Context Vector is an **Information Bottleneck**. Compressing "I grew up in France and after many years of living abroad I speak fluent ___" into 512 numbers forces the Encoder to throw away information. By the time the Decoder needs the word "France" to predict "French," it's been overwritten by later words. Translation quality plummets for sentences longer than ~20 words.

The core insight that fixes everything is deceptively simple:

> **What if the Decoder didn't have to rely on one compressed summary? What if, at each step, it could look back at ALL the Encoder's hidden states and decide which parts of the input to focus on?**

That's the **Attention Mechanism** — and it changed NLP forever.

---

## The Intuition — A Spotlight on the Stage 🎭

Imagine you're an English-to-French translator sitting in a theater. The English sentence is printed across a long banner on the stage. In the old Encoder-Decoder model (without attention), you read the entire banner once, close your eyes, and try to write the French translation from memory. For a short sentence, you're fine. For a paragraph? You'll forget the beginning.

Now imagine you have a **spotlight** that you can point at any part of the banner while you translate. When you're translating "chats" (cats), you swing the spotlight to focus on "cats." When you translate "J'aime" (I love), the spotlight hits "love." At every step, you choose where to look.

![Attention: The Decoder focuses on the most relevant Encoder state](content/large-language-models/natural-language-processing/images/attention_spotlight.png)

That spotlight is **Attention**. Instead of one fixed Context Vector for the entire sentence, the Decoder now computes a *different* Context Vector at *every* decoding step — one that's specifically weighted towards the most relevant parts of the input.

> **💡 "Why do we need Attention?"** The standard Encoder-Decoder compresses the entire input into a single fixed-length vector, creating an information bottleneck. As sequence length grows, crucial early information is lost. Attention solves this by giving the Decoder *direct access* to every Encoder hidden state at every decoding step, allowing it to dynamically focus on the most relevant parts of the input.

---

## Bahdanau Attention — The Original (2014) 🏆

Dzmitry Bahdanau introduced the first attention mechanism in 2014 in the paper "Neural Machine Translation by Jointly Learning to Align and Translate." The word "Align" is key — the model learns which source words *align* with which target words.

### How It Works — Step by Step

At each Decoder time step *t*, Bahdanau Attention does the following:

**Step 1: Compute Alignment Scores**

For each Encoder hidden state *hⱼ* (where j = 1 to T, the source sequence length), compute a score that measures "how relevant is Encoder position j to the current Decoder state?"

```
eₜⱼ = V^T · tanh(W₁ · sₜ₋₁ + W₂ · hⱼ)
```

Where:
- **sₜ₋₁** — the Decoder's previous hidden state (what we've generated so far)
- **hⱼ** — the j-th Encoder hidden state (the representation of source word j)
- **W₁, W₂** — learnable weight matrices
- **V** — a learnable weight vector
- **tanh** — the non-linearity (this is why it's called **additive** — we add the transformed states)

This is a tiny one-hidden-layer neural network that learns to score how well the Decoder's current state aligns with each Encoder position.

**Step 2: Convert Scores to Weights (Softmax)**

```
αₜⱼ = softmax(eₜⱼ) = exp(eₜⱼ) / Σⱼ exp(eₜⱼ)
```

The softmax normalizes the raw scores into a probability distribution — the **attention weights**. They always sum to 1, meaning they represent "how much attention to pay to each source word."

> **💡 "Is Attention the same as Softmax?"** No. Softmax is just one *step* in the attention mechanism — the normalization step. Attention is the full pipeline: compute alignment scores → normalize with softmax → compute weighted sum. Softmax converts raw scores into a probability distribution, but the *scoring function* and the *weighted aggregation* are equally important parts.

**Step 3: Compute the Dynamic Context Vector**

```
cₜ = Σⱼ αₜⱼ · hⱼ
```

The Context Vector at step *t* is the **weighted sum** of all Encoder hidden states, where the weights come from the attention distribution. If α₃ = 0.85 (high attention on word 3), the Context Vector will be dominated by h₃.

**Step 4: Generate the Output**

The Decoder combines the dynamic Context Vector with its own hidden state to produce the next word:

```
sₜ = LSTM(sₜ₋₁, [yₜ₋₁; cₜ])     ← concat previous output + context
output = softmax(W_out · sₜ)       ← predict next word
```

### The Key Difference from Vanilla Encoder-Decoder

| | Without Attention | With Attention |
|---|---|---|
| **Context Vector** | One vector for the entire sentence | A *different* vector at every step |
| **Encoder states used** | Only the last one (h_final) | ALL of them (h₁, h₂, ..., h_T) |
| **Focus** | Fixed — same summary for every output word | Dynamic — shifts focus per output word |
| **Long sentences** | Quality degrades after ~20 words | Works well up to 50+ words |

### Code: Bahdanau Attention

```python
import numpy as np

def bahdanau_attention(decoder_hidden, encoder_states, W1, W2, V):
    """
    Bahdanau (Additive) Attention.
    
    decoder_hidden: shape [hidden_dim]      — current decoder state (sₜ₋₁)
    encoder_states: shape [T, hidden_dim]   — all encoder hidden states
    W1: shape [hidden_dim, attn_dim]        — learned weights for decoder
    W2: shape [hidden_dim, attn_dim]        — learned weights for encoder
    V:  shape [attn_dim]                    — learned scoring vector
    
    Returns: context_vector [hidden_dim], attention_weights [T]
    """
    T = len(encoder_states)
    
    # Step 1: Alignment scores
    scores = np.zeros(T)
    for j in range(T):
        # eₜⱼ = V^T · tanh(W₁·sₜ₋₁ + W₂·hⱼ)
        combined = np.tanh(decoder_hidden @ W1 + encoder_states[j] @ W2)
        scores[j] = V @ combined
    
    # Step 2: Softmax → attention weights (sum to 1)
    exp_scores = np.exp(scores - np.max(scores))  # numerical stability
    attn_weights = exp_scores / exp_scores.sum()
    
    # Step 3: Weighted sum of encoder states
    context_vector = sum(attn_weights[j] * encoder_states[j] for j in range(T))
    
    return context_vector, attn_weights

# Example: translating "I love cats" → "J'aime les chats"
# When generating "chats", the attention weights might be:
#   α = [0.05, 0.10, 0.85]
#         "I"   "love" "cats"  ← spotlight on "cats"!
```

> **💡 "Why is Bahdanau called 'additive' attention?"** Because the alignment score is computed by *adding* the transformed decoder state and encoder state: `tanh(W₁·s + W₂·h)`. This contrasts with Luong's "multiplicative" attention (coming next), which uses a dot product instead of addition.

---

## Luong Attention — The Simpler Variant (2015) ⚡

A year after Bahdanau, Minh-Thang Luong proposed a simplified attention mechanism in "Effective Approaches to Attention-based Neural Machine Translation." The key difference? Instead of a learned neural network for scoring, Luong uses direct mathematical operations — making it faster and often just as effective.

### Three Scoring Functions

Luong proposed three ways to compute alignment scores:

| Variant | Formula | Intuition | Complexity |
|---|---|---|---|
| **Dot** | eₜⱼ = sₜ · hⱼ | "How similar are these vectors?" | Simplest — no extra parameters! |
| **General** | eₜⱼ = sₜ · W · hⱼ | "How similar, with a learned transform?" | One weight matrix |
| **Concat** | eₜⱼ = V · tanh(W · [sₜ; hⱼ]) | Same as Bahdanau (additive) | Most parameters |

The **dot** variant is the most commonly used because it's the simplest and fastest — no extra learnable parameters, just a dot product between two vectors. It works because two vectors with high cosine similarity will produce a high dot product score.

### Code: Luong Dot-Product Attention

```python
def luong_dot_attention(decoder_hidden, encoder_states):
    """
    Luong Dot-Product Attention.
    No extra parameters needed! Just dot products.
    
    decoder_hidden: shape [hidden_dim]       — current decoder state (sₜ)
    encoder_states: shape [T, hidden_dim]    — all encoder hidden states
    """
    # Step 1: Dot-product scores
    # Score = how similar is the decoder state to each encoder state?
    scores = encoder_states @ decoder_hidden  # shape: [T]
    
    # Step 2: Softmax
    exp_scores = np.exp(scores - np.max(scores))
    attn_weights = exp_scores / exp_scores.sum()
    
    # Step 3: Weighted sum
    context_vector = attn_weights @ encoder_states  # shape: [hidden_dim]
    
    return context_vector, attn_weights
```

### Bahdanau vs Luong — Side-by-Side

| Feature | Bahdanau (2014) | Luong (2015) |
|---|---|---|
| **Scoring function** | Additive (learned neural network) | Multiplicative (dot product) |
| **Formula** | V^T · tanh(W₁·s + W₂·h) | s · h (dot) or s · W · h (general) |
| **When attention is computed** | Before the Decoder LSTM step | After the Decoder LSTM step |
| **Decoder state used** | sₜ₋₁ (previous) | sₜ (current) |
| **Extra parameters** | W₁, W₂, V (more) | None (dot) or W (general) |
| **Speed** | Slower (tanh + learned weights) | Faster (just dot products) |
| **Performance** | Slightly better on some tasks | Comparable, often preferred for speed |
| **Historical significance** | The original attention paper | The simplification that made it practical |

> **💡 "What's the difference between Bahdanau and Luong attention?"** Two main differences: (1) The scoring function — Bahdanau uses an additive learned network (`tanh(W₁s + W₂h)`), Luong uses a multiplicative dot product (`s · h`). (2) The timing — Bahdanau computes attention using the *previous* decoder state (sₜ₋₁), while Luong uses the *current* state (sₜ). In practice, Luong's dot-product variant is the most widely used because it's fast and parameter-free.

---

## A Critical Leap — From Cross-Attention to Self-Attention 🔄

Everything we've discussed so far is **Cross-Attention** — the Decoder (one sequence) attends to the Encoder (a different sequence). English attending to French. The query comes from one place, the keys come from another.

But here's the question that changed everything:

> **What if a sequence attended to *itself*?**

Consider the sentence: "The **cat** sat on the mat because **it** was tired."

What does "it" refer to? A human instantly knows "it" = "the cat." But how does a model figure this out? The word "it" needs to look *backwards* in its own sentence and find the most relevant word. It needs to *attend to itself*.

![Self-Attention: "it" attends to "cat" — resolving the reference](content/large-language-models/natural-language-processing/images/attention_self_attention.png)

This is **Self-Attention** — every word in a sequence computes attention scores with *every other word in the same sequence*. It allows the model to capture long-range dependencies, resolve coreferences (like "it" → "cat"), and understand context — all without any recurrence.

> **💡 "What is Self-Attention?"** Self-Attention (also called intra-attention) is a mechanism where each element in a sequence computes attention scores against *all other elements in the same sequence*. Unlike cross-attention (where queries come from the decoder and keys/values come from the encoder), in self-attention the queries, keys, and values all come from the same input. This allows the model to capture relationships between any two positions in the sequence regardless of distance.

---

## Query, Key, Value — The QKV Framework 🔑

Self-Attention introduces the most important abstraction in modern deep learning: **Query, Key, and Value** (Q, K, V). This framework is the language of attention from here on out — it's used in Transformers, GPT, BERT, and every LLM you've heard of.

### The Library Analogy 📚

Imagine you walk into a library looking for information about "neural networks":

- **Query (Q)** — your search term: "neural networks." It's what you're *looking for*.
- **Key (K)** — the title/index card of every book in the library. It's what each book *advertises* about itself.
- **Value (V)** — the actual content of each book. It's the *information* you'd extract if you picked that book.

You compare your **Query** against every **Key** to find the best matches. Then you read the **Values** of the matching books. A book whose Key closely matches your Query gets a high attention weight, and you read more of its Value.

### The Math

For Self-Attention, we project each input word embedding into three separate vectors using three learned weight matrices:

```
Qᵢ = xᵢ · W_Q     ← "What am I looking for?"
Kᵢ = xᵢ · W_K     ← "What do I contain?"  
Vᵢ = xᵢ · W_V     ← "What information do I carry?"
```

Where:
- **xᵢ** is the input embedding for word i (shape: [d_model])
- **W_Q, W_K, W_V** are learned weight matrices (shape: [d_model, d_k])
- **Qᵢ, Kᵢ, Vᵢ** are the transformed vectors (shape: [d_k])

> **💡 "Why do we need separate Q, K, V? Why not just use the raw embeddings?"** Using the raw embedding for all three roles would force the model to use a single representation for three different purposes — asking questions, advertising content, and providing information. By projecting into separate Q, K, V spaces with *learned* weight matrices, the model can learn different representations for each role. For example, the word "bank" as a Query might focus on "financial institution" features, while as a Key in another context it might advertise "river bank" features. The separation gives the model vastly more expressive power.

### Computing Self-Attention — The Full Pipeline

For a sequence of T words:

```
Step 1: Project all words into Q, K, V
  Q = X · W_Q    shape: [T, d_k]
  K = X · W_K    shape: [T, d_k]
  V = X · W_V    shape: [T, d_v]

Step 2: Compute attention scores (every word against every word)
  Scores = Q · K^T     shape: [T, T]
  
  This gives us a T×T matrix where Score[i][j] = "how much should word i 
  attend to word j?"

Step 3: Scale (we'll explain WHY in a moment)
  Scaled = Scores / sqrt(d_k)

Step 4: Softmax (per row — each word's attention sums to 1)
  Weights = softmax(Scaled)    shape: [T, T]

Step 5: Weighted sum of Values
  Output = Weights · V    shape: [T, d_v]
```

### The Complete Formula

The entire Self-Attention mechanism in one elegant equation:

```
Attention(Q, K, V) = softmax(Q · K^T / sqrt(d_k)) · V
```

This single equation is the beating heart of Transformers, GPT, BERT, and every modern LLM. Memorize it.

### Code: Scaled Dot-Product Attention

```python
import numpy as np

def scaled_dot_product_attention(Q, K, V):
    """
    Scaled Dot-Product Attention.
    
    Q: shape [T, d_k]   — Queries
    K: shape [T, d_k]   — Keys
    V: shape [T, d_v]   — Values
    
    Returns: output [T, d_v], attention_weights [T, T]
    """
    d_k = Q.shape[-1]
    
    # Step 1: Q · K^T → raw scores [T, T]
    scores = Q @ K.T
    
    # Step 2: Scale by sqrt(d_k)
    scores = scores / np.sqrt(d_k)
    
    # Step 3: Softmax per row
    exp_scores = np.exp(scores - scores.max(axis=-1, keepdims=True))
    attn_weights = exp_scores / exp_scores.sum(axis=-1, keepdims=True)
    
    # Step 4: Weighted sum of Values
    output = attn_weights @ V
    
    return output, attn_weights

# Example: Self-Attention on "The cat sat"
np.random.seed(42)
T, d_model, d_k = 3, 8, 4  # 3 words, 8-dim embeddings, 4-dim QKV

X = np.random.randn(T, d_model)          # Word embeddings
W_Q = np.random.randn(d_model, d_k) * 0.1
W_K = np.random.randn(d_model, d_k) * 0.1
W_V = np.random.randn(d_model, d_k) * 0.1

Q = X @ W_Q
K = X @ W_K
V = X @ W_V

output, weights = scaled_dot_product_attention(Q, K, V)

print("Attention Weights (each row sums to 1):")
print(weights.round(3))
# Each row shows how much each word attends to every other word
# Row 0 = how "The" attends to ["The", "cat", "sat"]
```

---

## Why Scale by √d_k? — Preventing Softmax Saturation 📏

This is one of the most commonly asked interview questions about attention, and the answer reveals deep understanding of numerical stability.

### The Problem

When d_k (the dimension of Q and K) is large, the dot products `Q · K^T` grow large in magnitude. Here's why:

If Q and K have elements drawn from a distribution with mean 0 and variance 1, then their dot product has **variance = d_k**:

```python
# Demonstration: dot products grow with dimension
for d_k in [4, 64, 512]:
    q = np.random.randn(d_k)
    k = np.random.randn(d_k)
    dot = q @ k
    print(f"d_k={d_k:3d} → dot product = {dot:8.2f}")

# Typical output:
# d_k=  4 → dot product =    -1.23
# d_k= 64 → dot product =     7.45
# d_k=512 → dot product =   -23.81
```

When you pass these large values into softmax, it **saturates** — the largest score dominates completely, and all other scores collapse to near-zero:

```python
# Softmax saturation demonstration
scores_small = np.array([1.0, 2.0, 3.0])       # Small scores
scores_large = np.array([10.0, 20.0, 30.0])     # Large scores (high d_k)

def softmax(x):
    e = np.exp(x - x.max())
    return e / e.sum()

print(f"Small scores → {softmax(scores_small).round(4)}")
# → [0.0900, 0.2447, 0.6652]   ← smooth distribution, gradient flows!

print(f"Large scores → {softmax(scores_large).round(4)}")
# → [0.0000, 0.0000, 1.0000]   ← saturated! gradient ≈ 0 for positions 0, 1
```

When softmax saturates, the gradients vanish (they're near-zero for all non-maximum positions), and the model **stops learning** — it can't update the attention weights for positions that got crushed to zero.

### The Fix

Dividing by √d_k rescales the variance from d_k back to 1:

```
Variance of Q·K^T = d_k
Variance of Q·K^T / sqrt(d_k) = d_k / d_k = 1  ✅
```

This keeps the scores in a smooth range where softmax produces a well-behaved distribution and gradients flow properly.

> **💡 "Why divide by √d_k in attention?"** The dot product of two d_k-dimensional vectors has variance proportional to d_k. For large d_k, this pushes softmax into saturation (extreme values where one score dominates and gradients vanish). Dividing by √d_k normalizes the variance back to 1, keeping the softmax output smooth and the gradients healthy. Without this scaling, attention with large dimensions would be nearly impossible to train.

---

## Multi-Head Attention — Parallel Perspectives 🎯

So far, we've computed attention once — a single set of Q, K, V projections produces a single attention pattern. But a single attention head can only capture **one type of relationship** at a time.

Consider: "The cat sat on the mat because it was tired."

- One attention pattern might focus on **syntactic** relationships (subject ↔ verb: "cat" ↔ "sat")
- Another might focus on **coreference** ("it" → "cat")
- Another might focus on **positional proximity** (nearby words)
- Another might capture **semantic similarity** ("cat" ↔ "mat" — both nouns referring to physical things)

A single attention head is forced to average all these patterns into one — losing nuance.

### The Solution: Run Attention Multiple Times in Parallel

![Multi-Head Attention: Different heads capture different patterns](content/large-language-models/natural-language-processing/images/attention_multihead.png)

Multi-Head Attention runs **h** separate attention computations (typically h = 8) in parallel, each with its own learned W_Q, W_K, W_V matrices:

```
head₁ = Attention(X·W_Q1, X·W_K1, X·W_V1)
head₂ = Attention(X·W_Q2, X·W_K2, X·W_V2)
  ...
headₕ = Attention(X·W_Qh, X·W_Kh, X·W_Vh)
```

Then all heads are **concatenated** and projected through a final weight matrix:

```
MultiHead(Q, K, V) = Concat(head₁, head₂, ..., headₕ) · W_O
```

### The Dimension Trick

Here's the elegant efficiency: instead of running h full-sized attention heads (which would be h× more expensive), each head operates on a **reduced** dimension:

```
d_model = 512      ← total model dimension
h = 8              ← number of heads
d_k = d_model / h  ← dimension per head = 512 / 8 = 64
```

Each head projects into 64-dimensional Q, K, V spaces. After the h heads run in parallel, their 64-dimensional outputs are concatenated back to 512 dimensions. The total computation cost is roughly the **same** as a single full-dimensional attention head!

### Code: Multi-Head Attention

```python
def multi_head_attention(X, W_Qs, W_Ks, W_Vs, W_O, n_heads):
    """
    Multi-Head Attention.
    
    X:     shape [T, d_model]           — input sequence
    W_Qs:  list of n_heads matrices, each [d_model, d_k]
    W_Ks:  list of n_heads matrices, each [d_model, d_k]
    W_Vs:  list of n_heads matrices, each [d_model, d_v]
    W_O:   shape [n_heads * d_v, d_model]  — output projection
    """
    heads = []
    
    for i in range(n_heads):
        Q = X @ W_Qs[i]    # shape: [T, d_k]
        K = X @ W_Ks[i]    # shape: [T, d_k]
        V = X @ W_Vs[i]    # shape: [T, d_v]
        
        head_output, _ = scaled_dot_product_attention(Q, K, V)
        heads.append(head_output)   # shape: [T, d_v]
    
    # Concatenate all heads: [T, n_heads * d_v]
    concat = np.concatenate(heads, axis=-1)
    
    # Final linear projection: [T, d_model]
    output = concat @ W_O
    
    return output

# With 8 heads, d_model=512:
# Each head: Q,K,V are [T, 64]
# Concat: [T, 512]
# Output: [T, 512]  ← same shape as input! (residual-friendly)
```

### What Do Different Heads Actually Learn?

Researchers have visualized attention heads in trained Transformers and found remarkable specialization:

| Head | Learned Pattern | Example |
|---|---|---|
| Head 1 | **Syntactic dependencies** | Subject → Verb ("cat" → "sat") |
| Head 2 | **Positional / adjacent** | Each word → its immediate neighbor |
| Head 3 | **Coreference resolution** | Pronouns → their referents ("it" → "cat") |
| Head 4 | **Rare/important words** | Focuses on uncommon or content-heavy words |
| Head 5 | **Negation scope** | "not" → the word it negates ("not" → "great") |
| Head 6 | **Punctuation structure** | Clause boundaries, commas, periods |

> **💡 "Why Multi-Head instead of single attention?"** A single attention head computes one set of attention weights per position, forcing it to average multiple types of linguistic relationships (syntax, semantics, coreference, etc.) into a single pattern. Multi-Head Attention runs multiple independent attention computations in parallel, each with its own learned projections, allowing different heads to specialize in different relationship types. Crucially, this comes at roughly the same computational cost as a single full-dimensional head because each head operates on d_model/h dimensions.

---

## Putting It All Together — Attention in Context 🗺️

Let's zoom out and see where each type of attention fits:

| Attention Type | Query From | Key/Value From | Where It's Used |
|---|---|---|---|
| **Bahdanau/Luong** (Cross-Attention) | Decoder hidden state | Encoder hidden states | Seq2Seq translation |
| **Self-Attention** | Same sequence | Same sequence | Within Encoder or Decoder |
| **Multi-Head** | Parallel projections | Parallel projections | Everywhere in Transformers |

### The Evolution

```
Vanilla Encoder-Decoder (2014)
  → One fixed Context Vector per sentence
  → Bottleneck for long sequences

+ Bahdanau Attention (2014)
  → Dynamic Context Vector at every step
  → Decoder "looks back" at ALL encoder states

+ Luong Attention (2015)
  → Simpler scoring (dot product)
  → Faster, fewer parameters

+ Self-Attention (2017)
  → Sequences attend to THEMSELVES
  → No recurrence needed!
  → Q, K, V framework

+ Multi-Head Attention (2017)
  → Parallel attention heads
  → Different heads capture different patterns
  → Foundation of Transformers
```

---

## Summary — What We Learned 🎓

| Concept | Key Takeaway |
|---|---|
| **The Bottleneck** | Fixed-size Context Vector loses information for long sequences |
| **Attention** | Dynamic context — the Decoder looks at ALL encoder states at every step |
| **Bahdanau (Additive)** | Scores via learned network: V^T · tanh(W₁s + W₂h) — the original |
| **Luong (Multiplicative)** | Scores via dot product: s · h — simpler, faster, equally effective |
| **Attention Weights (α)** | Softmax-normalized scores that sum to 1 — a probability distribution |
| **Cross-Attention** | Query from Decoder, Keys/Values from Encoder (two different sequences) |
| **Self-Attention** | Q, K, V all from the same sequence — captures internal relationships |
| **Q, K, V** | Query = "what I'm looking for", Key = "what I advertise", Value = "what I contain" |
| **Scaled Dot-Product** | Divide by √d_k to prevent softmax saturation and vanishing gradients |
| **Multi-Head Attention** | h parallel heads on d_model/h dims each — different heads, different patterns |

---

## The Final Question... 🤔

We now have all the ingredients:
- **Self-Attention** lets a sequence understand its own context
- **Multi-Head Attention** captures multiple relationship types in parallel
- **Scaled Dot-Product** keeps everything numerically stable

But notice something: in Bahdanau and Luong attention, we still used LSTMs to process the sequence and *then* applied attention on top. The LSTM is still sequential — word 1 before word 2 before word 3. On a GPU with thousands of cores, this is painfully slow.

What if we **removed the LSTM entirely** and used *only* attention?

No recurrence. No sequential processing. Every word attends to every other word **simultaneously**, in a single matrix multiplication. Entire sentences processed in parallel. Training that takes weeks with LSTMs could take days.

In 2017, a team at Google published a paper with an unforgettable title: **"Attention Is All You Need."** They built an architecture using *nothing but* multi-head self-attention, positional encodings, and feed-forward networks. No RNNs. No LSTMs. No convolutions.

They called it the **Transformer** — and it is the architecture behind GPT, BERT, T5, LLaMA, Claude, Gemini, and every modern Large Language Model.

That's the next post. And it changes everything. ⚡

---

## What's Next? 🚀

```
RNNs → LSTMs → Encoder-Decoder → Attention → ???
```

We've traveled from simple sequence memory (RNNs) through selective memory (LSTMs), to reading-then-writing (Encoder-Decoder), to dynamically focusing on what matters (Attention). Each step solved a real limitation of the previous architecture.

But the LSTM backbone remains — sequential, slow, and unable to fully exploit modern hardware. The next architecture strips it away entirely and builds *everything* from attention alone.

👉 **[Transformers — Attention Is All You Need](content/large-language-models/natural-language-processing/transformers.md)**

---

Got questions or suggestions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*


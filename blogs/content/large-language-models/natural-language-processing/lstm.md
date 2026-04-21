---
title: "Long Short-Term Memory (LSTM) & Gated Recurrent Unit (GRU)"
date: 2026-04-18
tags: [nlp, lstm, gru, rnn, deep-learning, sequence-models, gates, vanishing-gradient, cell-state]
description: From the RNN's vanishing gradient problem to the LSTM's elegant solution — covering the cell state conveyor belt, the forget-input-output gate trio with full math, the gradient highway that kills vanishing gradients, the GRU's streamlined two-gate alternative with reset and update gates, complete forward passes in Python, and when to choose LSTMs vs GRUs vs vanilla RNNs.
---

# The Fix — Selective Memory 🧠🔒

In our [RNN blog](content/large-language-models/natural-language-processing/rnn.md), we built a network that finally gave neural networks **memory** — the ability to read words one at a time and carry context forward. Then in our [End-to-End RNN post](content/large-language-models/natural-language-processing/rnn-sentiment-analysis-mlops.md), we pushed that vanilla RNN into a production-grade MLOps pipeline — complete with DVC, MLflow, Docker, and CI/CD.

But even with all that engineering polish, the core architecture still has a fatal flaw.

The vanishing gradient problem means that after ~15 words, the gradient reaching the earliest time steps is essentially **zero**. The RNN can't learn long-range dependencies. It forgets the beginning of the sentence before reaching the end. The sentence "I grew up in **France** and after many years of living abroad I speak fluent **___**" is unsolvable — the word "France" has faded to nothing by the time the model needs it.

We ended the RNN theory post with a wish list:
- A **memory cell** that can selectively remember and forget
- **Gates** that control what information flows through
- A design that allows gradients to flow unchanged across long distances

Every single one of those wishes is granted by the **Long Short-Term Memory (LSTM)** network.

---

## The Core Intuition — A Conveyor Belt 🏭

Before diving into the math, let's build an intuition with an analogy.

### The RNN's Problem: One Notebook

Think of the vanilla RNN as a student who has **one small notebook**. Every time a new word arrives, the student erases everything and rewrites the entire context. After a few pages of erasing and rewriting, the early notes are completely gone. The notebook has been overwritten too many times.

### The LSTM's Solution: A Conveyor Belt + Selective Gates

Now imagine a **factory conveyor belt** running horizontally. Items (information) sit on the belt and move forward through time. At each station (time step), three workers stand by:

1. **The Forget Worker** (🔴) — looks at each item on the belt and decides: "Is this still relevant? Should I keep it or throw it off?"
2. **The Input Worker** (🟢) — looks at the new incoming material and decides: "Is this important enough to place on the belt?"
3. **The Output Worker** (🔵) — looks at everything on the belt and decides: "What should I report to the outside world right now?"

The belt itself just moves forward — it doesn't transform or multiply. Information that survives the Forget Worker and gets placed by the Input Worker can travel **hundreds of steps** without degradation.

![The Conveyor Belt Analogy — RNN vs LSTM Memory](content/large-language-models/natural-language-processing/images/lstm_conveyor_belt_analogy.png)

That conveyor belt is the **cell state** — and those three workers are the **gates**. Let's formalize them.

---

## The LSTM Cell — Full Architecture 🏗️

Here is the complete LSTM cell. Don't panic — we'll break it down gate by gate in the next sections.

![LSTM Cell — The Three Gates and Cell State](content/large-language-models/natural-language-processing/images/lstm_cell_gates.png)

### The Key Components

Every LSTM cell maintains **two** pieces of state (unlike the RNN which has only one):

| Component | Symbol | Role | Analogy |
|---|---|---|---|
| **Cell State** | Cₜ | Long-term memory — the conveyor belt | A notebook you rarely erase |
| **Hidden State** | hₜ | Short-term memory — what you output right now | Your working summary |

The cell state runs along the top — the golden arrow in the diagram. It carries long-term information. The hidden state is what gets passed to the **output** and to the **next time step** as context (just like the RNN's output did).

### The Three Gates

Each gate is a **neural network** in itself — it has its own weights, bias, and a **sigmoid activation** that outputs values between 0 and 1:

| Gate | Symbol | Activation | Purpose |
|---|---|---|---|
| **Forget Gate** | fₜ | σ (sigmoid) | What to **erase** from long-term memory |
| **Input Gate** | iₜ | σ (sigmoid) | What to **write** to long-term memory |
| **Output Gate** | oₜ | σ (sigmoid) | What to **read** from long-term memory |

> **Why sigmoid?** Because sigmoid outputs values between 0 and 1 — perfect for representing "how much" to forget, write, or read. A value of 0 means "completely block this," and 1 means "completely pass this through." It acts like a **dimmer switch**, not an on/off toggle.

Now let's walk through each gate, step by step.

---

## Step 1 — The Forget Gate 🔴 "What should I erase?"

The forget gate is the first decision point. It looks at the **previous hidden state** (hₜ₋₁) and the **current input** (xₜ), and for each element in the cell state, outputs a number between 0 and 1:

![Step 1 — The Forget Gate](content/large-language-models/natural-language-processing/images/lstm_forget_gate_detail.png)

### The Math

```
fₜ = σ(W_f · [hₜ₋₁, xₜ] + b_f)
```

Where:
- **[hₜ₋₁, xₜ]** — concatenation of previous hidden state and current input
- **W_f** — the forget gate's weight matrix (learned during training)
- **b_f** — the forget gate's bias vector (learned during training)
- **σ** — sigmoid activation → outputs a vector of values in [0, 1]

### What Does It Do?

The output fₜ is a vector of "keep scores" — one value per element of the cell state:

- **fₜ = 1** → "Keep this memory completely" (the gradient passes through untouched!)
- **fₜ = 0** → "Erase this memory completely"
- **fₜ = 0.7** → "Keep 70% of this memory"

### Real-World Example

Consider a language model tracking the **subject** of a sentence:

> "**The cat** sat on the mat. **The dog** then walked in and..."

When the model encounters "The dog" — a new subject — the forget gate should output values near **0** for the cell state elements that stored "cat" information, effectively saying: "We're not talking about the cat anymore. Forget it."

---

## Step 2 — The Input Gate 🟢 "What should I remember?"

The input gate decides what **new information** to store in the cell state. This happens in two parallel paths:

![Step 2 — The Input Gate](content/large-language-models/natural-language-processing/images/lstm_input_gate_detail.png)

### The Math — Two Parts

**Part A — What to update (the gatekeeper):**
```
iₜ = σ(W_i · [hₜ₋₁, xₜ] + b_i)
```
This produces a vector of values between 0 and 1 — "how much of each new candidate value should we actually write?"

**Part B — The candidate values (the content):**
```
C̃ₜ = tanh(W_C · [hₜ₋₁, xₜ] + b_C)
```
This produces a vector of **candidate values** between -1 and +1 — the actual new information that *could* be written to the cell state.

### Why Two Parts?

Think of it this way:
- **iₜ** (sigmoid) = "**Should** we write to this memory slot?" (yes/no/maybe)
- **C̃ₜ** (tanh) = "**What** should we write?" (the actual content)

The two are multiplied element-wise: `iₜ ⊗ C̃ₜ`. This gives us the **filtered new information** — only the parts that the gate deemed important actually get written.

> **Why tanh for candidates?** Because tanh outputs values between -1 and +1, which means it can both **add** and **subtract** from the cell state. Sigmoid can only add (since its output is always positive). The tanh gives the candidate values direction — "increase this" or "decrease this."

### Real-World Example

> "I grew up in **France** and I speak fluent ___"

When the model reads "France," the input gate should:
- **iₜ** outputs high values for the "country/language" memory slots
- **C̃ₜ** produces a representation encoding "France"
- Together, they write "France" into the cell state

Later, when predicting the blank, this stored information will produce "French."

---

## Step 3 — Update the Cell State ✏️ "Selectively forget and remember"

Now we combine the forget gate and input gate to update the cell state:

```
Cₜ = fₜ ⊗ Cₜ₋₁  +  iₜ ⊗ C̃ₜ
      ─────────     ──────────
      what we keep   what we add
      from the past  that's new
```

This is the **heart of the LSTM**. Read it carefully:

1. **fₜ ⊗ Cₜ₋₁** — element-wise multiply the old cell state by the forget gate. This erases what we decided to forget.
2. **iₜ ⊗ C̃ₜ** — element-wise multiply the candidate values by the input gate. This selects only the new information we decided to keep.
3. **Add them** — the new cell state is the old memories that survived + the new memories we added.

> **Critical insight — Additive updates:** Notice that the cell state update is an **addition**, not a multiplication. This is the key design choice that kills the vanishing gradient problem! When we backpropagate through an addition, the gradient flows through **unchanged**. Compare this to the vanilla RNN where the hidden state was computed by multiplying and passing through tanh — every step shrank the gradient.

---

## Step 4 — The Output Gate 🔵 "What should I tell the world?"

Finally, the output gate decides what part of the cell state to expose as the **hidden state** (the output):

![Step 3 — The Output Gate](content/large-language-models/natural-language-processing/images/lstm_output_gate_detail.png)

### The Math

```
oₜ = σ(W_o · [hₜ₋₁, xₜ] + b_o)
hₜ = oₜ ⊗ tanh(Cₜ)
```

Where:
- **oₜ** — the output gate values (which parts of cell state to expose)
- **tanh(Cₜ)** — squash the cell state values to [-1, 1]
- **hₜ** — the final hidden state that gets passed on

### Why tanh(Cₜ)?

The cell state Cₜ can accumulate very large or small values over time (since it's updated by addition). The tanh squashes it back to [-1, 1], keeping the values well-behaved before outputting.

### Real-World Example

> "The animal didn't cross the road because **it** was too tired."

The cell state carries information about both "animal" and "road." But the context "was too tired" is only relevant to the **animal**. The output gate selects the "animal" information from the cell state and suppresses the "road" information — producing a hidden state that says "the animal is tired."

---

## The Complete LSTM Equations — All in One Place 📐

Let's collect every equation for one time step. At each step t, given input xₜ, previous hidden state hₜ₋₁, and previous cell state Cₜ₋₁:

```
+-------------------------------------------------------------+
|                    LSTM - One Time Step                      |
+-------------------------------------------------------------+
|                                                             |
|  Forget Gate:   ft  = s(W_f . [h(t-1), xt] + b_f)          |
|  Input Gate:    it  = s(W_i . [h(t-1), xt] + b_i)          |
|  Candidate:     Ct~ = tanh(W_C . [h(t-1), xt] + b_C)       |
|  Cell State:    Ct  = ft * C(t-1)  +  it * Ct~              |
|  Output Gate:   ot  = s(W_o . [h(t-1), xt] + b_o)          |
|  Hidden State:  ht  = ot * tanh(Ct)                         |
|                                                             |
|  Inputs:  xt, h(t-1), C(t-1)                                |
|  Outputs: ht, Ct  (passed to next time step)                |
|                                                             |
+-------------------------------------------------------------+

Where: s = sigmoid, * = element-wise multiply, . = matrix multiply
```

> **Weight count comparison:** A vanilla RNN has **2 weight matrices** (W and W'). An LSTM has **8 weight matrices** (W_f, W_i, W_C, W_o — each with separate parameters for input and hidden state) and **4 bias vectors**. That's roughly **4× the parameters** — the price we pay for the ability to selectively remember.

---

## Forward Pass in Python 🐍

Let's implement the LSTM forward pass from scratch. Compare this to the [RNN forward pass](content/large-language-models/natural-language-processing/rnn.md) — you'll see the same structure, but now with gates:

```python
import numpy as np

def sigmoid(x):
    """Sigmoid activation — outputs values between 0 and 1."""
    return 1 / (1 + np.exp(-np.clip(x, -500, 500)))

def lstm_forward(inputs, Wf, Wi, Wc, Wo, bf, bi, bc, bo, h0, C0):
    """
    Forward pass of a single LSTM layer.
    
    inputs: list of word vectors [x1, x2, ..., xT]
    Wf, Wi, Wc, Wo: weight matrices for each gate 
                     (shape: [hidden_dim + input_dim, hidden_dim])
    bf, bi, bc, bo: bias vectors for each gate (shape: [hidden_dim])
    h0: initial hidden state (shape: [hidden_dim])
    C0: initial cell state (shape: [hidden_dim])
    """
    h = h0          # Hidden state (short-term memory)
    C = C0          # Cell state (long-term memory — the conveyor belt!)
    
    hidden_states = []
    cell_states = []
    
    for xt in inputs:
        # Concatenate: [hₜ₋₁, xₜ]
        combined = np.concatenate([h, xt])
        
        # === Gate 1: Forget Gate ===
        # "What should I erase from long-term memory?"
        f = sigmoid(combined @ Wf + bf)         # fₜ ∈ [0, 1]
        
        # === Gate 2: Input Gate ===
        # "What new information should I write?"
        i = sigmoid(combined @ Wi + bi)         # iₜ ∈ [0, 1]  (how much to write)
        C_tilde = np.tanh(combined @ Wc + bc)   # C̃ₜ ∈ [-1, 1] (what to write)
        
        # === Update Cell State (the conveyor belt!) ===
        # Cₜ = fₜ ⊗ Cₜ₋₁  +  iₜ ⊗ C̃ₜ
        C = f * C + i * C_tilde   # ← This ADDITIVE update is why gradients survive!
        
        # === Gate 3: Output Gate ===
        # "What should I tell the outside world?"
        o = sigmoid(combined @ Wo + bo)         # oₜ ∈ [0, 1]
        h = o * np.tanh(C)                      # hₜ = oₜ ⊗ tanh(Cₜ)
        
        hidden_states.append(h)
        cell_states.append(C)
    
    return hidden_states, cell_states

# ─── Example: Process a 4-word sentence ───
np.random.seed(42)

input_dim = 3    # Each word is a 3D vector (e.g., from Word2Vec)
hidden_dim = 5   # LSTM has 5 hidden units

# 4 word vectors
words = [np.random.randn(input_dim) for _ in range(4)]

# Initialize weights (input_dim + hidden_dim → hidden_dim for each gate)
combined_dim = input_dim + hidden_dim
Wf = np.random.randn(combined_dim, hidden_dim) * 0.1
Wi = np.random.randn(combined_dim, hidden_dim) * 0.1
Wc = np.random.randn(combined_dim, hidden_dim) * 0.1
Wo = np.random.randn(combined_dim, hidden_dim) * 0.1

bf = np.zeros(hidden_dim)
bi = np.zeros(hidden_dim)
bc = np.zeros(hidden_dim)
bo = np.zeros(hidden_dim)

h0 = np.zeros(hidden_dim)   # No previous hidden state
C0 = np.zeros(hidden_dim)   # No previous cell state (empty conveyor belt!)

hidden_states, cell_states = lstm_forward(words, Wf, Wi, Wc, Wo, bf, bi, bc, bo, h0, C0)

print("=== LSTM Hidden States (short-term memory) ===")
for t, h in enumerate(hidden_states, 1):
    print(f"h{t} (after word {t}): {h.round(4)}")

print("\n=== LSTM Cell States (long-term memory — the conveyor belt) ===")
for t, C in enumerate(cell_states, 1):
    print(f"C{t} (after word {t}): {C.round(4)}")

print("\n✅ Notice: BOTH h and C carry information forward!")
print("   h = what we output now (short-term)")
print("   C = what we remember for later (long-term)")
```

> **Compare to the RNN:** In our [RNN forward pass code](content/large-language-models/natural-language-processing/rnn.md), we had a single equation: `O = np.tanh(xt @ W + O @ W_prime)`. The LSTM replaces that one equation with **six equations** — but each one has a clear, interpretable purpose.

---

## Why Gradients Survive — The Gradient Highway 🛣️

This is the most important section. Let's understand *exactly* why LSTMs solve the vanishing gradient problem that killed vanilla RNNs.

![Gradient Flow Comparison — RNN vs LSTM](content/large-language-models/natural-language-processing/images/lstm_gradient_flow_comparison.png)

Recall from our [RNN blog](content/large-language-models/natural-language-processing/rnn.md): the vanilla RNN's gradient must pass through the **tanh derivative** (always < 1) at every time step. After 50 steps, the gradient shrinks to ~0.00018 — essentially zero. The network can't learn what happened at the beginning of the sentence.

Now look at the LSTM's cell state update:

```
Cₜ = fₜ ⊗ Cₜ₋₁  +  iₜ ⊗ C̃ₜ
```

When we backpropagate through this equation:

```
∂Cₜ / ∂Cₜ₋₁ = fₜ
```

The gradient of the cell state with respect to the **previous** cell state is simply **fₜ** — the forget gate! And here's the crucial difference: fₜ is a **learned** parameter. If the LSTM needs to carry information across 100 time steps, it learns to set fₜ ≈ 1. When fₜ = 1, the gradient passes through **completely unchanged** — like a highway with no speed bumps.

```
RNN:   gradient × tanh' × tanh' × tanh' × tanh' → 💀 dead

LSTM:  gradient × fₜ × fₜ₋₁ × fₜ₋₂ × fₜ₋₃ → ✅ alive
       (where fₜ can be close to 1 — the network LEARNS to keep it open!)
```

Furthermore, the cell state update is an **addition** (`Cₜ = fₜ ⊗ Cₜ₋₁ + iₜ ⊗ C̃ₜ`). During backpropagation, the gradient of an addition distributes equally to both branches — it doesn't get multiplied or shrunk. This is fundamentally different from the multiplicative updates in vanilla RNNs.

> **Can vanishing gradients still happen in LSTMs?** Yes, but it's much harder. If the forget gate learns fₜ ≈ 0 for many steps, the gradient will still vanish. But unlike RNNs where vanishing is **guaranteed** by the math, in LSTMs the forget gate is **learnable** — the network can choose to keep the gradient highway open. In practice, LSTMs can handle sequences of **200-500+ tokens** compared to the RNN's limit of ~15.

---

## LSTM Parameters — How Many Weights? 🔢

One common question: how many parameters does an LSTM have? Let's count:

```
Given:
  d = input dimension (e.g., word vector size = 100)
  h = hidden dimension (e.g., 128 LSTM units)

Each gate has:
  Weight matrix: (d + h) × h     ← input + hidden → hidden
  Bias vector:   h

Total per gate: (d + h) × h + h = (d + h + 1) × h

We have 4 sets of weights (forget, input, candidate, output):
  Total parameters = 4 × (d + h + 1) × h
```

For d = 100, h = 128:

```python
d, h = 100, 128
params = 4 * (d + h + 1) * h
print(f"LSTM parameters: {params:,}")
# Output: LSTM parameters: 117,248

# Compare to vanilla RNN:
rnn_params = (d * h) + (h * h) + h  # W, W', bias
print(f"RNN parameters:  {rnn_params:,}")
# Output: RNN parameters:  29,440

print(f"\nLSTM has {params / rnn_params:.1f}× more parameters than RNN")
# Output: LSTM has 4.0× more parameters than RNN
```

> **Is 4× more always worth it?** For sequences longer than ~15 tokens — **absolutely yes.** The extra parameters buy you the ability to learn long-range dependencies. For very short sequences (5-10 words), a vanilla RNN might suffice. But in NLP, sentences commonly exceed 20 words, and paragraphs far more.

---

## RNN vs LSTM — Quick Comparison 📊

![Simple RNN vs LSTM vs GRU — Architecture Comparison](content/large-language-models/natural-language-processing/images/rnn_lstm_gru_comparison.png)

| Feature | Vanilla RNN | LSTM |
|---|---|---|
| **States** | 1 (hₜ) | 2 (hₜ + Cₜ) |
| **Gates** | 0 | 3 (forget, input, output) |
| **Parameters** | ~(d+h)×h | ~4×(d+h)×h |
| **Max sequence length** | ~15 tokens | ~500+ tokens |
| **Gradient behavior** | Vanishes exponentially | Controlled by learned forget gate |
| **When to use** | Short sequences, simple patterns | Long sequences, complex dependencies |

We'll extend this comparison to include the **GRU** in a later section — it sits between these two in both complexity and parameters.

---

## When to Use LSTMs — Practical Decision Guide 🎯

### ✅ Use LSTMs when:
- Your sequences are **longer than 15-20 tokens** (most real NLP tasks)
- You need to capture **long-range dependencies** (e.g., "France" → "French")
- **Order matters** — sentiment analysis, translation, time-series
- You're working with **variable-length** sequences

### ❌ Don't use LSTMs when:
- Your data is **tabular** — use ANNs (from our [ANN blog](content/large-language-models/deep-learning/your-first-ann.md))
- Your sequences are very short (< 10 tokens) — vanilla RNN might suffice
- You need **parallelization** — LSTMs are sequential by nature; consider [Transformers](content/large-language-models/natural-language-processing/transformers.md) for massive parallelism
- **Training speed** is critical — LSTMs are ~4× slower per step than vanilla RNNs

### 🏢 Real-World LSTM Applications

| Application | Why LSTM? |
|---|---|
| **Machine Translation** | Source sentences can be 50+ words; need full context |
| **Speech Recognition** | Audio frames form long sequences (hundreds of steps) |
| **Text Generation** | Must remember themes/topics across paragraphs |
| **Sentiment Analysis** | Negation at the start affects meaning at the end ("I do **not** think this is great") |
| **Time Series Forecasting** | Seasonal patterns span months (long-range temporal dependency) |
| **Music Composition** | Musical phrases repeat and vary across hundreds of notes |

---

## Bidirectional LSTM — Reading Forward *and* Backward 🔄

So far, our LSTM reads the sentence left-to-right — word 1, then word 2, then word 3. But think about how *you* understand language. When you read:

> "The movie was **not** great"

The word "not" changes the meaning of "great" — but a left-to-right LSTM processes "not" *before* it ever sees "great." It has to somehow store the negation and hope it's relevant later. What if the model could also read right-to-left, so that when it processes "not," it *already knows* that "great" is coming?

That's exactly what a **Bidirectional LSTM (BiLSTM)** does.

![Bidirectional LSTM — Forward and Backward Context](content/large-language-models/natural-language-processing/images/lstm_bidirectional.png)

### How It Works

A BiLSTM runs **two separate LSTMs** on the same input:

| Direction | Processes | Captures |
|---|---|---|
| **Forward LSTM →** | word₁ → word₂ → word₃ → ... → wordₙ | Left context (what came *before*) |
| **Backward LSTM ←** | wordₙ → wordₙ₋₁ → ... → word₂ → word₁ | Right context (what comes *after*) |

At each time step t, the final hidden state is the **concatenation** of both directions:

```
hₜ = [h→ₜ ; h←ₜ]
```

This means every word in the sequence has access to the **full context** — both what came before it *and* what comes after it.

### The Math

```
Forward:   h→ₜ = LSTM_forward(xₜ, h→ₜ₋₁, C→ₜ₋₁)
Backward:  h←ₜ = LSTM_backward(xₜ, h←ₜ₊₁, C←ₜ₊₁)
Combined:  hₜ  = [h→ₜ ; h←ₜ]        (concatenation)
```

Each direction has its **own set of weights** — so a BiLSTM has **2× the parameters** of a unidirectional LSTM (8× a vanilla RNN).

### Why It Matters — A Concrete Example

Consider sentiment analysis on these two sentences:

> 1. "The food was **not** good at all"
> 2. "The food was **not** bad at all"

A unidirectional LSTM processing left-to-right hits "not" and has to guess: is it negating something positive or something negative? The backward LSTM already knows — it's read "good" or "bad" first. By combining both directions, the BiLSTM gets the full picture.

```python
import numpy as np

def bilstm_forward(inputs, forward_params, backward_params):
    """
    Simplified Bidirectional LSTM forward pass.
    
    inputs: list of word vectors [x1, x2, ..., xT]
    forward_params: dict with Wf, Wi, Wc, Wo, bf, bi, bc, bo, h0, C0
    backward_params: dict with same keys (separate weights!)
    """
    # Forward pass: left → right
    fwd_hidden, fwd_cell = lstm_forward(
        inputs, **forward_params
    )
    
    # Backward pass: right → left
    bwd_hidden, bwd_cell = lstm_forward(
        inputs[::-1], **backward_params  # Reverse the input!
    )
    bwd_hidden = bwd_hidden[::-1]  # Reverse back to align with forward
    
    # Concatenate at each time step
    combined = [
        np.concatenate([fwd_h, bwd_h])
        for fwd_h, bwd_h in zip(fwd_hidden, bwd_hidden)
    ]
    
    return combined

# Result: each combined[t] has 2 × hidden_dim dimensions
# combined[t] = [left_context_of_word_t ; right_context_of_word_t]
```

> **When to use BiLSTM vs LSTM?** Use BiLSTM when you have the **entire sequence available upfront** — sentiment analysis, named entity recognition, text classification. Don't use it for **real-time generation** (predicting the next word) because you can't look at future words that haven't been generated yet. We already used a BiLSTM (well, Bi-RNN) in our [End-to-End Sentiment Analysis pipeline](content/large-language-models/natural-language-processing/rnn-sentiment-analysis-mlops.md) — the same idea applies here with LSTMs.

| Feature | Unidirectional LSTM | Bidirectional LSTM |
|---|---|---|
| **Context** | Left only (past) | Left + Right (past + future) |
| **Parameters** | 4×(d+h)×h | 8×(d+h)×h |
| **Output dim** | h | 2h |
| **Use case** | Text generation, real-time | Classification, NER, tagging |
| **Can see future?** | ❌ No | ✅ Yes |

---

## The GRU — A Streamlined Alternative 🔀

In 2014, Kyunghyun Cho et al. proposed the **Gated Recurrent Unit (GRU)** — a simpler variant that achieves comparable performance to the LSTM with **fewer gates** and **fewer parameters**. The core idea: merge the forget and input gates into a single **update gate**, eliminate the separate cell state entirely, and add a **reset gate** to control how much past context to consider when computing new candidates.

### The Key Difference: Two Gates Instead of Three

The LSTM has three gates (forget, input, output) and two state vectors (hₜ, Cₜ). The GRU distills this down to **two gates** and **one state vector**:

| Component | LSTM | GRU |
|---|---|---|
| **Gates** | 3 (forget, input, output) | 2 (reset, update) |
| **State vectors** | 2 (hₜ + Cₜ) | 1 (hₜ only) |
| **Parameters** | ~4×(d+h)×h | ~3×(d+h)×h |
| **Separate long-term memory?** | ✅ Yes (cell state Cₜ) | ❌ No (hidden state does everything) |

### GRU Gate 1 — The Reset Gate rₜ 🔄 "How much past context should I use?"

The reset gate decides how much of the **previous hidden state** to consider when computing the new candidate value. Think of it as: "Should I use my full memory, or start fresh?"

```
rₜ = σ(W_r · [hₜ₋₁, xₜ] + b_r)
```

Where:
- **[hₜ₋₁, xₜ]** — concatenation of previous hidden state and current input
- **W_r** — the reset gate's weight matrix
- **b_r** — the reset gate's bias vector
- **σ** — sigmoid activation → output in [0, 1]

**What does it do?**
- **rₜ ≈ 1** → "Use all of my previous memory" (the candidate sees the full past)
- **rₜ ≈ 0** → "Ignore my previous memory" (the candidate computes almost entirely from the current input — like a fresh start)

**Real-World Example:** In the sentence "The cat sat on the mat. **A dog** then walked in" — when the model processes "A dog," the reset gate can output values near 0, effectively saying: "Forget the cat context; this is a brand new subject. Compute the candidate from scratch."

### GRU Gate 2 — The Update Gate zₜ 🔄 "How much should I update?"

The update gate serves **double duty** — it replaces both the LSTM's forget gate and input gate in a single mechanism. It decides how much of the old hidden state to **keep** versus how much of the new candidate to **accept**.

```
zₜ = σ(W_z · [hₜ₋₁, xₜ] + b_z)
```

**What does it do?**
- **zₜ ≈ 1** → "Keep the old hidden state as-is" (no update — information passes through unchanged, like the LSTM's forget gate set to 1)
- **zₜ ≈ 0** → "Replace the old hidden state with the new candidate" (fresh information overwrites the past)

> **The LSTM needs separate forget and input gates that can be set independently.** For instance, it can forget old info (fₜ = 0) while simultaneously writing new info (iₜ = 1). The GRU **couples** these decisions: the fraction you keep (zₜ) and the fraction you replace (1 - zₜ) must always sum to 1. This is a simpler but less flexible design.

### The Candidate Hidden State h̃ₜ

The candidate is where the reset gate does its work — it controls how much of the previous hidden state participates in computing new content:

```
h̃ₜ = tanh(W_h · [rₜ ⊗ hₜ₋₁, xₜ] + b_h)
```

Notice **rₜ ⊗ hₜ₋₁** — the reset gate element-wise multiplies the previous hidden state *before* it enters the tanh computation. When rₜ ≈ 0, the previous hidden state is zeroed out, and h̃ₜ is computed purely from the current input xₜ.

### The Final Hidden State Update

The new hidden state is a **linear interpolation** between the old state and the candidate:

```
hₜ = zₜ ⊗ hₜ₋₁  +  (1 - zₜ) ⊗ h̃ₜ
     ──────────     ──────────────
     what we keep    what we replace
     from the past   with new content
```

This is elegant: the update gate zₜ acts as a **dial** between "keep everything" (zₜ = 1 → hₜ = hₜ₋₁) and "replace everything" (zₜ = 0 → hₜ = h̃ₜ). There's no separate cell state — the hidden state itself carries both long-term and short-term information.

> **Gradient perspective:** When zₜ ≈ 1, the hidden state passes through unchanged (hₜ ≈ hₜ₋₁), and the gradient flows unimpeded — the same "gradient highway" trick as the LSTM's cell state. The GRU achieves gradient survival without needing a separate conveyor belt.

### The Complete GRU Equations

```
+-------------------------------------------------------------+
|                    GRU - One Time Step                       |
+-------------------------------------------------------------+
|                                                             |
|  Reset Gate:    rt  = s(W_r . [h(t-1), xt] + b_r)          |
|  Update Gate:   zt  = s(W_z . [h(t-1), xt] + b_z)          |
|  Candidate:     ht~ = tanh(W_h . [rt * h(t-1), xt] + b_h)  |
|  Hidden State:  ht  = zt * h(t-1)  +  (1 - zt) * ht~       |
|                                                             |
|  Inputs:  xt, h(t-1)                                        |
|  Outputs: ht  (passed to next time step)                    |
|                                                             |
+-------------------------------------------------------------+

Where: s = sigmoid, * = element-wise multiply, . = matrix multiply
```

Compare this to the LSTM's 6-equation block — the GRU achieves the same core idea (gated information flow) with only **4 equations** and **3 weight matrices** instead of 4.

### GRU Forward Pass in Python 🐍

```python
import numpy as np

def sigmoid(x):
    """Sigmoid activation — outputs values between 0 and 1."""
    return 1 / (1 + np.exp(-np.clip(x, -500, 500)))

def gru_forward(inputs, Wr, Wz, Wh, br, bz, bh, h0):
    """
    Forward pass of a single GRU layer.
    
    inputs: list of word vectors [x1, x2, ..., xT]
    Wr, Wz, Wh: weight matrices for reset, update, and candidate
                (shape: [hidden_dim + input_dim, hidden_dim])
    br, bz, bh: bias vectors (shape: [hidden_dim])
    h0: initial hidden state (shape: [hidden_dim])
    """
    h = h0
    hidden_states = []
    
    for xt in inputs:
        combined = np.concatenate([h, xt])
        
        # === Gate 1: Reset Gate ===
        # "How much past context should I use for the candidate?"
        r = sigmoid(combined @ Wr + br)          # rₜ ∈ [0, 1]
        
        # === Gate 2: Update Gate ===
        # "How much of the old state should I keep vs replace?"
        z = sigmoid(combined @ Wz + bz)          # zₜ ∈ [0, 1]
        
        # === Candidate Hidden State ===
        # Reset gate filters the previous hidden state BEFORE computing candidate
        combined_reset = np.concatenate([r * h, xt])  # rₜ ⊗ hₜ₋₁
        h_tilde = np.tanh(combined_reset @ Wh + bh)   # h̃ₜ ∈ [-1, 1]
        
        # === Final Hidden State (linear interpolation) ===
        # hₜ = zₜ ⊗ hₜ₋₁ + (1 - zₜ) ⊗ h̃ₜ
        h = z * h + (1 - z) * h_tilde  # ← Update gate controls the mix!
        
        hidden_states.append(h)
    
    return hidden_states

# ─── Example: Process a 4-word sentence ───
np.random.seed(42)

input_dim = 3    # Each word is a 3D vector
hidden_dim = 5   # GRU has 5 hidden units

# 4 word vectors
words = [np.random.randn(input_dim) for _ in range(4)]

# Initialize weights (3 weight matrices instead of LSTM's 4)
combined_dim = input_dim + hidden_dim
Wr = np.random.randn(combined_dim, hidden_dim) * 0.1
Wz = np.random.randn(combined_dim, hidden_dim) * 0.1
Wh = np.random.randn(combined_dim, hidden_dim) * 0.1

br = np.zeros(hidden_dim)
bz = np.zeros(hidden_dim)
bh = np.zeros(hidden_dim)

h0 = np.zeros(hidden_dim)

hidden_states = gru_forward(words, Wr, Wz, Wh, br, bz, bh, h0)

print("=== GRU Hidden States ===")
for t, h in enumerate(hidden_states, 1):
    print(f"h{t} (after word {t}): {h.round(4)}")

print("\n✅ Notice: Only ONE state vector — no separate cell state!")
print("   The hidden state carries BOTH long-term and short-term information.")
```

### LSTM vs GRU — When to Choose Which? 🤔

| Factor | LSTM | GRU |
|---|---|---|
| **Parameters** | 4 × (d+h) × h | 3 × (d+h) × h (~25% fewer) |
| **Training speed** | Slower | Faster (fewer matrix operations) |
| **Memory usage** | Higher (two state vectors) | Lower (one state vector) |
| **Flexibility** | Forget and input gates are **independent** | Update gate **couples** keep vs replace (must sum to 1) |
| **Long sequences (500+)** | Slight edge (separate cell state gives more control) | Comparable in most benchmarks |
| **Small datasets** | Can overfit more (more params) | Often generalizes better (fewer params) |
| **Default choice** | When you need maximum control over memory | When you want comparable performance at lower cost |

> **In practice:** For most NLP tasks, LSTM and GRU perform **nearly identically**. The GRU's simplicity makes it faster to train and easier to tune — so it's often the better starting point unless you have a specific reason to use LSTM (e.g., tasks requiring very precise memory control over extremely long sequences). When in doubt, try both and compare on your validation set.

---

## Summary — What We Learned 🎓

| Concept | Key Takeaway |
|---|---|
| **Cell State (Cₜ)** | The "conveyor belt" — carries long-term memory across time steps via additive updates |
| **Forget Gate (fₜ)** | Sigmoid gate that decides what to erase from long-term memory |
| **Input Gate (iₜ)** | Sigmoid gate + tanh candidate that decides what new info to write |
| **Output Gate (oₜ)** | Sigmoid gate that decides what to expose as the current output |
| **Cell State Update** | Cₜ = fₜ ⊗ Cₜ₋₁ + iₜ ⊗ C̃ₜ — **additive** (gradients survive!) |
| **Gradient Highway** | Forget gate ≈ 1 means gradient passes through unchanged — no vanishing! |
| **GRU** | Streamlined 2-gate variant — reset gate controls past context, update gate interpolates between old and new |
| **GRU vs LSTM** | ~25% fewer parameters, comparable performance; GRU couples forget/input into one gate |
| **Bidirectional LSTM** | Two LSTMs (forward + backward) capture full left-right context at every position |
| **Parameter Cost** | LSTM: ~4× RNN, GRU: ~3× RNN, BiLSTM: ~8× RNN — but handles 30× longer sequences |

---

## The Remaining Question... ⏳

The LSTM is an elegant, beautiful solution to the vanishing gradient problem. It dominated NLP from its invention in 1997 by Hochreiter & Schmidhuber all the way until 2017 — a remarkable 20-year reign.

But there's a new challenge. Consider **machine translation**: translating "I love cats" from English to French ("J'aime les chats"). The LSTM reads the English sentence word by word and produces a final hidden state — a single fixed-size vector that supposedly captures the *entire* meaning of the source sentence. Then we need a *second* LSTM to generate the French output, word by word, from that compressed vector.

This raises two critical questions:
- How do you **compress** an entire sentence into a single vector without losing information?
- How do you **generate** a variable-length output from that fixed-size summary?

The answer is an architecture pattern that splits the problem into two cooperating networks: one that reads and compresses (the **Encoder**), and one that generates the output (the **Decoder**). This Encoder-Decoder framework is the backbone of sequence-to-sequence models — and it's built entirely with the LSTMs we just learned.

---

## What's Next? 🚀

```
BoW / TF-IDF → Word2Vec → Average Word2Vec → RNNs → LSTMs → ???
```

We've now traveled from the simplest text representations all the way to networks that can selectively remember context across hundreds of words. The LSTM gave us **selective memory** — the ability to choose what to remember, what to forget, and what to output. The BiLSTM gave us **full context** — past and future at every position.

But how do we use these powerful sequence processors for tasks where the *input* and *output* are both sequences of different lengths — like translation, summarization, or chatbot responses? We need a framework that **encodes** the input into a compressed representation and then **decodes** it into the target output.

👉 **[Encoder-Decoder Architecture — Solving the Translation Problem](content/large-language-models/natural-language-processing/encoder-decoder.md)**

---

Got questions or suggestions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*

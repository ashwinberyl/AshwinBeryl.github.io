---
title: "Intro to RNNs & LSTMs — Teaching Neural Networks to Remember"
date: 2026-03-21
tags: [nlp, rnn, lstm, gru, deep-learning, sequence-models, keras]
description: From ANNs that forget everything to RNNs that remember sequences — covering the RNN architecture, vanishing gradients through time, the LSTM breakthrough with its three gates, GRU, and a practical Keras implementation for sentiment analysis.
---

# The Missing Piece — Memory 🧠

In our [ANN blog](content/large-language-models/deep-learning/your-first-ann.md), we built a neural network that classifies **tabular data** — rows of numbers where each feature (age, salary, credit score) is independent. The network treated every input the same way: multiply by weights, add bias, activate, done. No notion of order, no concept of "what came before."

And in our [Average Word2Vec post](content/large-language-models/natural-language-processing/average-word2vec-gensim.md), we spotted a critical flaw: averaging word vectors destroys **word order**. "Dog bites man" and "Man bites dog" produce the same vector. Our pipeline is deaf to sequence.

But **language is fundamentally sequential.** The meaning of the word "it" depends on what came before. The answer to "Is this review positive?" depends on reading the *entire* sentence, word by word, in order. You can't understand the end of a sentence without remembering the beginning.

We need a neural network with **memory** — one that reads words one at a time, carries forward what it's read, and uses that accumulated context to make a decision.

Enter the **Recurrent Neural Network (RNN).**

---

## Why Sequences Matter — Real-World Applications 🌍

Before diving into architecture, let's understand *why* sequence matters so much. These are the tasks that traditional ML and ANNs simply cannot do:

### 💬 Chatbots & Question Answering
When you ask a chatbot "What is the capital of France?", it needs to understand the **entire question** — not just individual words. "Capital" and "France" alone could mean anything. The sequence gives the context.

### 🌐 Language Translation
Google Translate doesn't just swap words — it rearranges them. "I am going to the store" in English becomes "Ich gehe zum Laden" in German. The grammar, word order, and structure change completely. The model must **read the full source sentence** before generating the translation.

### ✍️ Text Generation & Auto-Suggestion
When Gmail suggests "Sounds good, thanks!" or LinkedIn auto-completes your sentence, the model is predicting the **next word** based on all the words you've typed so far. That requires reading and remembering the sequence.

For all of these tasks, the **sequence of words is super important**. We need deep learning techniques that respect order — and that's where RNNs, LSTMs, and eventually Transformers come in.

---

## The RNN Architecture — A Neuron with a Loop 🔄

### The Core Idea

In a standard ANN, a neuron receives input, computes an output, and **forgets everything immediately**. It has no memory.

An RNN neuron does something different: **it sends its output back to itself as additional input at the next time step.** This self-loop is the magic ingredient that gives it memory.

### Compact vs Unrolled View

The same RNN can be drawn two ways:

![RNN Cell — Compact Loop vs Unrolled Through Time](content/large-language-models/natural-language-processing/images/rnn_cell_unrolled.png)

On the left, the self-loop makes it look mysterious. But when you **unroll** it through time (right side), it's just the same neuron copied multiple times, with each copy passing its hidden state to the next.

### Walking Through "the food is good"

Let's trace how an RNN processes the sentence "the food is good":

1. **T=1:** The word "the" (as a vector) enters the network. The RNN computes a hidden state **h₁** — a numerical summary of "the"
2. **T=2:** The word "food" enters, along with **h₁**. The RNN combines both to produce **h₂** — now it "knows" about "the food"
3. **T=3:** "is" enters with **h₂**. Output: **h₃** — the network has context for "the food is"
4. **T=4:** "good" enters with **h₃**. Output: **h₄** — the final hidden state encodes the meaning of the entire sentence "the food is good"

The final hidden state **h₄** is then passed to a Dense layer (just like our ANN!) to produce the prediction.

### The Math

At each time step t:

```
hₜ = tanh(Wₓ · xₜ + Wₕ · hₜ₋₁ + b)
```

Where:
- **xₜ** = the input word vector at time step t
- **hₜ₋₁** = the hidden state from the previous time step (the "memory")
- **Wₓ** = weight matrix for the input
- **Wₕ** = weight matrix for the previous hidden state
- **b** = bias
- **tanh** = activation function (squashes values to [-1, 1])

> **Critical insight:** The weights **Wₓ** and **Wₕ** are the **same** at every time step. The network doesn't learn separate weights for each word position — it learns one universal "reading function" that it applies at every step. This is called **weight sharing**, and it's what allows RNNs to handle sentences of any length.

### A Simple RNN Forward Pass in Python

```python
import numpy as np

def rnn_forward(inputs, Wx, Wh, b, h0):
    """
    Forward pass of a simple RNN.
    
    inputs: list of word vectors [x1, x2, ..., xT]
    Wx: weight matrix for inputs (input_dim × hidden_dim)
    Wh: weight matrix for hidden state (hidden_dim × hidden_dim)
    b: bias vector (hidden_dim,)
    h0: initial hidden state (hidden_dim,)
    """
    h = h0                   # Start with initial hidden state
    hidden_states = []
    
    for xt in inputs:
        # The RNN equation: combine input + previous memory
        h = np.tanh(xt @ Wx + h @ Wh + b)
        hidden_states.append(h)
    
    return hidden_states     # h[-1] is the final "summary" of the whole sequence

# Example: 4 words, each represented as a 3D vector
np.random.seed(42)
words = [np.random.randn(3) for _ in range(4)]  # "the food is good"

# Initialize weights (3 input features → 5 hidden units)
Wx = np.random.randn(3, 5) * 0.1
Wh = np.random.randn(5, 5) * 0.1
b = np.zeros(5)
h0 = np.zeros(5)

states = rnn_forward(words, Wx, Wh, b, h0)

print(f"Hidden state after word 1: {states[0].round(3)}")
print(f"Hidden state after word 4: {states[3].round(3)}")
print(f"\nFinal state encodes the ENTIRE sentence's context!")
```

---

## Types of RNN Architectures 🏗️

Not every sequence problem has the same shape. RNNs can be wired in four fundamental configurations:

![Four Types of RNN Architectures](content/large-language-models/natural-language-processing/images/rnn_types_grid.png)

### One-to-One
**Single input → single output.** This is just a standard neural network (no real recurrence). Think image classification — one image in, one label out.

### One-to-Many
**Single input → sequence output.** The network produces multiple outputs from a single starting point.
- 🎵 **Music generation** — give a starting note, generate a melody
- 📸 **Image captioning** — give an image, generate a sentence describing it

### Many-to-One
**Sequence input → single output.** Multiple inputs are read in order, but only one answer is produced at the end.
- 😊 **Sentiment analysis** — read a full review, output "positive" or "negative"
- 📈 **Next-day stock prediction** — read past 30 days of prices, predict tomorrow

### Many-to-Many
**Sequence input → sequence output.** Both input and output are sequences, potentially of different lengths.
- 🌐 **Language translation** — read an English sentence, generate a French sentence
- 💬 **Chatbots** — read a question, generate an answer
- ❓ **Question answering** — read a passage + question, generate an answer

---

## Forward Propagation Through Time ➡️

Let's walk through a complete **Many-to-One** example — the most common setup for text classification.

Given the sentence: **"the food is very good"** → predict sentiment (positive/negative).

![Forward Propagation Through Time — Processing Words Sequentially](content/large-language-models/natural-language-processing/images/rnn_forward_timesteps.png)

### Step by step:

1. Each word is converted to a vector using [Word2Vec](content/large-language-models/natural-language-processing/word-embeddings-word2vec.md) (our embedding layer)
2. At T=1: `x₁ ("the")` enters → combined with initial hidden state h₀ → produces h₁
3. At T=2: `x₂ ("food")` enters → combined with h₁ → produces h₂
4. At T=3: `x₃ ("is")` enters → combined with h₂ → produces h₃
5. At T=4: `x₄ ("very")` enters → combined with h₃ → produces h₄
6. At T=5: `x₅ ("good")` enters → combined with h₄ → produces h₅ (the final hidden state)
7. **h₅** → Dense layer → Sigmoid activation → **ŷ = 0.92** (92% probability = Positive ✓)

For the Final Output activation function: if it's a **binary classification** we apply **Sigmoid** (from our [Activation Functions blog](content/large-language-models/deep-learning/activation-functions.md)), and if it's a **multi-class classification** we apply **Softmax** to get the final prediction **ŷ**.

---

## Backpropagation Through Time (BPTT) 🔙

Once we have our prediction ŷ, we compute the loss (e.g., Binary Cross-Entropy, from our [Loss Functions blog](content/large-language-models/deep-learning/loss-functions.md)):

```
Loss = L(y, ŷ)
```

Now the network needs to learn — just like in our ANN. But here's the twist: the error must flow backward **through every time step**, not just through layers.

This process is called **Backpropagation Through Time (BPTT)**:

1. Compute the loss at the output
2. Send the gradient backward through the Dense layer
3. Send it backward through **T=5 → T=4 → T=3 → T=2 → T=1**
4. At each time step, update the **shared weights** Wₓ, Wₕ based on the accumulated gradients

Because the weights are shared across all time steps, the gradients from every step get **summed together** to produce the final weight update. In principle, this is the **same chain rule** we covered in [Neural Networks Continued](content/large-language-models/deep-learning/neural-networks-continued.md) — just applied through time instead of through depth.

---

## The RNN's Fatal Flaw — Vanishing Gradients Through Time 📉

Here's where things go wrong. In our [Neural Networks Continued blog](content/large-language-models/deep-learning/neural-networks-continued.md), we saw how gradients vanish when multiplied across many **layers**. In RNNs, the same problem occurs across **time steps** — and it's often worse.

![Vanishing Gradients Through Time — Early Words Stop Learning](content/large-language-models/natural-language-processing/images/rnn_vanishing_gradient_time.png)

### The Problem

When gradients flow backward through 50 time steps, they're multiplied over and over by the weight matrix **Wₕ** and by the activation function's derivative. If these multiplication factors are less than 1 (which they almost always are with tanh), the gradient **shrinks exponentially**:

```python
# Gradient dying through time steps
gradient = 1.0
for step in range(50):
    gradient *= 0.7  # Typical tanh derivative factor

print(f"Gradient after 50 time steps: {gradient:.10f}")
# Output: 0.0001798465 — essentially zero
```

After just 50 words, the gradient reaching the first word is essentially **zero**. The network cannot learn what happened at the beginning of the sentence.

### The Practical Consequence

Try this sentence:

> "The food that was served at the restaurant on Main Street near the park next to the library where I used to study was **___**"

By the time the RNN reaches the blank, it has **forgotten** that this sentence is about "food." The hidden state has been overwritten so many times that the early context is lost.

RNNs have **short-term memory** but no **long-term memory**. They can remember the last ~10-15 words, but anything further back fades to nothing.

We need a mechanism that can carry important information across **hundreds** of time steps without degradation. Enter the LSTM.

---

## LSTM — Long Short-Term Memory 🧠📓

### The Notebook Analogy

If an RNN is a person with short-term memory (they can only remember the last few things you said), then an **LSTM** is a person carrying a **notebook**:

- They can **write** important things down in the notebook (store long-term memory)
- They can **cross things out** when information is no longer relevant (forget)
- They can **read** specific entries from the notebook when making a decision (output)

The notebook is the **Cell State** — a conveyor belt that runs through the entire sequence, allowing critical information to flow unchanged across dozens or hundreds of time steps.

### The Architecture — Three Gates

The LSTM cell has three "gates" — each is a small neural network (sigmoid + multiplication) that controls information flow:

![LSTM Cell Architecture — Forget, Input, and Output Gates](content/large-language-models/natural-language-processing/images/lstm_cell_gates.png)

### 1. Forget Gate 🗑️ — "What to erase from the notebook?"

The Forget Gate looks at the current input (xₜ) and the previous hidden state (hₜ₋₁) and decides what percentage of the old cell state to **keep** (values close to 1) or **erase** (values close to 0).

```
fₜ = σ(Wf · [hₜ₋₁, xₜ] + bf)
```

*Example:* If the sentence shifts from talking about "weather" to "food", the forget gate learns to erase the weather information from the cell state.

### 2. Input Gate ✏️ — "What new info to write in the notebook?"

The Input Gate determines what new information to **add** to the cell state. It has two parts:
- A **sigmoid** decides *which* values to update
- A **tanh** creates a vector of *candidate* new values

```
iₜ = σ(Wi · [hₜ₋₁, xₜ] + bi)          ← What to write? (0-1)
C̃ₜ = tanh(Wc · [hₜ₋₁, xₜ] + bc)       ← What's the new info? (-1 to 1)
```

### 3. The Cell State Update — "Erase + Write"

Now we update the notebook:

```
Cₜ = fₜ * Cₜ₋₁ + iₜ * C̃ₜ
```

- **fₜ × Cₜ₋₁** → Erase irrelevant old info (multiply by forget gate)
- **iₜ × C̃ₜ** → Write in relevant new info (multiply by input gate)

This is the magic! The cell state **Cₜ** can carry information across hundreds of time steps because the forget gate can choose to multiply by **1.0** (keep everything unchanged). No vanishing gradient — the information just flows straight through on the conveyor belt.

### 4. Output Gate 📖 — "What to read from the notebook?"

Finally, the Output Gate decides what part of the cell state to **expose** as the hidden state (the output for this time step):

```
oₜ = σ(Wo · [hₜ₋₁, xₜ] + bo)
hₜ = oₜ * tanh(Cₜ)
```

The hidden state **hₜ** is a filtered version of the full cell state — the LSTM only reveals what's relevant for the current time step.

---

## GRU — The Lightweight Alternative ⚡

In 2014, Cho et al. introduced the **Gated Recurrent Unit (GRU)** — a simplified version of the LSTM that combines the Forget and Input gates into a single **Update Gate** and merges the cell state with the hidden state.

### The Simplification

| | LSTM | GRU |
|---|---|---|
| **Gates** | 3 (Forget, Input, Output) | 2 (Reset, Update) |
| **State vectors** | 2 (Cell state + Hidden state) | 1 (Hidden state only) |
| **Parameters** | More | Fewer |
| **Training speed** | Slower | Faster |
| **Performance** | Slightly better on complex tasks | Comparable in most cases |

### GRU Equations (Simplified)

```
zₜ = σ(Wz · [hₜ₋₁, xₜ])            ← Update gate: "How much old info to keep?"
rₜ = σ(Wr · [hₜ₋₁, xₜ])            ← Reset gate: "How much old info to use for new candidate?"
h̃ₜ = tanh(W · [rₜ * hₜ₋₁, xₜ])     ← Candidate hidden state
hₜ = (1 - zₜ) * hₜ₋₁ + zₜ * h̃ₜ     ← Final hidden state (blend old + new)
```

> **When to use which?** Start with **LSTM** if you're not sure — it's the safe, proven choice. Switch to **GRU** if you need faster training or have limited compute. In practice, the performance difference is usually negligible.

![RNN vs LSTM vs GRU — Cell Architecture Comparison](content/large-language-models/natural-language-processing/images/rnn_lstm_gru_comparison.png)

---

## Practical Implementation — Sentiment Analysis with Keras 💻

Let's put it all together with a complete, runnable example. We'll use the **IMDB Movie Reviews** dataset (built into Keras) to build an LSTM-based sentiment classifier.

Notice how similar the Keras workflow is to [our first ANN](content/large-language-models/deep-learning/your-first-ann.md) — `model.compile()`, `model.fit()`, `model.predict()` — the theory changes, but the framework stays the same.

```python
import numpy as np
import tensorflow as tf
from tensorflow.keras.datasets import imdb
from tensorflow.keras.preprocessing.sequence import pad_sequences
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Embedding, LSTM, Dense, Dropout
from tensorflow.keras.callbacks import EarlyStopping

# =============================================
# STEP 1: Load and Prepare the IMDB Dataset
# =============================================
# Only keep the top 10,000 most frequent words
vocab_size = 10000
max_length = 200  # Truncate/pad reviews to 200 words

(X_train, y_train), (X_test, y_test) = imdb.load_data(num_words=vocab_size)

# Pad sequences so all reviews are the same length
# Reviews shorter than 200 words → padded with zeros
# Reviews longer than 200 words → truncated to 200
X_train = pad_sequences(X_train, maxlen=max_length, padding='post')
X_test = pad_sequences(X_test, maxlen=max_length, padding='post')

print(f"Training samples: {X_train.shape[0]}")
print(f"Test samples: {X_test.shape[0]}")
print(f"Sequence length: {X_train.shape[1]}")

# =============================================
# STEP 2: Build the LSTM Model
# =============================================
model = Sequential()

# Embedding Layer: Converts word indices → dense vectors (like Word2Vec, but learned during training!)
model.add(Embedding(input_dim=vocab_size, output_dim=128, input_length=max_length))

# LSTM Layer: The recurrent layer that processes the sequence
model.add(LSTM(units=64, return_sequences=False))
# return_sequences=False → only output the FINAL hidden state (Many-to-One)

# Dropout for regularization (from our ANN blog!)
model.add(Dropout(0.5))

# Output Layer: Binary classification (Positive / Negative)
model.add(Dense(units=1, activation='sigmoid'))

model.summary()
```

```
Model: "sequential"
┌─────────────────────┬────────────────────────┬───────────────┐
│ Layer (type)         │ Output Shape           │ Param #       │
├─────────────────────┼────────────────────────┼───────────────┤
│ embedding (Embedding)│ (None, 200, 128)       │ 1,280,000     │
│ lstm (LSTM)          │ (None, 64)             │ 49,408        │
│ dropout (Dropout)    │ (None, 64)             │ 0             │
│ dense (Dense)        │ (None, 1)              │ 65            │
└─────────────────────┴────────────────────────┴───────────────┘
 Total params: 1,329,473
```

Let's break down the parameter counts (remember [reading model.summary()](content/large-language-models/deep-learning/your-first-ann.md) from our ANN blog?):

| Layer | Calculation | Params |
|---|---|---|
| **Embedding** | 10,000 words × 128 dimensions | 1,280,000 |
| **LSTM** | 4 × [(128 + 64) × 64 + 64] = 4 × 12,352 | 49,408 |
| **Dense** | 64 × 1 + 1 | 65 |

> **Why 4× in the LSTM?** Because an LSTM has 4 weight matrices internally — one for each of the Forget gate, Input gate, Output gate, and the Candidate computation. That's the cost of memory!

```python
# =============================================
# STEP 3: Compile and Train
# =============================================
model.compile(
    optimizer='adam',                # Our trusty optimizer
    loss='binary_crossentropy',     # Binary classification
    metrics=['accuracy']
)

early_stop = EarlyStopping(
    monitor='val_loss',
    patience=3,
    restore_best_weights=True
)

history = model.fit(
    X_train, y_train,
    epochs=10,
    batch_size=64,
    validation_split=0.2,
    callbacks=[early_stop]
)

# =============================================
# STEP 4: Evaluate
# =============================================
loss, accuracy = model.evaluate(X_test, y_test)
print(f"\nTest Accuracy: {accuracy * 100:.2f}%")
# Expected: ~85-87% accuracy on real IMDB data!
```

```python
# =============================================
# STEP 5: Make a Prediction
# =============================================
# Let's decode a test review and predict its sentiment
word_index = imdb.get_word_index()
reverse_index = {v + 3: k for k, v in word_index.items()}
reverse_index[0] = '<PAD>'
reverse_index[1] = '<START>'
reverse_index[2] = '<UNK>'

sample = X_test[0]
decoded = ' '.join([reverse_index.get(i, '?') for i in sample if i != 0])
prediction = model.predict(sample.reshape(1, -1), verbose=0)[0][0]

print(f"Review: {decoded[:200]}...")
print(f"Prediction: {'Positive 👍' if prediction > 0.5 else 'Negative 👎'} ({prediction:.2%})")
print(f"Actual: {'Positive' if y_test[0] == 1 else 'Negative'}")
```

### What Just Happened?

Compare this to [our first ANN](content/large-language-models/deep-learning/your-first-ann.md):

| ANN (Churn Prediction) | LSTM (Sentiment Analysis) |
|---|---|
| Input: 10 numerical features | Input: 200 word indices |
| No sequence awareness | Reads words in order, carries hidden state |
| `Dense → Dense → Dense` | `Embedding → LSTM → Dense` |
| ~115 parameters | ~1.3 million parameters |
| `model.compile()` → `model.fit()` | **Same** Keras workflow! |

The building blocks we learned (Dense layers, Sigmoid, Adam, BCE, Dropout, Early Stopping) are all here. The only new ingredient is the **LSTM layer** — which gives the network the ability to **remember**.

---

## Recap — RNN vs LSTM vs GRU 🎓

| | Simple RNN | LSTM | GRU |
|---|---|---|---|
| **Memory Type** | Short-term only | Short + Long-term | Short + Long-term |
| **Gates** | None | 3 (Forget, Input, Output) | 2 (Reset, Update) |
| **Cell State** | ❌ | ✅ (separate conveyor belt) | ❌ (merged with hidden) |
| **Vanishing Gradient?** | ⚠️ Severe | ✅ Mostly solved | ✅ Mostly solved |
| **Parameters** | Fewest | Most | Medium |
| **Best For** | Very short sequences | Complex, long sequences | Faster alternative to LSTM |

---

## The Remaining Limitation... ⏳

LSTMs and GRUs are vastly better than simple RNNs. They can remember across hundreds of time steps. But they still have one fundamental constraint:

**They process words one at a time, sequentially.**

Word 50 must wait for words 1 through 49 to be processed first. This means:
- **Training is slow** — you can't parallelize across time steps
- **Very long sequences** (1,000+ words) still cause problems despite the gates

What if there was an architecture that could look at **ALL words simultaneously** and decide which ones to pay **attention** to? One that doesn't need to read sequentially at all?

That's the **Transformer** — the architecture behind GPT, BERT, and every modern LLM. And it's coming next.

---

## What's Next? 🚀

```
BoW / TF-IDF → Word2Vec → Average Word2Vec → RNNs → LSTMs → ???
```

The next leap is the single most important architecture in modern AI: **the Transformer**. It throws away recurrence entirely and replaces it with a mechanism called **Self-Attention** — allowing the model to relate every word to every other word in the sentence simultaneously.

Stay tuned — we're getting closer to understanding how ChatGPT works. 🔥

---

Got questions or suggestions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*

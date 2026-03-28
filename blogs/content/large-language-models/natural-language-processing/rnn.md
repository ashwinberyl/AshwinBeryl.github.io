---
title: "Recurrent Neural Network"
date: 2026-03-21
tags: [nlp, rnn, deep-learning, sequence-models, backpropagation, bptt, vanishing-gradient]
description: From ANNs that forget everything to RNNs that remember sequences — covering the RNN architecture, forward propagation through time, complete backpropagation math with the chain rule, the weight update formula step-by-step, and why vanishing gradients ultimately doom vanilla RNNs.
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

For all of these tasks, the **sequence of words is super important**. We need deep learning techniques that respect order — and that's where RNNs come in.

---

## The RNN Architecture — A Neuron with a Loop 🔄

### The Core Idea

In a standard ANN, a neuron receives input, computes an output, and **forgets everything immediately**. It has no memory.

An RNN neuron does something different: **it sends its output back to itself as additional input at the next time step.** This self-loop is the magic ingredient that gives it memory.

### Compact vs Unrolled View

The same RNN can be drawn two ways:

![RNN Cell — Compact Loop vs Unrolled Through Time](content/large-language-models/natural-language-processing/images/rnn_cell_unrolled.png)

On the left, the self-loop makes it look mysterious. But when you **unroll** it through time (right side), it's just the same neuron copied multiple times, with each copy passing its output to the next. Let's label the key components:

- **x₁, x₂, x₃, x₄** — the input word vectors at each time step
- **W** — the weight matrix connecting inputs to the neuron (same at every step)
- **W'** — the weight matrix connecting the previous output to the current step (same at every step)
- **O₁, O₂, O₃, O₄** — the output (hidden state) produced at each time step
- **f** — the activation function applied inside each neuron (typically tanh)

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

## Forward Propagation Through Time — The Full Math ➡️📐

Now let's trace exactly how an RNN processes a sentence, step by step. We'll use a **Many-to-One** setup — the most common for text classification.

Given a 4-word input: **x₁, x₂, x₃, x₄** (each word converted to a vector using [Word2Vec](content/large-language-models/natural-language-processing/word-embeddings-word2vec.md)). The network has two weight matrices:
- **W** — input weight (connects each word vector to the neuron)
- **W'** — recurrent weight (connects the previous output to the current step)

![RNN Forward Propagation — Equations at Each Time Step](content/large-language-models/natural-language-processing/images/rnn_forward_equations.png)

### Step 1: Output at T=1

The first word **x₁** enters the network. Since there is no previous output yet, O₁ depends **only** on the input:

```
O₁ = f(x₁ · W)
```

The activation function **f** (tanh) squashes the result to the range [-1, 1].

### Step 2: Output at T=2

The second word **x₂** enters. Now the neuron also receives the **previous output O₁** through the recurrent connection. Both are combined:

```
O₂ = f(x₂ · W + O₁ · W')
```

Notice: the same weight **W** is applied to x₂ (just like it was to x₁), and the recurrent weight **W'** connects O₁ to this step. O₂ now carries context about **both** words.

### Step 3: Output at T=3

The third word **x₃** enters with the accumulated context from O₂:

```
O₃ = f(x₃ · W + O₂ · W')
```

O₃ now carries context from words 1, 2, and 3.

### Step 4: Output at T=4

The fourth word **x₄** enters with context from O₃:

```
O₄ = f(x₄ · W + O₃ · W')
```

O₄ is the **final output** — it encodes context from the **entire sequence** (all 4 words).

### Step 5: Prediction and Loss

The final output O₄ is passed through a **sigmoid** (binary classification) or **softmax** (multi-class) activation function to produce the prediction **ŷ**:

```
ŷ = σ(O₄)         ← sigmoid for binary classification
ŷ = softmax(O₄)   ← softmax for multi-class
```

Then we compute the loss:

```
Loss = L(y, ŷ)
```

And then the **backpropagation** will happen — which we'll cover in detail next.

### The General Pattern

```
O₁ = f(x₁ · W)                    ← depends on word 1 only
O₂ = f(x₂ · W  +  O₁ · W')       ← depends on words 1-2
O₃ = f(x₃ · W  +  O₂ · W')       ← depends on words 1-3
O₄ = f(x₄ · W  +  O₃ · W')       ← depends on words 1-4 (entire sequence)
         ↑              ↑
     input weight   recurrent weight
     (same W)       (same W')
```

> **Critical insight — Weight Sharing:** The weights **W** and **W'** are the **same** at every time step. The network doesn't learn separate weights for each word position — it learns one universal "reading function" that it applies at every step. This is what allows RNNs to handle sentences of **any length**.

> **Are the weights the same at initialization?** Yes! All these weights are the **same** at the initial stages. But in the backpropagation, we will try to **update** them. How many cycles it takes to converge — that we have to see based on training.

### Forward Pass in Python

```python
import numpy as np

def rnn_forward(inputs, W, W_prime, h0):
    """
    Forward pass of a simple RNN.
    
    inputs: list of word vectors [x1, x2, ..., xT]
    W:       weight matrix for inputs (input_dim × hidden_dim)
    W_prime: weight matrix for recurrent connection (hidden_dim × hidden_dim)
    h0:      initial hidden state (hidden_dim,)
    """
    O = h0                    # Start with initial hidden state (no previous output)
    outputs = []
    
    for xt in inputs:
        # The RNN equation at each time step:
        # O_t = f(x_t · W + O_{t-1} · W')
        O = np.tanh(xt @ W + O @ W_prime)
        outputs.append(O)
    
    return outputs    # outputs[-1] is O₄ — the final "summary" of the whole sequence

# Example: 4 words, each represented as a 3D vector
np.random.seed(42)
words = [np.random.randn(3) for _ in range(4)]  # x₁, x₂, x₃, x₄

# Initialize weights (3 input features → 5 hidden units)
W       = np.random.randn(3, 5) * 0.1   # input weight
W_prime = np.random.randn(5, 5) * 0.1   # recurrent weight
h0      = np.zeros(5)                    # no previous output at T=0

outputs = rnn_forward(words, W, W_prime, h0)

print(f"O₁ (after word 1): {outputs[0].round(3)}")
print(f"O₂ (after word 2): {outputs[1].round(3)}")
print(f"O₃ (after word 3): {outputs[2].round(3)}")
print(f"O₄ (after word 4): {outputs[3].round(3)}")
print(f"\nO₄ encodes the ENTIRE sentence's context!")
```

---

## Backpropagation Through Time (BPTT) — The Full Math 🔙📐

Now comes the most important part. Once we have our prediction ŷ, we compute the loss (e.g., Binary Cross-Entropy, from our [Loss Functions blog](content/large-language-models/deep-learning/loss-functions.md)):

```
Loss = L(y, ŷ)
```

The network needs to learn — just like in our ANN. But here's the twist: the error must flow backward **through every time step**, not just through layers. Every weight at every time step needs to get updated.

This process is called **Backpropagation Through Time (BPTT)**.

![RNN Backpropagation Through Time — Weight Update Path](content/large-language-models/natural-language-processing/images/rnn_bptt_weight_update.png)

### The Weight Update Formula

Remember the weight update formula from our [Neural Networks Continued blog](content/large-language-models/deep-learning/neural-networks-continued.md)?

```
W_new = W_old − η × (∂L / ∂W)
```

Where:
- **W_new** = the updated weight
- **W_old** = the current weight before update
- **η** (eta) = the learning rate (a small number like 0.01)
- **∂L / ∂W** = the partial derivative of loss with respect to the weight

This formula applies to **every** weight in the RNN — both **W** (input weights) and **W'** (recurrent weights). The challenge is computing that gradient **∂L / ∂W** for each weight, because in an RNN the dependencies chain through time.

---

### Step 1: Updating W' (The Recurrent Weight) — First Encounter

In the backpropagation, **W'** (the recurrent connection weight) is encountered **first** when going backward from the loss. Let's write the weight update:

```
W'_new = W'_old − η × (∂L / ∂W')
```

We already have W'_old and η. The question is: **how do we find ∂L / ∂W'?**

We use the **chain rule of differentiation**. Since the loss depends on ŷ, and ŷ depends on W', we can decompose:

```
∂L / ∂W' = (∂L / ∂ŷ) × (∂ŷ / ∂W')
```

This is exactly the same chain rule we covered in [Neural Networks Continued](content/large-language-models/deep-learning/neural-networks-continued.md) — just applied through the time dimension instead of through depth.

---

### Step 2: Updating W (The Input Weight) — Chain Rule Through Time

Now we need to update the input weight **W**. The weight update formula is:

```
W_new = W_old − η × (∂L / ∂W)
```

But **W** is buried deeper in the computation graph. Look at where W sits — it's at the input to each time step. To reach W from the loss, we have to go backward through multiple intermediate outputs.

For updating W at the **last time step** (T=4), the chain rule gives us:

```
∂L / ∂W = (∂L / ∂ŷ) × (∂ŷ / ∂O₄) × (∂O₄ / ∂W)
```

The gradient flows: **Loss → ŷ → O₄ → W**

Each factor in this chain rule corresponds to one step backward in the computation:
- **∂L / ∂ŷ** — how much does the loss change when ŷ changes?
- **∂ŷ / ∂O₄** — how much does ŷ change when O₄ changes?
- **∂O₄ / ∂W** — how much does O₄ change when W changes?

![Chain Rule of Differentiation for BPTT](content/large-language-models/natural-language-processing/images/rnn_chain_rule_bptt.png)

---

### Step 3: Updating W' at Different Time Steps

Here's where it gets interesting. The recurrent weight **W'** exists at **every connection between time steps**. When we want to update W' at a specific time step, the chain rule path changes.

**Updating W' at T=3** (the connection between O₃ and O₄):

```
∂L / ∂W'|ₜ₌₃ = (∂L / ∂ŷ) × (∂ŷ / ∂O₄) × (∂O₄ / ∂W')
```

The gradient flows: **Loss → ŷ → O₄ → W'** at the T=3→T=4 connection.

**Updating W' at T=2** (the connection between O₂ and O₃):

```
∂L / ∂W'|ₜ₌₂ = (∂L / ∂ŷ) × (∂ŷ / ∂O₄) × (∂O₄ / ∂O₃) × (∂O₃ / ∂W')
```

The gradient flows: **Loss → ŷ → O₄ → O₃ → W'** at the T=2→T=3 connection.

**Updating W' at T=1** (the connection between O₁ and O₂):

```
∂L / ∂W'|ₜ₌₁ = (∂L / ∂ŷ) × (∂ŷ / ∂O₄) × (∂O₄ / ∂O₃) × (∂O₃ / ∂O₂) × (∂O₂ / ∂W')
```

The gradient flows: **Loss → ŷ → O₄ → O₃ → O₂ → W'** at the T=1→T=2 connection.

> **Notice the pattern?** As we go further back in time, the chain rule gets **longer**. We multiply by more and more terms. And this is *exactly* where the vanishing gradient problem will bite us!

### The Complete Picture

To update **all** the weights, the backpropagation must traverse the entire unrolled network:

```
For each weight at each time step:
    1. Start from the Loss
    2. Chain-rule backward through ŷ
    3. Chain-rule through each output O₄ → O₃ → O₂ → O₁ 
       (as many steps as needed to reach the weight)
    4. Compute the gradient
    5. Apply: W_new = W_old − η × gradient
```

This forward and backward propagation repeats for some number of **epochs**. We can use **early stopping** (which we discussed in our deep learning sessions) — whenever the loss becomes almost stagnant, we conclude that the model training is complete.

### BPTT in Python (Simplified)

```python
import numpy as np

def bptt_simplified(inputs, targets, Wx, Wh, Wy, bh, by, learning_rate=0.01):
    """
    Simplified Backpropagation Through Time for a vanilla RNN.
    Shows the key concept: gradients accumulate through time steps.
    """
    T = len(inputs)
    
    # ===== FORWARD PASS =====
    h = {0: np.zeros_like(bh)}  # hidden states
    o = {}                       # outputs at each step

    for t in range(1, T + 1):
        # RNN forward equation
        h[t] = np.tanh(inputs[t-1] @ Wx + h[t-1] @ Wh + bh)
    
    # Final output
    y_hat = h[T] @ Wy + by    # Simplified: linear output
    loss = 0.5 * np.sum((y_hat - targets) ** 2)  # MSE loss
    
    # ===== BACKWARD PASS (BPTT) =====
    # Gradient of loss w.r.t. output
    dL_dy = y_hat - targets
    
    # Gradient for output weights
    dWy = h[T].T @ dL_dy
    dby = dL_dy.sum(axis=0)
    
    # Initialize gradient accumulators for shared weights
    dWx = np.zeros_like(Wx)
    dWh = np.zeros_like(Wh)
    dbh = np.zeros_like(bh)
    
    # Backpropagate through time: T → T-1 → ... → 1
    dh_next = dL_dy @ Wy.T  # gradient flowing into last hidden state
    
    for t in range(T, 0, -1):
        # Through tanh: derivative of tanh(x) = 1 - tanh²(x)
        dtanh = (1 - h[t] ** 2) * dh_next
        
        # Accumulate gradients for SHARED weights
        # This is the key insight — gradients from ALL time steps
        # contribute to the same weight matrices!
        dWx += inputs[t-1].T @ dtanh    # ∂L/∂W  (accumulated)
        dWh += h[t-1].T @ dtanh          # ∂L/∂W' (accumulated)
        dbh += dtanh.sum(axis=0)
        
        # Pass gradient to previous time step (the chain continues!)
        dh_next = dtanh @ Wh.T
    
    # ===== WEIGHT UPDATE =====
    Wx -= learning_rate * dWx
    Wh -= learning_rate * dWh
    Wy -= learning_rate * dWy
    bh -= learning_rate * dbh
    by -= learning_rate * dby
    
    return loss, Wx, Wh, Wy, bh, by
```

> **Key insight from the code:** Notice how `dWx` and `dWh` are **accumulated** across all time steps in the backward loop. Because the weights are shared, every time step contributes its own gradient to the same weight matrix. The final gradient is the **sum** of all per-time-step gradients.

---

## The RNN's Fatal Flaw — Vanishing Gradients Through Time 📉

Here's where things go wrong. In our [Neural Networks Continued blog](content/large-language-models/deep-learning/neural-networks-continued.md), we saw how gradients vanish when multiplied across many **layers**. In RNNs, the same problem occurs across **time steps** — and it's often worse.

![Vanishing Gradients in Deep RNN — Gradient Fading Through Time](content/large-language-models/natural-language-processing/images/rnn_vanishing_gradient_deep.png)

### Why It Happens

Remember our chain rule expressions from above? Look at the chain for updating W' at T=1:

```
∂L / ∂W'|ₜ₌₁ = (∂L / ∂ŷ) × (∂ŷ / ∂O₄) × (∂O₄ / ∂O₃) × (∂O₃ / ∂O₂) × (∂O₂ / ∂W')
```

Each of those intermediate derivatives **(∂Oₜ / ∂Oₜ₋₁)** involves the derivative of the activation function. If we use **sigmoid** inside the RNN cells:

- The **sigmoid** function outputs values between 0 and 1
- The **derivative of sigmoid** outputs values between **0 and 0.25**

So at every time step, the gradient gets multiplied by a number ≤ 0.25. After many time steps:

```python
# Gradient dying through time steps (sigmoid derivative)
gradient = 1.0
for step in range(50):
    gradient *= 0.25  # Maximum sigmoid derivative

print(f"After 50 steps: {gradient:.2e}")
# Output: After 50 steps: 7.89e-31 — essentially ZERO!
```

Even with **tanh** (derivative range 0 to 1), the gradient still decays:

```python
# Gradient with tanh derivative (typical values around 0.5-0.7)
gradient = 1.0
for step in range(50):
    gradient *= 0.7  # Typical tanh derivative factor

print(f"After 50 steps: {gradient:.10f}")
# Output: 0.0001798465 — essentially zero
```

After just 50 words, the gradient reaching the first word is essentially **zero**. The network cannot learn what happened at the beginning of the sentence.

> **What about ReLU?** You might think — "We solved vanishing gradients in ANNs with ReLU!" But ReLU has its own problem: it can create **dead neurons** during backpropagation. If a neuron's output becomes negative, ReLU's derivative is 0, and the neuron stops learning forever. So we can't simply swap in ReLU to fix RNNs.

### The Practical Consequence

Consider this sentence:

> "The food that was served at the restaurant on Main Street near the park next to the library where I used to study was **___**"

By the time the RNN reaches the blank, it has **forgotten** that this sentence is about "food." The hidden state has been overwritten so many times that the early context is lost.

### The Long-Range Dependency Problem

This brings us to the core issue: **long-range dependencies**.

Consider another example:

> "I grew up in **France** and I speak fluent **___**"

To predict "French," the model needs the context of "France" — but there are many words in between. When the gap between the relevant information and the point where it's needed is **small** (like "the clouds are in the ___"), an RNN can easily capture the context. But when the gap **grows**, the RNN becomes unable to connect the information.

```python
# Short range — RNN works fine
"The clouds are in the ___"  # Easy: "sky" (gap = 1 word)

# Long range — RNN fails
"I grew up in France and after many years of living abroad I speak fluent ___"
# Hard: "French" (gap = 12+ words, gradient has vanished)
```

RNNs have **short-term memory** but no **long-term memory**. They can remember the last ~10-15 words, but anything further back fades to nothing.

### Why Is This a Problem for NLP?

Think about reading a long paragraph. The subject established in the first sentence might not be referenced again until the last sentence. The RNN needs to carry that context across dozens of time steps — but the vanishing gradient makes it impossible for the network to learn these long-distance relationships.

| Sequence Length | Gradient After BPTT (tanh) | Can the RNN Learn? |
|---|---|---|
| 5 words | ~0.168 | ✅ Yes |
| 10 words | ~0.028 | ⚠️ Barely |
| 20 words | ~0.0008 | ❌ No |
| 50 words | ~0.00018 | ❌ Impossible |
| 100 words | ~0.00000003 | ❌ Completely dead |

---

## Summary — What We Learned 🎓

| Concept | Key Takeaway |
|---|---|
| **RNN Architecture** | A neuron with a self-loop — sends its output back as input at the next time step |
| **Weight Sharing** | Same weights W and W' at every time step — enables variable-length input |
| **Forward Propagation** | Each output Oₜ depends on input xₜ and previous output Oₜ₋₁ |
| **Weight Update Formula** | W_new = W_old − η × (∂L/∂W) — same as ANN but through time |
| **Chain Rule (BPTT)** | Gradient flows backward through every time step; longer chains = more multiplications |
| **Vanishing Gradient** | Sigmoid derivative (0–0.25) or tanh derivative (<1) causes gradients to shrink exponentially |
| **Short-Term Memory Only** | RNNs can remember ~10-15 words; long-range context is lost |

---

## The Remaining Limitation... ⏳

The vanilla RNN has powerful intuition — carry memory forward through time — but its math defeats it. The vanishing gradient problem means that for any sentence longer than ~15 words, the earliest words effectively have **zero influence** on the output.

We need a mechanism that can carry important information across **hundreds** of time steps without gradient degradation. Something with:
- A **memory cell** that can selectively remember and forget information
- **Gates** that control what information flows through
- A design that allows gradients to flow unchanged across long distances

That mechanism is the **LSTM (Long Short-Term Memory)** — and it's coming in the next post.

---

## What's Next? 🚀

```
BoW / TF-IDF → Word2Vec → Average Word2Vec → RNNs → ??? 
```

Now that we deeply understand how RNNs work *and* why they fail, we're ready for the breakthrough architecture that fixed everything: the **LSTM**. It introduces a "notebook" that the network carries through time — allowing it to write, erase, and read information selectively. No more vanishing gradients, no more forgetting the beginning of the sentence.

Stay tuned — the LSTM is one of the most elegant architectures in deep learning. 🔥

---

Got questions or suggestions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*

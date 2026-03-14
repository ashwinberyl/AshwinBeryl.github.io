---
title: "Neural Networks Continued — Gradients & the Chain Rule"
date: 2026-03-14
tags: [deep-learning, neural-networks, backpropagation, gradients]
description: Understanding the chain rule, exploding gradients, and vanishing gradients — the three concepts that determine whether your neural network will actually learn.
---

# Where We Left Off 🔄

In the [previous post](content/large-language-models/deep-learning/intro-to-neural-networks.md), we built a neural network from scratch. We saw the training loop:

1. Forward propagation → get a prediction
2. Compute the cost
3. Backpropagation → compute gradients
4. Update weights
5. Repeat

Simple enough. But here's the thing — **this process can go horribly wrong.** Two specific ways:

- The gradients can grow so large that training explodes 💥
- The gradients can shrink so small that training freezes 🧊

To understand *why*, we first need to understand the math engine behind backpropagation: **the chain rule.**

---

## The Chain Rule — The Engine of Backpropagation ⛓️

### A Simple Analogy

Imagine this:
- A **car** goes 2× faster than a **bike**
- A **bike** goes 3× faster than **walking**

How many times faster is a car than walking?

**2 × 3 = 6×**

That's the chain rule. When effects happen in sequence, you **multiply** the rates.

### How It Works in Neural Networks

In a neural network, the chain rule answers the question: **"How much does changing weight `w₁` in Layer 1 affect the final loss?"**

The answer: multiply all the intermediate effects, layer by layer.

```
∂Loss/∂w₁ = ∂Loss/∂a₃ × ∂a₃/∂z₃ × ∂z₃/∂a₂ × ∂a₂/∂z₂ × ∂z₂/∂w₁
```

In plain English: the gradient for `w₁` is the **product** of all the partial derivatives along the path from the output back to `w₁`.

![Chain Rule — Multiply Gradients Layer by Layer](content/large-language-models/deep-learning/images/chain_rule_backprop.png)

### The Key Insight

Look at that formula. The gradient is a **product of many numbers**. This means:

- If each number is **slightly greater than 1** → the product **grows exponentially**
- If each number is **slightly less than 1** → the product **shrinks to zero**

This single observation explains the two biggest problems in training deep networks.

---

### A Walk-Through Example

Let's trace gradients through a 3-layer network. Suppose the partial derivatives at each layer are:

```
Layer 3 → 2: ∂ = 0.8
Layer 2 → 1: ∂ = 0.6
Layer 1:     ∂ = 0.5
```

The gradient at Layer 1:

```
gradient = 0.8 × 0.6 × 0.5 = 0.24
```

Not bad. But with 20 layers, each contributing 0.8:

```
gradient = 0.8²⁰ = 0.0115
```

And with 50 layers:

```
gradient = 0.8⁵⁰ = 0.00001
```

The gradient practically **disappears**. Layer 1 barely learns anything.

Now imagine each partial derivative is 1.5 instead:

```
gradient = 1.5⁵⁰ = 637,621
```

The gradient **explodes**. The weights swing wildly, and training blows up.

---

## The Exploding Gradient Problem 💥

### What Is It?

When gradients are **greater than 1** at each layer and get multiplied together, they grow exponentially. By the time the gradient reaches the early layers, it's **enormous**.

### What Happens

- Weights change by **massive** amounts each update
- The loss curve goes haywire — spiking up, crashing down, going to `NaN`
- The model **diverges** instead of converging

![Exploding Gradient — Loss Goes Haywire](content/large-language-models/deep-learning/images/exploding_gradient.png)

### Numeric Example

```python
# Gradient multiplied through 50 layers
gradient = 1.5
for layer in range(50):
    gradient *= 1.5

print(f"Gradient after 50 layers: {gradient:.0f}")
# Output: 637,621 — that's insane
```

### How to Spot It

- Your loss suddenly becomes `NaN` or `inf`
- Weights grow to absurdly large values
- Training looks fine for a while, then suddenly crashes

### The Fix: Gradient Clipping ✂️

The simplest solution? Just **cap the gradient** at a maximum value:

```python
import tensorflow as tf

# Clip gradients to max norm of 1.0
optimizer = tf.keras.optimizers.Adam(
    learning_rate=0.001,
    clipnorm=1.0  # gradients capped at norm 1.0
)
```

```python
# Or manually in raw Python:
max_grad = 1.0

def clip_gradient(gradient, max_grad):
    """Clip gradient to a maximum value."""
    if gradient > max_grad:
        return max_grad
    elif gradient < -max_grad:
        return -max_grad
    return gradient
```

This prevents any single gradient from becoming absurdly large. Simple, effective, widely used.

---

## The Vanishing Gradient Problem 👻

### What Is It?

The opposite problem. When gradients are **less than 1** at each layer and get multiplied together, they shrink exponentially toward **zero**.

### What Happens

- Early layers (close to the input) receive **tiny** gradients
- Their weights barely change — they **stop learning**
- Only the last few layers actually train
- The network is "deep" in name only — most layers are dead weight

![Vanishing Gradient — Early Layers Stop Learning](content/large-language-models/deep-learning/images/vanishing_gradient.png)

### Why Sigmoid Makes It Worse

Remember sigmoid? Its derivative is:

```
σ'(x) = σ(x) × (1 - σ(x))
```

The maximum value of this derivative is **0.25** (when x = 0). For most inputs, it's even smaller.

So at every layer using sigmoid, the gradient gets multiplied by at most 0.25:

```python
# Sigmoid derivative max = 0.25
# Multiply through layers:
gradient = 1.0
for layer in range(10):
    gradient *= 0.25   # sigmoid derivative max

print(f"Gradient after 10 layers: {gradient}")
# Output: 0.00000095 — essentially zero
```

After just 10 layers, the gradient is practically **dead**.

### The Solutions

There are three main approaches (each covered in more detail in upcoming posts):

### 1. Better Activation Functions — ReLU 🏆

ReLU's derivative is either **0** or **1** — no shrinking!

```python
def relu_derivative(x):
    return 1 if x > 0 else 0
```

When x is positive, the gradient passes through **unchanged** (multiplied by 1). This prevents vanishing. That's why ReLU replaced sigmoid for hidden layers.

### 2. Better Weight Initialization

Starting with the right scale of weights prevents gradients from being too large or too small from the beginning. We cover this in detail in the [next post](content/large-language-models/deep-learning/weights-and-optimizers.md).

### 3. Skip Connections (Residual Networks)

Instead of forcing gradients through every single layer, create "shortcut" paths that let gradients flow directly to early layers. This is the idea behind **ResNets** — but that's a topic for a future post.

---

## The Big Picture

| Problem | What Happens | Cause | Quick Fix |
|---|---|---|---|
| **Exploding Gradients** | Loss → NaN, weights blow up | Gradients > 1 multiplied many times | Gradient clipping |
| **Vanishing Gradients** | Early layers stop learning | Gradients < 1 (sigmoid) multiplied many times | ReLU activation |

Both problems come from the same root: **the chain rule multiplies gradients through layers.** The solutions? Control what's being multiplied:

- Use **ReLU** so derivatives are 1 (not 0.25)
- Use proper **weight initialization** so initial gradients are the right scale
- Use **gradient clipping** as a safety net

In the next post, we'll look at the first line of defense against vanishing and exploding gradients: the gatekeepers of the neuron.

Next up: **[Activation Functions — The Evolution of Neural Gatekeepers](content/large-language-models/deep-learning/activation-functions.md)**.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*

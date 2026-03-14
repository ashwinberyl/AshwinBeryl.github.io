---
title: "Activation Functions — From Sigmoid to Softmax"
date: 2026-03-14
tags: [deep-learning, neural-networks, activation-functions, relu, sigmoid]
description: Why neural networks need activation functions, how they work, and a practical guide on when to use which one.
---

# Why Activation Functions? 🤔

Without an activation function, a neural network is just a giant linear regression model (`y = mx + b` with extra steps). No matter how many layers you add, a sequence of linear transformations is still just one big linear transformation.

Activation functions add **non-linearity** — the ability to learn curves, complex boundaries, and intricate patterns. They are the "logic gates" of neural networks, deciding which information should pass through and which should be silenced.

If you're new to the series, check out the [Intro to Neural Networks](content/large-language-models/deep-learning/intro-to-neural-networks.md) first!

---

## 1. Sigmoid — The Classic 🔔

The Sigmoid function was the original standard for neural networks. It squashes any input into a range between **0 and 1**.

### The Formula
`σ(x) = 1 / (1 + e⁻ˣ)`

### Use Case
Today, Sigmoid is primarily used in the **output layer** for binary classification problems (where you want a probability between 0 and 1).

### The Problem: Vanishing Gradient 👻
The maximum value of the Sigmoid derivative is **0.25**. When you multiply many of these small numbers together (as seen in the [Gradients post](content/large-language-models/deep-learning/neural-networks-continued.md)), the gradient vanishes, and early layers stop learning.

![Sigmoid and its Derivative](content/large-language-models/deep-learning/images/sigmoid_and_derivative.png)

```python
import numpy as np

def sigmoid(x):
    return 1 / (1 + np.exp(-x))

# Sigmoid always returns 0 to 1
print(sigmoid(10))   # 0.9999
print(sigmoid(-10))  # 0.00004
```

---

## 2. Tanh — Sigmoid's Better Sibling 〰️

Tanh (Hyperbolic Tangent) is very similar to Sigmoid but squashes values between **-1 and 1**.

### The Formula
`tanh(x) = (eˣ - e⁻ˣ) / (eˣ + e⁻ˣ)`

### Why it's better
Tanh is **zero-centered**. This means the average output is closer to zero, which helps the gradients during backpropagation flow more efficiently. It makes the optimization process smoother compared to Sigmoid.

### The Problem
It still has horizontal "saturation" zones at the extremes. Just like Sigmoid, gradients become nearly zero when the input is very large or very small.

![Tanh and its Derivative](content/large-language-models/deep-learning/images/tanh_and_derivative.png)

---

## 3. ReLU — The King 👑

ReLU (Rectified Linear Unit) is the current **default choice** for hidden layers in almost every modern neural network.

### The Formula
`f(x) = max(0, x)`

### Why it's the standard
1. **Computationally Fast:** It's just a simple comparison. No expensive exponentials like Sigmoid or Tanh.
2. **No Vanishing Gradient:** For positive inputs, the derivative is exactly **1**. Gradients flow through perfectly without shrinking.

### The Problem: Dead Neurons ⚰️
If a neuron's input is always negative, it will always output 0, and its gradient will always be 0. That neuron "dies" and never updates again.

![ReLU variants](content/large-language-models/deep-learning/images/relu_variants.png)

---

## 4. Leaky ReLU — Fixing Dead Neurons 🩹

Leaky ReLU is a small variation designed to keep neurons alive.

### The Formula
`f(x) = x if x > 0, else 0.01x`

Instead of being exactly 0 for negative values, it has a tiny slope (0.01). This ensures that even "dead" neurons still get a tiny gradient and have a chance to wake up.

```python
def leaky_relu(x):
    return np.maximum(0.01 * x, x)
```

---

### PReLU (Parametric ReLU)
If you don't want to rely on a fixed `0.01` slope for Leaky ReLU, you can use **PReLU**. It makes the small slope `a` a **learnable parameter** that the network adjusts during training.

---

## 5. ELU (Exponential Linear Unit) — The Smooth Curve 🌊

ELU tries to solve the dying ReLU problem while forcing the mean of the activations closer to zero (which speeds up learning).

### The Formula
`f(x) = x if x > 0, else α(eˣ - 1)`

### Why it's useful
Unlike Leaky ReLU which has a sharp "corner" at zero, ELU is perfectly smooth. This reduces unwanted oscillations during training. The downside? Computing `eˣ` is mathematically expensive.

![ELU Activation Function](content/large-language-models/deep-learning/images/elu_activation.png)

```python
def elu(x, alpha=1.0):
    return np.where(x > 0, x, alpha * (np.exp(x) - 1))
```

---

## 6. Swish & GELU — The Modern Giants ⚡

If you're looking at the architecture of the biggest AI models today—like GPT-4, Llama, or BERT—you won't see much standard ReLU. You'll see Swish or GELU.

### Swish (developed by Google)
`f(x) = x · sigmoid(x)`

Swish is **non-monotonic**. Notice how it dips *below* zero before going up. This tiny "bump" allows small negative values to still carry gradients, proving incredibly effective in incredibly deep networks.

![Swish Activation Function](content/large-language-models/deep-learning/images/swish_activation.png)

### GELU (Gaussian Error Linear Unit)
`f(x) = x · Φ(x)` *(where Φ is the cumulative distribution function for the Gaussian distribution)*

Visually, GELU is almost identical to Swish. Instead of applying a harsh `max(0, x)` filter, GELU weights the inputs by their probability under a normal distribution. It is the **default activation function in modern Transformers**.

![GELU Activation Function](content/large-language-models/deep-learning/images/gelu_activation.png)

---

## 7. Linear — For Regression 📏

Sometimes, you don't want to squash the output at all.

### The Formula
`f(x) = x`

### Use Case
The **output layer for regression**. If you are predicting house prices or temperature, you want the raw continuous value, not a probability between 0 and 1.

---

## 8. Softmax — Multi-class Probabilities 🎯

Softmax is the big brother of Sigmoid. While Sigmoid is for a simple Yes/No, Softmax is for **multi-class classification**.

### The Formula
`softmax(xᵢ) = eˣⁱ / Σeˣʲ`

It takes an entire vector of raw scores and turns them into **probabilities that sum to exactly 1**.

### Use Case
The **output layer** for models that predict one of several categories (e.g., Cat, Dog, or Bird).

---

## Cheat Sheet: Which one should I use? 📝

| Function | Range | Best For | Watch Out For |
|---|---|---|---|
| **ReLU** | [0, ∞) | **Hidden Layers (Default)** | Dead neurons |
| **GELU / Swish** | (-~0.1, ∞) | **Deep LLMs / Transformers** | Computationally heavy |
| **Sigmoid** | (0, 1) | Output Layer (Binary) | Vanishing gradient |
| **Softmax** | (0, 1) | Output Layer (Multi-class) | Not for hidden layers |
| **Linear** | (-∞, ∞) | Output Layer (Regression) | Not for hidden layers |
| **Tanh** | (-1, 1) | Hidden Layers (older LSTM models)| Saturation |
| **Leaky ReLU** | (-∞, ∞) | Hidden Layers (alternative) | — |
| **ELU** | (-α, ∞) | Hidden Layers (smoothness) | Slower calculations |

## The "Modern Recipe"
If you're unsure, start with this:
1. Use **ReLU** for standard hidden layers (or **GELU** if you're building a Transformer).
2. Use **Sigmoid** if your output is Yes/No.
3. Use **Softmax** if your output is one of many categories.
4. Use **Linear** if your output is a continuous number.

Next up: **[Weight Initialization & Optimizers](content/large-language-models/deep-learning/weights-and-optimizers.md)** — how the way we start the network can make or break everything.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*

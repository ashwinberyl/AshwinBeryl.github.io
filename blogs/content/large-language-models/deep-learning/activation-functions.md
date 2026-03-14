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

## 5. Linear — For Regression 📏

Sometimes, you don't want to squash the output at all.

### The Formula
`f(x) = x`

### Use Case
The **output layer for regression**. If you are predicting house prices or temperature, you want the raw continuous value, not a number between 0 and 1.

---

## 6. Softmax — Multi-class Probabilities 🎯

Softmax is the big brother of Sigmoid. While Sigmoid is for 2 classes, Softmax is for **multi-class classification**.

### The Formula
`softmax(xᵢ) = eˣⁱ / Σeˣʲ`

It takes a vector of raw scores and turns them into **probabilities that sum to exactly 1**.

### Use Case
The **output layer** for models that predict one of several categories (e.g., Cat, Dog, or Bird).

---

## Cheat Sheet: Which one should I use? 📝

| Function | Range | Best For | Watch Out For |
|---|---|---|---|
| **ReLU** | [0, ∞) | **Hidden Layers (Default)** | Dead neurons |
| **Sigmoid** | (0, 1) | Output Layer (Binary) | Vanishing gradient |
| **Tanh** | (-1, 1) | Hidden Layers (less common) | Saturation |
| **Leaky ReLU** | (-∞, ∞) | Hidden Layers (alternative) | Slow calculations |
| **Softmax** | (0, 1) | Output Layer (Multi-class) | Not for hidden layers |
| **Linear** | (-∞, ∞) | Output Layer (Regression) | Not for hidden layers |

## The "Modern Recipe"
If you're unsure, start with this:
1. Use **ReLU** for all hidden layers.
2. Use **Sigmoid** if your output is Yes/No.
3. Use **Softmax** if your output is one of many categories.
4. Use **Linear** if your output is a continuous number.

Next up: **[Weight Initialization & Optimizers](content/large-language-models/deep-learning/weights-and-optimizers.md)** — how the way we start the network can make or break everything.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*

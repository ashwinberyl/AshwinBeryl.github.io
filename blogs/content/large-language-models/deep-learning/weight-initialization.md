---
title: "Weight Initialization — Starting the Network Right"
date: 2026-03-14
tags: [deep-learning, weight-initialization, xavier, he]
description: How weight initialization evolved from basic guessing to today's mathematical standards to prevent vanishing and exploding gradients.
---

# The Problems Are Clear. Now Let's Fix Them. 🔧

In the [previous post](content/large-language-models/deep-learning/loss-functions.md), we saw how networks measure their mistakes. But before you can even begin making mistakes and correcting them, how do you start the network? 

If you start with the wrong numbers, training can break in two ways:
- **Exploding gradients** — weights blow up
- **Vanishing gradients** — early layers stop learning

Both problems boil down to: the **initial scale of weights** is wrong. Let's trace the evolutionary journey of how we start the network, from terrible guessing to modern mathematical standards.

---

## 1. Zero Initialization ❌

### How it works
Set all weights to 0.

```python
import numpy as np

# Zero init: all weights are 0
weights = np.zeros((3, 3))
print(weights)
# [[0. 0. 0.]
#  [0. 0. 0.]
#  [0. 0. 0.]]
```

### The Problem: Symmetry

If all weights are the same, every neuron computes the **exact same thing**. During backpropagation, they all get the **exact same gradient**. They all update **identically**.

You have 100 neurons, but they all behave like **one neuron**. Completely useless.

> Think of it like a classroom where every student gives the exact same answer. Having 30 students adds no value over having 1.

**→ Next technique solves this by:** making each weight different.

---

## 2. Random Initialization 🎲

### How it works
Set weights to small random numbers.

```python
# Random init: small random numbers
weights = np.random.randn(3, 3) * 0.01
print(weights)
# [[ 0.0049,  0.0031, -0.0015],
#  [-0.0023,  0.0041,  0.0087],
#  [ 0.0012, -0.0056,  0.0033]]
```

### Advantage
Breaks symmetry! Every neuron starts differently, so they learn different features.

### The Problem: What Scale?

- If random numbers are **too large** → activations saturate → gradients explode 💥
- If random numbers are **too small** → activations shrink to 0 → gradients vanish 👻

There's no clear rule for "how random." You just... guess. And hope.

```python
# Too large — outputs explode
large_weights = np.random.randn(1000, 1000) * 1.0
x = np.random.randn(1000)
for _ in range(10):
    x = np.tanh(large_weights @ x)
print(f"After 10 layers: mean={x.mean():.4f}, std={x.std():.4f}")
# std ≈ 1.0 — saturated at boundaries

# Too small — outputs collapse
small_weights = np.random.randn(1000, 1000) * 0.001
x = np.random.randn(1000)
for _ in range(10):
    x = np.tanh(small_weights @ x)
print(f"After 10 layers: mean={x.mean():.10f}, std={x.std():.10f}")
# std ≈ 0.0000000001 — effectively dead
```

**→ Next technique solves this by:** calculating the right scale mathematically.

---

## 3. Xavier/Glorot Initialization (2010) 📐

### How it works
Scale random weights by `1/√(fan_in)`, where `fan_in` is the number of input connections to the neuron.

```python
# Xavier init
fan_in = 256  # number of inputs to this layer
weights = np.random.randn(fan_in, 128) * np.sqrt(1.0 / fan_in)
```

### The Math Intuition

If a neuron has 256 inputs, and each weight is multiplied by an input, then the sum of 256 weighted inputs will have a variance of `256 × var(w)`. To keep the variance at **1** (not growing, not shrinking), set `var(w) = 1/256`.

That's `1/√(fan_in)`.

### Advantage
Keeps the variance of activations **stable** across layers. No exploding, no vanishing. Works beautifully with **Sigmoid** and **Tanh**.

### The Problem: Breaks with ReLU

Xavier was designed for symmetric activation functions (sigmoid, tanh). But ReLU kills half the outputs (everything negative → 0), which **halves the variance!** After a few ReLU layers, activations collapse to zero again.

**→ Next technique solves this by:** doubling the variance to compensate for ReLU.

---

## 4. He/Kaiming Initialization (2015) 🏆

### How it works
Same idea as Xavier, but scale by `√(2/fan_in)` instead of `√(1/fan_in)`. The extra **2×** compensates for ReLU zeroing out half the activations.

```python
# He init
fan_in = 256
weights = np.random.randn(fan_in, 128) * np.sqrt(2.0 / fan_in)
```

### Advantage
Designed specifically for ReLU. Keeps activations and gradients stable even in very deep networks (50+ layers).

### Current Standard
This is **what you should use** for any modern neural network with ReLU activations.

```python
# In TensorFlow/Keras — it's the default!
import tensorflow as tf

layer = tf.keras.layers.Dense(128, activation='relu')
# Keras automatically uses He initialization for ReLU layers ✅
# You can also set it explicitly:
layer = tf.keras.layers.Dense(128, activation='relu',
                               kernel_initializer='he_normal')
```

---

## Initialization Summary

| Technique | Formula | Best For | Weakness |
|---|---|---|---|
| **Zero** | `w = 0` | Nothing | Symmetry problem |
| **Random** | `w = random × 0.01` | Simple cases | No rule for scale |
| **Xavier (2010)** | `w = random × √(1/fan_in)` | Sigmoid, Tanh | Breaks with ReLU |
| **He (2015)** | `w = random × √(2/fan_in)` | **ReLU (standard)** | — |

---

## What's Next? 🚀

You now know how to start the network perfectly. But once the network completes its forward pass and calculates its loss, how exactly does it *update* those weights to get better?

Next up, we explore the engine of training: **[Optimizers — Navigating the Loss Landscape](content/large-language-models/deep-learning/optimizers.md)**.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*

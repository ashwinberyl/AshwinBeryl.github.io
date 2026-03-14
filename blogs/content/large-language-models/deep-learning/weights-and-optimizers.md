---
title: "Weight Initialization & Optimizers — The Evolution"
date: 2026-03-14
tags: [deep-learning, optimizers, weight-initialization, adam, sgd]
description: How weight initialization and optimizers evolved from basic techniques to today's standards — each solving the previous one's flaw.
---

# The Problems Are Clear. Now Let's Fix Them. 🔧

In the [previous post](content/large-language-models/deep-learning/neural-networks-continued.md), we saw two ways training can break:

- **Exploding gradients** — weights blow up
- **Vanishing gradients** — early layers stop learning

Both problems boil down to: the **initial scale of weights** is wrong, and the **way we update them** isn't smart enough.

This post covers two evolution stories:
1. **Weight Initialization** — how we start the network
2. **Optimizers** — how we update the weights during training

Each technique solves the previous one's weakness. Let's trace the journey.

---

# Part 1: Weight Initialization — How to Start Right 🏗️

The weights you start with matter **enormously**. Bad initialization → bad gradients → bad training. Let's see how we got from terrible to great.

![Weight Initialization — The Evolution](content/large-language-models/deep-learning/images/weight_init_evolution.png)

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
| Zero | `w = 0` | Nothing | Symmetry problem |
| Random | `w = random × 0.01` | Simple cases | No rule for scale |
| Xavier (2010) | `w = random × √(1/fan_in)` | Sigmoid, Tanh | Breaks with ReLU |
| **He (2015)** | `w = random × √(2/fan_in)` | **ReLU (standard)** | — |

---

# Part 2: Optimizers — How to Update Weights Smarter ⚡

Once gradients are computed, we need to **update the weights**. The simplest approach is gradient descent. But there are much better ways.

Each optimizer here solves the previous one's limitation.

![Optimizer Paths to the Minimum](content/large-language-models/deep-learning/images/optimizer_comparison.png)

---

## 1. SGD — Stochastic Gradient Descent 🚶

### Formula
```
w = w - learning_rate × gradient
```

### Intuition
Take a step downhill. That's it. The gradient tells you the direction, the learning rate tells you how big the step is.

### Advantage
Dead simple. Easy to understand, easy to implement. Works for simple problems.

### The Problems

1. **Same learning rate for every weight** — some weights need big updates, others need tiny ones. SGD treats them all the same.
2. **Oscillates in ravines** — when the loss surface is shaped like a narrow valley, SGD zigzags back and forth across it instead of sliding down.
3. **Slow convergence** — takes many steps to reach the minimum.

```python
# SGD in raw Python
learning_rate = 0.01

for epoch in range(1000):
    gradient = compute_gradient(weights, data)
    weights = weights - learning_rate * gradient
```

**→ Next optimizer solves this by:** adding "memory" of past steps.

---

## 2. SGD + Momentum 🏃‍♂️

### Formula
```
velocity = β × velocity + gradient
w = w - learning_rate × velocity
```

Where `β` (typically 0.9) controls how much past gradients influence the current step.

### Intuition
Imagine a **ball rolling downhill**. It doesn't stop and restart at every bump — it builds up speed. Momentum does the same for gradient descent.

If the gradient keeps pointing in the same direction, the velocity builds up → **faster convergence**. If the gradient keeps changing direction (oscillation), the back-and-forth cancels out → **smoother path**.

### Advantage
- **Faster** than vanilla SGD
- **Less oscillation** in ravines
- Helps escape small local minima (the ball has enough speed to roll over bumps)

### The Problem
Still uses the **same learning rate for every weight**. Some parameters may need large steps, others may need tiny steps. Momentum doesn't adapt to this.

```python
# SGD + Momentum
velocity = 0
beta = 0.9
learning_rate = 0.01

for epoch in range(1000):
    gradient = compute_gradient(weights, data)
    velocity = beta * velocity + gradient
    weights = weights - learning_rate * velocity
```

**→ Next optimizer solves this by:** adapting the learning rate per parameter.

---

## 3. RMSProp — Root Mean Square Propagation 📊

### Formula
```
cache = β × cache + (1-β) × gradient²
w = w - learning_rate × gradient / (√cache + ε)
```

Where `ε` is a tiny number (like 1e-8) to prevent division by zero.

### Intuition
Track how **big** each gradient has been recently. If a weight has been getting consistently large gradients, **slow it down** (divide by a big number). If a weight has been getting tiny gradients, **speed it up** (divide by a small number).

Each weight gets its own **adaptive learning rate**.

### Advantage
- **Adapts learning rate per parameter** — no more one-size-fits-all
- Works well on problems where different features have very different scales
- Great for **noisy** or **non-stationary** problems

### The Problem
No momentum. Doesn't build up speed in consistent directions.

```python
# RMSProp
cache = 0
beta = 0.999
epsilon = 1e-8
learning_rate = 0.001

for epoch in range(1000):
    gradient = compute_gradient(weights, data)
    cache = beta * cache + (1 - beta) * gradient ** 2
    weights = weights - learning_rate * gradient / (np.sqrt(cache) + epsilon)
```

**→ Next optimizer solves this by:** combining the best of both Momentum and RMSProp.

---

## 4. Adam — Adaptive Moment Estimation 🏆

### Formula
```
# Momentum part (1st moment — mean of gradients)
m = β₁ × m + (1-β₁) × gradient

# RMSProp part (2nd moment — mean of squared gradients)
v = β₂ × v + (1-β₂) × gradient²

# Bias correction (important for early steps)
m_hat = m / (1 - β₁ᵗ)
v_hat = v / (1 - β₂ᵗ)

# Update
w = w - learning_rate × m_hat / (√v_hat + ε)
```

### Intuition
Adam = **Momentum + RMSProp + bias correction**

- The **momentum** part (m) smooths out the direction → less oscillation, faster convergence
- The **RMSProp** part (v) adapts the step size per parameter → no wasted effort
- **Bias correction** fixes the fact that m and v start at 0 and are biased toward zero in early steps

### Advantage
- ✅ Adaptive learning rate per parameter
- ✅ Momentum for faster convergence
- ✅ Works well out of the box with default settings
- ✅ **The default optimizer** for most deep learning tasks today

### Current Standard

```python
import tensorflow as tf

# Adam with default settings — this is what you use 90% of the time
model.compile(
    optimizer='adam',  # lr=0.001, β₁=0.9, β₂=0.999 by default
    loss='mse'
)

# Or with custom settings:
optimizer = tf.keras.optimizers.Adam(
    learning_rate=0.001,
    beta_1=0.9,
    beta_2=0.999,
    epsilon=1e-7
)
```

---

## Optimizer Summary

| Optimizer | Key Idea | Advantage | Weakness |
|---|---|---|---|
| **SGD** | Basic step downhill | Simple | Slow, oscillates, fixed LR |
| **Momentum** | SGD + memory of past steps | Faster, smoother | Still fixed LR per param |
| **RMSProp** | Adaptive LR per parameter | Smart step sizes | No momentum |
| **Adam** | Momentum + RMSProp | Best of both worlds | — (current standard) |

---

# The Default Recipe (2024+) 🍳

When starting a new neural network, use this as your default setup:

```python
import tensorflow as tf

model = tf.keras.Sequential([
    tf.keras.layers.Dense(128, activation='relu',
                          kernel_initializer='he_normal'),  # He init
    tf.keras.layers.Dense(64, activation='relu',
                          kernel_initializer='he_normal'),   # He init
    tf.keras.layers.Dense(1, activation='sigmoid')            # Output
])

model.compile(
    optimizer='adam',          # Adam optimizer
    loss='binary_crossentropy'
)
```

| Setting | Choice | Why |
|---|---|---|
| **Initialization** | He/Kaiming | Designed for ReLU, prevents vanishing/exploding |
| **Activation** | ReLU (hidden), Sigmoid/Softmax (output) | Derivative = 1 for positives, no vanishing |
| **Optimizer** | Adam | Adaptive LR + momentum = fast, stable |

This combination works well for **most** problems. Adjust when you need to.

---

## What's Next? 🚀

You now understand the full training pipeline:
1. **Initialize** weights properly (He)
2. **Forward propagation** through ReLU layers
3. **Compute loss** (MSE, cross-entropy)
4. **Backprop** with chain rule
5. **Update weights** with Adam

Next up in the series: **How text becomes numbers** — Tokenization & Embeddings. The bridge between human language and neural networks.

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*

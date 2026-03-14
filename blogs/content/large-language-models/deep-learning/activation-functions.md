---
title: "Activation Functions — The Evolution of Neural Gatekeepers"
date: 2026-03-14
tags: [deep-learning, neural-networks, activation-functions, relu, sigmoid, pytorch]
description: How activation functions evolved from Sigmoid to modern GELU to solve critical training problems in deep learning.
---

# What is an Activation Function? 🧠

Imagine a highly exclusive nightclub. At the door stands a bouncer. The bouncer listens to all the people requesting entry, calculates how VIP they are, and makes a final decision: *Do they get in, or are they shut out?*

In a neural network, the **Activation Function** is that bouncer.

Every neuron receives a bunch of inputs, multiplies them by their weights, and adds them up (the linear part). But without an activation function to make a non-linear "decision" on that sum, the neuron would just naively pass everything forward. 

As we learned in our previous post, [Neural Networks Continued: Gradients & Backpropagation](content/large-language-models/deep-learning/neural-networks-continued.md), neural networks learn by calculating gradients. If you don't use non-linear activation functions, a network with 100 layers collapses mathematically into a single linear equation (`y = mx + b`). You would never be able to learn complex patterns like image recognition or language translation.

Activation functions add **curves, bends, and thresholds** to the network's understanding of the world. But finding the *perfect* gatekeeper took researchers decades. Let's look at the evolutionary journey of these functions, and how each new invention solved a critical flaw of the previous one.

---

## Stage 1: The Sigmoid Era 🔔 (Solving Linearity)

In the early days of neural networks, researchers needed a function that felt biological—something that smoothly transitioned from "inactive" to "fully active."

### The Fix
They chose the **Sigmoid** function. It takes any number, no matter how huge or negative, and squashes it beautifully between **0 and 1**.

### The Formula
`σ(x) = 1 / (1 + e⁻ˣ)`

![Sigmoid and its Derivative](content/large-language-models/deep-learning/images/sigmoid_and_derivative.png)

```python
# NumPy
import numpy as np
def sigmoid(x): return 1 / (1 + np.exp(-x))

# PyTorch Equivalent
import torch.nn as nn
activation = nn.Sigmoid()
```

### 🚨 The Fatal Flaw: Vanishing Gradients
Look at the flat tails of the Sigmoid curve in the image above. If an input is very large (e.g., 100) or very small (e.g., -100), the curve is completely flat. 

Because the curve is flat, the **gradient (slope) is basically zero**. 
As discussed in our [previous post on Gradients](content/large-language-models/deep-learning/neural-networks-continued.md), if the gradient is zero, backpropagation fails. The network physically cannot update its weights. This **Vanishing Gradient Problem** made it impossible to train networks with more than a few layers.

*(Note: Today, Sigmoid is almost exclusively reserved for the **Output Layer** when doing Yes/No Binary Classification).*

---

## Stage 2: Tanh 〰️ (Trying to fix optimization speed)

Researchers realized that Sigmoid's output is purely positive (0 to 1). This causes issues during gradient descent because updates are forced to swing in the same direction, slowing down training.

### The Fix
Enter **Tanh** (Hyperbolic Tangent). It's essentially a stretched Sigmoid that outputs values between **-1 and 1**. Because it is **zero-centered**, the positive and negative activations balance out, making optimization much faster and more stable.

### The Formula
`tanh(x) = (eˣ - e⁻ˣ) / (eˣ + e⁻ˣ)`

![Tanh and its Derivative](content/large-language-models/deep-learning/images/tanh_and_derivative.png)

```python
# NumPy
def tanh(x): return np.tanh(x)

# PyTorch
activation = nn.Tanh()
```

### 🚨 The Fatal Flaw: Still Vanishing
While it trained faster than Sigmoid, Tanh didn't solve the core issue. It still squashes large numbers, meaning its tails are perfectly flat. **Deep networks still suffered from vanishing gradients.**

---

## Stage 3: ReLU 👑 (The Breakthrough)

How do you stop a gradient from vanishing when numbers get large? You stop squashing them!

### The Fix
In a massive philosophical shift, researchers introduced **ReLU** (Rectified Linear Unit). The logic is incredibly simple: *If the input is negative, output zero. If the input is positive, just pass it through unchanged.*

Because positive numbers are passed through linearly (`y=x`), the slope (gradient) is exactly **`1`**. No matter how deep your network is, multiplying by `1` during backpropagation means the gradient *never* vanishes. ReLU single-handedly allowed the creation of massive deep learning models.

### The Formula
`f(x) = max(0, x)`

![ReLU variants](content/large-language-models/deep-learning/images/relu_variants.png)

```python
# NumPy
def relu(x): return np.maximum(0, x)

# PyTorch
activation = nn.ReLU()
```

### 🚨 The Fatal Flaw: Dead Neurons ⚰️
ReLU is great, but look at the left side of the graph. For *all* negative values, the output is `0` and the slope gradient is `0`. If a neuron is pushed into negative territory by a bad weight update, it outputs zero forever. It receives zero gradient, meaning it can never update its weights to recover. That neuron is effectively **dead**.

---

## Stage 4: Leaky ReLU & PReLU 🩹 (Resurrecting the Dead)

To fix the dead neuron problem, we just need to ensure the left side of the graph isn't perfectly flat.

### The Fix
**Leaky ReLU** introduces a tiny, slight slope (usually `0.01`) for negative numbers. This ensures that even if a neuron dips into the negative, a tiny gradient still flows back, giving it a chance to "wake up" during training.

**PReLU (Parametric ReLU)** takes this a step further by making that `0.01` slope a learnable parameter, allowing the network to decide its own leakiness!

### The Formula (Leaky ReLU)
`f(x) = x if x > 0, else 0.01x`

```python
# NumPy
def leaky_relu(x): return np.where(x > 0, x, 0.01 * x)

# PyTorch
activation = nn.LeakyReLU(negative_slope=0.01)
```

---

## Stage 5: The Smooth Modern Giants ⚡ (ELU, Swish, GELU)

While ReLU and Leaky ReLU are the workhorses of standard deep learning, modern architectures like Transformers (GPT, Llama) require even more stability. The problem with ReLU is the sharp "corner" at zero. In calculus, sharp corners are bad because the derivative abruptly jumps.

### The Fix: Smoothness
Modern activation functions smooth out that corner.

1.  **ELU (Exponential Linear Unit):** Uses an exponential curve for negative numbers, creating a butter-smooth transition while keeping the mean activation close to zero.
2.  **Swish (Google):** Introduced the idea of a *non-monotonic* bump. It dips slightly below zero before rising. This tiny negative bump proved mathematically superior in very deep networks.
3.  **GELU (Gaussian Error Linear Unit):** Almost identical visually to Swish, but modeled on statistical probability distributions. **GELU is the absolute standard for modern Transformers.**

![ELU Activation Function](content/large-language-models/deep-learning/images/elu_activation.png)
![Swish Activation Function](content/large-language-models/deep-learning/images/swish_activation.png)
![GELU Activation Function](content/large-language-models/deep-learning/images/gelu_activation.png)

```python
# PyTorch examples of the state-of-the-art
elu_act = nn.ELU()
swish_act = nn.SiLU() # Swish is called SiLU in PyTorch
gelu_act = nn.GELU()
```

---

## Summary: Output Layer Functions 🎯

While the functions above are used inside the "hidden" layers of a network, the final Output Layer requires specific functions depending on your specific task:

1.  **Linear (`y=x`)**: Used for **Regression**. (e.g., Outputting a continuous house price).
2.  **Sigmoid**: Used for **Binary Classification**. (e.g., Outputting a probability of Spam vs Not Spam).
3.  **Softmax**: Used for **Multi-class Classification**. It takes a raw list of scores and forces them into probabilities that sum perfectly to 100%. (e.g., Is this photo a Cat: 80%, Dog: 15%, or Bird: 5%?).

By understanding this evolutionary history, you now know *why* we use what we use.

Next up: Now that we know how neurons activate, how do we evaluate if they did a good job? Let's explore exactly that in **[Loss Functions — Measuring the Mistakes](content/large-language-models/deep-learning/loss-functions.md)**.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*

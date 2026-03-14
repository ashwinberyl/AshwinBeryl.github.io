---
title: "Optimizers — Navigating the Loss Landscape"
date: 2026-03-14
tags: [deep-learning, neural-networks, optimizers, adam, sgd]
description: How neural networks actually learn by updating their weights, tracing the evolution from SGD to Adam.
---

# What is an Optimizer? 🧭

In our previous post, [Loss Functions — Measuring the Mistakes](content/large-language-models/deep-learning/loss-functions.md), we learned how a neural network calculates *how wrong* its predictions are. 

But knowing you are wrong doesn't magically fix the problem. You have to actively change something to be right next time. In a neural network, that means **updating the weights and biases**.

This is exactly what an **Optimizer** does.

### The Mountain Analogy
Imagine you are blindfolded on top of a highly rugged, bumpy mountain. Your goal is to reach the absolute lowest valley (the minimum loss). 

- The **Loss Function** tells you your current altitude (error).
- The **Gradients** (from backpropagation) tell you the slope under your feet.
- The **Optimizer** is your *strategy for walking*. Do you take small careful steps? Do you run wildly downhill? What happens when you hit a small ditch?

Let's look at the evolutionary history of how researchers figured out the best way to walk down this mathematical mountain.

---

## 1. Stochastic Gradient Descent (SGD) 🚶‍♂️

Stochastic Gradient Descent is the granddaddy of all optimizers. The word "Stochastic" just means we calculate the slope using a small, random batch of data, rather than checking the *entire* dataset for every single step (which would take too long).

### The Strategy
SGD simply asks the gradient: *"Which way is downhill?"* and takes a step in that direction. 
The size of the step is determined by the **Learning Rate**.

### 🚨 The Fatal Flaw: The Drunk Walk
Because SGD only looks at the immediate slope under its feet, it frequently gets confused by narrow ravines. If the terrain is steeper left-to-right than it is forward, SGD will wildly zig-zag back and forth across the ravine, making very slow progress toward the actual bottom.

It can also easily get completely stuck in shallow ditches (local minima).

![SGD Path Optimization](content/large-language-models/deep-learning/images/optimizer_sgd.png)

```python
# PyTorch Implementation
import torch.optim as optim

# A basic SGD optimizer using a learning rate of 0.01
optimizer = optim.SGD(model.parameters(), lr=0.01)
```

---

## 2. SGD with Momentum 🎳 (Solving the Zig-Zag)

How do we stop SGD from zig-zagging and getting stuck in small ditches? We add physics!

### The Fix
Instead of taking a step strictly based on the current slope, **Momentum** remembers the *previous* steps. 

Imagine rolling a heavy bowling ball down the mountain. Even if it hits a small bump or the slope briefly changes direction, the sheer momentum of the ball keeps it rolling forward down the main path of the valley. 

Momentum smooths out the chaotic zig-zags of standard SGD, dampening oscillations and accelerating the optimizer directly toward the minimum.

![Momentum Path Optimization](content/large-language-models/deep-learning/images/optimizer_momentum.png)

```python
# PyTorch Implementation
# We simply add the 'momentum' flag to the SGD optimizer
optimizer = optim.SGD(model.parameters(), lr=0.01, momentum=0.9)
```

### 🚨 The Fatal Flaw: One Size Fits All
Momentum is great, but it has a blind spot. It applies the exact same Learning Rate (step size) to *every single weight* in the network. If your network is reading text, the word "the" appears constantly (large frequent updates), but the word "xylophone" appears rarely. 

Applying the massive momentum built up by "the" to the rare "xylophone" weights destroys their delicate learning process.

---

## 3. RMSprop 📉 (Solving the Single Learning Rate)

We need an optimizer that treats every weight individually, giving them their own custom learning rate.

### The Fix
**RMSprop** (Root Mean Square Propagation) does exactly this. It keeps a running average of the recent gradients for *every specific weight*.

- If a weight has been taking massive, wild steps, RMSprop brutally **shrinks its learning rate** to calm it down.
- If a weight has barely been updated (like our rare "xylophone"), RMSprop **boosts its learning rate** so it actually learns something.

### 🚨 The Fatal Flaw: Missing Momentum
RMSprop brilliantly handles adaptive learning rates, but it threw away the bowling ball! It lost the raw, smooth speed of Momentum.

---

## 4. Adam 👑 (The Modern Standard)

In 2014, researchers asked an obvious question: *Why not both?*

### The Fix
**Adam** (Adaptive Moment Estimation) is quite literally the combination of Momentum and RMSprop. 

1. It calculates the rolling bowling-ball momentum.
2. It calculates the individual, adaptive learning rates for every single weight.
3. It applies them together.

Because it combines the best of both worlds, Adam slices straight through complex loss landscapes, ignoring noise, dodging local minima, and perfectly balancing rare and frequent features. 

**Adam is so good that it is the default starting optimizer for almost 99% of modern Deep Learning architectures (including massive Transformers).**

![Adam Path Optimization](content/large-language-models/deep-learning/images/optimizer_adam.png)

```python
# PyTorch Implementation
# The default, highly optimized standard
optimizer = optim.Adam(model.parameters(), lr=0.001)

# Note: You might also see AdamW, a modern variant that handles 
# weight decay (regularization) slightly better than standard Adam.
optimizer = optim.AdamW(model.parameters(), lr=0.001)
```

---

## Summary: Which one should I use? 📝

| Optimizer | What it is | When to use it |
|---|---|---|
| **Adam / AdamW** | Momentum + Adaptive Learning Rates | **Always start here. It is the gold standard.** |
| **SGD + Momentum** | Fast, rolling updates | When squeezing the absolute last 1% of accuracy in computer vision (ResNets). |
| **Vanilla SGD** | Slow, zig-zagging baseline | Mostly for academic teaching, rarely used in production. |
| **RMSprop** | Adaptive Learning Rates | Used occasionally in older Recurrent Neural Networks (RNNs). |

By pairing the right **Activation Function** (to make decisions), the right **Loss Function** (to measure mistakes), and the right **Optimizer** (to fix the mistakes), you have the complete recipe for a modern neural network.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*---

## What's Next? 🚀

We've covered all the theoretical pieces needed to run a deep learning engine: data flows forward, predictions are made, loss is calculated, the chain rule sends the error backward, and optimizers update the weights.

It's time to build the engine yourself.

Next up: **[Your First ANN — Bringing It All Together](content/large-language-models/deep-learning/your-first-ann.md)**.

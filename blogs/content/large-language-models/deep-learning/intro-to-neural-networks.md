---
title: "The Building Blocks of Neural Networks"
date: 2026-03-14
tags: [deep-learning, neural-networks, beginner, python]
description: A beginner-friendly guide to the core building blocks of neural networks — neurons, layers, weights, biases, and forward propagation.
---

# What Is a Neural Network? 🧠

Imagine you're putting together a team to make a decision.

Each team member looks at one piece of information, forms a quick opinion, and passes it to the next person. The next person combines opinions from multiple people, forms *their* opinion, and passes it along. By the time the message reaches the final person, you've got a well-informed decision.

That's essentially what a neural network does. It's a bunch of small, simple decision-makers (**neurons**) wired together in layers. Each neuron does a tiny calculation, passes the result forward, and together they can learn incredibly complex patterns.

> Neural networks are *inspired* by the human brain, but they're not a simulation of it. They're just a clever way of arranging math functions.

---

## The Neuron — The Smallest Unit 🔬

Let's zoom into a single neuron. Here's what it does:

1. **Takes inputs** — numbers coming in (could be pixel values, prices, anything)
2. **Multiplies each input by a weight** — some inputs matter more than others
3. **Adds them all up** — plus a little extra number called the **bias**
4. **Passes through an activation function** — a non-linear transformation that decides whether to "fire" or not

The formula:

> `z = w₁·x₁ + w₂·x₂ + w₃·x₃ + b`
>
> `output = activation(z)`

That's it. Every neuron in every neural network does exactly this.

![Anatomy of a Single Neuron](content/large-language-models/deep-learning/images/single_neuron.png)

Sound familiar? It should — it's basically the equation of a line (`y = mx + b`) from our [linear regression post](content/large-language-models/machine-learning/simple-linear-regression.md), but with multiple inputs and an activation function on top!

---

## The Perceptron — The Simplest Neural Network 🎯

A **perceptron** is just a single neuron used for **classification** — yes or no, 1 or 0.

Let's say you want to predict: **"Will I pass the exam?"** based on two inputs:
- `x₁` = hours studied
- `x₂` = hours slept

Here's a tiny perceptron:

```python
def perceptron(x1, x2):
    # Weights (how important each input is)
    w1 = 0.7   # studying matters more
    w2 = 0.3   # sleep matters too
    bias = -4   # threshold to pass

    # Weighted sum
    z = w1 * x1 + w2 * x2 + bias

    # Activation: if z > 0, predict "pass" (1), else "fail" (0)
    return 1 if z > 0 else 0

# Test it:
print(perceptron(6, 8))   # Studied 6 hrs, slept 8 hrs → ?
print(perceptron(2, 3))   # Studied 2 hrs, slept 3 hrs → ?
```

```
1   # Pass! ✅
0   # Fail  ❌
```

That's the whole thing. A perceptron is the simplest neural network — one neuron making one decision.

But one neuron can only draw a straight line between "yes" and "no." That's why we need...

---

## Layers — Stacking Neurons 📚

A real neural network has **layers** of neurons:

- **Input Layer** — where raw data enters (one neuron per feature)
- **Hidden Layer(s)** — the "thinking" happens here. Each neuron learns a different pattern
- **Output Layer** — the final answer (a class, a number, a probability)

![Neural Network Layers](content/large-language-models/deep-learning/images/neural_network_layers.png)

### Why hidden layers matter

A single neuron can only learn straight lines. But when you stack neurons in layers, each one learns a piece of the puzzle:

- **Layer 1** might learn edges in an image
- **Layer 2** might combine edges into shapes
- **Layer 3** might combine shapes into objects

More layers = **deeper** network = "**deep learning**." That's literally where the name comes from.

---

## Weights & Biases — The Knobs 🎛️

If a neural network is a machine, then **weights and biases are the knobs you turn** to make it work better.

- **Weights** control how important each input is to a neuron
- **Bias** is an extra nudge — like the intercept in linear regression (remember `b` in `y = mx + b`?)

At the start of training, weights and biases are **random**. The network starts dumb. Through training, it **adjusts** these values until they produce good predictions.

The entire learning process is just this: **find the right weights and biases.**

---

## Forward Propagation — Making a Prediction ➡️

**Forward propagation** is just a fancy term for: *data flows from left to right through the network.*

Each layer takes input → multiplies by weights → adds bias → applies an activation function → sends output to the next layer.

Let's walk through a tiny example:

![Forward Propagation — Data Flows Forward](content/large-language-models/deep-learning/images/forward_propagation.png)

Here's the code for a simple forward pass:

```python
import math

def sigmoid(z):
    """Squashes any number to a value between 0 and 1"""
    return 1 / (1 + math.exp(-z))

def forward_pass(x1, x2):
    # Hidden layer (2 neurons)
    h1 = sigmoid(0.4 * x1 + 0.6 * x2 + 0.1)   # neuron 1
    h2 = sigmoid(-0.2 * x1 + 0.3 * x2 + 0.1)   # neuron 2

    # Output layer (1 neuron)
    output = sigmoid(0.5 * h1 + 0.7 * h2 + 0.0)

    return output

# Pass inputs through the network
result = forward_pass(0.5, 0.8)
print(f"Prediction: {result:.4f}")
```

> We're using a function called **sigmoid** here — it takes any number and squashes it between 0 and 1. Don't worry about the details yet. We have an [entire post dedicated to activation functions](content/large-language-models/deep-learning/activation-functions.md) coming up, where we'll explore why they exist and how they evolved over decades.

That's it. Forward propagation is just **plugging numbers in and calculating the output**, layer by layer.

---

## But Wait — How Does It Actually Learn? 🤔

So far we've built a network that can take inputs and produce an output. But the weights are random, so the output is garbage. The network needs to **learn** the right weights.

This involves three things we haven't covered yet:

1. **How do we figure out which weights caused the error, and how do we fix them?** → That's [Backpropagation](content/large-language-models/deep-learning/neural-networks-continued.md)
2. **How do we measure how wrong the prediction is?** → That's the job of [Loss Functions](content/large-language-models/deep-learning/loss-functions.md)
3. **How do we actually update the weights?** → That's the job of [Optimizers](content/large-language-models/deep-learning/optimizers.md)

Each of these deserves its own deep dive, and that's exactly what the next few posts cover.

---

## Recap — What You Just Learned 🎓

| Concept | What It Does |
|---|---|
| **Neuron** | Takes inputs, multiplies by weights, adds bias, applies activation |
| **Perceptron** | Single neuron for yes/no classification |
| **Layers** | Stack neurons → input layer, hidden layers, output layer |
| **Weights & Biases** | The "knobs" the network adjusts during training |
| **Forward Propagation** | Data flows forward through layers to produce a prediction |

These are the building blocks of **every** neural network — from a single perceptron all the way to the architecture behind ChatGPT. Everything builds on these fundamentals.

---

## What's Next? 🚀

We know how data flows forward through the network. But the network is still dumb — its weights are random. How does it learn from its mistakes and get better?

Next up: **[Backpropagation & Gradient Problems — How Neural Networks Learn](content/large-language-models/deep-learning/neural-networks-continued.md)**.

---

Got questions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*

---
title: "Intro to Neural Networks"
date: 2026-03-14
tags: [deep-learning, neural-networks, beginner, python]
description: A beginner-friendly guide to neural networks — from a single neuron to backpropagation, with illustrations and Python code.
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
4. **Passes through an activation function** — decides whether to "fire" or not

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

Each layer takes input → multiplies by weights → adds bias → applies activation → sends output to the next layer.

Let's walk through a tiny example:

![Forward Propagation — Data Flows Forward](content/large-language-models/deep-learning/images/forward_propagation.png)

Here's the code for a simple forward pass:

```python
import math

def sigmoid(z):
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

That's it. Forward propagation is just **plugging numbers in and calculating the output**, layer by layer.

---

## Activation Functions — Adding the Curves 〰️

Here's a critical question: if every neuron just does `z = w₁x₁ + w₂x₂ + b`, then stacking layers would still give you... a linear equation. You'd just be doing `y = mx + b` with extra steps.

**Activation functions** fix this. They add **non-linearity**, allowing the network to learn curves, not just straight lines.

The three most common ones:

### Sigmoid
- Squashes everything between **0 and 1**
- Great for probabilities
- Formula: `σ(x) = 1 / (1 + e⁻ˣ)`

### ReLU (Rectified Linear Unit)
- Returns **0** for negative inputs, passes positive inputs through unchanged
- The most popular: fast and simple
- Formula: `f(x) = max(0, x)`

### Tanh
- Squashes to **-1 to 1**
- Like sigmoid but centered at zero
- Formula: `tanh(x)`

![Common Activation Functions — Sigmoid, ReLU, Tanh](content/large-language-models/deep-learning/images/activation_functions.png)

```python
import math

def sigmoid(x):
    return 1 / (1 + math.exp(-x))

def relu(x):
    return max(0, x)

def tanh(x):
    return math.tanh(x)

# Compare them
x = -2.0
print(f"Sigmoid({x}) = {sigmoid(x):.4f}")   # 0.1192
print(f"ReLU({x})    = {relu(x)}")            # 0
print(f"Tanh({x})    = {tanh(x):.4f}")        # -0.9640
```

> **Rule of thumb:** Use **ReLU** for hidden layers (fast, works well). Use **Sigmoid** for the output layer when you need a probability (0-1).

---

## Loss Function vs Cost Function 📉

The network made a prediction via forward propagation. But how do we know if it's **good or bad**?

### Loss Function — Error for ONE data point

The loss function measures how wrong the prediction is for a **single** example:

> `Loss = (actual - predicted)²`

If the answer should be `1.0` and the network predicted `0.7`, the loss is `(1.0 - 0.7)² = 0.09`.

### Cost Function — Average error across ALL data points

The cost function is just the **average loss** across your entire dataset:

> `Cost = (1/n) × Σ (actualᵢ - predictedᵢ)²`

This is the **Mean Squared Error (MSE)** we saw in the [linear regression post](content/large-language-models/machine-learning/simple-linear-regression.md). Same concept, different context.

```python
def loss(actual, predicted):
    """Error for one data point"""
    return (actual - predicted) ** 2

def cost(actuals, predictions):
    """Average error across all data points"""
    n = len(actuals)
    total = sum(loss(a, p) for a, p in zip(actuals, predictions))
    return total / n

# Example
actuals     = [1.0, 0.0, 1.0, 0.0]
predictions = [0.9, 0.1, 0.8, 0.3]

print(f"Cost (MSE): {cost(actuals, predictions):.4f}")
# Cost (MSE): 0.0375 — pretty good!
```

Common loss functions:
- **MSE** — for regression (predicting numbers)
- **Binary Cross-Entropy** — for classification (yes/no)
- **Categorical Cross-Entropy** — for multi-class (cat/dog/bird)

The goal of training is simple: **minimize the cost function.**

---

## Backpropagation — How the Network Learns 🔄

Okay, so the network made a prediction (forward propagation) and we measured the error (cost function). Now what?

We need to figure out: **which weights caused the error, and how should we adjust them?**

### The Manager Analogy

Imagine a project failed at a company. The CEO (output layer) knows the project failed, but they need to figure out **who in the chain is responsible.**

They trace backward:
- Did the final team deliver bad work? → Adjust their process
- Did they get bad inputs from a previous team? → Trace further back
- Did the original data team mess up? → Adjust at the source

That's **backpropagation**. The error flows **backward** through the network, and at each step, we figure out how much each weight contributed to the error.

![Backpropagation — Error Flows Backward](content/large-language-models/deep-learning/images/backpropagation_flow.png)

### How it works (intuition, not heavy math)

1. **Compute the error** at the output
2. **Ask:** "How much did each weight in the last layer contribute to this error?"
3. **Send the error backward** to the previous layer
4. **Repeat** through every layer until you reach the inputs
5. **Update all the weights** using **gradient descent** (from our [linear regression post](content/large-language-models/machine-learning/simple-linear-regression.md)!)

The chain rule from calculus makes this possible — but you don't need to know the math to understand the concept. The key insight is:

> **Every weight gets a "blame score" (gradient) telling it how much to change and in which direction.**

---

## The Full Picture — The Training Loop 🔁

Let's put it all together. Training a neural network is just this loop:

```
1. Initialize random weights and biases
2. Forward propagation → get a prediction
3. Compute the cost (how wrong?)
4. Backpropagation → compute gradients (who's to blame?)
5. Update weights using gradient descent
6. Repeat steps 2-5 for many epochs
```

> **What's an epoch?** One epoch = one complete pass through your entire training dataset. If you have 1,000 data points and train for 10 epochs, the network sees every data point 10 times. More epochs = more chances to learn, but too many can lead to **overfitting** (memorizing the data instead of learning the pattern).

Here's a complete mini neural network in Python:

```python
import math
import random

# Sigmoid and its derivative
def sigmoid(x):
    return 1 / (1 + math.exp(-x))

def sigmoid_derivative(x):
    s = sigmoid(x)
    return s * (1 - s)

# Training data: XOR problem (inputs → expected output)
X = [[0, 0], [0, 1], [1, 0], [1, 1]]
y = [0, 1, 1, 0]

# Initialize random weights
random.seed(42)
w_hidden = [[random.uniform(-1, 1) for _ in range(2)] for _ in range(2)]
b_hidden = [random.uniform(-1, 1) for _ in range(2)]
w_output = [random.uniform(-1, 1) for _ in range(2)]
b_output = random.uniform(-1, 1)

learning_rate = 0.5

# Training loop
for epoch in range(10000):
    total_loss = 0

    for inputs, target in zip(X, y):
        # --- Forward propagation ---
        h = []
        h_raw = []
        for j in range(2):
            z = sum(inputs[i] * w_hidden[j][i] for i in range(2)) + b_hidden[j]
            h_raw.append(z)
            h.append(sigmoid(z))

        z_out = sum(h[j] * w_output[j] for j in range(2)) + b_output
        predicted = sigmoid(z_out)

        # --- Cost ---
        loss = (target - predicted) ** 2
        total_loss += loss

        # --- Backpropagation ---
        d_output = -2 * (target - predicted) * sigmoid_derivative(z_out)

        for j in range(2):
            d_hidden = d_output * w_output[j] * sigmoid_derivative(h_raw[j])

            # Update hidden weights
            for i in range(2):
                w_hidden[j][i] -= learning_rate * d_hidden * inputs[i]
            b_hidden[j] -= learning_rate * d_hidden

        # Update output weights
        for j in range(2):
            w_output[j] -= learning_rate * d_output * h[j]
        b_output -= learning_rate * d_output

    if epoch % 2000 == 0:
        print(f"Epoch {epoch}, Cost: {total_loss:.4f}")

# Test the trained network
print("\nResults after training:")
for inputs, target in zip(X, y):
    h = [sigmoid(sum(inputs[i] * w_hidden[j][i] for i in range(2)) + b_hidden[j]) for j in range(2)]
    pred = sigmoid(sum(h[j] * w_output[j] for j in range(2)) + b_output)
    print(f"  Input: {inputs} → Predicted: {pred:.4f} (Expected: {target})")
```

```
Epoch 0, Cost: 1.0154
Epoch 2000, Cost: 0.0185
Epoch 4000, Cost: 0.0063
Epoch 6000, Cost: 0.0035
Epoch 8000, Cost: 0.0023

Results after training:
  Input: [0, 0] → Predicted: 0.0354 (Expected: 0)
  Input: [0, 1] → Predicted: 0.9640 (Expected: 1)
  Input: [1, 0] → Predicted: 0.9639 (Expected: 1)
  Input: [1, 1] → Predicted: 0.0432 (Expected: 0)
```

The network **started random** and **learned XOR** — a pattern that a single perceptron cannot learn, but a two-layer network can. That's the power of hidden layers.

---

## In Practice — Using TensorFlow/Keras 🔧

You just built a neural network from scratch — every weight, every gradient, every update by hand. That's how you learn. But in the real world, you use a framework.

Here's the same XOR network in [TensorFlow/Keras](https://www.tensorflow.org/):

```python
import numpy as np
import tensorflow as tf

# Data — same XOR problem
X = np.array([[0, 0], [0, 1], [1, 0], [1, 1]], dtype=np.float32)
y = np.array([[0], [1], [1], [0]], dtype=np.float32)

# Build the network — same architecture: 2 inputs → 2 hidden → 1 output
model = tf.keras.Sequential([
    tf.keras.layers.Dense(2, activation='sigmoid', input_shape=(2,)),
    tf.keras.layers.Dense(1, activation='sigmoid')
])

# Compile — same loss and learning rate
model.compile(
    optimizer=tf.keras.optimizers.SGD(learning_rate=0.5),
    loss='mse'
)

# Train — same 10,000 epochs
model.fit(X, y, epochs=10000, verbose=0)

# Test
predictions = model.predict(X, verbose=0)
for inputs, pred, target in zip(X, predictions, y):
    print(f"Input: {inputs.astype(int)} → Predicted: {pred[0]:.4f} (Expected: {int(target[0])})")
```

```
Input: [0 0] → Predicted: 0.0341 (Expected: 0)
Input: [0 1] → Predicted: 0.9658 (Expected: 1)
Input: [1 0] → Predicted: 0.9659 (Expected: 1)
Input: [1 1] → Predicted: 0.0398 (Expected: 0)
```

Same result, **way less code**. `Dense(2, activation='sigmoid')` creates a layer with 2 neurons and sigmoid activation — exactly what we built by hand. `model.fit()` handles forward prop, backprop, and weight updates.

> **Why learn the raw code first?** Because when you see `Dense(2, activation='sigmoid')`, you now know exactly what it's doing: weighted sums, biases, sigmoid squashing, gradient updates. You're not guessing — you *know*.

---

## Recap — What You Just Learned 🎓

| Concept | What It Does |
|---|---|
| **Neuron** | Takes inputs, multiplies by weights, adds bias, applies activation |
| **Perceptron** | Single neuron for yes/no classification |
| **Layers** | Stack neurons for deeper learning |
| **Weights & Biases** | The "knobs" the network adjusts during training |
| **Forward Propagation** | Data flows forward to make a prediction |
| **Activation Functions** | Add non-linearity so the network can learn curves |
| **Loss / Cost Function** | Measure how wrong the prediction is |
| **Backpropagation** | Error flows backward to figure out which weights to adjust |
| **Training Loop** | Forward → Cost → Backward → Update → Repeat |

You now understand the core of **every** neural network — from a single perceptron all the way to the architecture behind ChatGPT. Everything builds on these fundamentals.

---

## What's Next? 🚀

Now that you know how neural networks learn, it's time to explore how **text** gets converted into numbers that networks can understand. Next up: **Tokenization & Embeddings** — the bridge between human language and neural networks.

Got questions or suggestions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*

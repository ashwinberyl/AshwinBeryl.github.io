---
title: Simple Linear Regression
date: 2026-03-13
tags: [machine-learning, linear-regression, python, gradient-descent]
description: A beginner-friendly, visual guide to Simple Linear Regression — from a chocolate shop analogy to gradient descent, with illustrations and Python code.
---

# The Chocolate Shop 🍫

Imagine you walk into a chocolate shop. The price list is simple:

| Chocolates | Price (₹) |
|---|---|
| 1 | 1 |
| 2 | 2 |
| 3 | 3 |
| 5 | 5 |
| 10 | 10 |

Now I ask you: **how much for 50 chocolates?**

You instantly say **₹50**. No calculator, no formula — you just *saw the pattern*.

Congratulations. You just did **machine learning** in your head. You looked at data, found a pattern, and used it to **predict** a value you'd never seen before.

That pattern? It's called **Linear Regression**, and it's the very first algorithm you'll learn in ML. Let's break it down.

---

## Drawing the Line ✏️

Let's plot that chocolate data on a graph — chocolates on the X-axis, price on the Y-axis.

![The Chocolate Shop — A Perfect Linear Relationship](content/large-language-models/machine-learning/images/chocolate_line_plot.png)

See how all the points fall perfectly on a straight line? That line has an equation you probably remember from school:

> **y = mx + b**

Where:
- **y** = the thing we want to predict (price)
- **x** = the input (number of chocolates)
- **m** = the **slope** (how steep the line is)
- **b** = the **intercept** (where the line crosses the Y-axis)

In our chocolate shop: `y = 1x + 0` — slope is 1, intercept is 0. Simple.

---

## What's the Slope? 📐

The slope tells you: **for every additional unit of X, how much does Y change?**

In plain English:
- Slope of 1 = "every extra chocolate costs ₹1 more"
- Slope of 0.8 = "every extra chocolate costs ₹0.80 more" (bulk discount!)
- Slope of 2 = "every extra chocolate costs ₹2 more" (premium chocolates!)

The formula is straightforward:

```
m = (y₂ - y₁) / (x₂ - x₁)
```

Pick any two points — say (2, 2) and (5, 5):

```
m = (5 - 2) / (5 - 2) = 3/3 = 1
```

A steeper line means a bigger slope. A flatter line means a smaller slope.

![Slope Comparison — Steep vs Flat Lines](content/large-language-models/machine-learning/images/slope_comparison.png)

---

## What's the Intercept? 🎯

Now imagine the shop charges a **₹5 bag fee** — even if you buy zero chocolates, you still pay ₹5.

That ₹5 is the **y-intercept** (`b`). It's the value of Y when X is 0.

Our equation becomes:

```
y = 1x + 5
```

So 10 chocolates = `1(10) + 5 = ₹15`.

![The Y-Intercept — Your Starting Cost](content/large-language-models/machine-learning/images/intercept_illustration.png)

The intercept shifts the entire line up or down. It's the "starting point" of your prediction, even before the slope kicks in.

---

## Let's Get Real — Predicting House Prices 🏠

Chocolates are nice, but let's try something real. Imagine you have data on house sizes and their prices:

| Size (sq ft) | Price (₹ Lakhs) |
|---|---|
| 600 | 25 |
| 800 | 32 |
| 1000 | 38 |
| 1200 | 45 |
| 1500 | 55 |
| 1800 | 60 |
| 2000 | 72 |
| 2200 | 78 |

Unlike chocolates, these points **don't fall on a perfect line**. They're scattered around a general trend. So which line is the "best" one?

Here's how you'd plot it in Python:

```python
import matplotlib.pyplot as plt

sizes = [600, 800, 1000, 1200, 1500, 1800, 2000, 2200]
prices = [25, 32, 38, 45, 55, 60, 72, 78]

plt.scatter(sizes, prices, color='steelblue', s=80)
plt.xlabel('House Size (sq ft)')
plt.ylabel('Price (₹ Lakhs)')
plt.title('House Size vs Price')
plt.grid(alpha=0.3)
plt.show()
```

This is exactly the problem **Linear Regression** solves — finding the best values of `m` and `b` so the line fits the data as closely as possible.

---

## The Algorithm — How Does It Find the Best Line?

Linear Regression's goal is simple:

> Find the values of **m** (slope) and **b** (intercept) that draw the **best-fit line** through the data.

But "best-fit" needs a definition. How do we *measure* how good a line is?

---

## The Cost Function — Measuring Errors 📏

For every data point, there's a gap between what our line **predicts** and the **actual** value. That gap is the **error** (or "residual").

![Cost Function — Measuring the Errors](content/large-language-models/machine-learning/images/error_lines.png)

We need a single number that captures how bad *all* the errors are. The most common one is **Mean Squared Error (MSE)**:

```
MSE = (1/n) × Σ (actual - predicted)²
```

Why *squared*?
- So positive and negative errors don't cancel each other out
- So larger errors are penalized more heavily

**Lower MSE = better fit.** Our goal is to find the `m` and `b` that **minimize** the MSE.

Here's MSE in Python:

```python
def compute_mse(m, b, X, y):
    """Calculate Mean Squared Error."""
    n = len(X)
    total_error = 0
    for i in range(n):
        predicted = m * X[i] + b
        total_error += (y[i] - predicted) ** 2
    return total_error / n

# Example: a random guess
mse = compute_mse(m=0.03, b=5, X=sizes, y=prices)
print(f"MSE with initial guess: {mse:.2f}")
```

So now we have a way to score any line. But how do we find the line with the **lowest** score?

---

## Gradient Descent — Finding the Minimum ⛰️

This is where the magic happens. Here's the intuition:

> Imagine you're **blindfolded** at the top of a valley. You can't see the bottom, but you can **feel the slope** under your feet. So you take a step in the direction that goes downhill. Then another. And another. Eventually, you reach the bottom.

That's **Gradient Descent**. The "valley" is the cost function, and the "bottom" is the lowest MSE.

![Gradient Descent — Rolling to the Minimum](content/large-language-models/machine-learning/images/gradient_descent_curve.png)

### Step by step:

1. **Start with random values** for `m` and `b` (your starting position on the hill)
2. **Calculate the cost** (MSE) — how far are you from the bottom?
3. **Compute the gradients** — which direction is downhill?
   - Gradient for m: `∂MSE/∂m = (-2/n) × Σ xᵢ(yᵢ - ŷᵢ)`
   - Gradient for b: `∂MSE/∂b = (-2/n) × Σ (yᵢ - ŷᵢ)`
4. **Update the parameters:**
   - `m = m - learning_rate × gradient_m`
   - `b = b - learning_rate × gradient_b`
5. **Repeat** until the cost stops decreasing

Here's the full implementation in Python:

```python
def gradient_descent(X, y, learning_rate=0.0000001, epochs=1000):
    m, b = 0, 0  # Start with zeros
    n = len(X)

    for epoch in range(epochs):
        # Predictions with current m and b
        predictions = [m * x + b for x in X]

        # Compute gradients
        grad_m = (-2/n) * sum(X[i] * (y[i] - predictions[i]) for i in range(n))
        grad_b = (-2/n) * sum(y[i] - predictions[i] for i in range(n))

        # Update parameters
        m = m - learning_rate * grad_m
        b = b - learning_rate * grad_b

        # Print progress every 200 steps
        if epoch % 200 == 0:
            cost = sum((y[i] - predictions[i])**2 for i in range(n)) / n
            print(f"Epoch {epoch}: m={m:.4f}, b={b:.4f}, MSE={cost:.2f}")

    return m, b

# Run it on our house data
m, b = gradient_descent(sizes, prices)
print(f"\nFinal: y = {m:.4f}x + {b:.4f}")
```

Each iteration, the algorithm takes a small step closer to the best line. After enough steps, `m` and `b` converge to optimal values.

---

## Learning Rate — The Step Size 👟

The **learning rate** controls how big each step is. Get it wrong, and things break:

- **Too large** → You overshoot the minimum, bounce back and forth, and may never converge
- **Too small** → You'll get there eventually... in a million years
- **Just right** → Smooth, efficient convergence

![Choosing the Right Learning Rate](content/large-language-models/machine-learning/images/learning_rate_comparison.png)

In practice:
- Start with a small value like `0.01` or `0.001`
- If the cost *increases*, your learning rate is too high
- If it barely decreases, try a larger rate
- Many frameworks auto-tune this for you

---

## Wrapping Up — What Else? 📦

We've covered the core of Simple Linear Regression. Here's a quick mention of a few related topics for future deep dives:

- **Multiple Linear Regression** — When you have more than one input feature (e.g., house size *and* number of bedrooms). The equation becomes `y = m₁x₁ + m₂x₂ + ... + b`
- **R² Score** — A metric from 0 to 1 that tells you how well your model explains the data. 1.0 = perfect fit
- **Assumptions** — Linear regression assumes a linear relationship, independent errors, and normally distributed residuals
- **Regularization (Ridge & Lasso)** — Techniques to prevent overfitting by penalizing large coefficients

These are topics for future posts!

---

## The Big Picture

Let's zoom out. Everything we learned today started with a chocolate shop:

| Concept | Chocolate Analogy |
|---|---|
| **Data** | Price list (1 chocolate = ₹1) |
| **Model** | The equation y = mx + b |
| **Slope (m)** | Price per chocolate |
| **Intercept (b)** | Bag charge |
| **Cost function** | How "wrong" our line is |
| **Gradient Descent** | Adjusting m and b until the line fits |
| **Learning Rate** | How fast we adjust |

Linear Regression is the "Hello World" of machine learning. Once you understand it, everything else — logistic regression, neural networks, deep learning — is built on the same fundamental ideas: **data in, find patterns, predict**.

---

*Happy learning! 🚀*

*— Ashwin*

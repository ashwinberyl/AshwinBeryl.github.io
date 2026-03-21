---
title: "Your First ANN — Bringing It All Together"
date: 2026-03-15
tags: [deep-learning, artificial-neural-networks, keras, google-colab, tutorial, hands-on]
description: A practical, step-by-step tutorial on building your first Artificial Neural Network for binary classification in Google Colab, applying all the theoretical concepts we've learned so far.
---

# Your First Artificial Neural Network (ANN)

Over the past few posts, we've taken a deep dive into the theoretical machinery of deep learning. We've looked at how networks make predictions, how they learn through backpropagation, the gatekeepers of signals (activation functions), how we measure mistakes (loss functions), and how we update our knowledge to improve (optimizers).

Now, it's time to stop looking at the blueprints and start building the engine. In this hands-on tutorial, we are going to build **Your First Artificial Neural Network**. 

## What is an ANN? 🧠

Before we write code, let's briefly recap. An **Artificial Neural Network (ANN)** is a computing system inspired by the biological neural networks that constitute human brains. Think of it as a complex mathematical function designed to recognize underlying relationships in a set of data. 

It consists of:
- **Input Layer:** Receives the raw data (features).
- **Hidden Layers:** One or more layers of "neurons" that apply mathematical weights and non-linear activation functions to extract patterns.
- **Output Layer:** Provides the final prediction (e.g., a classification or a continuous value).

By repeatedly passing data through these layers, measuring the error, and adjusting the internal weights mathematically (learning), the ANN becomes highly accurate at complex tasks that traditional programming struggles with.

Here's the exact architecture we'll be building today — a 4-layer network tailored for our binary classification task:

![Our ANN Architecture — 10 inputs → 6 neurons → 6 neurons → 1 output](content/large-language-models/deep-learning/images/ann_architecture_10_6_6_1.png)

## The Mission: Predicting Customer Churn 📉

The best way to learn is by doing. We are going to solve a classic **binary classification** problem: predicting whether a customer will leave a company (churn) or stay, based on their data. 

To follow along, open up a new notebook in [Google Colab](https://colab.research.google.com/) — a free, browser-based Python environment perfect for deep learning.

### Let's set the stage

First, let's import the powerful libraries we need for this task. Copy and paste the block below into your first Colab cell and hit `Shift + Enter`.

```python
# Import data manipulation and machine learning libraries
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

# Import deep learning libraries (TensorFlow and Keras)
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, Dropout, BatchNormalization
from tensorflow.keras.callbacks import EarlyStopping

# Import evaluation and visualization libraries
from sklearn.metrics import accuracy_score, confusion_matrix, classification_report
import matplotlib.pyplot as plt
```

---

## Step 1: Data Preprocessing (The Foundation) 🧹

Neural networks are powerful, but they are very sensitive to the format of the data. They don't understand text like "France" or "Male", and they struggle if one feature is measured in thousands (like Salary) while another is measured in single digits (like Credit Score). 

Here's the pipeline our raw data goes through before the model ever sees it:

![Data Preprocessing Pipeline — From Raw Data to Model-Ready](content/large-language-models/deep-learning/images/data_pipeline_flow.png)

Let's load our dataset, clean it up, and scale it.

```python
# 1. Load the dataset (Assuming you have a CSV named 'Churn_Modelling.csv')
# For this tutorial, we will create a dummy dataset for you to run immediately
np.random.seed(42)
# Simulating 10,000 customers with 10 numerical features
X_dummy = np.random.rand(10000, 10) * 100 
# Simulating binary target (0 = Stayed, 1 = Churned)
y_dummy = np.random.randint(2, size=10000)

# 2. Split into Training (80%) and Testing (20%) sets
X_train, X_test, y_train, y_test = train_test_split(X_dummy, y_dummy, test_size = 0.2, random_state = 0)

# 3. Feature Scaling (CRUCIAL for Neural Networks)
# This normalizes our data so all features have a mean of 0 and variance of 1
sc = StandardScaler()
X_train = sc.fit_transform(X_train)
X_test = sc.transform(X_test)

print("Data successfully preprocessed and scaled!")
print(f"Training set: {X_train.shape[0]} samples")
print(f"Test set: {X_test.shape[0]} samples")
```

> **Why Feature Scaling?** Scaling ensures that our [Optimizers](content/large-language-models/deep-learning/optimizers.md) can navigate the mathematical landscape smoothly and converge on the best solution much faster without bouncing wildly out of control.

> **Why `fit_transform` only on training data?** We call `fit_transform` on the training set to learn the mean and variance, then call `transform` on the test set using those *same* statistics. This prevents **data leakage** — if we calculated the mean/variance using the test set too, we'd be peeking at data the model should never have seen during training.

---

## Step 2: Building the Architecture (Putting Concepts Together) 🏗️

Now we use Keras to stack our layers together, initializing an empty `Sequential` model.

```python
# Initialize the ANN
ann = Sequential()

# Add the First Hidden Layer (and implicitly define the input layer size)
# We use 'relu' to handle non-linear patterns.
ann.add(Dense(units=6, activation='relu', input_dim=10))

# Add the Second Hidden Layer
ann.add(Dense(units=6, activation='relu'))

# Add the Output Layer
# Since it's binary classification (Churn: Yes or No), we need 1 output neuron
# We use 'sigmoid' to squash the output into a probability between 0 and 1.
ann.add(Dense(units=1, activation='sigmoid'))

# View the blueprint of our network
ann.summary()
```

Notice the callbacks to our previous concepts! We use the **[ReLU](content/large-language-models/deep-learning/activation-functions.md)** activation function in the hidden layers because it's computationally efficient and helps mitigate the vanishing gradient problem. We cap off the network with a **Sigmoid** function because we need our final answer to act as a probability percentage (e.g., "There is a 78% chance this customer will churn.")

---

### Reading the `model.summary()` Blueprint 🔍

When you run `ann.summary()`, Keras prints a table like this:

```
Model: "sequential"
┌─────────────────────┬────────────────────────┬───────────────┐
│ Layer (type)        │ Output Shape           │ Param #       │
├─────────────────────┼────────────────────────┼───────────────┤
│ dense (Dense)       │ (None, 6)              │ 66            │
│ dense_1 (Dense)     │ (None, 6)              │ 42            │
│ dense_2 (Dense)     │ (None, 1)              │ 7             │
└─────────────────────┴────────────────────────┴───────────────┘
 Total params: 115
 Trainable params: 115
 Non-trainable params: 0
```

This is one of the most useful debugging tools in Keras. Here's how to read it:

- **Output Shape `(None, 6)`:** `None` is a placeholder for the batch size (how many samples the model processes at once). `6` means this layer outputs 6 values per sample.
- **Param #:** The total number of trainable weights and biases in that layer.

**How to calculate parameters:**

Each Dense layer has `(inputs × neurons) + neurons` parameters — the first term is the weights, the second is the biases.

| Layer | Inputs | Neurons | Weights | Biases | Total |
|---|---|---|---|---|---|
| Dense 1 | 10 | 6 | 10 × 6 = 60 | 6 | **66** |
| Dense 2 | 6 | 6 | 6 × 6 = 36 | 6 | **42** |
| Output | 6 | 1 | 6 × 1 = 6 | 1 | **7** |
| | | | | **Grand Total** | **115** |

That's 115 individual numbers the network has to learn the right values for! Understanding this helps you estimate model complexity. A model with millions of parameters needs more data and more training time than one with hundreds.

---

## Step 3: Compiling the Model (Choosing the Rules) ⚖️

The architecture is built, but before we can train it, we have to tell it *how* to learn and *how* to measure its mistakes.

```python
# Compile the ANN
ann.compile(optimizer = 'adam', loss = 'binary_crossentropy', metrics = ['accuracy'])
```

Again, our theory pays off:
- **Optimizer (`adam`):** As discussed in our [Optimizers post](content/large-language-models/deep-learning/optimizers.md), Adam is the current market standard. It dynamically adjusts the learning rate for each parameter, ensuring fast and reliable convergence.
- **Loss (`binary_crossentropy`):** As discussed in our [Loss Functions post](content/large-language-models/deep-learning/loss-functions.md), this is the mathematically correct way to penalize a network that outputs probabilities for a two-class problem.

---

## Step 4: Training with Early Stopping (Working Smart) 🧠⚡

We could just tell the network to train for 1,000 epochs (full passes over the data). But what if it perfectly learns the training data by epoch 200, and starts memorizing the noise (overfitting) by epoch 201? 

To prevent this, we use **Early Stopping**. We tell the network to monitor its performance on a separate validation set, and if that performance stops improving for a set number of epochs (patience), it halts training and restores its best state.

```python
# Set up early stopping
early_stop = EarlyStopping(
    monitor='val_loss', # Watch the validation loss
    patience=10,        # Wait 10 epochs for improvement before stopping
    restore_best_weights=True # Keep the best version of the model
)

# Train the ANN!
history = ann.fit(
    X_train, 
    y_train, 
    batch_size = 32,      # Update weights after every 32 rows of data
    epochs = 100,         # Maximum number of passes
    validation_split=0.2, # Hold back 20% of training data to check performance
    callbacks=[early_stop] # Apply our smart stopping rule
)
```

Run this cell and watch the epochs fly by! You are officially training a neural network.

---

## Step 5: Visualizing the Training History 📊

Training is done, but before evaluating the final number, let's **look** at how the training went. The `history` object we captured contains loss and accuracy values for every single epoch. Plotting them reveals critical insights.

![Training Curves — Spotting Overfitting](content/large-language-models/deep-learning/images/training_curves.png)

```python
# Plot Training vs Validation Loss
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# Loss Curve
axes[0].plot(history.history['loss'], label='Training Loss', color='#3b82f6')
axes[0].plot(history.history['val_loss'], label='Validation Loss', color='#f97316', linestyle='--')
axes[0].set_title('Loss Over Epochs')
axes[0].set_xlabel('Epoch')
axes[0].set_ylabel('Loss')
axes[0].legend()
axes[0].grid(alpha=0.3)

# Accuracy Curve
axes[1].plot(history.history['accuracy'], label='Training Accuracy', color='#3b82f6')
axes[1].plot(history.history['val_accuracy'], label='Validation Accuracy', color='#f97316', linestyle='--')
axes[1].set_title('Accuracy Over Epochs')
axes[1].set_xlabel('Epoch')
axes[1].set_ylabel('Accuracy')
axes[1].legend()
axes[1].grid(alpha=0.3)

plt.tight_layout()
plt.show()
```

### How to read these curves:

- **Healthy training:** Both lines decrease together (loss) or increase together (accuracy), staying close to each other.
- **Overfitting:** The training line keeps improving, but the validation line **stops improving or gets worse**. The gap between them is your model memorizing training noise rather than learning general patterns.
- **Early Stopping kicks in** when the validation loss stops decreasing for `patience` epochs, catching overfitting before it gets bad.

---

## Step 6: Evaluation and Prediction 🎯

Training is done. Let's see how our model performs on the test set data it has never seen before.

```python
# Predict probabilities on the test set
y_pred_prob = ann.predict(X_test)

# Convert probabilities to binary predictions (Threshold: 50%)
y_pred = (y_pred_prob > 0.5).astype(int)

# Calculate final accuracy
accuracy = accuracy_score(y_test, y_pred)
print(f"\nFinal Test Accuracy: {accuracy * 100:.2f}%")
```

*(Note: Because we used dummy randomized data for this specific tutorial code block, the accuracy will hover around 50%, like a coin flip. On the real Churn Modelling dataset with actual customer behaviors, this simple network can easily achieve 85%+ accuracy!)*

---

### Beyond Accuracy — The Confusion Matrix 🧩

Accuracy alone can be misleading. Imagine you have 9,500 customers who stayed and only 500 who churned. A model that *always* predicts "Stay" would be 95% accurate — but it would **never catch a single churner**. Completely useless for the business.

That's why we need a **Confusion Matrix** — it breaks down *exactly* what the model got right and wrong.

![Confusion Matrix — Understanding What Your Model Gets Right and Wrong](content/large-language-models/deep-learning/images/confusion_matrix_labeled.png)

The four quadrants tell you:
- **True Negative (TN):** Model correctly predicted "Stay" → ✅ Good
- **True Positive (TP):** Model correctly predicted "Churn" → ✅ Good
- **False Positive (FP):** Model predicted "Churn" but customer stayed → ⚠️ Unnecessary intervention
- **False Negative (FN):** Model predicted "Stay" but customer actually churned → 🚨 Missed opportunity

```python
# Generate the confusion matrix
cm = confusion_matrix(y_test, y_pred)
print("Confusion Matrix:")
print(cm)
print()

# Generate a detailed classification report
print("Classification Report:")
print(classification_report(y_test, y_pred, target_names=['Stayed', 'Churned']))
```

### What the classification report tells you:

| Metric | What It Means | Formula |
|---|---|---|
| **Precision** | "Of all the customers we *predicted* would churn, how many actually did?" | TP / (TP + FP) |
| **Recall** | "Of all the customers who *actually* churned, how many did we catch?" | TP / (TP + FN) |
| **F1-Score** | The harmonic mean of Precision and Recall — a single balanced score | 2 × (P × R) / (P + R) |

> **When does this matter?** In churn prediction, **Recall** is often more important than Precision. Missing a churning customer (FN) costs the company revenue. Sending an extra retention offer to a loyal customer (FP) is just a small marketing cost. Understanding these trade-offs is what separates a good data scientist from someone who just checks accuracy.

---

## Step 7: Leveling Up — Dropout & Batch Normalization 🛡️

Our basic network works, but production models use two additional techniques to make training more robust. Both are forms of **regularization** — they prevent the model from memorizing the training data.

### Dropout — Teaching Resilience 🎲

Dropout is a brilliantly simple idea: during training, **randomly disable** a percentage of neurons in each layer. This forces the network to spread knowledge across all neurons instead of relying on just a few "star" neurons.

![Dropout — Randomly Disabling Neurons During Training](content/large-language-models/deep-learning/images/dropout_illustration.png)

Think of it like a football team. If the same player always gets the ball, the team falls apart when that player is injured. By randomly benching players during practice, every player learns to contribute, making the whole team more resilient.

During testing/prediction, **all neurons are active** — you get the full team for game day.

### Batch Normalization — Stabilizing the Assembly Line ⚙️

Remember how we scaled the input data in Step 1 using `StandardScaler`? Batch Normalization applies that same idea **inside the network**, normalizing the inputs to every hidden layer, not just the first one.

Without it, as data passes through layers, the distribution of values can shift wildly (a phenomenon called **internal covariate shift**). This forces each layer to constantly readjust, slowing down training. Batch Normalization keeps the data distribution stable at every layer, allowing higher learning rates and faster convergence.

### The Enhanced Architecture

Here's our network rebuilt with both techniques:

```python
# The enhanced, production-ready ANN
ann_v2 = Sequential()

# Hidden Layer 1 + BatchNorm + Dropout
ann_v2.add(Dense(units=6, activation='relu', input_dim=10))
ann_v2.add(BatchNormalization())
ann_v2.add(Dropout(0.3))   # Drop 30% of neurons randomly each training step

# Hidden Layer 2 + BatchNorm + Dropout
ann_v2.add(Dense(units=6, activation='relu'))
ann_v2.add(BatchNormalization())
ann_v2.add(Dropout(0.3))

# Output Layer (NO dropout here — we always want the final prediction)
ann_v2.add(Dense(units=1, activation='sigmoid'))

ann_v2.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])
ann_v2.summary()
```

> **The pattern:** `Dense → BatchNormalization → Dropout` is a common stacking order used in many production architectures. Dense computes the weighted sum, BatchNorm stabilizes the distribution, and Dropout forces resilience. Your model trains faster, generalizes better, and is less likely to overfit.

---

## Bonus: Adapting for Multi-Class Problems 🎨

Everything we built today was for **binary** classification (Churn: Yes or No). But what if you need to classify into 3+ categories, like predicting a customer's plan type (Basic, Premium, Enterprise)?

The changes are surprisingly small:

```python
# For multi-class with 3 categories:
# 1. Output layer uses 'softmax' instead of 'sigmoid'
ann.add(Dense(units=3, activation='softmax'))

# 2. Loss function changes to 'categorical_crossentropy'
ann.compile(optimizer='adam', loss='categorical_crossentropy', metrics=['accuracy'])

# 3. Target labels must be one-hot encoded [1,0,0], [0,1,0], [0,0,1]
#    OR use 'sparse_categorical_crossentropy' with integer labels (0, 1, 2)
```

The theory behind Softmax and Categorical Cross-Entropy is already covered in our [Loss Functions post](content/large-language-models/deep-learning/loss-functions.md) — here we're just showing you the practical Keras implementation.

---

## Congratulations! 🎉

You have successfully built, compiled, trained, and evaluated your first Artificial Neural Network. But more than that — you've learned the practical skills that separate textbook knowledge from real-world application:

### Full Concept Map — Everything You Used Today

| Concept | Where We Used It | Deep Dive |
|---|---|---|
| Neurons, Layers, Forward Propagation | Model architecture with `Dense` layers | [Intro to Neural Networks](content/large-language-models/deep-learning/intro-to-neural-networks.md) |
| ReLU Activation | Hidden layers `activation='relu'` | [Activation Functions](content/large-language-models/deep-learning/activation-functions.md) |
| Sigmoid Activation | Output layer for binary probability | [Activation Functions](content/large-language-models/deep-learning/activation-functions.md) |
| Binary Cross-Entropy Loss | `loss='binary_crossentropy'` | [Loss Functions](content/large-language-models/deep-learning/loss-functions.md) |
| He Weight Initialization | Keras default for ReLU layers | [Weight Initialization](content/large-language-models/deep-learning/weight-initialization.md) |
| Adam Optimizer | `optimizer='adam'` | [Optimizers](content/large-language-models/deep-learning/optimizers.md) |
| Backpropagation & Chain Rule | Happens inside `model.fit()` | [Neural Networks Continued](content/large-language-models/deep-learning/neural-networks-continued.md) |
| Feature Scaling | `StandardScaler` on input data | *This post (Step 1)* |
| Data Leakage Prevention | `fit_transform` vs `transform` | *This post (Step 1)* |
| Model Summary Interpretation | Reading `ann.summary()` output | *This post (Step 2)* |
| Early Stopping | `EarlyStopping` callback | *This post (Step 4)* |
| Training Curve Visualization | Plotting loss/accuracy history | *This post (Step 5)* |
| Confusion Matrix & F1-Score | `classification_report` evaluation | *This post (Step 6)* |
| Dropout Regularization | `Dropout(0.3)` layers | *This post (Step 7)* |
| Batch Normalization | `BatchNormalization()` layers | *This post (Step 7)* |

You now have a foundational, working template that you can apply to almost any structured tabular dataset. Welcome to the world of applied Deep Learning!

---

## Where to Go From Here 🚀

We've built a powerful engine for **tabular data** (rows and columns). But to understand modern AI—specifically Large Language Models (LLMs) like ChatGPT—we need to tackle a much messier type of data: **Language**.

Neural networks only understand numbers, not words. Before we can use Deep Learning architectures on text, we must first learn how to mathematically represent language. Because of this, **we are hitting pause on the Deep Learning module for now**. 

Our next stop is the **Natural Language Processing (NLP)** module. There, we will:
1. Learn how to clean and prepare text.
2. Discover how to turn words into numbers (Word Embeddings).
3. Once we know how to feed words into neural networks, we will **resume Deep Learning** by applying **Recurrent Neural Networks (RNNs)** to our text data.

This is the exact evolutionary path AI researchers took to build LLMs. Let's start the NLP journey here:

👉 **[Introduction to Natural Language Processing (NLP)](content/large-language-models/natural-language-processing/intro-to-nlp.md)**

And if you want to jump straight to where Deep Learning and NLP finally meet, head here:

👉 **[Intro to RNNs & LSTMs — Teaching Neural Networks to Remember](content/large-language-models/natural-language-processing/intro-to-rnn-lstm.md)**

Stay tuned — we're just getting started. 🔥

---

Got questions or suggestions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*

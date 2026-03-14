---
title: "Your First ANN — Bringing It All Together"
date: 2026-03-15
tags: [deep-learning, artificial-neural-networks, keras, google-colab, tutorial, hands-on]
description: A practical, step-by-step tutorial on building your first Artificial Neural Network for binary classification in Google Colab, applying all the theoretical concepts we've learned so far.
---

# Your First Artificial Neural Network (ANN)

Over the past few posts, we’ve taken a deep dive into the theoretical machinery of deep learning. We’ve looked at how networks make predictions, how they learn through backpropagation, the gatekeepers of signals (activation functions), how we measure mistakes (loss functions), and how we update our knowledge to improve (optimizers).

Now, it’s time to stop looking at the blueprints and start building the engine. In this hands-on tutorial, we are going to build **Your First Artificial Neural Network**. 

## What is an ANN? 🧠

Before we write code, let's briefly recap. An **Artificial Neural Network (ANN)** is a computing system inspired by the biological neural networks that constitute animal brains. Think of it as a complex mathematical function designed to recognize underlying relationships in a set of data. 

It consists of:
- **Input Layer:** Receives the raw data (features).
- **Hidden Layers:** One or more layers of "neurons" that apply mathematical weights and non-linear activation functions to extract patterns.
- **Output Layer:** Provides the final prediction (e.g., a classification or a continuous value).

By repeatedly passing data through these layers, measuring the error, and adjusting the internal weights mathematically (learning), the ANN becomes highly accurate at complex tasks that traditional programming struggles with.

## The Mission: Predicting Customer Churn 📉

The best way to learn is by doing. We are going to solve a classic **binary classification** problem: predicting whether a customer will leave a company (churn) or stay, based on their data. 

To follow along, open up a new notebook in [Google Colab](https://colab.research.google.com/) — a free, browser-based Python environment perfect for deep learning.

### Let's set the stage

First, let's import the powerful libraries we need for this task. Copy and paste the block below into your first Colab cell and hit `Shift + Enter`.

```python
# Import data manipulation and machine learning libraries
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

# Import deep learning libraries (TensorFlow and Keras)
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense
from tensorflow.keras.callbacks import EarlyStopping
```

---

## Step 1: Data Preprocessing (The Foundation) 🧹

Neural networks are powerful, but they are very sensitive to the format of the data. They don't understand text like "France" or "Male", and they struggle if one feature is measured in thousands (like Salary) while another is measured in single digits (like Credit Score). 

Let's load our dataset, clean it up, and scale it.

```python
# 1. Load the dataset (Assuming you have a CSV named 'Churn_Modelling.csv')
# For this tutorial, we will create a dummy dataset for you to run immediately
import numpy as np
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
```

> **Why Feature Scaling?** Scaling ensures that our [Optimizers](content/large-language-models/deep-learning/optimizers.md) can navigate the mathematical landscape smoothly and converge on the best solution much faster without bouncing wildly out of control.

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

## Step 5: Evaluation and Prediction 🎯

Training is done. Let's see how our model performs on the test set data it has never seen before.

```python
# Predict probabilities on the test set
y_pred_prob = ann.predict(X_test)

# Convert probabilities to binary predictions (Threshold: 50%)
y_pred = (y_pred_prob > 0.5)

# Calculate final accuracy
from sklearn.metrics import accuracy_score
accuracy = accuracy_score(y_test, y_pred)
print(f"\\nFinal Test Accuracy: {accuracy * 100:.2f}%")
```

*(Note: Because we used dummy randomized data for this specific tutorial code block, the accuracy will hover around 50%, like a coin flip. On the real Churn Modelling dataset with actual customer behaviors, this simple network can easily achieve 85%+ accuracy!)*

---

## Congratulations! 🎉

You have successfully built, compiled, trained, and evaluated your first Artificial Neural Network. You took raw data, scaled it, built a multi-layer architecture, applied modern optimizers and loss functions, and even instituted smart early-stopping callbacks.

You now have a foundational, working template that you can apply to almost any structured tabular dataset for binary classification. Welcome to the world of applied Deep Learning!

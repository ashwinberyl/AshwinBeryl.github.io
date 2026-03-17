---
title: "Word Embeddings & Word2Vec — Words That Understand Meaning"
date: 2026-03-17
tags: [nlp, word-embeddings, word2vec, cbow, skip-gram, cosine-similarity, deep-learning]
description: How Word2Vec uses neural networks to create dense vectors where similar words live close together — covering embeddings, cosine similarity, CBOW vs Skip-Gram, and the famous King − Man + Woman = Queen equation.
---

# From Dumb Vectors to Smart Vectors 🧠

In the [previous post](content/large-language-models/natural-language-processing/bow-tfidf.md), we built our way from One Hot Encoding through Bag of Words to TF-IDF. Each technique was an improvement — TF-IDF even captures word importance. But they all share one fatal flaw: **they have zero understanding of what words actually mean.** "Happy" and "joyful" are complete mathematical strangers. "King" and "queen" are as unrelated as "king" and "bicycle."

Today, we fix that. We're entering the world of **Word Embeddings** — vectors that capture meaning, relationships, and even analogy. This is where NLP starts to feel like magic.

---

## What Are Word Embeddings? 📐

A **word embedding** is a way of representing words as **dense, real-valued vectors** (not sparse binary vectors like One Hot Encoding) where the position of each word in the vector space reflects its **meaning**.

The key principle:

> **Words with similar meanings get vectors that are close together. Words with different meanings get vectors that are far apart.**

Imagine a 2D map (in reality it's 100-300 dimensions, but let's visualize):

![Word Embedding Space — Similar words cluster together, dissimilar words are far apart](content/large-language-models/natural-language-processing/images/embedding_space.svg)

"Happy", "joyful", and "excited" cluster together because they share similar meaning. "Sad" and "angry" are far away. The distances between these points **are** the meaning.

### Sparse vs Dense — What's the Difference?

| | One Hot / BoW / TF-IDF | Word Embeddings |
|---|---|---|
| **Vector type** | Sparse (mostly zeros) | Dense (all values meaningful) |
| **Dimensions** | Vocabulary size (10,000+) | Fixed small size (100-300) |
| **Values** | 0s and 1s (or TF-IDF weights) | Real numbers (e.g., 0.42, -0.17, 0.83) |
| **Meaning** | No semantic info | Position = meaning |
| **Example** | `[0, 0, 0, 1, 0, ..., 0]` | `[0.42, -0.17, 0.83, 0.11, ...]` |

Instead of a 50,000-dimensional sparse vector with one lonely `1`, we now have a compact 300-dimensional dense vector where **every single dimension captures some aspect of the word's meaning.**

---

## Word2Vec — The Breakthrough (Google, 2013) 🚀

**Word2Vec** is the model that made word embeddings mainstream. Published by Tomas Mikolov and his team at Google in 2013, it uses a **shallow neural network** to learn dense vector representations for words.

### How Does It Work? (The Intuition)

Word2Vec is based on a simple but powerful idea:

> **"You shall know a word by the company it keeps."** — J.R. Firth, 1957

A word's meaning is defined by the words that typically surround it. If you see:

```
"The ___ sat on the mat."
"The ___ chased the mouse."
"The ___ purred loudly."
```

You'd guess the blank is **"cat"** — because cats sit on mats, chase mice, and purr. Word2Vec learns exactly this way: it reads billions of sentences, notices which words appear near each other, and assigns similar vectors to words that share similar contexts.

### The Hidden Features

The neural network in Word2Vec doesn't explicitly learn labeled features. But the resulting vectors **implicitly capture** hidden relational features like:

| Dimension | Might Capture | Example |
|---|---|---|
| Dimension 23 | Gender | "king" and "man" high, "queen" and "woman" high |
| Dimension 87 | Royalty | "king" and "queen" high, "man" and "woman" low |
| Dimension 142 | Age | "child" low, "adult" high |
| Dimension 201 | Food-ness | "pizza" and "burger" high, "car" low |

No one explicitly told the model about "gender" or "royalty" — it **discovered** these patterns by reading millions of sentences and noticing that "king" appears in similar contexts as "queen."

### The Famous Equation: King − Man + Woman = Queen 👑

This is the moment that made the entire NLP community lose their minds. Word2Vec vectors support **arithmetic on meaning.**

```
vector("king") - vector("man") + vector("woman") ≈ vector("queen")
```

Here's the intuition: if you take the concept of "king" and subtract the concept of "man" (removing the male component), you're left with the concept of "royalty." Now add the concept of "woman" to that royalty, and you get **"queen."**

![King − Man + Woman = Queen — Vector arithmetic captures semantic relationships](content/large-language-models/natural-language-processing/images/king_queen_equation.svg)

This works because the vector relationships are **consistent**:

```
king → queen    (same offset as)    man → woman
```

The difference between "king" and "queen" is roughly the same vector as the difference between "man" and "woman" — both represent the gender direction in the vector space.

More examples that actually work:

```
Paris - France + Italy     ≈ Rome         (capital city relationship)
bigger - big + small       ≈ smaller      (comparative form)
swimming - swim + run      ≈ running      (verb tense)
```

---

## Cosine Similarity — Measuring Closeness 📏

If Word2Vec places similar words close together, we need a way to **measure** how close two words are. The standard measure is **Cosine Similarity**.

### The Intuition

Instead of measuring the straight-line distance between two vectors (which can be misleading in high dimensions), cosine similarity measures the **angle** between them:

- **Angle of 0°** → Cosine similarity = **1** → Words are identical in meaning
- **Angle of 90°** → Cosine similarity = **0** → Words are completely unrelated
- **Angle of 180°** → Cosine similarity = **-1** → Words are opposite in meaning

![Cosine Similarity — Measuring angles between vectors (0° = identical, 90° = unrelated, 180° = opposite)](content/large-language-models/natural-language-processing/images/cosine_similarity.svg)

### The Math 🧮

For two vectors **A** and **B**:

```
                    A · B             Σ(Aᵢ × Bᵢ)
cos(θ) = ───────────────── = ─────────────────────────
              ‖A‖ × ‖B‖       √(ΣAᵢ²) × √(ΣBᵢ²)
```

Where:
- **A · B** is the **dot product** (multiply corresponding elements and sum them up)
- **‖A‖** is the **magnitude** of A (square root of the sum of squares)

### Worked Example

Let's compute cosine similarity for two tiny 3D vectors:

```
A = [1, 2, 3]    (let's say this represents "happy")
B = [2, 3, 4]    (let's say this represents "joyful")
```

**Step 1: Dot product (A · B)**
```
(1×2) + (2×3) + (3×4) = 2 + 6 + 12 = 20
```

**Step 2: Magnitudes**
```
‖A‖ = √(1² + 2² + 3²) = √(1 + 4 + 9) = √14 ≈ 3.742
‖B‖ = √(2² + 3² + 4²) = √(4 + 9 + 16) = √29 ≈ 5.385
```

**Step 3: Cosine similarity**
```
cos(θ) = 20 / (3.742 × 5.385) = 20 / 20.15 ≈ 0.992
```

A cosine similarity of **0.992** (very close to 1.0) means these vectors point in almost the same direction — "happy" and "joyful" are very similar. ✅

```python
from numpy import dot
from numpy.linalg import norm

A = [1, 2, 3]
B = [2, 3, 4]

cosine_sim = dot(A, B) / (norm(A) * norm(B))
print(f"Cosine Similarity: {cosine_sim:.4f}")
# Cosine Similarity: 0.9926
```

### Why Cosine Over Euclidean Distance?

Euclidean distance measures *how far apart* two points are. But in high-dimensional spaces, two documents about the same topic can have very different magnitudes (one might be a tweet, another a novel) while pointing in the same direction.

Cosine similarity only cares about **direction**, not **magnitude** — making it far more reliable for comparing word and document vectors.

---

## Word2Vec Architectures: CBOW vs Skip-Gram 🏗️

Word2Vec isn't just one algorithm — it has two architectural variants for training. Both learn word embeddings, but they approach the problem from opposite directions.

![CBOW vs Skip-Gram — Two architectures, opposite directions](content/large-language-models/natural-language-processing/images/cbow_vs_skipgram.svg)

### Continuous Bag of Words (CBOW) 🎯

**CBOW** takes the **surrounding context words** as input and tries to predict the **center (target) word.**

Imagine the sentence: `"the cat sat on the mat"`

With a window size of 2 (2 words on each side), CBOW would set up training examples like:

```
Context: [the, sat]        → Predict: cat
Context: [cat, on]         → Predict: sat
Context: [sat, the]        → Predict: on
```

The model asks: *"Given these context words, which word fits in the middle?"*

```
     ┌──────────┐
 the │          │
     │  Neural  │──→ cat (predicted center word)
 sat │ Network  │
     └──────────┘
    (context in)       (target out)
```

### Skip-Gram 🎯

**Skip-Gram** does the exact opposite. It takes a **single center word** as input and tries to predict the **surrounding context words.**

From the same sentence with the same window:

```
Input: cat  → Predict: [the, sat]
Input: sat  → Predict: [cat, on]
Input: on   → Predict: [sat, the]
```

The model asks: *"Given this center word, which words are likely to appear near it?"*

```
     ┌──────────┐
     │          │──→ the
cat  │  Neural  │──→ sat    (predicted context words)
     │ Network  │
     └──────────┘
   (center in)       (context out)
```

### When to Use Which?

| | CBOW | Skip-Gram |
|---|---|---|
| **Input** | Context words | Single center word |
| **Output** | Center word | Context words |
| **Speed** | ⚡ Faster (one prediction) | 🐌 Slower (multiple predictions) |
| **Best for** | **Small** datasets/corpora | **Large, massive** datasets |
| **Strength** | Better on frequent words | Better on rare words |

**Research recommendation:** Use **CBOW** for small datasets (it's faster and smooths over noise). Use **Skip-Gram** for large datasets (it's better at capturing rare words because it creates more training examples per word).

### Window Size — It Matters More Than You Think

The **window size** determines how many words on each side of the center word are considered "context." This number directly affects the quality and dimensionality of your embeddings.

- **Small window (2-5):** Captures **syntactic** relationships (grammatical patterns). Words that are grammatically interchangeable get similar vectors
- **Large window (5-15):** Captures **semantic** relationships (topical similarity). Words that discuss similar topics get similar vectors

> **Fun fact:** Google's famous pre-trained Word2Vec model uses a **300-dimensional** vector space with a window size that produces 300 features per word. That means each word in the English language is represented as a point in 300-dimensional space — and the distances between those points encode meaning.

---

## How the Neural Network Actually Learns 🧠

Let's peek under the hood. Word2Vec's architecture is surprisingly simple — it's a shallow neural network with just **one hidden layer.**

### The Architecture (CBOW example)

```
Input Layer          Hidden Layer         Output Layer
(vocabulary size)    (embedding dim)      (vocabulary size)

  [0]                                       [0.01]
  [0]                  [0.42]               [0.03]
  [1]  ← "cat"        [-0.17]              [0.92] ← "sat" (highest probability)
  [0]      ──→         [0.83]      ──→      [0.02]
  [0]                  [0.11]               [0.01]
  [0]                                       [0.01]

 One-hot input       This IS the          Softmax probabilities
                     embedding!            for each word
```

The **hidden layer weights** *are* the word embeddings. After training on millions of sentences, we throw away the output layer entirely and just keep the hidden layer — those weight values become our word vectors.

### Training Process

1. **Feed** a one-hot encoded word (or averaged context words) into the input
2. **Multiply** by the input→hidden weight matrix → get the embedding
3. **Multiply** by the hidden→output weight matrix → get a probability for every word in the vocabulary
4. **Compare** the predicted word to the actual target word (using cross-entropy loss)
5. **Backpropagate** the error and update the weights
6. **Repeat** for billions of word pairs from the training corpus

After enough iterations, the weight matrix organizes itself so that words appearing in similar contexts get similar vector values.

---

## Recap — What You've Learned 🎓

| Concept | What It Does |
|---|---|
| **Word Embeddings** | Dense vectors where position = meaning |
| **Word2Vec** | Neural network that learns embeddings from context |
| **Cosine Similarity** | Measures how similar two vectors are (0 = unrelated, 1 = identical) |
| **CBOW** | Context → predicts center word (fast, good for small data) |
| **Skip-Gram** | Center word → predicts context (slow, good for big data) |
| **Vector Arithmetic** | King − Man + Woman = Queen (meaning is encoded in directions) |

---

## What's Next? 🚀

Word2Vec gives every individual word a brilliant 300-dimensional vector. But here's the problem we haven't solved yet: **ML models don't take individual words as input — they need a single vector for the entire sentence (or document).**

If a sentence has 10 words, that's 10 separate 300-dimensional vectors. How do you collapse those into **one** 300-dimensional vector that represents the entire sentence's meaning? And how do you actually use Word2Vec in practice, loading Google's pre-trained model and querying real word relationships?

Next up: **[Average Word2Vec & Practical Implementation with Gensim](content/large-language-models/natural-language-processing/average-word2vec-gensim.md)**

---

*— Ashwin*

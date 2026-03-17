---
title: "From Words to Vectors — One Hot Encoding, Bag of Words & TF-IDF"
date: 2026-03-17
tags: [nlp, one-hot-encoding, bag-of-words, tf-idf, text-vectorization, math]
description: Three classical techniques for converting text into numbers — One Hot Encoding, Bag of Words, and TF-IDF — with full math breakdowns, Python code, and an honest look at where each one fails.
---

# The Moment of Truth — Numbers! 🔢

In the [previous post](content/large-language-models/natural-language-processing/text-preprocessing.md), we cleaned our text — tokenized it, removed stop words, and lemmatized everything down to clean root words. But clean text is still *text*. Our ML models still can't eat it. Now we finally cross the bridge: **converting words into numerical vectors.** We'll start with the three simplest approaches, and for each one, we'll see exactly where it shines — and exactly where it falls apart.

---

## 1. One Hot Encoding — The Simplest Possible Approach 🎯

The idea is dead simple: give every unique word in your vocabulary its own "slot," then represent each word as a binary vector of 1s and 0s.

### How It Works

Take this corpus:

```
Document 1: "the cat sat"
Document 2: "the dog played"
```

**Vocabulary:** `[the, cat, sat, dog, played]` → 5 unique words

Now, each word gets a vector of length 5, with a `1` in its position and `0` everywhere else:

| Word | the | cat | sat | dog | played |
|---|---|---|---|---|---|
| **the** | 1 | 0 | 0 | 0 | 0 |
| **cat** | 0 | 1 | 0 | 0 | 0 |
| **sat** | 0 | 0 | 1 | 0 | 0 |
| **dog** | 0 | 0 | 0 | 1 | 0 |
| **played** | 0 | 0 | 0 | 0 | 1 |

```python
from sklearn.preprocessing import OneHotEncoder
import numpy as np

# Our vocabulary
words = ["the", "cat", "sat", "dog", "played"]
words_array = np.array(words).reshape(-1, 1)

encoder = OneHotEncoder(sparse_output=False)
encoded = encoder.fit_transform(words_array)

for word, vec in zip(words, encoded):
    print(f"{word:10s} → {vec.astype(int)}")
```

```
the        → [0 0 0 0 1]
cat        → [1 0 0 0 0]
sat        → [0 0 1 0 0]
dog        → [0 1 0 0 0]
played     → [0 0 0 1 0]
```

Looks neat, right? Now let's talk about why this approach is **terrible** for real NLP.

![One Hot Encoding — The Sparse Matrix Problem](content/large-language-models/natural-language-processing/images/one_hot_sparse.svg)

### 🚨 Problem 1: Sparse Matrix (Too Many Zeros)

A real-world vocabulary might have **50,000+ unique words**. That means every single word is a vector of 50,000 numbers — with only ONE of them being `1` and the rest all `0`.

```
"cat" → [0, 0, 0, ..., 0, 1, 0, ..., 0, 0]   ← 49,999 zeros!
```

This is called a **sparse matrix**. It's horrifically wasteful in memory and leads to severe **overfitting** — the model has way too many features (dimensions) relative to the amount of data.

### 🚨 Problem 2: Variable Input Size

ML models require **fixed-size inputs**. But One Hot vectors for an entire sentence have variable length:

- "the cat sat" → 3 words → 3 vectors of size 5
- "the big fluffy cat sat on the comfortable mat" → 9 words → 9 vectors of size 5

The total input dimensions change depending on the sentence length. You can't feed that directly to a standard ML model.

### 🚨 Problem 3: No Semantic Meaning

This is the killer flaw. In One Hot Encoding, **every word is equally distant from every other word.**

Think about it: "pizza", "burger", and "football". Intuitively, "pizza" and "burger" should be *close* (both are food), and "football" should be *far* (a sport). But in One Hot space:

```
pizza    → [1, 0, 0]
burger   → [0, 1, 0]
football → [0, 0, 1]
```

The mathematical distance between pizza↔burger is the **exact same** as pizza↔football. The model learns **zero** relationships between words. They're all strangers.

![No Semantic Meaning — All words are equidistant in One Hot space](content/large-language-models/natural-language-processing/images/no_semantic_meaning.svg)

### 🚨 Problem 4: Out of Vocabulary (OOV)

What if during testing, a word appears that wasn't in the training vocabulary? For example, the model was trained on `["good", "bad", "great"]` but during testing it sees the word `"excellent"`. 

The model has no vector for it. It **completely fails** — no representation, no prediction. This is called the **Out of Vocabulary (OOV)** problem.

> **Verdict:** One Hot Encoding is great for teaching the concept, but it's practically useless for real NLP. We need something better.

---

## 2. Bag of Words (BoW) — Counting Frequencies 📊

Bag of Words fixes one of One Hot Encoding's problems: it creates **fixed-size vectors** for entire sentences, not individual words.

### How It Works

1. Build the vocabulary from the entire corpus
2. For each document (sentence), count how many times each vocabulary word appears
3. The result is a fixed-size vector where each position represents a word and the value is its **frequency count**

### Worked Example

```
Corpus:
  Document 1: "the food is good"
  Document 2: "the food is not good"
  Document 3: "the food is not bad"
```

**Vocabulary (sorted):** `[bad, food, good, is, not, the]` → 6 unique words

Now count frequencies:

| Document | bad | food | good | is | not | the |
|---|---|---|---|---|---|---|
| "the food is good" | 0 | 1 | 1 | 1 | 0 | 1 |
| "the food is not good" | 0 | 1 | 1 | 1 | 1 | 1 |
| "the food is not bad" | 1 | 1 | 0 | 1 | 1 | 1 |

Each document now has a **fixed-size vector of length 6**, regardless of how many words it contains. ✅

```python
from sklearn.feature_extraction.text import CountVectorizer

corpus = [
    "the food is good",
    "the food is not good",
    "the food is not bad"
]

vectorizer = CountVectorizer()
X = vectorizer.fit_transform(corpus)

print("Vocabulary:", vectorizer.get_feature_names_out())
print("\nBoW Vectors:")
print(X.toarray())
```

```
Vocabulary: ['bad' 'food' 'good' 'is' 'not' 'the']

BoW Vectors:
[[0 1 1 1 0 1]
 [0 1 1 1 1 1]
 [1 1 0 1 1 1]]
```

### Binary BoW vs Normal BoW

By default, BoW counts exact frequencies. But there's a **Binary** variant where any word that appears gets a `1`, regardless of how many times:

```python
# Binary BoW — caps everything at 1
binary_vectorizer = CountVectorizer(binary=True)
X_binary = binary_vectorizer.fit_transform(corpus)

print("Binary BoW:")
print(X_binary.toarray())
```

In our example, the results look the same because no word repeats within a single document. But if Document 1 were "the food food is good good good", Normal BoW would show `food=2, good=3` while Binary BoW would still show `food=1, good=1`.

### 🚨 Problem 1: Word Order Is Destroyed

"Bag of Words" is called that because it literally treats the sentence as a **bag** — it throws away all word ordering.

These two sentences produce **identical** vectors:

```
"the dog bit the man"  → {the: 2, dog: 1, bit: 1, man: 1}
"the man bit the dog"  → {the: 2, man: 1, bit: 1, dog: 1}
```

Same words, same counts, **completely opposite meanings.** BoW can't tell the difference.

### 🚨 Problem 2: Semantic Similarity Failure

Compare these two sentences:

```
Document 1: "the food is good"      → [0, 1, 1, 1, 0, 1]
Document 2: "the food is not good"  → [0, 1, 1, 1, 1, 1]
```

These vectors differ by **only one value** (the "not" column). Mathematically, they look almost identical — the cosine similarity would be extremely high. But they mean the **complete opposite!**

A model trained on BoW vectors would think "the food is good" and "the food is not good" are nearly the same sentence. That's a catastrophic failure for sentiment analysis.

> **Verdict:** BoW gives us fixed-size vectors (good!) and captures word presence (okay!), but it loses word order and fails at understanding meaning. We need a method that also captures **word importance** — some words matter more than others.

---

## 3. TF-IDF — Weighing Words by Importance ⚖️

TF-IDF stands for **Term Frequency – Inverse Document Frequency**. Instead of just counting how often a word appears, it asks a much smarter question:

> *"How important is this word in this specific document, relative to the entire corpus?"*

The intuition: if a word appears in **every** document (like "the"), it's not very informative. But if a word appears in only **one** document (like "delicious"), it's probably a key distinguishing word.

### The Math (Don't Worry, It's Simple) 🧮

![TF-IDF Formula Breakdown — TF measures local frequency, IDF penalizes common words](content/large-language-models/natural-language-processing/images/tfidf_formula.svg)

TF-IDF is the product of two values:

```
TF-IDF(word, document) = TF(word, document) × IDF(word)
```

#### Term Frequency (TF)

How often does the word appear in *this specific document*?

```
TF(word, doc) = (Number of times the word appears in the document)
                ÷ (Total number of words in the document)
```

It's just the fraction of the document that this word occupies.

#### Inverse Document Frequency (IDF)

How rare is this word across the *entire corpus*?

```
IDF(word) = logₑ(Total number of documents ÷ Number of documents containing the word)
```

- If a word appears in **every** document → IDF = log(n/n) = log(1) = **0** → the word gets **zero** weight!
- If a word appears in only **one** document → IDF = log(n/1) = high value → the word gets **high** weight!

### Worked Example (Step by Step) 📝

Let's compute TF-IDF by hand for this corpus:

```
Document 1: "the food is good"         (4 words)
Document 2: "the food is not good"     (5 words)
Document 3: "the food is not bad"      (5 words)
```

**Total documents = 3**

#### Step 1: Compute TF for each word in each document

| Word | Doc 1: TF | Doc 2: TF | Doc 3: TF |
|---|---|---|---|
| the | 1/4 = 0.250 | 1/5 = 0.200 | 1/5 = 0.200 |
| food | 1/4 = 0.250 | 1/5 = 0.200 | 1/5 = 0.200 |
| is | 1/4 = 0.250 | 1/5 = 0.200 | 1/5 = 0.200 |
| good | 1/4 = 0.250 | 1/5 = 0.200 | 0/5 = 0.000 |
| not | 0/4 = 0.000 | 1/5 = 0.200 | 1/5 = 0.200 |
| bad | 0/4 = 0.000 | 0/5 = 0.000 | 1/5 = 0.200 |

#### Step 2: Compute IDF for each word

| Word | Documents containing it | IDF = log(3 / count) |
|---|---|---|
| the | 3 (all of them) | log(3/3) = log(1) = **0.000** |
| food | 3 | log(3/3) = **0.000** |
| is | 3 | log(3/3) = **0.000** |
| good | 2 (Doc 1, Doc 2) | log(3/2) = **0.405** |
| not | 2 (Doc 2, Doc 3) | log(3/2) = **0.405** |
| bad | 1 (Doc 3 only) | log(3/1) = **1.099** |

Look at that! The words "the", "food", and "is" appear in *every* document, so their IDF is **exactly 0**. They get completely nullified — TF-IDF automatically recognizes them as uninformative common words.

Meanwhile, "bad" appears in only one document, so it gets the **highest** IDF of 1.099.

#### Step 3: Multiply TF × IDF

| Word | Doc 1: TF-IDF | Doc 2: TF-IDF | Doc 3: TF-IDF |
|---|---|---|---|
| the | 0.250 × 0.000 = **0.000** | 0.200 × 0.000 = **0.000** | 0.200 × 0.000 = **0.000** |
| food | 0.250 × 0.000 = **0.000** | 0.200 × 0.000 = **0.000** | 0.200 × 0.000 = **0.000** |
| is | 0.250 × 0.000 = **0.000** | 0.200 × 0.000 = **0.000** | 0.200 × 0.000 = **0.000** |
| good | 0.250 × 0.405 = **0.101** | 0.200 × 0.405 = **0.081** | 0.000 × 0.405 = **0.000** |
| not | 0.000 × 0.405 = **0.000** | 0.200 × 0.405 = **0.081** | 0.200 × 0.405 = **0.081** |
| bad | 0.000 × 1.099 = **0.000** | 0.000 × 1.099 = **0.000** | 0.200 × 1.099 = **0.220** |

**Final TF-IDF Vectors:**

```
Document 1: [0.000, 0.000, 0.000, 0.101, 0.000, 0.000]
Document 2: [0.000, 0.000, 0.000, 0.081, 0.081, 0.000]
Document 3: [0.000, 0.000, 0.000, 0.000, 0.081, 0.220]  ← "bad" gets the highest weight!
```

The common words ("the", "food", "is") are all zeros. The rare, meaningful words ("good", "not", "bad") carry all the weight. **That's TF-IDF's superpower: it automatically identifies which words matter.**

### TF-IDF in Python (The Easy Way)

```python
from sklearn.feature_extraction.text import TfidfVectorizer

corpus = [
    "the food is good",
    "the food is not good",
    "the food is not bad"
]

vectorizer = TfidfVectorizer()
X = vectorizer.fit_transform(corpus)

print("Vocabulary:", vectorizer.get_feature_names_out())
print("\nTF-IDF Vectors:")
print(X.toarray().round(3))
```

> **Note:** Scikit-learn's implementation uses a slightly different formula (adds smoothing and L2 normalization), so the exact numbers will differ from our hand calculation, but the *principle* is identical — common words get low weights, rare words get high weights.

---

## The Scoreboard — Comparing All Three 📋

| Feature | One Hot Encoding | Bag of Words | TF-IDF |
|---|---|---|---|
| **Vector type** | Per word | Per document | Per document |
| **Fixed size?** | ❌ Variable | ✅ Fixed | ✅ Fixed |
| **Captures frequency?** | ❌ No | ✅ Yes | ✅ Yes |
| **Captures word importance?** | ❌ No | ❌ No | ✅ Yes |
| **Captures meaning?** | ❌ No | ❌ No | ❌ No |
| **Captures word order?** | ❌ No | ❌ No | ❌ No |
| **OOV handling?** | ❌ Fails | ❌ Fails | ❌ Fails |

TF-IDF is clearly the best of the three — it gives us fixed-size vectors that highlight important words. It's still used today for search engines, document ranking, and simpler classification tasks.

But look at that last column. **None of them capture meaning.** None of them understand that "happy" and "joyful" are similar, or that "king" and "queen" are related. They treat every word as an isolated, independent entity.

---

## What's Next? 🚀

TF-IDF got us pretty far. It gives smart, weighted vectors that highlight the words that matter. But all three methods we've seen share a fundamental, unfixable flaw: **they have zero understanding of what words actually mean.**

"Happy" and "joyful" are complete mathematical strangers in BoW and TF-IDF space. "King" and "queen" are as unrelated as "king" and "pizza." The vectors carry no semantic information whatsoever.

What if we could create vectors where words with similar meanings are **mathematically close** to each other? Where "happy" and "excited" cluster together, and "happy" and "angry" are far apart? Where you could literally do math like `King - Man + Woman = Queen`?

That's exactly what **Word Embeddings** and **Word2Vec** deliver.

Next up: **[Word Embeddings & Word2Vec — Words That Understand Meaning](content/large-language-models/natural-language-processing/word-embeddings-word2vec.md)**

---

*— Ashwin*

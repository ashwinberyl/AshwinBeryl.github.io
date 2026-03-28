---
title: "Building a Fake News Classifier Using LSTM — A Practical NLP Walkthrough"
date: 2026-03-22
tags: [nlp, lstm, deep-learning, tensorflow, keras, fake-news, binary-classification, practical]
description: Day 10 of our NLP series — a hands-on, step-by-step implementation of an LSTM network to classify fake news. Covers data cleaning, stemming, one-hot encoding, sequence padding, embedding layers, model training, evaluation metrics, and dropout regularization.
---

# Welcome Back, NLP Enthusiasts! 🗞️🔍

In our [previous post](content/large-language-models/natural-language-processing/rnn.md), we explored the theory behind **Recurrent Neural Networks (RNNs)** — how they process sequences, why vanilla RNNs suffer from vanishing gradients, and how the mathematics of Backpropagation Through Time (BPTT) works.

Today, we're putting all of that theory into practice. We're building a **Fake News Classifier** — a real-world binary classification system that reads a news headline and predicts whether the article is **Real** or **Fake**.

This walkthrough follows our Google Colab notebook ([FakeNewsClassifierUsingLSTM.ipynb](https://github.com/AshwinBeryl/AshwinBeryl.github.io/blob/main/FakeNewsClassifierUsingLSTM.ipynb)) step by step. Every code block below is production code from the notebook, and every decision is explained with a clear *why*.

Let's dive in!

---

## The Full Pipeline at a Glance 🔭

Before we get into each step, here's the entire journey our data takes — from a raw CSV file to a trained LSTM producing predictions:

![LSTM Fake News Classification Pipeline — From Raw CSV to Prediction](content/large-language-models/natural-language-processing/images/fake_news_pipeline_flow.png)

Each box in the diagram above is a step we'll implement below. By the end, you'll understand exactly how text goes from messy human language to a mathematical signal an LSTM can learn from.

---

## Step 1: Loading and Inspecting the Data 📂

We start by importing pandas and reading our `train.csv` dataset, which comes from the [Kaggle Fake News competition](https://www.kaggle.com/c/fake-news/data#). The dataset contains features like `id`, `title`, `author`, `text`, and `label`.

```python
import pandas as pd

df = pd.read_csv('train.csv')
df.head()
```

```
   id                                              title              author  ...  label
0   0  House Dem Aide: We Didn't Even See Comey's Let...       Darrell Lucus  ...      1
1   1  FLYNN: Hillary Clinton, Big Woman on Campus - ...     Daniel J. Flynn  ...      0
2   2                  Why the Truth Might Get You Fired  Consortiumnews.com  ...      1
3   3  15 Civilians Killed In Single US Airstrike Hav...     Jessica Purkiss  ...      1
4   4  Iranian woman jailed for fictional unpublished...      Howard Portnoy  ...      1
```

```python
df.shape
# Output: (20800, 5)
```

> **Why this matters:** Inspecting raw data is the foundational step of any machine learning pipeline. Notice the `label` column — a value of **1** indicates **Fake News**, while **0** indicates **Real News**. This makes our problem a straightforward **binary classification** task — exactly the kind of problem [sigmoid + binary cross-entropy](content/large-language-models/deep-learning/loss-functions.md) was designed for.

---

## Step 2: Handling Missing Values (Data Cleaning) 🧹

Text data can't be imputed like numerical features. You can't take the "mean" of a missing title!

```python
df.isnull().sum()
```

```
id           0
title      558
author    1957
text        39
label        0
dtype: int64
```

That's roughly 2,000 rows with missing data. Since we have over **20,800 records**, dropping these incomplete rows is a safe approach:

```python
# Drop NaN values
df = df.dropna()

# Separate independent and dependent features
X = df.drop('label', axis=1)
y = df['label']

X.shape, y.shape
# Output: ((18285, 4), (18285,))
```

> **Why drop instead of impute?** In NLP, you cannot mathematically impute missing text data — substituting a missing title or author with a mean/median value makes no sense. With **18,285 clean records remaining**, we have more than enough data for our LSTM to learn from.

> **Why isolate the title column?** Training an LSTM on the entire article text body would be **heavily computationally expensive** and time-consuming. The title alone carries enough signal for classification, and it keeps our sequences short (most titles are 10-12 words), making training fast and practical.

---

## Step 3: Text Preprocessing — Stemming and Stopwords 🔤

This is where we transform messy human text into clean, normalized input. We build a **Corpus** — a list of cleaned title strings.

```python
import nltk
import re
from nltk.corpus import stopwords
from nltk.stem.porter import PorterStemmer

nltk.download('stopwords')
ps = PorterStemmer()

corpus = []
for i in range(0, len(messages)):
    # Step 1: Remove special characters (keep only letters)
    review = re.sub('[^a-zA-Z]', ' ', messages['title'][i])
    
    # Step 2: Convert to lowercase
    review = review.lower()
    
    # Step 3: Split into individual words
    review = review.split()
    
    # Step 4: Remove stopwords and apply stemming
    review = [ps.stem(word) for word in review 
              if not word in stopwords.words('english')]
    
    # Step 5: Rejoin into a clean string
    review = ' '.join(review)
    corpus.append(review)
```

**Before preprocessing:**
```
"FLYNN: Hillary Clinton, Big Woman on Campus - Breitbart"
```

**After preprocessing:**
```
"flynn hillari clinton big woman campu breitbart"
```

> **Why strip special characters?** Characters like colons, dashes, and commas don't contribute to the factual or sentimental classification of text. They're noise.
>
> **Why remove stopwords?** Words like "he", "she", "the", "is", "on" appear in virtually every sentence. They carry no discriminative power for classification and just bloat our vocabulary.
>
> **Why stemming over lemmatization?** We covered both techniques in our [Text Preprocessing blog](content/large-language-models/natural-language-processing/text-preprocessing.md). Stemming is **computationally faster** because it simply chops word endings without dictionary lookups. With 18,285 titles to process, speed matters. "Hillary" → "hillari" loses some readability, but maintains the root signal the model needs.

---

## Step 4: One-Hot Representation 🔢

Neural networks can't process raw text strings. We need to map every word to a number. TensorFlow's `one_hot` function does exactly this — it maps each word to an integer index within a fixed-size vocabulary dictionary.

```python
from tensorflow.keras.preprocessing.text import one_hot

# Define vocabulary size
voc_size = 5000

# Convert each word to its one-hot index
onehot_repr = [one_hot(words, voc_size) for words in corpus]
```

**Example:**
```
Cleaned title:  "flynn hillari clinton big woman campu breitbart"
One-hot indices: [2861, 147, 1342, 1829, 62, 4605, 721]
```

Each word gets mapped to a number between 0 and 4,999. These numbers are **not** meaningful on their own — they're just lookup keys that the Embedding layer (next step) will use to find the actual dense vector representation.

> **Why cap at 5,000?** Capping the vocabulary size controls the dimensions of our representations. A vocabulary of 50,000 would need a much larger embedding matrix (50,000 × 40 = 2 million parameters just for embeddings). Our 5,000-word vocabulary captures the most frequent and important words while keeping the model lightweight and fast to train.

---

## Step 5: Sequence Padding ✂️📏

Our titles have wildly different lengths — some are 4 words, others are 15+. But LSTMs require **fixed-length inputs**. We need every sequence to be exactly the same size.

```python
from tensorflow.keras.preprocessing.sequence import pad_sequences

sent_length = 20
embedded_docs = pad_sequences(onehot_repr, padding='post', maxlen=sent_length)
```

**Before padding** (variable lengths):
```
[4719, 1908, 3457, 2009]                              # 4 words
[2861, 147, 1342, 1829, 62, 4605, 721]                # 7 words
[4623, 3077, 4413, 4442, 1884, 3018, 1538, 4216, 902, 4473]  # 10 words
```

**After padding** (all length 20):
```
[4719, 1908, 3457, 2009, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
[2861,  147, 1342, 1829, 62, 4605, 721, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
[4623, 3077, 4413, 4442, 1884, 3018, 1538, 4216, 902, 4473, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
```

![Sequence Padding — Variable-length titles equalized to length 20](content/large-language-models/natural-language-processing/images/sequence_padding.png)

> **Why length 20?** Most titles in our dataset max out around **10-12 words** after preprocessing. Padding to 20 gives us a comfortable buffer without wasting too much compute on unnecessary zeros. The LSTM will quickly learn to "skip" over the padding.
>
> **Why post-padding?** We add zeros to the **end** of shorter sequences. In some implementations you'll see pre-padding (zeros at the start) — both work for LSTMs since they maintain hidden state across the full sequence regardless.

---

## Step 6: Building the Embedding + LSTM Model 🏗️

Now we assemble the neural network. If you've followed our [Deep Learning series](content/large-language-models/deep-learning/your-first-ann.md), this Keras workflow will feel familiar — `Sequential()`, `.add()`, `.compile()`:

```python
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Embedding, LSTM, Dense

# Hyperparameters
embedding_vector_features = 40  # Each word → 40-dimensional vector

# Build the model
model = Sequential()
model.add(Embedding(voc_size, embedding_vector_features, input_length=sent_length))
model.add(LSTM(100))
model.add(Dense(1, activation='sigmoid'))

model.compile(loss='binary_crossentropy', optimizer='adam', metrics=['accuracy'])
print(model.summary())
```

```
Model: "sequential"
_________________________________________________________________
 Layer (type)                Output Shape              Param #   
=================================================================
 embedding (Embedding)       (None, 20, 40)            200,000    
 lstm (LSTM)                 (None, 100)               56,400     
 dense (Dense)               (None, 1)                 101        
=================================================================
Total params: 256,501
```

![LSTM Fake News Classifier — Model Architecture](content/large-language-models/natural-language-processing/images/lstm_fake_news_architecture.png)

### Breaking Down Each Layer:

| Layer | What It Does | Parameters |
|---|---|---|
| **Embedding** | Converts each integer index into a dense 40-dimensional vector. This is essentially our **Word2Vec** layer — but instead of using pre-trained vectors, it **learns the embeddings during training**. | 5,000 words × 40 dims = **200,000** |
| **LSTM** | Processes the 20-word sequence one step at a time, maintaining a hidden state that accumulates context. Has 100 neurons (hidden units). | 4 × [(40 + 100) × 100 + 100] = **56,400** |
| **Dense** | Single output neuron with **sigmoid** activation — outputs a probability between 0 and 1. | 100 × 1 + 1 = **101** |

> **Why 4× parameters in the LSTM?** As we learned in our [Recurrent Neural Network blog](content/large-language-models/natural-language-processing/rnn.md), an LSTM has **4 internal weight matrices** — one for each of the Forget gate, Input gate, Output gate, and the Candidate computation. That's the computational cost of memory!
>
> **Why sigmoid + binary cross-entropy?** This is a **binary classification** problem (Fake vs Real), which is exactly what sigmoid + BCE was designed for. We covered this combination in depth in our [Loss Functions blog](content/large-language-models/deep-learning/loss-functions.md).
>
> **Why Adam optimizer?** Adam combines the benefits of momentum and adaptive learning rates. It's the go-to optimizer for most deep learning tasks — we covered it in our [Optimizers blog](content/large-language-models/deep-learning/optimizers.md).

---

## Step 7: Model Training 🏋️

Time to train! First, we convert our data to NumPy arrays for TensorFlow compatibility, then perform a train-test split.

```python
import numpy as np
from sklearn.model_selection import train_test_split

X_final = np.array(embedded_docs)
y_final = np.array(y)

X_final.shape, y_final.shape
# Output: ((18285, 20), (18285,))

X_train, X_test, y_train, y_test = train_test_split(
    X_final, y_final, test_size=0.33, random_state=42
)
```

Now we train the model:

```python
model.fit(X_train, y_train, 
          validation_data=(X_test, y_test), 
          epochs=10, 
          batch_size=64)
```

```
Epoch 1/10  - loss: 0.3495 - accuracy: 0.8247 - val_loss: 0.2056 - val_accuracy: 0.9114
Epoch 2/10  - loss: 0.1464 - accuracy: 0.9429 - val_loss: 0.2070 - val_accuracy: 0.9104
Epoch 3/10  - loss: 0.1037 - accuracy: 0.9635 - val_loss: 0.2376 - val_accuracy: 0.9125
Epoch 4/10  - loss: 0.0699 - accuracy: 0.9758 - val_loss: 0.2565 - val_accuracy: 0.9183
Epoch 5/10  - loss: 0.0547 - accuracy: 0.9801 - val_loss: 0.2616 - val_accuracy: 0.9075
Epoch 6/10  - loss: 0.0456 - accuracy: 0.9839 - val_loss: 0.3549 - val_accuracy: 0.9127
Epoch 7/10  - loss: 0.0319 - accuracy: 0.9891 - val_loss: 0.3948 - val_accuracy: 0.8998
Epoch 8/10  - loss: 0.0286 - accuracy: 0.9904 - val_loss: 0.3906 - val_accuracy: 0.9072
Epoch 9/10  - loss: 0.0217 - accuracy: 0.9923 - val_loss: 0.4145 - val_accuracy: 0.9054
Epoch 10/10 - loss: 0.0224 - accuracy: 0.9918 - val_loss: 0.4555 - val_accuracy: 0.9036
```

> **What we're seeing:** The training loss drops beautifully from **0.35** to **0.02**, and training accuracy climbs to **99.2%**. But the validation loss starts **increasing** after epoch 4 (from 0.21 to 0.46), while validation accuracy plateaus around **90-91%**. This divergence is a classic sign of **overfitting** — the model is memorizing training data instead of generalizing. We'll address this with Dropout in Step 9.

---

## Step 8: Performance Evaluation 📊

Let's see how well our model performs on the test set. We generate predictions and apply a classification threshold:

```python
y_pred = model.predict(X_test)

# Classify: values > 0.5 → Fake News (1), otherwise Real News (0)
y_pred = np.where(y_pred > 0.5, 1, 0)
```

### Confusion Matrix

```python
from sklearn.metrics import confusion_matrix
confusion_matrix(y_test, y_pred)
```

```
array([[3135,  284],
       [ 297, 2319]])
```

| | Predicted Real (0) | Predicted Fake (1) |
|---|---|---|
| **Actual Real (0)** | 3,135 ✅ (True Neg) | 284 ❌ (False Pos) |
| **Actual Fake (1)** | 297 ❌ (False Neg) | 2,319 ✅ (True Pos) |

### Accuracy & Classification Report

```python
from sklearn.metrics import accuracy_score, classification_report

accuracy_score(y_test, y_pred)
# Output: 0.9037 → ~90.4% accuracy!

print(classification_report(y_test, y_pred))
```

```
              precision    recall  f1-score   support

           0       0.91      0.92      0.92      3419
           1       0.89      0.89      0.89      2616

    accuracy                           0.90      6035
   macro avg       0.90      0.90      0.90      6035
weighted avg       0.90      0.90      0.90      6035
```

> **Interpreting the results:** Our LSTM achieves **~90% accuracy** using only news **titles** — remarkably good for such a compact input! The model is slightly better at identifying Real News (91% precision) than Fake News (89% precision).
>
> **Note on the 0.5 threshold:** We used the standard 0.5 cutoff here. In a real-world deployment, you might want to examine an **AUC-ROC curve** to find the optimal threshold — especially if the cost of missing fake news (False Negatives) is higher than falsely flagging real news (False Positives).

---

## Step 9: Adding Dropout for Regularization 🎯

Remember the overfitting we spotted in Step 7? The training loss kept dropping while validation loss increased. **Dropout** is our weapon against this.

```python
from tensorflow.keras.layers import Dropout

model = Sequential()
model.add(Embedding(voc_size, embedding_vector_features, input_length=sent_length))
model.add(Dropout(0.3))      # Drop 30% of embedding outputs
model.add(LSTM(100))
model.add(Dropout(0.3))      # Drop 30% of LSTM outputs
model.add(Dense(1, activation='sigmoid'))

model.compile(loss='binary_crossentropy', optimizer='adam', metrics=['accuracy'])
```

> **How Dropout works:** During training, Dropout randomly **disables** 30% of neurons at each step. This forces the network to spread its learning across multiple pathways — no single neuron can become a "crutch." At test time, all neurons are active, but their outputs are scaled down proportionally.
>
> We covered Dropout in our [first ANN blog](content/large-language-models/deep-learning/your-first-ann.md) — the same concept applies here, but we place it strategically:
> - **After Embedding:** Prevents the model from over-relying on specific word vectors
> - **After LSTM:** Prevents the model from over-relying on specific hidden state features
>
> This should help close the gap between training and validation performance, making the model generalize better to truly unseen news headlines.

---

## Recap — What We Built 🎓

Let's zoom out and see how this project connects to everything we've learned in the NLP series:

| Concept | Blog Where We Learned It | How We Used It Here |
|---|---|---|
| Stemming & Stopwords | [Text Preprocessing](content/large-language-models/natural-language-processing/text-preprocessing.md) | Cleaned 18,285 news titles |
| One-Hot Encoding | [BoW & TF-IDF](content/large-language-models/natural-language-processing/bow-tfidf.md) | Mapped words → integer indices (vocab=5,000) |
| Word Embeddings | [Word2Vec](content/large-language-models/natural-language-processing/word-embeddings-word2vec.md) | Embedding layer learns 40-dim vectors during training |
| LSTM Architecture | [Recurrent Neural Network](content/large-language-models/natural-language-processing/rnn.md) | 100-neuron LSTM processes padded sequences |
| Sigmoid + BCE | [Loss Functions](content/large-language-models/deep-learning/loss-functions.md) | Binary classification output |
| Adam Optimizer | [Optimizers](content/large-language-models/deep-learning/optimizers.md) | Standard training optimizer |
| Dropout | [Your First ANN](content/large-language-models/deep-learning/your-first-ann.md) | Regularization to combat overfitting |
| Model Training | [Your First ANN](content/large-language-models/deep-learning/your-first-ann.md) | Same Keras workflow: compile → fit → evaluate |

Everything builds on everything else. The theory we covered in Days 1-9 directly powered this practical implementation.

---

## Key Takeaways 💡

1. **Text preprocessing is critical** — stemming, stopword removal, and special character stripping reduce noise dramatically
2. **LSTMs can classify text with high accuracy** (~90%) even when trained on only headlines, not full article bodies
3. **Padding equalizes input dimensions** — LSTMs need fixed-length sequences, and padding handles variable-length text gracefully
4. **Embedding layers learn word relationships** — they transform sparse integer indices into dense, meaningful vector representations
5. **Overfitting is real** — watch for the training/validation loss divergence and apply Dropout as needed
6. **The NLP pipeline is a chain** — each step (cleaning → encoding → padding → embedding → LSTM → Dense) feeds into the next

---

## What's Next? 🚀

We've now built a complete, working NLP application from scratch. The LSTM reads sequences, remembers context, and makes predictions. But it still processes words **one at a time** — sequentially.

What if we could look at **all words simultaneously** and let the model decide which ones to pay **attention** to? That's the **Transformer architecture** — the foundation of GPT, BERT, and every modern Large Language Model.

The Transformer is coming next. And it changes *everything*.

> 🔧 **Want to see the full production pipeline?** We've taken this exact approach further by building an **end-to-end MLOps pipeline** for RNN sentiment analysis — with DVC, MLflow, FastAPI, Docker, Terraform, and automated CI/CD/CT:
> 👉 **[End-to-End RNN Sentiment Analysis — From Model to Production MLOps](content/large-language-models/natural-language-processing/rnn-sentiment-analysis-mlops.md)**

---

Got questions or suggestions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*

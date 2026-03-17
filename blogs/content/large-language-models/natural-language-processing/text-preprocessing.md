---
title: "Text Preprocessing — Cleaning Text for Machines"
date: 2026-03-17
tags: [nlp, tokenization, stemming, lemmatization, stop-words, pos-tagging, ner, nltk]
description: A hands-on guide to the complete NLP preprocessing pipeline — tokenization, stemming, lemmatization, stop words, POS tagging, and Named Entity Recognition with NLTK.
---

# The Cleanup Crew 🧹

In the [last post](content/large-language-models/natural-language-processing/intro-to-nlp.md), we set the destination — convert raw text into numerical vectors that ML models can digest. But if you try to convert messy, unprocessed text directly into numbers, you'll get garbage vectors that produce garbage predictions. Capital letters, punctuation marks, word variations ("running", "runs", "ran"), and noise words like "the" all need to be handled first. This post covers the **entire text preprocessing pipeline** — every step that happens before a single number is created.

---

## 1. Tokenization — Breaking Text Apart ✂️

**Tokenization** is the very first step: splitting a block of text into smaller pieces.

There are two levels:
- **Sentence tokenization:** Split a paragraph into individual sentences
- **Word tokenization:** Split a sentence into individual words (tokens)

Let's use NLTK (Natural Language Toolkit) — the most popular Python library for NLP preprocessing.

```python
import nltk
nltk.download('punkt_tab')

from nltk.tokenize import sent_tokenize, word_tokenize

text = "Hello! My name is Ashwin. I love NLP, and I enjoy coding."

# Sentence tokenization
sentences = sent_tokenize(text)
print("Sentences:", sentences)
# ['Hello!', 'My name is Ashwin.', 'I love NLP, and I enjoy coding.']

# Word tokenization
words = word_tokenize(text)
print("Words:", words)
# ['Hello', '!', 'My', 'name', 'is', 'Ashwin', '.', 'I', 'love',
#  'NLP', ',', 'and', 'I', 'enjoy', 'coding', '.']
```

### How does `sent_tokenize` know where to split?

It doesn't just look for periods. It uses a pre-trained model that understands abbreviations like "Dr.", "U.S.A.", and "etc." — so it won't accidentally split "Dr. Smith went to the store" into two sentences.

### The Punctuation Problem

Notice how `word_tokenize` treats commas and periods as **separate tokens**? That's by design — punctuation marks carry meaning (a question mark vs. a period tells you a lot). But different tokenizers handle this differently.

### Comparing Tokenizers

```python
from nltk.tokenize import word_tokenize, WordPunctTokenizer, TreebankWordTokenizer

text = "It's a beautiful day. Let's go!"

# word_tokenize (default)
print(word_tokenize(text))
# ['It', "'s", 'a', 'beautiful', 'day', '.', 'Let', "'s", 'go', '!']

# WordPunctTokenizer — splits ALL punctuation from words
wpt = WordPunctTokenizer()
print(wpt.tokenize(text))
# ['It', "'", 's', 'a', 'beautiful', 'day', '.', 'Let', "'", 's', 'go', '!']

# TreebankWordTokenizer — keeps the final period attached
tbwt = TreebankWordTokenizer()
print(tbwt.tokenize(text))
# ['It', "'s", 'a', 'beautiful', 'day.', 'Let', "'s", 'go', '!']
```

| Tokenizer | How it handles `"It's"` | Final period |
|---|---|---|
| `word_tokenize` | `['It', "'s"]` | Separate token |
| `WordPunctTokenizer` | `['It', "'", 's']` | Separate token |
| `TreebankWordTokenizer` | `['It', "'s"]` | **Attached** to last word |

> **Which one to use?** `word_tokenize` is the safe default for most NLP tasks. Use `WordPunctTokenizer` when you need to strip every bit of punctuation aggressively.

---

## 2. Stemming — Chopping Words to Their Roots 🪓

**Stemming** reduces a word to its base form (the "stem") by chopping off suffixes.

```
eating   → eat
playing  → play
happily  → happili  ← Uh oh...
```

Why bother? Because in tasks like **sentiment analysis**, "eating", "eats", "eaten", and "ate" all carry the same core meaning. By reducing them to one form, we shrink the vocabulary size — fewer features mean a simpler, less overfitted model.

### Porter Stemmer (The Original)

The most famous stemmer. But it has a well-known problem — it often creates **fake, misspelled words**.

```python
from nltk.stem import PorterStemmer

ps = PorterStemmer()

words = ["eating", "eats", "eaten", "history", "congratulations", "fairly"]

for word in words:
    print(f"{word:20s} → {ps.stem(word)}")
```

```
eating               → eat
eats                 → eat
eaten                → eaten
history              → histori        ← Not a real word!
congratulations      → congratul      ← Not a real word!
fairly               → fairli         ← Not a real word!
```

"histori", "congratul", and "fairli" are gibberish. The Porter Stemmer doesn't care about producing real words — it just follows mechanical suffix-stripping rules.

### Regex Stemmer (Custom Rules)

If you know exactly which suffixes to strip, you can write your own stemmer with regular expressions:

```python
from nltk.stem import RegexpStemmer

# Remove "ing", "s", "able" from the end of words
rs = RegexpStemmer('ing$|s$|able$', min=4)

print(rs.stem("eating"))      # eat
print(rs.stem("readable"))    # read
print(rs.stem("cats"))        # cat
```

This gives you full control, but you have to manually define every rule — it doesn't generalize.

### Snowball Stemmer (The Better Choice ❄️)

The Snowball Stemmer is the **improved version** of Porter. It applies smarter rules that produce more accurate roots:

```python
from nltk.stem import SnowballStemmer

ss = SnowballStemmer("english")

words = ["eating", "eats", "history", "congratulations", "fairly"]

for word in words:
    print(f"{word:20s} → {ss.stem(word)}")
```

```
eating               → eat
eats                 → eat
history              → histori
congratulations      → congratul
fairly               → fair           ← Correct! (Porter gave "fairli")
```

> **Rule of thumb:** Always prefer Snowball over Porter. It handles more cases correctly. But stemming overall has a major limitation — it doesn't guarantee real words. For applications where grammatical correctness matters (chatbots, Q&A systems, text summarization), you need something better.

![Stemming vs Lemmatization — Rule-based chopping vs dictionary lookup](content/large-language-models/natural-language-processing/images/stemming_vs_lemmatization.svg)

---

## 3. Lemmatization — The Dictionary Approach 📖

**Lemmatization** does the same job as stemming — reduce words to their root — but uses a **dictionary** (specifically, the WordNet corpus) to ensure the result is a real, valid English word called a **lemma**.

```python
import nltk
nltk.download('wordnet')

from nltk.stem import WordNetLemmatizer

lemmatizer = WordNetLemmatizer()

print(lemmatizer.lemmatize("eating"))        # eating (Wait, what?)
print(lemmatizer.lemmatize("eating", pos='v'))  # eat   (There we go!)
```

### The POS Trap ⚠️

Did you catch that? By default, the lemmatizer assumes every word is a **noun** (`pos='n'`). If "eating" is tagged as a noun, it stays as "eating" because that *is* a valid noun ("the eating was enjoyable").

You **must** pass the correct Part of Speech tag:

```python
# Without POS - assumes noun
print(lemmatizer.lemmatize("going"))          # going  ← Failed!
print(lemmatizer.lemmatize("better"))         # better ← Failed!

# With correct POS
print(lemmatizer.lemmatize("going", pos='v'))   # go     ← Correct!
print(lemmatizer.lemmatize("better", pos='a'))  # good   ← Correct!
```

| POS Code | Meaning | Example |
|---|---|---|
| `'n'` | Noun (default) | "cars" → "car" |
| `'v'` | Verb | "running" → "run" |
| `'a'` | Adjective | "better" → "good" |
| `'r'` | Adverb | "fairly" → "fairly" |

### Stemming vs. Lemmatization — When to Use Which?

| | Stemming | Lemmatization |
|---|---|---|
| **Speed** | ⚡ Fast (rule-based) | 🐌 Slower (dictionary lookup) |
| **Output** | May produce non-words | Always a real word |
| **Use when** | Speed matters, exact word not critical (spam filters, search engines) | Meaning matters (chatbots, Q&A, summarization) |

> **Bottom line:** If you're building a chatbot or any system where a user reads the output, **always use lemmatization.** If you're building a behind-the-scenes classifier where speed trumps readability, stemming is fine.

---

## 4. Stop Words — Stripping the Noise 🔇

**Stop words** are extremely common words that appear in almost every sentence but carry little to no meaning on their own: "I", "the", "is", "a", "an", "she", "he", "was", "in"...

Removing them shrinks your vocabulary and removes noise that would confuse your model.

```python
import nltk
nltk.download('stopwords')

from nltk.corpus import stopwords

stop_words = set(stopwords.words('english'))

print(f"Total English stop words: {len(stop_words)}")
# Total English stop words: 179

# A few examples:
print(list(stop_words)[:10])
# ['ourselves', 'between', "shouldn't", 'again', 'there', 'about', ...]
```

### Applying Stop Word Removal

```python
sentence = "This movie is not good and I would not recommend it to anyone"

words = sentence.lower().split()  # Always lowercase first!
filtered = [word for word in words if word not in stop_words]

print("Before:", words)
print("After: ", filtered)
```

```
Before: ['this', 'movie', 'is', 'not', 'good', 'and', 'i', 'would', 'not', 'recommend', 'it', 'to', 'anyone']
After:  ['movie', 'good', 'would', 'recommend', 'anyone']
```

### ⚠️ The Sentiment Analysis Trap

Wait — look at the filtered output: `['movie', 'good', 'would', 'recommend', 'anyone']`. That sounds **positive!** But the original sentence was: "This movie is **not** good and I would **not** recommend it."

The word **"not"** was removed because it's in the default stop word list. That completely flipped the meaning!

**For sentiment analysis, you MUST customize your stop word list:**

```python
# Create a custom stop word list that KEEPS negation words
custom_stop = stop_words - {"not", "no", "nor", "neither", "never", 
                             "don't", "doesn't", "didn't", "won't", 
                             "wouldn't", "shouldn't", "couldn't",
                             "aren't", "isn't", "wasn't", "weren't"}

filtered = [word for word in words if word not in custom_stop]
print("Smart filter:", filtered)
# Smart filter: ['movie', 'not', 'good', 'would', 'not', 'recommend', 'anyone']
```

Now "not" is preserved, and the sentiment stays correct!

> **Pro tip:** Always convert text to `.lower()` **before** checking against stop words. Otherwise "The" (capitalized) won't match "the" (lowercase) in the stop word list and will slip through.

### Multilingual Stop Words

NLTK has stop word lists for many languages:

```python
print(stopwords.fileids())
# ['arabic', 'danish', 'dutch', 'english', 'finnish', 'french',
#  'german', 'hungarian', 'italian', 'norwegian', 'portuguese',
#  'russian', 'spanish', 'swedish', 'turkish', ...]
```

---

## 5. Parts of Speech (POS) Tagging 🏷️

**POS tagging** assigns a grammatical category to every word — noun, verb, adjective, etc.

We already saw why this matters: lemmatization *needs* the POS tag to work correctly. But POS tagging is also valuable on its own — it helps models understand sentence structure.

```python
import nltk
nltk.download('averaged_perceptron_tagger_eng')

from nltk import pos_tag, word_tokenize

sentence = "Ashwin is learning Natural Language Processing in Python"
tokens = word_tokenize(sentence)
tagged = pos_tag(tokens)

print(tagged)
# [('Ashwin', 'NNP'), ('is', 'VBZ'), ('learning', 'VBG'), 
#  ('Natural', 'NNP'), ('Language', 'NNP'), ('Processing', 'NNP'), 
#  ('in', 'IN'), ('Python', 'NNP')]
```

### Common POS Tags

| Tag | Meaning | Example |
|---|---|---|
| `NNP` | Proper noun, singular | Ashwin, Python |
| `NN` | Noun, singular | dog, book |
| `VBZ` | Verb, 3rd person singular present | is, runs |
| `VBG` | Verb, gerund/present participle | learning, running |
| `PRP` | Personal pronoun | I, he, she |
| `JJ` | Adjective | good, beautiful |
| `IN` | Preposition | in, at, on |
| `RB` | Adverb | quickly, very |

### ⚠️ The Common Mistake

A very easy mistake to make: passing a **raw string** instead of a **list of tokens** to `pos_tag()`:

```python
# WRONG — passing a string directly
pos_tag("Hello")
# [('H', 'NN'), ('e', 'NN'), ('l', 'NN'), ('l', 'NN'), ('o', 'NN')]
# It tagged every CHARACTER individually!

# CORRECT — pass a list of tokenized words
pos_tag(word_tokenize("Hello"))
# [('Hello', 'NNP')]
```

Always tokenize first, **then** POS tag. The function expects a list, not a string.

---

## 6. Named Entity Recognition (NER) 🏛️

**NER** goes one step beyond POS tagging. Instead of just labeling *grammar*, it identifies **real-world entities** — specific people, organizations, locations, dates, and monetary values.

```python
import nltk
nltk.download('maxent_ne_chunker_tab')
nltk.download('words')

from nltk import ne_chunk, pos_tag, word_tokenize

text = "Gustave Eiffel designed the Eiffel Tower in Paris in 1889."
tokens = word_tokenize(text)
tagged = pos_tag(tokens)
entities = ne_chunk(tagged)

print(entities)
```

```
(S
  (PERSON Gustave/NNP Eiffel/NNP)
  designed/VBD
  the/DT
  (ORGANIZATION Eiffel/NNP Tower/NNP)
  in/IN
  (GPE Paris/NNP)
  in/IN
  1889/CD
  ./.)
```

Look at what NER figured out:

| Entity | Type | Meaning |
|---|---|---|
| Gustave Eiffel | `PERSON` | A human being |
| Eiffel Tower | `ORGANIZATION` | NLTK thinks it's an org (close enough — it's a landmark) |
| Paris | `GPE` | A geo-political entity (city/country) |

### Visualizing the Entity Tree

NLTK can generate a pop-up visual tree showing the entity relationships:

```python
# This opens a window with a visual tree diagram
entities.draw()
```

This produces a tree graph where named entities are grouped together in brackets, making it easy to visually inspect what the model recognized.

> **Real-world usage:** NER is used everywhere — search engines extract organization names, news aggregators identify mentioned people and places, and chatbots pull out dates, times, and monetary amounts from user messages.

---

## The Complete Preprocessing Pipeline 🔗

Let's put everything together into a single pipeline:

```python
import nltk
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer

def preprocess(text):
    """Complete NLP preprocessing pipeline."""
    
    # Step 1: Lowercase
    text = text.lower()
    
    # Step 2: Tokenize
    tokens = word_tokenize(text)
    
    # Step 3: Remove stop words (keep negations for sentiment)
    stop_words = set(stopwords.words('english')) - {"not", "no", "nor", "never"}
    tokens = [t for t in tokens if t not in stop_words]
    
    # Step 4: Remove punctuation tokens
    tokens = [t for t in tokens if t.isalpha()]
    
    # Step 5: Lemmatize
    lemmatizer = WordNetLemmatizer()
    tokens = [lemmatizer.lemmatize(t, pos='v') for t in tokens]
    
    return tokens

# Test it
raw = "The cats were running quickly through the beautiful gardens!"
print("Raw:      ", raw)
print("Processed:", preprocess(raw))
# Raw:       The cats were running quickly through the beautiful gardens!
# Processed: ['cat', 'run', 'quickly', 'beautiful', 'garden']
```

From messy English to clean, lemmatized tokens — ready for the next step.

---

## Recap — The Preprocessing Toolkit 🎓

| Step | What It Does | Tool |
|---|---|---|
| **Tokenization** | Splits text into sentences/words | `sent_tokenize`, `word_tokenize` |
| **Stemming** | Chops suffixes (fast, may produce non-words) | `SnowballStemmer` |
| **Lemmatization** | Dictionary lookup for valid root words | `WordNetLemmatizer` |
| **Stop Words** | Removes common noise words | `stopwords.words('english')` |
| **POS Tagging** | Labels grammar (noun, verb, adj...) | `pos_tag()` |
| **NER** | Identifies people, places, orgs, dates | `ne_chunk()` |

---

## What's Next? 🚀

Our text is clean, tokenized, and lemmatized. Beautiful. But it's still just **text** — still just strings of characters.

Now comes the moment we've been building toward: **turning these words into actual numbers.** We'll start with the three simplest approaches — One Hot Encoding, Bag of Words, and TF-IDF — and discover exactly where each one shines and where each one spectacularly fails.

Next up: **[From Words to Vectors — One Hot Encoding, Bag of Words & TF-IDF](content/large-language-models/natural-language-processing/bow-tfidf.md)**

---

*— Ashwin*

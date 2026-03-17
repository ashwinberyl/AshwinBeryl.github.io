---
title: "AI vs ML vs DL vs Data Science — What's the Difference?"
date: 2026-03-13
tags: [ai, machine-learning, deep-learning, data-science, beginner]
description: A simple, no-jargon breakdown of AI, Machine Learning, Deep Learning, and Data Science — and why this blog series exists.
---

# Why This Series Exists

Let's be honest — there are hundreds of AI and ML resources online. Courses, videos, blog posts, research papers. Some skip the basics entirely. Others drown you in math before you've written a single line of code. And most of them are **disconnected** — you finish one tutorial and have no idea what to learn next.

This blog series is different.

The goal is simple: **take anyone with basic Python knowledge and walk them all the way to understanding Large Language Models (LLMs)** — step by step, in the right order, covering only the prerequisites you actually need, at just the right depth.

No random jumps. No "left as an exercise to the reader." Just a clear, connected path from Python to LLMs.

But before we start building that path, let's clear up the most common confusion in this entire field.

---

## The Five Terms Everyone Mixes Up

You've probably heard these thrown around interchangeably:

- Artificial Intelligence
- Machine Learning
- Deep Learning
- Data Science

They're **not** the same thing. They're related, but each one means something specific.

The easiest way to understand them? **Think of Russian nesting dolls.**

![AI vs ML vs DL vs LLMs — The Nested Relationship](content/large-language-models/images/ai_ml_dl_circles.png)

---

## Artificial Intelligence (AI) 🧠

**AI is the biggest doll.** It includes *any* technique that lets a machine do something that normally requires human intelligence.

That's a broad definition on purpose. A chess engine from the 1990s that follows hardcoded rules? That's AI. A spam filter that learns from your emails? Also AI. A chatbot that writes poetry? Still AI.

AI doesn't have to involve "learning." It just means the machine is doing something smart.

---

## Machine Learning (ML) 📊

**ML lives inside AI.** It's a specific approach to AI where instead of programming rules by hand, you **let the machine learn patterns from data**.

Remember the [chocolate shop analogy](content/large-language-models/machine-learning/simple-linear-regression.md) from our previous post? That's ML in action — you gave the machine data (chocolates vs price), and it figured out the pattern (`y = mx + b`) on its own.

The key difference from traditional AI: **you don't tell the machine the rules. You give it data, and it discovers the rules itself.**

---

## Deep Learning (DL) 🔮

**DL lives inside ML.** It's a subset of ML that uses **neural networks with many layers** (hence "deep").

While regular ML works great for structured data and simpler problems, deep learning shines when the data is complex — images, audio, video, text. It's what powers:

- Image recognition (Google Photos knowing that's your dog)
- Voice assistants (Siri, Alexa understanding speech)
- Language models (ChatGPT, Claude generating text)

The "deep" just means the neural network has many layers stacked on top of each other, each one learning increasingly abstract patterns.

---

## Data Science 📈

**Data Science is the odd one out.** It's not a subset of AI — it's a **separate discipline** that *overlaps* with all of them.

A data scientist's job is to **extract insights from data** to help make decisions. They might use ML, but they also use statistics, SQL, dashboards, A/B testing, and good old Excel.

Think of it this way:
- A machine learning engineer builds the spam filter
- A data scientist analyzes *why* spam increased 40% last month and presents findings to the team

---

## The Quick Comparison

| | AI | ML | DL | Data Science |
|---|---|---|---|---|
| **What is it?** | Machines acting smart | Learning from data | Deep neural networks | Insights from data |
| **How?** | Rules OR learning | Algorithms + data | Many-layered networks | Stats + ML + tools |
| **Example** | Chess engine | Spam filter | ChatGPT | Sales dashboard |
| **Needs data?** | Not always | Yes | Yes (lots of it) | Yes |
| **Subset of** | — | AI | ML | Overlaps all |

---

## So Where Do LLMs Fit?

LLMs — **Large Language Models** — sit right inside Deep Learning. They're deep learning models trained on massive amounts of text data to understand and generate human language.

```
AI → Machine Learning → Deep Learning → LLMs
```

That's what this blog series is building towards. And now you know exactly where LLMs sit in the bigger picture.

---

## The Road Ahead 🛤️

Here's the path we'll follow in this series:

| # | Topic | Status |
|---|---|---|
| 1 | AI vs ML vs DL vs Data Science | ✅ [Done!](content/large-language-models/ai-vs-ml-vs-dl-vs-data-science.md) |
| 2 | Machine Learning Fundamentals (Linear Regression) | ✅ [Done!](content/large-language-models/machine-learning/simple-linear-regression.md) |
| 3 | Neural Networks — The Building Blocks | ✅ [Done!](content/large-language-models/deep-learning/intro-to-neural-networks.md) |
| 4 | NLP — Introduction | ✅ [Done!](content/large-language-models/natural-language-processing/intro-to-nlp.md) |
| 5 | NLP — Text Preprocessing | ✅ [Done!](content/large-language-models/natural-language-processing/text-preprocessing.md) |
| 6 | NLP — One Hot Encoding, BoW & TF-IDF | ✅ [Done!](content/large-language-models/natural-language-processing/bow-tfidf.md) |
| 7 | NLP — Word Embeddings & Word2Vec | ✅ [Done!](content/large-language-models/natural-language-processing/word-embeddings-word2vec.md) |
| 8 | NLP — Average Word2Vec & Gensim | ✅ [Done!](content/large-language-models/natural-language-processing/average-word2vec-gensim.md) |
| 9 | The Attention Mechanism | 🔜 Coming soon |
| 10 | Transformers — The Architecture Behind LLMs | 🔜 Coming soon |
| 11 | Building & Using LLMs | 🔜 Coming soon |

Each post builds on the previous one. No random jumps, no missing pieces.

---

## Got Suggestions? 💬

This series is a work in progress, and I'd love your input. If you have ideas for topics, feedback on the writing, or just want to say hi — reach out!

👉 [Send me a message here](https://ashwinberyl.github.io/#contact)

---

*Let's get started. Next stop: Neural Networks! 🚀*

*— Ashwin*

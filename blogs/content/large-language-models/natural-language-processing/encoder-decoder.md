---
title: "Encoder-Decoder Architecture"
date: 2026-04-18
tags: [nlp, lstm, sequence-to-sequence, seq2seq, encoder-decoder, context-vector, bottleneck]
description: Overcoming the limitation of LSTMs where inputs and outputs must match in length. Learn how the Encoder-Decoder architecture uses two networks and a Context Vector to power machine translation, summarization, and more.
---

# The Translation Problem 🌐

In our [LSTM blog](content/large-language-models/natural-language-processing/lstm.md), we saw how the BiLSTM gives us an elegant way to capture context from both sides of a word in a sequence. But it has a major structural flaw when applied to certain real-world problems.

Standard RNNs and LSTMs are **seq2seq (sequence-to-sequence)** models, but they are *synchronous*. For every input token you give them, they produce one output token. 

This works great for tasks like Part-of-Speech tagging where every word gets exactly one tag. But what about **Machine Translation**?

> "I love cats" (3 words, English)  
> "J'aime les chats" (4 words, French)

![The Language Translation Problem](content/large-language-models/natural-language-processing/images/encoder_decoder_translation_problem.png)

A synchronous LSTM reads "I" and must immediately output a French word. Then it reads "love" and outputs another word. It forces a 1:1 mapping. Because English and French have different grammar, word orders, and sentence lengths, this approach fails miserably. 

We need a way to **read the entire sentence first**, understand its meaning, and *then* generate a translated sentence of whatever length is necessary. 

Enter the **Encoder-Decoder Architecture**.

---

## Two Networks are Better than One 🤝

If one LSTM can't handle mismatched lengths, what if we use two?

1. **The Encoder (The Reader):** One LSTM that reads the entire input sentence and compresses its meaning into a single mental representation.
2. **The Decoder (The Writer):** A completely separate LSTM that takes that mental representation and writes out the translation, word by word, until it decides the sentence is finished.

This simple but profound idea—splitting the task into reading and writing—is the foundation of modern NLP.

![Encoder-Decoder Architecture](content/large-language-models/natural-language-processing/images/encoder_decoder_architecture.png)

### The Context Vector: The Ultimate Summary 🗜️

As the Encoder processes the input ("I" → "love" → "cats"), it updates its hidden state *hₜ* at each step. 

The most important moment happens when the Encoder reads the very last word ("cats"). At this point, the final hidden state—let's call it *h_final*—must contain the meaning of the *entire* sentence. 

We give this final state a special name: the **Context Vector**.

The Context Vector is passed to the Decoder as its *initial* hidden state. The Decoder then starts generating words. Crucially, it predicts an `<EOS>` (End of Sentence) token when it decides the translation is complete, allowing it to generate 4 words from a 3-word input!

---

## Beyond Translation: The Power of Seq2Seq 🌍

While we've used translation as our primary example, the Encoder-Decoder architecture is the foundation for almost every major generative NLP task. Because it successfully divorces the input length from the output length, it can handle:

### 1. Text Summarization 📝
- **Input (Encoder):** A 500-word long-form news article.
- **Output (Decoder):** A 30-word executive summary.
- **How it works:** The Encoder reads the entire article, compressing the core facts and narrative into the Context Vector in its final state. The Decoder then unpacks that compressed meaning into a concise, newly generated summary.

### 2. Conversational Agents (Chatbots) 🤖
- **Input (Encoder):** The user's prompt (e.g., "What are your hours of operation?").
- **Output (Decoder):** The bot's response (e.g., "We are open from 9 AM to 5 PM, Monday through Friday.").
- **How it works:** The Encoder captures the *intent* and *context* of the user's question in the Context Vector. The Decoder uses that intent to formulate a natural-sounding, contextually appropriate conversational reply.

In all of these scenarios, the magical bridge between the two distinct sequences is the Context Vector.

---

## Code-as-Math: The Seq2Seq Forward Pass 🐍

Let's see this in code. We'll use our `lstm_forward` concept from previous posts.

```python
import numpy as np

def encoder_decoder_forward(source_words, target_length, encoder_params, decoder_params):
    """
    Simplified Encoder-Decoder forward pass for translation.
    """
    # ==========================
    # Phase 1: THE ENCODER 🎧
    # ==========================
    # Initial states are empty
    h_enc, c_enc = np.zeros(hidden_dim), np.zeros(hidden_dim)
    
    # Read the entire source sentence
    for word in source_words:
        h_enc, c_enc = lstm_step(word, h_enc, c_enc, **encoder_params)
        
    # The final states become our CONTEXT VECTOR!
    context_h = h_enc
    context_c = c_enc
    
    # ==========================
    # Phase 2: THE DECODER ✍️
    # ==========================
    # The Decoder STARTS with the Encoder's summary
    h_dec, c_dec = context_h, context_c
    
    # Start with a special <START> token
    current_word = get_start_token()
    generated_words = []
    
    # Generate words until we hit the desired length (or <EOS>)
    for _ in range(target_length):
        h_dec, c_dec = lstm_step(current_word, h_dec, c_dec, **decoder_params)
        
        # Predict the next word based on the decoder's state
        next_word = predict_word(h_dec)
        generated_words.append(next_word)
        
        # Autoregression: feed the predicted word as the NEXT input
        current_word = next_word
        
        if is_eos_token(next_word):
            break
            
    return generated_words
```

Notice the **Autoregression** in the Decoder: it uses its own previous output as its next input!

---

## The Fatal Flaw: The Information Bottleneck 🚰

The Encoder-Decoder architecture dominated translation from 2014 to 2017. It was magical. But it had one catastrophic flaw.

Look at the code above. The ENTIRE source sentence has to be compressed into `h_enc` and `c_enc`—fixed-size vectors (e.g., 512 numbers).

![The Context Vector Bottleneck](content/large-language-models/natural-language-processing/images/encoder_decoder_bottleneck.png)

This is fine for "I love cats." But what if the source sentence is 50 words long? A 100-word paragraph? 

Imagine reading a 100-page book and being asked to compress the entire plot, character arcs, and themes into a single tweet. When you try to write the sequel (decode), you've lost all the fine details. 

In a basic Seq2Seq model, the Context Vector is an **Information Bottleneck**. The beginning of a long sentence is completely forgotten by the time the final word is read, causing the translation quality for long sentences to plummet.

---

## What's Next? 🚀

```
RNNs → LSTMs → Encoder-Decoder → ???
```

How do we solve the bottleneck? Instead of forcing the Encoder to compress everything into one final vector, what if the Decoder could *look back* at the entire input sentence while it was translating?

What if, when translating the word "chats", the Decoder could say: *"Let me pay special attention to the word 'cats' in the source sentence right now."*

This simple idea changed the world. It is the **Attention Mechanism**—and it's coming next. 🔥

---

Got questions or suggestions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*

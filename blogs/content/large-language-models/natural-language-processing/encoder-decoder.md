---
title: "Encoder-Decoder Architecture"
date: 2026-04-18
tags: [nlp, lstm, sequence-to-sequence, seq2seq, encoder-decoder, context-vector, bottleneck, teacher-forcing, stacked-lstm]
description: From the LSTM's fixed-length limitation to the Encoder-Decoder solution — covering the Context Vector intuition, special tokens (<START>/<END>), tensor dimensions at every stage, Stacked LSTMs, Teacher Forcing training, autoregressive decoding, and the fatal information bottleneck that leads us to Attention.
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

This simple but profound idea — splitting the task into reading and writing — is the foundation of modern NLP.

![Encoder-Decoder Architecture](content/large-language-models/natural-language-processing/images/encoder_decoder_architecture.png)

---

## Special Tokens — `<START>` and `<END>` 🏁

Before we dive deeper, we need two special tokens that make the whole system work:

| Token | Also Called | Where It's Used | Purpose |
|---|---|---|---|
| **`<START>`** | `<SOS>` (Start of Sentence) | Decoder input (first step) | Tells the Decoder: "Begin generating now" |
| **`<END>`** | `<EOS>` (End of Sentence) | Encoder input (last token) + Decoder output (stop signal) | Tells the model: "The sequence is complete" |

### Why Do We Need Them?

**The Decoder needs a trigger.** When translation starts, the Decoder has no previous word to work with — it hasn't generated anything yet. The `<START>` token acts as the ignition key. It's a real, learnable word embedding (just like "cat" or "love") that the model learns means *"time to start writing."*

**The Decoder needs a stop signal.** Without `<END>`, the Decoder would generate words forever — it has no way to know when the sentence is done. When the Decoder predicts `<END>` as the next word, we stop generation. During training, we also append `<END>` to the source sentence so the Encoder knows when the input is finished.

### How the Sequences Actually Look

Here's what the training data looks like for translating "I love cats" → "J'aime les chats":

```
Encoder input:   ["I", "love", "cats", "<END>"]
Decoder input:   ["<START>", "J'aime", "les", "chats"]
Decoder target:  ["J'aime", "les", "chats", "<END>"]
```

> **Notice the offset!** The Decoder input is shifted right by one position compared to the target. At each step, the Decoder receives the *previous* correct word and must predict the *next* word. This is the setup for **Teacher Forcing**, which we'll cover in the training section.

---

## The Context Vector — Intuition 🗜️

As the Encoder processes the input ("I" → "love" → "cats" → "`<END>`"), it updates its hidden state *hₜ* and cell state *Cₜ* at each step, building up a richer representation with every word.

The most important moment happens when the Encoder reads the very last token. At this point, the final hidden state and cell state must contain the meaning of the *entire* sentence.

We give this final state a special name: the **Context Vector**.

### The Analogy: Memorizing Before the Exam

Think about reading a textbook chapter before a closed-book exam. You read every page (the Encoder), building up understanding. When you close the book, everything you've absorbed is compressed into **your memory** — that's the Context Vector. Then you sit down and write your exam answers (the Decoder), pulling entirely from that compressed memory.

If the chapter was 3 pages, your memory probably captures it well. If it was 300 pages? You'll forget the early details. That's *exactly* the problem we'll hit later.

### What Does the Context Vector Actually Contain?

The Context Vector isn't a simple summary — it's a **dense, distributed representation** where every dimension encodes some aspect of the input's meaning:

```
Context Vector (512 numbers):
  [0.83, -0.21, 0.45, ..., 0.12, -0.67, 0.91]
   ↑       ↑       ↑              ↑       ↑
   subject  tense   sentiment     topic   plurality
   info     info    info          info    info
```

These dimensions aren't handcrafted — the model *learns* what to store through training. The gradient tells the Encoder: "If you want the Decoder to produce good translations, you'd better encode the right information into this vector."

---

## Following the Shapes — Tensor Dimensions at Every Stage 📐

One of the best ways to truly understand any deep learning architecture is to track the tensor shapes at every step. Let's trace "I love cats" through the entire pipeline.

### Configuration

```python
vocab_size_en     = 10000   # English vocabulary (unique words)
vocab_size_fr     = 12000   # French vocabulary (unique words)
embedding_dim     = 256     # Word vector size
hidden_dim        = 512     # LSTM hidden state size
max_seq_len       = 50      # Maximum sequence length
```

### Step-by-Step Shape Tracking

```
Step 1: Raw Text
  "I love cats <END>"
  Shape: just a string (not a tensor yet!)

Step 2: Tokenization (word → integer index)
  [42, 891, 203, 1]              ← each word mapped to its vocab index
  Shape: [4]                     ← 4 tokens (3 words + <END>)

Step 3: Embedding Lookup (integer → dense vector)
  Each token → 256-dimensional vector
  Shape: [4, 256]                ← 4 tokens × 256 embedding dims

Step 4: Encoder LSTM processes token by token
  At each step t:
    Input:  xt         shape: [256]     (one word embedding)
    Hidden: h(t-1)     shape: [512]     (previous hidden state)
    Cell:   C(t-1)     shape: [512]     (previous cell state)
    Output: ht         shape: [512]     (new hidden state)
    Output: Ct         shape: [512]     (new cell state)

  After processing ALL 4 tokens:
    h_final  shape: [512]   ← THIS IS THE CONTEXT VECTOR (hidden)
    C_final  shape: [512]   ← THIS IS THE CONTEXT VECTOR (cell)

Step 5: Context Vector passed to Decoder
  Decoder initial h0 = h_final   shape: [512]
  Decoder initial C0 = C_final   shape: [512]

Step 6: Decoder LSTM generates token by token
  Step 6a: Input = <START> embedding    shape: [256]
           LSTM outputs h1              shape: [512]
           Linear layer: h1 → logits    shape: [12000]  ← one score per French word!
           Softmax → probabilities      shape: [12000]
           argmax → predicted token     shape: [1]      ← "J'aime" (index 4721)

  Step 6b: Input = "J'aime" embedding   shape: [256]
           LSTM outputs h2               shape: [512]
           Linear → Softmax → argmax    → "les"

  Step 6c: Input = "les" embedding       shape: [256]
           LSTM outputs h3               shape: [512]
           Linear → Softmax → argmax    → "chats"

  Step 6d: Input = "chats" embedding     shape: [256]
           LSTM outputs h4               shape: [512]
           Linear → Softmax → argmax    → "<END>"  ← STOP!

Final output: ["J'aime", "les", "chats"]  (3 words generated from 3 words!)
```

> **The key insight:** The Encoder's input embedding and the Decoder's input embedding are **completely separate**. The Encoder uses English word vectors, and the Decoder uses French word vectors. They live in different embedding spaces — but the hidden state dimension (512) must match because the Context Vector bridges them.

---

## Stacked LSTMs — Going Deeper 📚

A single-layer LSTM might not be expressive enough for complex translations. The original Seq2Seq paper (Sutskever et al., 2014) used **4 stacked LSTM layers** and showed that depth was crucial.

![Stacked LSTM Encoder-Decoder](content/large-language-models/natural-language-processing/images/encoder_decoder_stacked.png)

### How Stacking Works

In a stacked LSTM, **Layer 1's hidden states become Layer 2's inputs**, and so on:

```
Layer 1:  Processes raw word embeddings → captures basic patterns (syntax)
Layer 2:  Processes Layer 1's outputs   → captures intermediate patterns (phrases)
Layer 3:  Processes Layer 2's outputs   → captures high-level patterns (meaning)
```

Each layer operates at a different level of abstraction — just like the layers in a CNN capture edges → textures → objects.

### Context Vector in Stacked LSTMs

With N stacked layers, the Context Vector is no longer a single (h, C) pair — it's **N pairs**, one from each layer:

```
Single-layer:  Context = (h_final, C_final)
                         shape: [512] + [512] = 1024 numbers

3-layer stack: Context = [(h1_final, C1_final),
                          (h2_final, C2_final),
                          (h3_final, C3_final)]
                         shape: 3 × ([512] + [512]) = 3072 numbers
```

Each Encoder layer's final state initializes the **corresponding** Decoder layer. Layer 1 → Layer 1, Layer 2 → Layer 2, etc. This preserves the hierarchical structure — low-level syntactic information stays in the lower layers, and high-level semantic information stays in the upper layers.

### Parameter Count

```python
# Single-layer Encoder-Decoder
enc_params = 4 * (embedding_dim + hidden_dim) * hidden_dim  # One LSTM
dec_params = 4 * (embedding_dim + hidden_dim) * hidden_dim  # One LSTM
output_layer = hidden_dim * vocab_size_fr                    # Linear layer
# Total ≈ 7.6M parameters

# 4-layer Stacked Encoder-Decoder
enc_params = 4 * (embedding_dim + hidden_dim) * hidden_dim              # Layer 1
           + 3 * 4 * (hidden_dim + hidden_dim) * hidden_dim             # Layers 2-4
dec_params = same structure
# Total ≈ 27M parameters  (3.5× more — but dramatically better translations)
```

> **Why does stacking help so much?** A single-layer LSTM must capture *everything* — syntax, semantics, pragmatics — in one hidden state. By stacking layers, each layer can specialize: lower layers handle local word patterns while upper layers handle global sentence meaning. The original Google Neural Machine Translation system used 8 stacked LSTM layers!

---

## Training — Teacher Forcing 🎓

How do we train this whole system? The Encoder and Decoder are trained **jointly** as a single model, end to end. The loss from the Decoder's predictions backpropagates all the way through to the Encoder's weights.

But there's a subtle problem during training: **error accumulation**.

### The Problem Without Teacher Forcing

Imagine the Decoder is learning to translate "I love cats" → "J'aime les chats":

```
Step 1: Input <START>, predict → "J'aime"  ✅ Correct!
Step 2: Input "J'aime", predict → "des"    ❌ Wrong! (should be "les")
Step 3: Input "des",    predict → ???       💀 We fed a wrong word!
```

If the Decoder makes a mistake at step 2, that mistake cascades — step 3 receives the wrong input, making step 3 even more likely to be wrong, which makes step 4 worse, and so on. This is called **exposure bias** — during training, the model is exposed to its own errors, which spiral out of control.

### The Solution: Teacher Forcing

![Teacher Forcing during Training](content/large-language-models/natural-language-processing/images/encoder_decoder_training.png)

During training, instead of feeding the Decoder its own predictions, we feed it the **correct target word** at every step — regardless of what it predicted:

```
Step 1: Input <START>,   predict → "J'aime"  ✅ (compare with target "J'aime")
Step 2: Input "J'aime",  predict → "des"     ❌ (compare with target "les")
Step 3: Input "les",     predict → "chats"   ✅ (we fed the CORRECT "les", not "des"!)
Step 4: Input "chats",   predict → "<END>"   ✅ (compare with target "<END>")
```

Even though step 2 predicted wrong, step 3 still receives the correct input ("les"). The error is **isolated** — each step learns independently without cascading mistakes.

### The Training Loop

```python
def train_step(source_sentence, target_sentence, encoder, decoder, loss_fn, optimizer):
    """
    One training step with Teacher Forcing.
    """
    # Phase 1: Encode
    # Encoder reads: ["I", "love", "cats", "<END>"]
    context_h, context_c = encoder(source_sentence)
    
    # Phase 2: Decode with Teacher Forcing
    # Decoder input:  ["<START>", "J'aime", "les", "chats"]    ← correct words!
    # Decoder target:  ["J'aime", "les", "chats", "<END>"]     ← shifted by 1
    h, c = context_h, context_c
    total_loss = 0
    
    for t in range(len(target_sentence)):
        # Feed the CORRECT previous word (teacher forcing!)
        decoder_input = target_sentence[t]  # NOT the model's own prediction
        
        h, c = decoder.lstm_step(decoder_input, h, c)
        predicted_logits = decoder.output_layer(h)   # shape: [vocab_size_fr]
        
        # Compare prediction with the target
        target_word = target_sentence[t + 1]  # shifted target
        loss = loss_fn(predicted_logits, target_word)  # Cross-Entropy Loss
        total_loss += loss
    
    # Backpropagate through EVERYTHING — Decoder → Context Vector → Encoder
    total_loss.backward()
    optimizer.step()
```

> **Training vs Inference — the big difference:** During training, we use Teacher Forcing (feed the correct previous word). During inference (actual translation), we don't have the correct words — we feed the model's own predictions. This mismatch between training and inference is called **exposure bias**, and it's a known limitation of Teacher Forcing. Some systems use **scheduled sampling** — gradually mixing in the model's own predictions during training to bridge the gap.

---

## Autoregressive Decoding — How Inference Actually Works 🔮

During inference (when we actually want to translate a new sentence), we don't have the target words. The Decoder must work alone:

```python
def translate(source_sentence, encoder, decoder, max_length=50):
    """
    Translate a sentence using autoregressive decoding.
    """
    # Phase 1: Encode the entire source
    context_h, context_c = encoder(source_sentence)
    
    # Phase 2: Decode autoregressively
    h, c = context_h, context_c
    current_token = "<START>"
    translation = []
    
    for step in range(max_length):
        # Feed the model's OWN previous prediction
        embedding = embed(current_token)
        h, c = decoder.lstm_step(embedding, h, c)
        logits = decoder.output_layer(h)           # shape: [vocab_size_fr]
        
        # Pick the most likely next word
        predicted_token = vocab_fr[argmax(logits)]
        
        if predicted_token == "<END>":
            break  # Model says "I'm done!"
            
        translation.append(predicted_token)
        current_token = predicted_token  # Autoregression!
    
    return translation

# Example:
translate(["I", "love", "cats", "<END>"])
# → ["J'aime", "les", "chats"]
```

### Step-by-Step Decoding Walkthrough

Let's trace through translating "I love cats":

```
+------+------------------+----------------+----------------+--------+
| Step | Decoder Input    | Hidden State   | Prediction     | Action |
+------+------------------+----------------+----------------+--------+
|  1   | <START> [256-d]  | context [512-d]| P("J'aime")=0.87| Keep   |
|  2   | "J'aime" [256-d] | h1 [512-d]     | P("les")=0.72  | Keep   |
|  3   | "les" [256-d]    | h2 [512-d]     | P("chats")=0.91| Keep   |
|  4   | "chats" [256-d]  | h3 [512-d]     | P("<END>")=0.95| STOP!  |
+------+------------------+----------------+----------------+--------+

Output: ["J'aime", "les", "chats"]
```

> **Why `max_length`?** If the model never predicts `<END>` (due to a bad model or adversarial input), it would loop forever. The `max_length` parameter acts as a safety valve — "if you haven't stopped after 50 words, stop anyway."

---

## Beyond Translation: The Power of Seq2Seq 🌍

While we've used translation as our primary example, the Encoder-Decoder architecture is the foundation for almost every major generative NLP task. Because it successfully divorces the input length from the output length, it can handle:

### 1. Text Summarization 📝
- **Input (Encoder):** A 500-word long-form news article.
- **Output (Decoder):** A 30-word executive summary.
- **How it works:** The Encoder reads the entire article, compressing the core facts and narrative into the Context Vector. The Decoder unpacks that compressed meaning into a concise, newly generated summary.

```
Encoder input:  [500 word article about the Mars rover landing...]
Context Vector: [512 numbers encoding the key facts]
Decoder output: "NASA's Perseverance rover successfully landed on Mars,
                 beginning its mission to search for ancient microbial life."
```

### 2. Conversational Agents (Chatbots) 🤖
- **Input (Encoder):** The user's prompt (e.g., "What are your hours of operation?").
- **Output (Decoder):** The bot's response (e.g., "We are open from 9 AM to 5 PM, Monday through Friday.").
- **How it works:** The Encoder captures the *intent* and *context* of the user's question. The Decoder generates a natural-sounding, contextually appropriate reply.

```
Encoder input:  ["What", "are", "your", "hours", "of", "operation", "?", "<END>"]
Context Vector: [512 numbers encoding "user wants business hours"]
Decoder output: ["We", "are", "open", "9", "AM", "to", "5", "PM", "."]
```

### 3. Machine Translation 🌐 (our running example)
- **Input:** Source language sentence → **Output:** Target language sentence.
- The Encoder and Decoder can even use different vocabularies and embedding spaces!

| Task | Encoder Input | Decoder Output | Length Match? |
|---|---|---|---|
| **Translation** | "I love cats" (3 words) | "J'aime les chats" (4 words) | ❌ No |
| **Summarization** | 500-word article | 30-word summary | ❌ No |
| **Chatbot** | "What time do you close?" (6 words) | "We close at 9 PM daily." (6 words) | Maybe |
| **Code Generation** | "sort a list in python" (5 words) | `sorted(my_list)` (1 token) | ❌ No |

In all of these scenarios, the magical bridge between the two distinct sequences is the **Context Vector**.

---

## Summary — What We Learned 🎓

| Concept | Key Takeaway |
|---|---|
| **The Problem** | Standard LSTMs enforce 1:1 input-output mapping — useless for translation |
| **Encoder** | Reads the full input and compresses meaning into a fixed-size Context Vector |
| **Decoder** | Takes the Context Vector and generates output word by word (autoregressively) |
| **`<START>` / `<END>`** | Special tokens that trigger generation start and signal completion |
| **Context Vector** | The final (h, C) from the Encoder — the compressed "summary" of the input |
| **Teacher Forcing** | During training, feed the correct previous word instead of the model's prediction |
| **Autoregressive Decoding** | During inference, feed the model's own predictions — no teacher available |
| **Stacked LSTMs** | Multiple layers capture syntax → phrases → meaning at increasing abstraction |
| **Exposure Bias** | Mismatch between training (teacher forcing) and inference (autoregression) |

---

## The Fatal Flaw: The Information Bottleneck 🚰

The Encoder-Decoder architecture dominated translation from 2014 to 2017. It was magical. But it had one catastrophic flaw.

Look at the dimensions above. The ENTIRE source sentence — whether 3 words or 300 words — has to be compressed into `h_final` and `C_final` — **fixed-size vectors** (e.g., 512 numbers each).

![The Context Vector Bottleneck](content/large-language-models/natural-language-processing/images/encoder_decoder_bottleneck.png)

This is fine for "I love cats." But what if the source sentence is 50 words long? A 100-word paragraph? 

Imagine reading a 100-page book and being asked to compress the entire plot, character arcs, and themes into a single tweet. When you try to write the sequel (decode), you've lost all the fine details. The BLEU scores (translation quality metric) plummet for sentences longer than ~20 words.

In a basic Seq2Seq model, the Context Vector is an **Information Bottleneck**. The beginning of a long sentence is completely forgotten by the time the final word is read, causing the translation quality for long sentences to collapse.

---

## What's Next? 🚀

```
RNNs → LSTMs → Encoder-Decoder → ???
```

The Context Vector tries to be a zip file for language — and just like a zip file, there's a limit to how much you can compress before losing quality.

How do we solve the bottleneck? Instead of forcing the Encoder to compress everything into one final vector, what if the Decoder could *look back* at **every hidden state** the Encoder produced — not just the last one?

What if, when translating the word "chats," the Decoder could say: *"Let me pay special **attention** to the word 'cats' in the source sentence right now."*

And when translating "J'aime," it could attend to "love" instead. Each output word could focus on the most relevant input word — dynamically, at every step.

This simple, elegant idea changed the world. It is the **Attention Mechanism** — and it's coming next. 🔥

---

Got questions or suggestions? 👉 [Send me a message!](https://ashwinberyl.github.io/#contact)

---

*— Ashwin*

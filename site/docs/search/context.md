# Context Pack

Static, deterministic view of the context pack for the canonical
example query. The page is regenerated on every
`wiki build-site --refresh` and is byte-stable for a given set
of indexes. The data is produced by the same code path that
powers `wiki build-context` (Prompt 33) and `wiki build-rag-prompt`
(Prompt 34 MVP closure).

## Query

`attention transformer`

## Retrieval mode

`hybrid` (BM25 + vector fusion).

## Indexes

- BM25 index built: True
- Vector index built: True
- Chunk index built: True

## Context Pack summary

- Schema version: `context_pack_v1`
- Total chunks: 5
- Total sources: 2
- Used chars: 15391
- Limit: 5
- Max chars (per chunk): 0

## Chunks

### [cite:1] (rank 1)

- Resource: `pdf:bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697` — Attention Is All You Need
- Source type: `pdf`
- Score: 0.863751
- Chunk id: `pdf:bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697-p0001`

```
1 Introduction
Recurrent neural networks, long short-term memory [13] and gated recurrent [7] neural networks
in particular, have been firmly established as state of the art approaches in sequence modeling and
transduction problems such as language modeling and machine translation [ 35, 2, 5]. Numerous
efforts have since continued to push the boundaries of recurrent language models and encoder-decoder
architectures [38, 24, 15].
Recurrent models typically factor computation along the symbol positions of the input and output
sequences. Aligning the positions to steps in computation time, they generate a sequence of hidden
states ht, as a function of the previous hidden state ht−1 and the input for position t. This inherently
sequential nature precludes parallelization within training examples, which becomes critical at longer
sequence lengths, as memory constraints limit batching across examples. Recent work has achieved
significant improvements in computational efficiency through factorization tricks [21] and conditional
computation [32], while also improving model performance in case of the latter. The fundamental
constraint of sequential computation, however, remains.
Attention mechanisms have become an integral part of compelling sequence modeling and transduc-
tion models in various tasks, allowing modeling of dependencies without regard to their distance in
the input or output sequences [2, 19]. In all but a few cases [27], however, such attention mechanisms
are used in conjunction with a recurrent network.
In this work we propose the Transformer, a model architecture eschewing recurrence and instead
relying entirely on an attention mechanism to draw global dependencies between input and output.
The Transformer allows for significantly more parallelization and can reach a new state of the art in
translation quality after being trained for as little as twelve hours on eight P100 GPUs.
2 Background
The goal of reducing sequential computation also forms the foundation of the Extended Neural GPU
[16], ByteNet [18] and ConvS2S [9], all of which use convolutional neural networks as basic building
block, computing hidden representations in parallel for all input and output positions. In these models,
the number of operations required to relate signals from two arbitrary input or output positions grows
in the distance between positions, linearly for ConvS2S and logarithmically for ByteNet. This makes
it more difficult to learn dependencies between distant positions [ 12]. In the Transformer this is
reduced to a constant number of operations, albeit at the cost of reduced effective resolution due
to averaging attention-weighted positions, an effect we counteract with Multi-Head Attention as
described in section 3.2.
Self-attention, sometimes called intra-attention is an attention mechanism relating different positions
of a single sequence in order to compute a representation of the sequence. Self-attention has been
used successfully in a variety of tasks including reading comprehension, abstractive summarization,
textual entailment and learning task-independent sentence representations [4, 27, 28, 22].
End-to-end memory networks are based on a recurrent attention mechanism instead of sequence-
aligned recurrence and have been shown to perform well on simple-language question answering and
language modeling tasks [34].
To the best of our knowledge, however, the Transformer is the first transduction model relying
entirely on self-attention to compute representations of its input and output without using sequence-
aligned RNNs or convolution. In the following sections, we will describe the Transformer, motivate
self-attention and discuss its advantages over models such as [17, 18] and [9].
3 Model Architecture
Most competitive neural sequence transduction models have an encoder-decoder structure [5, 2, 35].
Here, the encoder maps an input sequence of symbol representations (x1, ..., xn) to a sequence
of continuous representations z = (z1, ..., zn). Given z, the decoder then generates an output
sequence (y1, ..., ym) of symbols one element at a time. At each step the model is auto-regressive
[10], consuming the previously generated symbols as additional input when generating the next.
2
```

### [cite:2] (rank 2)

- Resource: `youtube:yHAcgyntYDQ` — How vLLM Works + Journey of Prompts to vLLM + Paged Attention
- Source type: `youtube`
- Score: 0.832995
- Chunk id: `youtube:yHAcgyntYDQ-c0000`

```
This video explains the journey of prompts in VLLLM. We start with three example prompts. The tokenizer takes each prompt and converts it into word token ID pairs. As each prompt enters the tokenizer, it transforms into its tokenized representation. Model execution contains two phases. the pre-filling stage where the model processes all prompt tokens in parallel and the decoding stage where the model generates new tokens one step at a time. This is the prefilling phase. Each prompt embeddings moves into the transformer block and their key/v valueue pairs are calculated for every token. This occurs in every transformer layer where each block computes the key value cache for each token embedding at every transformer block. In the following sections, we will explain how exactly these key values are stored. As shown, all input tokens have their key value caches computed in every layer. That's the reason prefilling is computebound. Let's take a look at the decoding phase. Each prompt shows its full key value pairs, including the newly added tokens from the prefilling phase. As shown, only new tokens do not have key values for this step. When these tokens are passed through the transformer layers, only the new tokens produce fresh key value entries. Previous KVs are reused from the cache. Because we compute KVs only for newly generated tokens, decoding is memory bound rather than computebound. Theuler prioritizes decode requests over prefill ones. Let's look at memory management. Suppose we have 40 GB of memory. What resources need to be allocated when loading a model into it? The first allocation is for models weights. In this example, it's 13 GB. PyTorch temporarily uses memory for activations during computation, for example, in pre-filling. and this represents the peak of that usage. The remaining GPU memory is reserved for KV caches. We will deep dive into this section later. Some memory is also taken by system components like CUDA kernels and drivers outside of PyTorch. The KV cache is organized into blocks which serve as the main units used by page attention. Block size is dynamically calculated based on each model specifications. Let's take a look at how each block is allocated. By default, each block has space to store the key value of 16 tokens for all layers. To calculate each block size, the model exeutor gives us three key pieces of information. The number of transformer layers, the number of attention heads in each layer, and the size of each attention head. Using these three pieces of information, each layer space is computed from the number of heads and the head dimension. Since a block stores key value caches for 16 tokens across all layers, we multiply the per layer requirement by the total number of transformer layers. Each block must have enough space to hold key value data for every layer. To compute the memory footprint of each block, we multiply the number of transformer layers, four, the number of tokens per block, 16, the two cache
```

### [cite:3] (rank 3)

- Resource: `pdf:bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697` — Attention Is All You Need
- Source type: `pdf`
- Score: 0.763514
- Chunk id: `pdf:bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697-p0009`

```
Table 4: The Transformer generalizes well to English constituency parsing (Results are on Section 23
of WSJ)
Parser Training WSJ 23 F1
Vinyals & Kaiser el al. (2014) [37] WSJ only, discriminative 88.3
Petrov et al. (2006) [29] WSJ only, discriminative 90.4
Zhu et al. (2013) [40] WSJ only, discriminative 90.4
Dyer et al. (2016) [8] WSJ only, discriminative 91.7
Transformer (4 layers) WSJ only, discriminative 91.3
Zhu et al. (2013) [40] semi-supervised 91.3
Huang & Harper (2009) [14] semi-supervised 91.3
McClosky et al. (2006) [26] semi-supervised 92.1
Vinyals & Kaiser el al. (2014) [37] semi-supervised 92.1
Transformer (4 layers) semi-supervised 92.7
Luong et al. (2015) [23] multi-task 93.0
Dyer et al. (2016) [8] generative 93.3
increased the maximum output length to input length + 300. We used a beam size of 21 and α = 0.3
for both WSJ only and the semi-supervised setting.
Our results in Table 4 show that despite the lack of task-specific tuning our model performs sur-
prisingly well, yielding better results than all previously reported models with the exception of the
Recurrent Neural Network Grammar [8].
In contrast to RNN sequence-to-sequence models [37], the Transformer outperforms the Berkeley-
Parser [29] even when training only on the WSJ training set of 40K sentences.
7 Conclusion
In this work, we presented the Transformer, the first sequence transduction model based entirely on
attention, replacing the recurrent layers most commonly used in encoder-decoder architectures with
multi-headed self-attention.
For translation tasks, the Transformer can be trained significantly faster than architectures based
on recurrent or convolutional layers. On both WMT 2014 English-to-German and WMT 2014
English-to-French translation tasks, we achieve a new state of the art. In the former task our best
model outperforms even all previously reported ensembles.
We are excited about the future of attention-based models and plan to apply them to other tasks. We
plan to extend the Transformer to problems involving input and output modalities other than text and
to investigate local, restricted attention mechanisms to efficiently handle large inputs and outputs
such as images, audio and video. Making generation less sequential is another research goals of ours.
The code we used to train and evaluate our models is available at https://github.com/
tensorflow/tensor2tensor.
Acknowledgements We are grateful to Nal Kalchbrenner and Stephan Gouws for their fruitful
comments, corrections and inspiration.
References
[1] Jimmy Lei Ba, Jamie Ryan Kiros, and Geoffrey E Hinton. Layer normalization. arXiv preprint
arXiv:1607.06450, 2016.
[2] Dzmitry Bahdanau, Kyunghyun Cho, and Yoshua Bengio. Neural machine translation by jointly
learning to align and translate. CoRR, abs/1409.0473, 2014.
[3] Denny Britz, Anna Goldie, Minh-Thang Luong, and Quoc V . Le. Massive exploration of neural
machine translation architectures. CoRR, abs/1703.03906, 2017.
[4] Jianpeng Cheng, Li Dong, and Mirella Lapata. Long short-term memory-networks for machine
reading. arXiv preprint arXiv:1601.06733, 2016.
10
```

### [cite:4] (rank 4)

- Resource: `pdf:bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697` — Attention Is All You Need
- Source type: `pdf`
- Score: 0.744569
- Chunk id: `pdf:bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697-p0002`

```
Figure 1: The Transformer - model architecture.
The Transformer follows this overall architecture using stacked self-attention and point-wise, fully
connected layers for both the encoder and decoder, shown in the left and right halves of Figure 1,
respectively.
3.1 Encoder and Decoder Stacks
Encoder: The encoder is composed of a stack of N = 6 identical layers. Each layer has two
sub-layers. The first is a multi-head self-attention mechanism, and the second is a simple, position-
wise fully connected feed-forward network. We employ a residual connection [11] around each of
the two sub-layers, followed by layer normalization [ 1]. That is, the output of each sub-layer is
LayerNorm(x + Sublayer(x)), where Sublayer(x) is the function implemented by the sub-layer
itself. To facilitate these residual connections, all sub-layers in the model, as well as the embedding
layers, produce outputs of dimension dmodel = 512.
Decoder: The decoder is also composed of a stack of N = 6identical layers. In addition to the two
sub-layers in each encoder layer, the decoder inserts a third sub-layer, which performs multi-head
attention over the output of the encoder stack. Similar to the encoder, we employ residual connections
around each of the sub-layers, followed by layer normalization. We also modify the self-attention
sub-layer in the decoder stack to prevent positions from attending to subsequent positions. This
masking, combined with fact that the output embeddings are offset by one position, ensures that the
predictions for position i can depend only on the known outputs at positions less than i.
3.2 Attention
An attention function can be described as mapping a query and a set of key-value pairs to an output,
where the query, keys, values, and output are all vectors. The output is computed as a weighted sum
3
```

### [cite:5] (rank 5)

- Resource: `pdf:bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697` — Attention Is All You Need
- Source type: `pdf`
- Score: 0.735736
- Chunk id: `pdf:bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697-p0007`

```
Table 2: The Transformer achieves better BLEU scores than previous state-of-the-art models on the
English-to-German and English-to-French newstest2014 tests at a fraction of the training cost.
Model
BLEU Training Cost (FLOPs)
EN-DE EN-FR EN-DE EN-FR
ByteNet [18] 23.75
Deep-Att + PosUnk [39] 39.2 1.0 · 1020
GNMT + RL [38] 24.6 39.92 2.3 · 1019 1.4 · 1020
ConvS2S [9] 25.16 40.46 9.6 · 1018 1.5 · 1020
MoE [32] 26.03 40.56 2.0 · 1019 1.2 · 1020
Deep-Att + PosUnk Ensemble [39] 40.4 8.0 · 1020
GNMT + RL Ensemble [38] 26.30 41.16 1.8 · 1020 1.1 · 1021
ConvS2S Ensemble [9] 26.36 41.29 7.7 · 1019 1.2 · 1021
Transformer (base model) 27.3 38.1 3.3 · 1018
Transformer (big) 28.4 41.8 2.3 · 1019
Residual Dropout We apply dropout [33] to the output of each sub-layer, before it is added to the
sub-layer input and normalized. In addition, we apply dropout to the sums of the embeddings and the
positional encodings in both the encoder and decoder stacks. For the base model, we use a rate of
Pdrop = 0.1.
Label Smoothing During training, we employed label smoothing of value ϵls = 0.1 [36]. This
hurts perplexity, as the model learns to be more unsure, but improves accuracy and BLEU score.
6 Results
6.1 Machine Translation
On the WMT 2014 English-to-German translation task, the big transformer model (Transformer (big)
in Table 2) outperforms the best previously reported models (including ensembles) by more than 2.0
BLEU, establishing a new state-of-the-art BLEU score of 28.4. The configuration of this model is
listed in the bottom line of Table 3. Training took 3.5 days on 8 P100 GPUs. Even our base model
surpasses all previously published models and ensembles, at a fraction of the training cost of any of
the competitive models.
On the WMT 2014 English-to-French translation task, our big model achieves a BLEU score of 41.0,
outperforming all of the previously published single models, at less than 1/4 the training cost of the
previous state-of-the-art model. The Transformer (big) model trained for English-to-French used
dropout rate Pdrop = 0.1, instead of 0.3.
For the base models, we used a single model obtained by averaging the last 5 checkpoints, which
were written at 10-minute intervals. For the big models, we averaged the last 20 checkpoints. We
used beam search with a beam size of 4 and length penalty α = 0.6 [38]. These hyperparameters
were chosen after experimentation on the development set. We set the maximum output length during
inference to input length + 50, but terminate early when possible [38].
Table 2 summarizes our results and compares our translation quality and training costs to other model
architectures from the literature. We estimate the number of floating point operations used to train a
model by multiplying the training time, the number of GPUs used, and an estimate of the sustained
single-precision floating-point capacity of each GPU 5.
6.2 Model Variations
To evaluate the importance of different components of the Transformer, we varied our base model
in different ways, measuring the change in performance on English-to-German translation on the
5We used values of 2.8, 3.7, 6.0 and 9.5 TFLOPS for K80, K40, M40 and P100, respectively.
8
```

## Sources

- [cite:1] `pdf:bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697` — Attention Is All You Need (pdf)
    - chunk: `pdf:bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697-p0001`
    - chunk: `pdf:bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697-p0009`
    - chunk: `pdf:bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697-p0002`
    - chunk: `pdf:bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697-p0007`
- [cite:2] `youtube:yHAcgyntYDQ` — How vLLM Works + Journey of Prompts to vLLM + Paged Attention (youtube)
    - chunk: `youtube:yHAcgyntYDQ-c0000`

## Reproduce with the CLI

```
.venv/bin/python -m wiki build-context "attention transformer"
.venv/bin/python -m wiki build-context "attention transformer" --json
.venv/bin/python -m wiki build-rag-prompt "attention transformer"
.venv/bin/python -m wiki build-rag-prompt "attention transformer" --json
```

## Out of scope

The context pack is a deterministic, no-LLM projection of the
upstream retrieval result list. The page does **not** add:

- LLM calls (no Ollama, no OpenAI, no Gemini, no model providers).
- Model embeddings (no sentence-transformers, no transformers).
- Vector databases (no FAISS, no Chroma, no LanceDB).
- Answer generation (no chat reply, no grounded answer).
- Re-ranking of the upstream retrieval result list.

## Provenance

- Generated by `wiki build-site --refresh`.
- Source: on-disk BM25, vector, and chunk indexes (Prompts 28, 29, 27).
- Deterministic: no LLM, no embeddings, no vector DB, no random ordering.

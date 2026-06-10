---
pageClass: graph-relationships-page
---

# Resource Relationships

Deterministic resource-to-resource relationships detected at graph build
time (Prompt 24). Each row corresponds to a single edge in the
knowledge graph. Scores and reason lists come from the edge metadata.

## Why This Page Matters

These edges show which resources reinforce each other, overlap on
concepts, or appear to cover adjacent ground. Use this page as a
summary layer before jumping into the interactive graph workspace.

<div class="graph-stat-grid">
  <div class="graph-stat-card"><span class="graph-stat-kicker">resource_may_be_prerequisite_for_resource</span><strong>0</strong><span>Relationship edges currently generated for this type.</span></div>
  <div class="graph-stat-card"><span class="graph-stat-kicker">resource_may_expand_on_resource</span><strong>0</strong><span>Relationship edges currently generated for this type.</span></div>
  <div class="graph-stat-card"><span class="graph-stat-kicker">resource_same_source_type_as_resource</span><strong>126</strong><span>Relationship edges currently generated for this type.</span></div>
  <div class="graph-stat-card"><span class="graph-stat-kicker">resource_shares_concept_with_resource</span><strong>210</strong><span>Relationship edges currently generated for this type.</span></div>
  <div class="graph-stat-card"><span class="graph-stat-kicker">resource_shares_topic_with_resource</span><strong>68</strong><span>Relationship edges currently generated for this type.</span></div>
  <div class="graph-stat-card"><span class="graph-stat-kicker">resource_similar_to_resource</span><strong>211</strong><span>Relationship edges currently generated for this type.</span></div>
</div>

## Open In Graph Workspace

- [Open the full graph workspace](/graph/explore) — start from the default view.
- [Focus on resource relationships](/graph/explore?lens=resources&layout=concentric) — start in a resource-focused lens.
- [Trace 7 AI Terms You Need to Know: Agents, RAG, ASI & More to Top 3 RAG Retrieval Strategies: Sparse, Dense, & Hybrid Explained](/graph/explore?layout=concentric&lens=resources&source=resource:youtube_VSFuqMh4hus&target=resource:youtube_r0Dciuq0knU&path=1)
- [Trace Getting Started With Embeddings to 7 AI Terms You Need to Know: Agents, RAG, ASI & More](/graph/explore?layout=concentric&lens=resources&source=resource:webpage_7e46dca0acc3e5be16343595987da50cc15588cd13cbfe86a069fd9d38079216&target=resource:youtube_VSFuqMh4hus&path=1)
- [Trace Getting Started With Embeddings to Top 3 RAG Retrieval Strategies: Sparse, Dense, & Hybrid Explained](/graph/explore?layout=concentric&lens=resources&source=resource:webpage_7e46dca0acc3e5be16343595987da50cc15588cd13cbfe86a069fd9d38079216&target=resource:youtube_r0Dciuq0knU&path=1)

## Edge type summary

| Edge type | Count |
|---|---:|
| resource_may_be_prerequisite_for_resource | 0 |
| resource_may_expand_on_resource | 0 |
| resource_same_source_type_as_resource | 126 |
| resource_shares_concept_with_resource | 210 |
| resource_shares_topic_with_resource | 68 |
| resource_similar_to_resource | 211 |

## Per-type details

### `resource_same_source_type_as_resource`

Both resources share a source type and at least one of topic/concept/keyword overlap.

| Source | Target | Score | Reasons | Shared topics | Shared concepts | Shared keywords |
|---|---|---:|---|---|---|---|
| sentence-transformers (Sentence Transformers) | Getting Started With Embeddings | 0.5 | same_source_type, shared_concepts, shared_topics | embeddings, rag-retrieval | embeddings, inference, llm, rag, retrieval, transformer, vector-database |  |
| sentence-transformers (Sentence Transformers) | Linear Algebra Course Introduction \| Linear Algebra \| Mathematics \| MIT OpenCourseWare | 0.5 | same_source_type, shared_concepts |  | embeddings, inference, llm, rag |  |
| sentence-transformers (Sentence Transformers) | Inside vLLM: Anatomy of a High-Throughput LLM Inference System - Aleksa Gordić | 0.5 | same_source_type, shared_concepts |  | inference, llm, rag, transformer |  |
| Getting Started With Embeddings | Linear Algebra Course Introduction \| Linear Algebra \| Mathematics \| MIT OpenCourseWare | 0.5 | same_source_type, shared_concepts |  | attention, embeddings, inference, llm, rag |  |
| Getting Started With Embeddings | Inside vLLM: Anatomy of a High-Throughput LLM Inference System - Aleksa Gordić | 0.5 | same_source_type, shared_concepts |  | attention, inference, llm, rag, transformer |  |
| Linear Algebra Course Introduction \| Linear Algebra \| Mathematics \| MIT OpenCourseWare | Inside vLLM: Anatomy of a High-Throughput LLM Inference System - Aleksa Gordić | 0.5 | same_source_type, shared_concepts |  | attention, inference, llm, rag |  |
| Agent Harness explained in 8min.. | Strategies for LLM Evals (GuideLLM, lm-eval-harness, OpenAI Evals Workshop) — Taylor Jordan Smith | 0.5 | same_source_type, shared_concepts, shared_topics | agents | context-window, llm, rag |  |
| Agent Harness explained in 8min.. | What are LLM Evals ? | 0.5 | same_source_type, shared_concepts |  | llm, prompt-engineering, rag |  |
| Agent Harness explained in 8min.. | RAG vs. CAG: Solving Knowledge Gaps in AI Models | 0.5 | same_source_type, shared_concepts |  | context-window, llm, rag |  |
| Agent Harness explained in 8min.. | AgentFlayer: ChatGPT Connectors 0click Exfiltration Attack | 0.5 | same_source_type, shared_concepts, shared_keywords |  | context-window, llm, rag | agent |
| Agent Harness explained in 8min.. | 7 AI Terms You Need to Know: Agents, RAG, ASI & More | 0.5 | same_source_type, shared_concepts, shared_keywords, shared_topics | agents | llm, rag | agent |
| Agent Harness explained in 8min.. | Adam Optimizer VISUALLY Explained | 0.5 | same_source_type, shared_concepts |  | llm, rag |  |
| Agent Harness explained in 8min.. | Inside vLLM: How vLLM works | 0.5 | same_source_type, shared_concepts |  | llm, rag |  |
| Agent Harness explained in 8min.. | Lessons from the Trenches: Building LLM Evals That Work IRL: Aparna Dhinkaran | 0.5 | same_source_type, shared_concepts |  | context-window, llm, rag |  |
| Agent Harness explained in 8min.. | vLLM: Easily Deploying & Serving LLMs | 0.5 | same_source_type, shared_concepts |  | llm, rag |  |
| Agent Harness explained in 8min.. | Introduction: AI Evals For Everyone | 0.5 | same_source_type, shared_concepts |  | llm, rag |  |
| Agent Harness explained in 8min.. | Top 3 RAG Retrieval Strategies: Sparse, Dense, & Hybrid Explained | 0.5 | same_source_type, shared_concepts |  | llm, rag |  |
| Agent Harness explained in 8min.. | Better RAG: Hybrid Search in Chat with Documents \| BM25 and Ensemble | 0.5 | same_source_type, shared_concepts |  | llm, prompt-engineering, rag |  |
| Agent Harness explained in 8min.. | 2 Methods For Improving Retrieval in RAG | 0.5 | same_source_type, shared_concepts |  | llm, prompt-engineering, rag |  |
| Agent Harness explained in 8min.. | Understanding Embeddings in RAG and How to use them - Llama-Index | 0.5 | same_source_type, shared_concepts |  | llm, rag |  |

_Showing top 20 of 126 edges for this type._

### `resource_shares_concept_with_resource`

Both resources mention the same concept slug.

| Source | Target | Score | Reasons | Shared topics | Shared concepts | Shared keywords |
|---|---|---:|---|---|---|---|
| Getting Started With Embeddings | 7 AI Terms You Need to Know: Agents, RAG, ASI & More | 30.0 | shared_concepts |  | attention, cosine-similarity, embeddings, fine-tuning, inference, llm, rag, retrieval, transformer, vector-database |  |
| 7 AI Terms You Need to Know: Agents, RAG, ASI & More | Top 3 RAG Retrieval Strategies: Sparse, Dense, & Hybrid Explained | 30.0 | shared_concepts |  | chunking, cosine-similarity, embeddings, fine-tuning, inference, llm, rag, retrieval, transformer, vector-database |  |
| Getting Started With Embeddings | Top 3 RAG Retrieval Strategies: Sparse, Dense, & Hybrid Explained | 27.0 | shared_concepts |  | cosine-similarity, embeddings, fine-tuning, inference, llm, rag, retrieval, transformer, vector-database |  |
| sentence-transformers (Sentence Transformers) | Getting Started With Embeddings | 21.0 | shared_concepts |  | embeddings, inference, llm, rag, retrieval, transformer, vector-database |  |
| sentence-transformers (Sentence Transformers) | 7 AI Terms You Need to Know: Agents, RAG, ASI & More | 21.0 | shared_concepts |  | embeddings, inference, llm, rag, retrieval, transformer, vector-database |  |
| sentence-transformers (Sentence Transformers) | Top 3 RAG Retrieval Strategies: Sparse, Dense, & Hybrid Explained | 21.0 | shared_concepts |  | embeddings, inference, llm, rag, retrieval, transformer, vector-database |  |
| Getting Started With Embeddings | RAG vs. CAG: Solving Knowledge Gaps in AI Models | 21.0 | shared_concepts |  | attention, embeddings, llm, rag, retrieval, transformer, vector-database |  |
| RAG vs. CAG: Solving Knowledge Gaps in AI Models | 7 AI Terms You Need to Know: Agents, RAG, ASI & More | 21.0 | shared_concepts |  | attention, embeddings, llm, rag, retrieval, transformer, vector-database |  |
| 7 AI Terms You Need to Know: Agents, RAG, ASI & More | Better RAG: Hybrid Search in Chat with Documents \| BM25 and Ensemble | 21.0 | shared_concepts |  | chunking, cosine-similarity, embeddings, inference, llm, rag, retrieval |  |
| 7 AI Terms You Need to Know: Agents, RAG, ASI & More | Understanding Embeddings in RAG and How to use them - Llama-Index | 21.0 | shared_concepts |  | chunking, cosine-similarity, embeddings, llm, rag, retrieval, vector-database |  |
| Top 3 RAG Retrieval Strategies: Sparse, Dense, & Hybrid Explained | Better RAG: Hybrid Search in Chat with Documents \| BM25 and Ensemble | 21.0 | shared_concepts |  | chunking, cosine-similarity, embeddings, inference, llm, rag, retrieval |  |
| Top 3 RAG Retrieval Strategies: Sparse, Dense, & Hybrid Explained | Understanding Embeddings in RAG and How to use them - Llama-Index | 21.0 | shared_concepts |  | chunking, cosine-similarity, embeddings, llm, rag, retrieval, vector-database |  |
| sentence-transformers (Sentence Transformers) | RAG vs. CAG: Solving Knowledge Gaps in AI Models | 18.0 | shared_concepts |  | embeddings, llm, rag, retrieval, transformer, vector-database |  |
| Getting Started With Embeddings | Strategies for LLM Evals (GuideLLM, lm-eval-harness, OpenAI Evals Workshop) — Taylor Jordan Smith | 18.0 | shared_concepts |  | attention, fine-tuning, inference, llm, rag, retrieval |  |
| Getting Started With Embeddings | vLLM: Easily Deploying & Serving LLMs | 18.0 | shared_concepts |  | attention, fine-tuning, inference, llm, rag, transformer |  |
| Getting Started With Embeddings | Better RAG: Hybrid Search in Chat with Documents \| BM25 and Ensemble | 18.0 | shared_concepts |  | cosine-similarity, embeddings, inference, llm, rag, retrieval |  |
| Getting Started With Embeddings | Understanding Embeddings in RAG and How to use them - Llama-Index | 18.0 | shared_concepts |  | cosine-similarity, embeddings, llm, rag, retrieval, vector-database |  |
| Getting Started With Embeddings | How vLLM Works + Journey of Prompts to vLLM + Paged Attention | 18.0 | shared_concepts |  | attention, embeddings, inference, llm, rag, transformer |  |
| Inside vLLM: Anatomy of a High-Throughput LLM Inference System - Aleksa Gordić | Inside vLLM: How vLLM works | 18.0 | shared_concepts |  | attention, inference, llm, rag, tokenization, transformer |  |
| Inside vLLM: Anatomy of a High-Throughput LLM Inference System - Aleksa Gordić | How vLLM Works + Journey of Prompts to vLLM + Paged Attention | 18.0 | shared_concepts |  | attention, inference, llm, rag, tokenization, transformer |  |

_Showing top 20 of 210 edges for this type._

### `resource_shares_topic_with_resource`

Both resources match the same canonical topic.

| Source | Target | Score | Reasons | Shared topics | Shared concepts | Shared keywords |
|---|---|---:|---|---|---|---|
| Inside vLLM: How vLLM works | How vLLM Works + Journey of Prompts to vLLM + Paged Attention | 6.0 | shared_topics | llm-inference, transcription-asr, vllm |  |  |
| sentence-transformers (Sentence Transformers) | Getting Started With Embeddings | 4.0 | shared_topics | embeddings, rag-retrieval |  |  |
| sentence-transformers (Sentence Transformers) | Top 3 RAG Retrieval Strategies: Sparse, Dense, & Hybrid Explained | 4.0 | shared_topics | embeddings, rag-retrieval |  |  |
| sentence-transformers (Sentence Transformers) | Understanding Embeddings in RAG and How to use them - Llama-Index | 4.0 | shared_topics | embeddings, rag-retrieval |  |  |
| Getting Started With Embeddings | Top 3 RAG Retrieval Strategies: Sparse, Dense, & Hybrid Explained | 4.0 | shared_topics | embeddings, rag-retrieval |  |  |
| Getting Started With Embeddings | Understanding Embeddings in RAG and How to use them - Llama-Index | 4.0 | shared_topics | embeddings, rag-retrieval |  |  |
| Inside vLLM: Anatomy of a High-Throughput LLM Inference System - Aleksa Gordić | Inside vLLM: How vLLM works | 4.0 | shared_topics | llm-inference, vllm |  |  |
| Inside vLLM: Anatomy of a High-Throughput LLM Inference System - Aleksa Gordić | vLLM: Easily Deploying & Serving LLMs | 4.0 | shared_topics | llm-inference, vllm |  |  |
| Inside vLLM: Anatomy of a High-Throughput LLM Inference System - Aleksa Gordić | How vLLM Works + Journey of Prompts to vLLM + Paged Attention | 4.0 | shared_topics | llm-inference, vllm |  |  |
| What are LLM Evals ? | Understanding Embeddings in RAG and How to use them - Llama-Index | 4.0 | shared_topics | llm-evals, transcription-asr |  |  |
| Inside vLLM: How vLLM works | vLLM: Easily Deploying & Serving LLMs | 4.0 | shared_topics | llm-inference, vllm |  |  |
| vLLM: Easily Deploying & Serving LLMs | How vLLM Works + Journey of Prompts to vLLM + Paged Attention | 4.0 | shared_topics | llm-inference, vllm |  |  |
| Top 3 RAG Retrieval Strategies: Sparse, Dense, & Hybrid Explained | Understanding Embeddings in RAG and How to use them - Llama-Index | 4.0 | shared_topics | embeddings, rag-retrieval |  |  |
| COG-RAG-Giving-RAG-A-Brain | sentence-transformers (Sentence Transformers) | 2.0 | shared_topics | rag-retrieval |  |  |
| COG-RAG-Giving-RAG-A-Brain | Getting Started With Embeddings | 2.0 | shared_topics | rag-retrieval |  |  |
| COG-RAG-Giving-RAG-A-Brain | RAG vs. CAG: Solving Knowledge Gaps in AI Models | 2.0 | shared_topics | rag-retrieval |  |  |
| COG-RAG-Giving-RAG-A-Brain | 7 AI Terms You Need to Know: Agents, RAG, ASI & More | 2.0 | shared_topics | rag-retrieval |  |  |
| COG-RAG-Giving-RAG-A-Brain | Top 3 RAG Retrieval Strategies: Sparse, Dense, & Hybrid Explained | 2.0 | shared_topics | rag-retrieval |  |  |
| COG-RAG-Giving-RAG-A-Brain | Better RAG: Hybrid Search in Chat with Documents \| BM25 and Ensemble | 2.0 | shared_topics | rag-retrieval |  |  |
| COG-RAG-Giving-RAG-A-Brain | 2 Methods For Improving Retrieval in RAG | 2.0 | shared_topics | rag-retrieval |  |  |

_Showing top 20 of 68 edges for this type._

### `resource_similar_to_resource`

Catch-all similarity edge. Emitted when a pair's combined topic/concept/keyword score meets the threshold.

| Source | Target | Score | Reasons | Shared topics | Shared concepts | Shared keywords |
|---|---|---:|---|---|---|---|
| 7 AI Terms You Need to Know: Agents, RAG, ASI & More | Top 3 RAG Retrieval Strategies: Sparse, Dense, & Hybrid Explained | 33.5 | same_source_type, shared_concepts, shared_keywords, shared_topics | rag-retrieval | chunking, cosine-similarity, embeddings, fine-tuning, inference, llm, rag, retrieval, transformer, vector-database | rag |
| Getting Started With Embeddings | 7 AI Terms You Need to Know: Agents, RAG, ASI & More | 32.0 | shared_concepts, shared_topics | rag-retrieval | attention, cosine-similarity, embeddings, fine-tuning, inference, llm, rag, retrieval, transformer, vector-database |  |
| Getting Started With Embeddings | Top 3 RAG Retrieval Strategies: Sparse, Dense, & Hybrid Explained | 31.0 | shared_concepts, shared_topics | embeddings, rag-retrieval | cosine-similarity, embeddings, fine-tuning, inference, llm, rag, retrieval, transformer, vector-database |  |
| Top 3 RAG Retrieval Strategies: Sparse, Dense, & Hybrid Explained | Understanding Embeddings in RAG and How to use them - Llama-Index | 26.5 | same_source_type, shared_concepts, shared_keywords, shared_topics | embeddings, rag-retrieval | chunking, cosine-similarity, embeddings, llm, rag, retrieval, vector-database | rag |
| sentence-transformers (Sentence Transformers) | Getting Started With Embeddings | 25.5 | same_source_type, shared_concepts, shared_topics | embeddings, rag-retrieval | embeddings, inference, llm, rag, retrieval, transformer, vector-database |  |
| Inside vLLM: How vLLM works | How vLLM Works + Journey of Prompts to vLLM + Paged Attention | 25.5 | same_source_type, shared_concepts, shared_keywords, shared_topics | llm-inference, transcription-asr, vllm | attention, inference, llm, rag, tokenization, transformer | vllm |
| sentence-transformers (Sentence Transformers) | Top 3 RAG Retrieval Strategies: Sparse, Dense, & Hybrid Explained | 25.0 | shared_concepts, shared_topics | embeddings, rag-retrieval | embeddings, inference, llm, rag, retrieval, transformer, vector-database |  |
| RAG vs. CAG: Solving Knowledge Gaps in AI Models | 7 AI Terms You Need to Know: Agents, RAG, ASI & More | 24.5 | same_source_type, shared_concepts, shared_keywords, shared_topics | rag-retrieval | attention, embeddings, llm, rag, retrieval, transformer, vector-database | rag |
| 7 AI Terms You Need to Know: Agents, RAG, ASI & More | Better RAG: Hybrid Search in Chat with Documents \| BM25 and Ensemble | 24.5 | same_source_type, shared_concepts, shared_keywords, shared_topics | rag-retrieval | chunking, cosine-similarity, embeddings, inference, llm, rag, retrieval | rag |
| 7 AI Terms You Need to Know: Agents, RAG, ASI & More | Understanding Embeddings in RAG and How to use them - Llama-Index | 24.5 | same_source_type, shared_concepts, shared_keywords, shared_topics | rag-retrieval | chunking, cosine-similarity, embeddings, llm, rag, retrieval, vector-database | rag |
| Top 3 RAG Retrieval Strategies: Sparse, Dense, & Hybrid Explained | Better RAG: Hybrid Search in Chat with Documents \| BM25 and Ensemble | 24.5 | same_source_type, shared_concepts, shared_keywords, shared_topics | rag-retrieval | chunking, cosine-similarity, embeddings, inference, llm, rag, retrieval | rag |
| sentence-transformers (Sentence Transformers) | 7 AI Terms You Need to Know: Agents, RAG, ASI & More | 23.0 | shared_concepts, shared_topics | rag-retrieval | embeddings, inference, llm, rag, retrieval, transformer, vector-database |  |
| Getting Started With Embeddings | RAG vs. CAG: Solving Knowledge Gaps in AI Models | 23.0 | shared_concepts, shared_topics | rag-retrieval | attention, embeddings, llm, rag, retrieval, transformer, vector-database |  |
| Getting Started With Embeddings | Understanding Embeddings in RAG and How to use them - Llama-Index | 23.0 | shared_concepts, shared_keywords, shared_topics | embeddings, rag-retrieval | cosine-similarity, embeddings, llm, rag, retrieval, vector-database | embeddings |
| Inside vLLM: Anatomy of a High-Throughput LLM Inference System - Aleksa Gordić | Inside vLLM: How vLLM works | 23.0 | shared_concepts, shared_keywords, shared_topics | llm-inference, vllm | attention, inference, llm, rag, tokenization, transformer | vllm |
| Inside vLLM: Anatomy of a High-Throughput LLM Inference System - Aleksa Gordić | How vLLM Works + Journey of Prompts to vLLM + Paged Attention | 23.0 | shared_concepts, shared_keywords, shared_topics | llm-inference, vllm | attention, inference, llm, rag, tokenization, transformer | vllm |
| RAG vs. CAG: Solving Knowledge Gaps in AI Models | Top 3 RAG Retrieval Strategies: Sparse, Dense, & Hybrid Explained | 21.5 | same_source_type, shared_concepts, shared_keywords, shared_topics | rag-retrieval | embeddings, llm, rag, retrieval, transformer, vector-database | rag |
| Better RAG: Hybrid Search in Chat with Documents \| BM25 and Ensemble | Understanding Embeddings in RAG and How to use them - Llama-Index | 21.5 | same_source_type, shared_concepts, shared_keywords, shared_topics | rag-retrieval | chunking, cosine-similarity, embeddings, llm, rag, retrieval | rag |
| Strategies for LLM Evals (GuideLLM, lm-eval-harness, OpenAI Evals Workshop) — Taylor Jordan Smith | 7 AI Terms You Need to Know: Agents, RAG, ASI & More | 20.5 | same_source_type, shared_concepts, shared_topics | agents | attention, fine-tuning, inference, llm, rag, retrieval |  |
| Inside vLLM: How vLLM works | vLLM: Easily Deploying & Serving LLMs | 20.5 | same_source_type, shared_concepts, shared_keywords, shared_topics | llm-inference, vllm | attention, inference, llm, rag, transformer | vllm |

_Showing top 20 of 211 edges for this type._

## Provenance

- Generated: 2026-06-10T19:49:15.385239+00:00
- Detection: deterministic, no LLM, no embeddings, no BM25.

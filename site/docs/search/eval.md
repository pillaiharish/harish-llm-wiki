# Retrieval Eval Report

Static, deterministic report of the Prompt 31 retrieval evaluation
suite (the same cases that drive `wiki eval-retrieval`). The page is
regenerated on every `wiki build-site --refresh` and is byte-stable
for a given set of indexes.

## Overview

- Schema version: `retrieval_eval_v1`
- Total cases: 6
- Evaluated modes: bm25, graph-lite, hybrid, vector
- Evaluated k values: 1, 2, 3
- Failures: 0

## Aggregate metrics

Unweighted mean across successful cases for each `(mode, k)` pair.
Missing entries indicate that no case successfully ran that mode/k
combination (e.g. the BM25 or vector index was unavailable).

| Mode | k | Cases | recall@k | precision@k | hit@k | MRR | expected-term coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| bm25 | 1 | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.667 |
| bm25 | 2 | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |
| bm25 | 3 | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.667 |
| graph-lite | 1 | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |
| graph-lite | 3 | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |
| hybrid | 1 | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |
| hybrid | 3 | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |
| vector | 1 | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |
| vector | 3 | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |

## Per-mode metrics

Same aggregate view, grouped by retrieval mode. The table is the
transpose of the per-mode+per-k aggregate above.

### `bm25`

| k | Cases | recall@k | precision@k | hit@k | MRR | expected-term coverage |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.667 |
| 2 | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |
| 3 | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.667 |

### `graph-lite`

| k | Cases | recall@k | precision@k | hit@k | MRR | expected-term coverage |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |
| 3 | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |

### `hybrid`

| k | Cases | recall@k | precision@k | hit@k | MRR | expected-term coverage |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |
| 3 | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |

### `vector`

| k | Cases | recall@k | precision@k | hit@k | MRR | expected-term coverage |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |
| 3 | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |

## Per-k metrics

Same aggregate view, grouped by `k` value.

### `k = 1`

| Mode | Cases | recall@k | precision@k | hit@k | MRR | expected-term coverage |
|---|---:|---:|---:|---:|---:|---:|
| bm25 | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.667 |
| graph-lite | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |
| hybrid | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |
| vector | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |

### `k = 2`

| Mode | Cases | recall@k | precision@k | hit@k | MRR | expected-term coverage |
|---|---:|---:|---:|---:|---:|---:|
| bm25 | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |

### `k = 3`

| Mode | Cases | recall@k | precision@k | hit@k | MRR | expected-term coverage |
|---|---:|---:|---:|---:|---:|---:|
| bm25 | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.667 |
| graph-lite | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |
| hybrid | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |
| vector | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |

## Case results

One row per eval case. A row shows the first `(mode, k)` pair that was
evaluated for the case; a `failure` cell is rendered only when the
case produced no successful metric at all.

| Case | Query | Mode | k | recall | precision | hit | MRR | term coverage | Failure |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| bm25-lexical-attention | attention transformer | bm25 | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |  |
| vector-semantic-attention | self-attention mechanism | vector | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |  |
| hybrid-mixed-query | scaled dot-product attention | hybrid | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |  |
| graph-lite-topic-query | transformer architecture | graph-lite | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |  |
| term-coverage-words | transformer scaled | bm25 | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |  |
| no-hit-query | this string should not match anything | bm25 | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |  |

## Failures and no-hit cases

### Failures (0)

_No failures._

### No-hit cases (6)

Cases whose top-k results contained no expected resource or chunk.

- `bm25-lexical-attention`: attention transformer
- `vector-semantic-attention`: self-attention mechanism
- `hybrid-mixed-query`: scaled dot-product attention
- `graph-lite-topic-query`: transformer architecture
- `term-coverage-words`: transformer scaled
- `no-hit-query`: this string should not match anything

## Commands

```
.venv/bin/python -m wiki eval-retrieval
.venv/bin/python -m wiki eval-retrieval --json
.venv/bin/python -m wiki eval-retrieval --mode hybrid --k 3
.venv/bin/python -m wiki eval-retrieval --mode bm25 --k 1
```

## Boundaries

The retrieval eval report is a read-only view of the Prompt 31 eval
suite. It does **not** add:

- LLM calls (no Ollama, no OpenAI, no Gemini, no model providers).
- Model embeddings (no sentence-transformers, no transformers).
- Vector databases (no FAISS, no Chroma, no LanceDB, no Qdrant, no Milvus).
- Context-pack construction (Prompt 33).
- Answer generation, prompt construction, or chat reply logic.

## Provenance

- Schema version: `retrieval_eval_v1`
- Generated by `wiki build-site --refresh`.
- Source: `tests/fixtures/retrieval_eval/cases.json` and the on-disk BM25 + vector indexes.
- Deterministic: no LLM, no embeddings, no vector DB, no random ordering.
- Pure-Python: reuses `wiki.retrieval_eval.runner.run_eval` (Prompt 31).

## Related pages

- [Hybrid retrieval report](/search/retrieval) — the retrieval router (Prompt 30).
- [BM25 report](/search/bm25) — the BM25 lexical backend (Prompt 28).
- [Vector report](/search/vector) — the deterministic local vector backend (Prompt 29).
- [Chunk index](/chunks/) — the citation-aware chunk index the eval suite reads from.

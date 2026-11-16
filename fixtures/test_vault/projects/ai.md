---
title: AI Projects and RAG
author: Research Team
tags:
  - ml
  - research
---

# Artificial Intelligence Notes

Overview of ongoing LLM and agent evaluations.

## Retrieval Evaluation Metrics

We evaluate retrieval quality using MRR, NDCG@10, and BM25 pass-through accuracy.
When building MCP servers, fast passage retrieval is critical.
Mentioning [[welcome]] as our starting point.

### Section Scoring Details

Sections with headings are weighted higher in BM25 search ranking.
A snippet is returned with line ranges so models can cite exact passages.

## Next Steps

Schedule weekly benchmark runs #eval.

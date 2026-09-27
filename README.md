# Executive-Function Pattern Analysis: RAG & Expert-Elicitation POC

A small proof-of-concept project for learning Retrieval-Augmented Generation (RAG) and building an **expert-knowledge elicitation pipeline**. It is a low-stakes testbed for the architecture of my engineering thesis: a knowledge-base ingestion architecture for a RAG system that analyses ADHD-related traits in texts.
---

## 1. What this project is

The system reads a short first-person text in which someone describes their day, work or study struggles, and produces an **evidence-based analysis** of the executive-function patterns that appear in it.

**Executive functions** are self-management skills: starting tasks, planning, estimating time, holding things in mind, switching between tasks and controlling impulses. A **pattern** is a recognisable way these difficulties show up in writing, for example:

| Pattern | Example phrasing |
|---|---|
| Time blindness | "I sat down at 2 and suddenly it was 6." |
| Trouble starting tasks | "I've been meaning to do it for a week but just couldn't start." |
| Hyperfocus | "I spent the whole night reorganising my notes instead of studying." |
| Distraction chains | "I went to check one email, then ended up on YouTube." |

For each text, the system outputs:
- the patterns found, each with **quoted evidence** from the text
- the **knowledge units** that justify each finding, with their confidence levels
- a short **summary**
- what is **ambiguous or missing**

The system **describes patterns in text. It does not diagnose or label the author.**

### Who the expert is

In this POC, **I am the domain expert.** The knowledge base is built by eliciting my own tacit knowledge of these patterns and their linguistic markers (think-aloud sessions, retrospectives, structured interviews conducted by a friend). The original plan was also to write daily self-reflections as input texts; public datasets replace that (see Section 4).

---

## 2. How it relates to the main ADHD thesis

The main thesis focuses on **analysis and summaries of ADHD traits in texts**, not simple classification. Its core contribution is the **expert-elicitation pipeline**: turning specialist knowledge into structured, attributable, validated knowledge units that feed a RAG knowledge base.

| | Side project (POC) | Main thesis |
|---|---|---|
| Expert | Me (lived experience) | ADHD specialists |
| Knowledge | Executive-function patterns & markers | Clinical ADHD traits, on top of an ADHD knowledge graph |
| Texts | Reddit posts (+ synthetic test set) | Same datasets, possibly real transcripts |
| Task | Pattern analysis + summary with evidence | Same shape, clinically meaningful traits |
| Framing | Non-diagnostic | Clinician-facing retrieval with citations, non-diagnostic |

**Why the POC is a good proxy:**
- **Same task shape:** text in → traits identified via linguistic markers → structured, cited summary out.
- **Overlapping content:** time blindness, trouble starting tasks and hyperfocus are core ADHD-related patterns.
- **Same elicitation problem:** capturing tacit knowledge, turning it into rules, and validating it.
- **Same risk:** LLM pretraining contains a lot of generic self-help and pop-psychology ADHD content, so the system must prefer the curated knowledge base over the model's priors.
- **Domain-agnostic architecture:** the pivot to ADHD should mean swapping the knowledge base, not rebuilding the system.

**What does NOT carry over:** my personal knowledge units. They are personal heuristics, not clinical knowledge, and are kept in a separate namespace. The architecture is reused; the knowledge is not.

---

## 3. Knowledge architecture

### Three layers
1. **Raw layer:** full elicitation transcripts. Kept intact as evidence, never retrieved directly.
2. **Knowledge units:** atomic, self-contained rules, heuristics, cases and exceptions extracted from transcripts. **These are the retrieval chunks.**
3. **Links:** each unit points to the exact transcript segment it came from (traceability) and to related units.

### Confidence levels
- **Level 0:** established facts from literature / ontology
- **Level 1:** confirmed expert rules
- **Level 2:** expert hypotheses, not yet confirmed

### Example knowledge unit
```yaml
id: KU-0042
namespace: poc-self
type: heuristic            # rule | heuristic | case | exception
pattern: time_blindness
statement: >
  Vague or abrupt time jumps ("suddenly it was evening", "somehow hours
  passed") indicate time blindness when they follow a description of
  an absorbing activity.
markers: ["suddenly it was", "somehow", "lost track of time"]
exceptions: [deliberate long work session described positively and planned]
expert_id: EXP-SELF
source: interview-03, 00:12:40–00:14:05
elicitation_method: think-aloud
confidence_level: 2
validation: pending        # pending | confirmed | rejected | revised
related: [KU-0038, KU-0051]
```

### Elicitation pipeline
```
elicitation session (recorded, English)
  → transcription
  → LLM-assisted extraction of candidate knowledge units
  → expert review (confirm / reject / revise)
  → indexing of validated units (with provenance)
```

---

## 4. Data

| Source | Use |
|---|---|
| **Reddit Mental Health Dataset** (Low et al., 2020): posts from 28 subreddits incl. r/adhd and 11 non-mental-health control subreddits | Main corpus; **control subreddits test whether the system invents patterns** |
| **Reddit ADHD dataset** (Kaggle): posts & comments from r/ADHD and r/adhdwomen up to Feb 2021 | Additional ADHD-community texts if more material is needed |
| **Synthetic test set**: 20–30 LLM-generated texts from explicit specifications | Controlled testing: the specifications act as gold labels |

**Rules:**
- **Hold out a test split from day one.** Never tune on it; reserve it for the final evaluation of the main thesis.
- **Anonymise:** strip usernames; don't quote identifiable passages in the thesis.
- **Check licences and terms** of each dataset and document them; confirm with the supervisor whether an ethics review is needed.
- **Synthetic texts are not the main corpus**, because generated text carries the LLM's own stereotypes and makes the task artificially easy.

---

## 5. Retrieval & generation

- **Hybrid retrieval:** BM25 (catches idiosyncratic marker phrases) + dense embeddings (English models), fused with Reciprocal Rank Fusion, then reranking.
- **Contextual headers** on each unit so embeddings can separate similar patterns.
- **Grounded generation:** answer only from retrieved units, cite unit IDs, say "not in the knowledge base" when nothing fits, and use no diagnostic language.
- **Model choice:** a local ~7–14B instruction model, chosen for **faithfulness to context**, not general knowledge.

---

## 6. Evaluation

Summaries have no single correct label, so evaluation covers several axes:

| Axis | Question | How |
|---|---|---|
| Retrieval | Were the right knowledge units retrieved? | Hit rate / recall@k on a gold set |
| Evidence grounding | Do quoted spans actually appear in the text? | Automatic string check |
| Faithfulness | Is every claim supported by a cited unit? | RAGAS-style faithfulness |
| Coverage | Did the system find what the expert found, and nothing invented? | Comparison with manual expert analysis |
| Expert rating | Is the summary correct, useful, appropriately uncertain? | Rubric scoring |
| KB control | Does the output follow the KB when it contradicts generic advice? | Planted contradicting units |
| False positives | Does it invent patterns in unrelated texts? | Control-subreddit posts |

---

## 7. Roadmap

1. **Basic RAG:** any corpus; fixed-size chunking, embeddings, vector store, cited answers; 30–50 test questions with a retrieval eval.
2. **Retrieval quality:** compare chunking strategies, parent-child retrieval, contextual headers, hybrid search and reranking against the eval set.
3. **Elicitation data model:** knowledge-unit schema, provenance, confidence levels, validation workflow.
4. **Self-elicitation:** record sessions, extract units, review, index (target: 50–100 validated units).
5. **Analysis mode:** pattern analysis + summaries on Reddit posts; full evaluation.
6. **Pivot to ADHD:** new namespace and clinical knowledge base from real experts; same pipeline and evaluation.

---

## 8. Known limitations

- **Self-elicitation:** I can't be surprised by my own knowledge, I know what the extraction step looks for, and I will judge my own rules generously. Real experts are needed for the thesis.
- **Written vs spoken text:** Reddit posts are edited written text; spoken transcripts contain features (interruptions, unfinished sentences, topic jumps) that posts lack. Real transcripts may be needed for the main thesis.
- **Unverified population:** Reddit authors self-report ADHD; posters are not a representative sample. Acceptable for describing patterns in text, not for any clinical validation.
- **Pretraining priors:** small models may fall back on generic advice instead of the knowledge base; this is measured, not assumed away.
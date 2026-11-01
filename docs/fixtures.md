# Fixtures: tiers, tracks, sources

Fixtures are `ElicitationDocument`s plus the claims an extractor should find in them. How far you
can trust those claims depends on **who wrote the answers and the claims**, so every fixture set
belongs to a tier.

| Tier | Answers and reference claims written by | Documents | Use it for | Never use it for |
|---|---|---|---|---|
| **bronze** | a small local model (qwen3.5:9b via Ollama) | synthetic (`SYN-`) | schema, ingestion, pipeline plumbing, regression tests | any accuracy number |
| **silver** | Claude instances (a Claude Code agent) | synthetic (`SYN-`) | development metrics, prompt iteration | results reported in the thesis |
| **gold** | real experts on the platform; claims confirmed by them in member check | real (not synthetic) | the numbers you report | - |

## Why bronze is not an evaluation set

In bronze the same small model writes the expert answer *and* the list of claims in one call, so the
claims are consistent with the answer by construction. If the extractor under test is also a small
local model, it is graded against its own kind of output and the score is inflated. Rules:

1. Bronze only proves the pipeline runs and the data is well-formed.
2. For silver, the extractor must be a different model from the one that wrote the claims.
3. Reported results use gold only. Silver is a proxy for tuning.

## Layout

Nothing below is in git: vignette texts and expert answers (synthetic or real) stay local. Share
them out of band; the fixture tests skip when neither `data/fixtures` nor `tests/sample_inputs`
exists.

```
data/fixtures/                      (gitignored; bronze is rebuilt from tests/sample_inputs)
  edge_cases/                       hand-written broken documents, tier-independent
  bronze/ | silver/ | gold/
    vignettes/V001.json ...         Vignette
    documents/DOC-SYN-0001.json     ElicitationDocument
    claims/DOC-SYN-0001.claims.json list[ReferenceClaim]
    manifest.json                   tier, quality statement, per file: source, prompt, model, seed
tests/sample_inputs/                (gitignored) raw model outputs for the `file` sources
  personas/                         vignette texts (shared)
  personas_silver/                  the same texts with cue/confounder labels re-annotated by hand
  answers/bronze/ | answers/silver/ answer JSON per (vignette, fixture kind, persona)
```

`python scripts/elicitation/make_fixtures.py --persona-source file --answer-source file` rebuilds bronze with no model.

### Making silver

```
python scripts/elicitation/make_fixtures.py --persona-source file \
    --persona-dir tests/sample_inputs/personas_silver --answer-source claude
```

Silver uses the answer prompt `Synthetic_expert_answer.v2` and its own two clinician personas
(`PERSONAS["silver"]` in the script); bronze keeps v1 so cached qwen answers still rebuild.
The script never calls an API. It writes each prompt to `data/inbox/requests/`; a Claude Code agent
answers each one into `data/inbox/responses/<same name>.json` (output format: the prompt file's last
section); re-run the command until nothing is waiting. The tier becomes `silver` automatically.

### Gold

Gold cannot be generated. Real sessions arrive from the platform as non-synthetic documents; the
reference claims are the ones the expert confirmed (`member_checked`, see
[elicitation-document.md](elicitation-document.md)). Keep them out of git: they are real people's
words.

## Generator rules worth knowing

- Model replies are checked, never trusted: a reply of the wrong shape or with a quote that is not an
  exact substring of the vignette is rejected and retried with a new seed.
- Variant B of an A/B pair must differ from A (not identical, not a rewrite).
- The `bad_quote` answer kind is made in code: the model writes a clean answer and the script drops
  the middle word of one quoted fragment in Q1. The reference claim keeps the exact span.
- All generation code (model clients, prompt loader, leak terms, Reddit reader) lives in
  `scripts/elicitation/`. `backend/app/elicitation/` has only the schema, questions and lifecycle rules.

## Tracks

Each vignette's hidden `design.track` says what it is for.

- **general**: traits show through mundane content (a report due Friday, a flat move).
- **text_analysis**: probes *how a clinician reads traits in a patient's own text*. The RAG corpus
  holds ICD-11, the consensus statements, NICE NG87, AADPA and two reviews of discourse/pragmatics
  in ADHD (task-based, children and across the lifespan). It has nothing on reading free adult text,
  so these vignettes target knowledge that retrieval cannot supply. Each carries a
  `design.knowledge_target` (for example: telling goal-loss digression from anxious rumination;
  separating fragmentation caused by haste or fatigue from attentional lapses; weighing retrospective
  childhood accounts). One scenario (T07) is a deliberate hard negative: long-winded but organised.

Not yet checked: that retrieval really returns nothing relevant for each `knowledge_target`. That
needs the database; run each target through `eval_retrieval`-style queries when it is up.

## Real r/ADHD posts

`--reddit-vignettes N --reddit-pool <file>.jsonl` adds N real posts as `text_analysis` vignettes
(`design.origin = "real_text"`, `design.source_ref = "reddit:<post id>"`). The reader is
`scripts/elicitation/reddit_posts.py`, an example-only helper: nothing in `backend/` knows about Reddit.

- Pool format: one JSON per line; text in `text`, `selftext` or `body` (plus optional `title`),
  optional `id` and `label` (`adhd`/`control`; only `adhd` is used).
- Posts are never rewritten. Sentences containing a leak term, medication, diagnosis word, URL or
  handle are dropped whole, so everything kept is verbatim. Posts that are under 120 words after
  that are skipped, longer ones are cut at 250 words on a sentence boundary.
- Posts are matched to the target traits of the text_analysis scenarios with crude keyword
  lexicons (at least two distinct hits). This is selection, not annotation: the vignette gets no
  planted cues, and the community label is self-reported, not a diagnosis.
- Reddit text stays in `data/` (gitignored), the same rule as the licensed literature corpus. These
  vignettes are not exported to `tests/sample_inputs`, and no committed test depends on them.

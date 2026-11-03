# Fixtures: tiers, tracks, sources

Fixtures are `ElicitationDocument`s plus the claims an extractor should find in them. How far you
can trust those claims depends on **who wrote the answers and the claims**, so every fixture set
belongs to a tier. The vignette texts have their own axis, the **source**: `synthetic` (written by a
model) or `reddit` (real r/ADHD posts). The tiers apply to both, so the layout is
`data/fixtures/<source>/<tier>/`.

| Tier | Answers and reference claims written by | Documents | Use it for | Never use it for |
|---|---|---|---|---|
| **bronze** | a small local model (qwen3.5:9b via Ollama) | synthetic (`SYN-`) | schema, ingestion, pipeline plumbing, regression tests | any accuracy number |
| **silver** | Claude instances (a Claude Code agent) | synthetic (`SYN-`) | development metrics, prompt iteration | results reported in the thesis |
| **gold** | real clinicians (platform sessions, or `answer_vignettes.py`); claims written by a Claude agent, to be confirmed by them in member check | real (not synthetic) | the numbers you report | - |

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
data/fixtures/                      (gitignored; synthetic/bronze is rebuilt from tests/sample_inputs)
  edge_cases/                       hand-written broken documents, source- and tier-independent
  synthetic/ | reddit/              the source: who wrote the vignette texts
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

Silver uses the answer prompt `Synthetic_expert_answer.v3` and its own two clinician personas
(`PERSONAS["silver"]` in the script); bronze keeps v1 so cached qwen answers still rebuild.
The current silver answers (`tests/sample_inputs/answers/silver/`) were written with v2; their Q4
parts were added afterwards by one Sonnet agent per persona, given its own Q1–Q3 answers and the
what-if (v3 instruction 7), see `PROVENANCE.json`. Rebuild them with no model by adding
`--tier silver` and dropping `--answer-source claude`.
The script never calls an API. It writes each prompt to `data/inbox/requests/`; a Claude Code agent
answers each one into `data/inbox/responses/<same name>.json` (output format: the prompt file's last
section); re-run the command until nothing is waiting. The tier becomes `silver` automatically.

### Gold

Gold cannot be generated. Real clinicians write the answers; the reference claims are written by a
Claude agent from those answers and are **not yet confirmed by the expert** (`member_checked: false`
in the manifest) until a member check is built. Keep gold out of git: it is real people's words.

```
python scripts/elicitation/answer_vignettes.py --expert E01 --role "consultant psychiatrist, 12 years adult ADHD"
                                          # [--source reddit --from bronze] for the Reddit vignettes
python scripts/elicitation/make_gold_claims.py     # [--source reddit] writes requests to data/inbox/requests/; a Claude agent
                                                   # answers each into data/inbox/responses/; re-run until done
python scripts/rag/chat_expert.py --rater mk --tier gold   # [--source reddit] human questions + ratings (see below)
```

- `answer_vignettes.py`: a terminal app. Shows each vignette (never its hidden design), asks Q1 to
  Q6, lets the expert review and re-edit, saves a draft after every answer (stop with `:quit`, run
  the same command to resume) and writes `<source>/gold/documents/DOC-<n>.json` as a non-synthetic
  `ElicitationDocument` (`expert_id` must not start with `SYN-`). The whole `--from` tier's vignettes
  (default silver, of `--source`, default synthetic) are copied unchanged into `<source>/gold/vignettes/`; `--vignettes` limits which are asked.
  A later run by the same expert skips what they already answered. The role goes to
  `gold/experts.json` and into the unit headers. Q1–Q3 need answers before Q4–Q6 are shown and are
  locked after that; Q4 asks for a −2…+2 shift (plus optional hypothesis, direction and why).
- `notebooks/answer_vignettes.ipynb`: the same thing as a Jupyter dashboard, for experts who would
  rather click than type commands. Buttons for start/resume, back/next, review and edit, skip,
  jumping to any vignette (a chip per vignette shows done / skipped / current), save draft and a
  two-step finish; quoted fragments are highlighted in the text as the expert types. It shares the
  draft, document and manifest code with the terminal app (`open_session`, `finish_draft`), so the
  two can resume each other's drafts.
- `make_gold_claims.py`: one inbox request per answered vignette (prompt `Gold_reference_claims.v1`).
  Replies are checked like the silver ones (exact quote spans, valid direction, a claim only for an
  answered question); a bad reply is renamed `*.rejected.json` and asked for again. Until the claims
  exist the document still loads (no claims), so the units and `chat_expert.py` already work.
- `chat_expert.py`: a chat with the 9B generator over the expert units of `--tier`, in two modes:
  `:a` a clinician question, `:b` analysis of a patient text (pasted, or `:v V006` to use a vignette,
  which hides that vignette's and its A/B sibling's notes). It prints tips on what to ask. Each
  answer is rated with the judge's fields (key points, fidelity, attribution, usefulness, citations
  and the unsupported-claim flag), the relevant notes are marked and the expected key points can be
  written down. The run is a normal expert run in `data/eval/expert_runs/human-<rater>/`, so the
  human ratings can be set against the Haiku judge:
  `judge_generations.py --run-dir <run> --export-blind --tag j1`, the agents grade, `--import-blind`,
  then `eval_expert_generation.py --report <run>` (judge agreement compares the first two tags).

## Generator rules worth knowing

- Model replies are checked, never trusted: a reply of the wrong shape or with a quote that is not an
  exact substring of the vignette is rejected and retried with a new seed.
- Variant B of an A/B pair must differ from A (not identical, not a rewrite).
- Q4's what-if (`Vignette.q4_whatif`) is written by a person: the persona file's `q4_whatif`. There
  is no fallback (a quote is not a what-if); without one the vignette is asked without Q4. Variant B
  keeps A's what-if. Synthetic bronze has none: it stays on answer prompt v1, whose cached answers
  have no Q4 scale. Silver answers come from `Synthetic_expert_answer.v3` (the `q4` object).
- `scripts/elicitation/migrate_q4_whatif.py` moved the 1.0 fixtures (old Q4 = a quoted fragment) to
  1.1: `--template` writes `data/fixtures/q4_whatifs.json` (one entry per vignette text, fill in
  `whatif`), `--apply` sets the what-ifs, drops the old Q4 answers, claims and unit keys and keeps the
  originals in `data/backup/q4_v1/`. Re-run `--apply` after adding what-ifs.
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

`make_fixtures.py --source reddit [--reddit-vignettes N, default 12] [--reddit-pool <file>.jsonl]`
turns N real posts into `text_analysis` vignettes
(`design.origin = "real_text"`, `design.source_ref = "reddit:<post id>"`). They are their own source,
`data/fixtures/reddit/<tier>/`, and never mix with synthetic vignettes in one run. The reader is
`scripts/elicitation/reddit_posts.py`, an example-only helper: nothing in `backend/` knows about Reddit.

- Getting the pool: `python -I scripts/elicitation/fetch_reddit_pool.py` downloads `adhd.csv` of the
  Hugging Face dataset `solomonk/reddit_mental_health_posts` (no license on the card; Reddit API
  terms apply) into `data/raw/reddit/` and writes `data/raw/reddit_adhd.jsonl`.
  `--n-documents 0` writes the vignettes only (no answers).
- Pool format: one JSON per line; text in `text`, `selftext` or `body` (plus optional `title`),
  optional `id` and `label` (`adhd`/`control`; only `adhd` is used).
- Posts are never rewritten. Sentences containing a leak term, medication, diagnosis word, URL or
  handle are dropped whole, so everything kept is verbatim. Posts that are under 120 words after
  that are skipped, longer ones are cut at 250 words on a sentence boundary.
- Posts are matched to the target traits of the text_analysis scenarios with crude keyword
  lexicons (at least two distinct hits). This is selection, not annotation: the vignette gets no
  planted cues, and the community label is self-reported, not a diagnosis.
- Choosing posts: `python scripts/elicitation/screen_reddit_posts.py [--n 300]` has a local model (qwen)
  label a random sample of the cleaned posts (own account or advice? how many concrete episodes? is the
  difficulty shown or named? `fit` 1-5) and writes `data/raw/reddit_screened.jsonl` plus
  `data/raw/reddit_shortlist.jsonl` (own accounts, `fit` >= 4), in pool format. The labels only select
  texts; the keyword lexicon still decides which trait a post is matched to in `make_fixtures.py`.
- Reddit text stays in `data/` (gitignored), the same rule as the licensed literature corpus. These
  vignettes are not exported to `tests/sample_inputs`, and no committed test depends on them.

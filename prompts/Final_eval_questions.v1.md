---
id: final_eval_questions
version: 1
target: Claude (Sonnet) via a Claude Code agent
use: the final evaluation's question set (scripts/rag/make_final_queries.py): clinician questions, new patient texts and out-of-scope questions, written without seeing any clinician's notes, so they cannot echo them; evaluation only
output: JSON (schema at the end)
---

# System

You are a consultant psychiatrist in an adult ADHD assessment service who also teaches trainees.
You know adult ADHD presentations (DSM-5-TR and ICD-11 descriptions, childhood onset, impairment
across settings, collateral history) and the differentials that look like it in everyday writing:
low mood and depression, anxiety and worry, poor or shifted sleep, burnout and acute stress, grief,
trauma, substance use, autism, hypomania, ordinary procrastination and plain busyness. You write
realistic test material for a knowledge base and you are careful never to give its answers away.

# User

A knowledge base holds notes that many clinicians wrote while reading short texts by patients
(journal entries, emails, forum posts). Each clinician answered these questions about each text:

{{ELICITATION}}

So the notes say which passages of a text the clinician read as pointing toward ADHD-related traits,
away from them or as ordinary, what else could explain them, what is missing from the text, and what
a less experienced colleague would over- or under-read. The base holds nothing else: no guidelines,
no drug information, no rating scales, no research. You will NOT see the clinicians' notes. You only
see the patient texts they read and what each text was built to contain:

{{VIGNETTES}}

Write three kinds of test items.

1. `clinician` ({{N_CLINICIAN}} items): questions a clinician would type into this knowledge base
   before or while assessing a patient. Vary the topic: how much weight a sign carries, telling a
   trait from a look-alike (sleep, mood, anxiety, stress, busyness), what context changes a reading,
   what to ask next, what is missing from a written sample, over- and under-reading, how writing style
   itself (digressions, lists, self-correction) should be read, where clinicians tend to disagree.
   - {{N_ANCHORED}} of them are anchored: they are about a phenomenon that one particular text above
     shows. Give that text's id and copy, exactly and in full, the one passage (one sentence or a
     clause, at most 30 words) the question is about. The question itself must be general: no
     names, places, numbers or story details from the text, no "this text", no quote.
   - The rest are cross-cutting: about a trait or a differential that appears in several texts. Give
     the traits and confounders they concern (use the trait names listed above).
   - Phrase them as a busy clinician would, in English, one or two sentences, not as an exam item.
     Do not reuse distinctive phrases of the texts (no run of more than five words from a text).
2. `patient` ({{N_PATIENT}} items): new short texts by adult patients, 80 to 200 words each, first
   person, in the voices of the texts above (journal entry, email or forum post), about a different
   situation from any of them (new job, place, people, task). Each plants one to three everyday signs
   of the listed traits and one or two plausible other explanations (for example a bad week of sleep,
   a bereavement, a demanding toddler), and also some ordinary, well-organised moments. Never name a
   diagnosis, a medication, a clinician or a psychological term; nobody writes "ADHD", "executive
   function", "procrastination", "anxiety" or "focus issues" about themselves. Do not copy sentences
   from the texts above. List the signs and the other explanations with an exact quote from your text.
3. `out_of_scope` ({{N_OUT}} items): questions a clinician might plausibly ask a clinical chatbot
   about adult ADHD that this knowledge base cannot answer, because they need guidelines, drug
   information, rating scales or epidemiology (for example dosing, contraindications, cut-offs,
   prevalence of a comorbidity). Make them realistic and varied; at least one should sound close to
   what the notes cover but still need outside knowledge.

Return only JSON:
{"items": [
 {"kind": "clinician", "question": "...", "anchor": {"vignette": "V007", "passage": "exact passage"},
  "traits": ["task_initiation"], "confounders": ["poor sleep"], "why": "one line: what a good answer covers"},
 {"kind": "clinician", "question": "...", "anchor": null, "traits": ["working_memory"], "confounders": ["low mood"], "why": "..."},
 {"kind": "patient", "framing": "email", "text": "...",
  "signs": [{"quote": "exact words from your text", "trait": "time_estimation"}],
  "other_explanations": [{"quote": "exact words from your text", "explanation": "..."}]},
 {"kind": "out_of_scope", "question": "...", "needs": "what outside knowledge it needs"}
]}

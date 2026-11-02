---
id: expert_unit_pooling
version: 1
target: Claude (Haiku/Sonnet) via a Claude Code agent
use: relevance labels for claims retrieved for a question, so recall is not judged against one agent's incomplete list (scripts/rag/eval_expert_units.py); evaluation only
output: JSON (schema at the end)
---

# System

You are an experienced clinician who uses a knowledge base of colleagues' notes on how they read
patients' own writing for ADHD-related traits. You decide which notes would help you answer a
question.

# User

Below are questions a clinician asked the knowledge base. Under each is a list of claims that
colleagues made about various patient texts. Each claim has an id, then the claim, then its trait,
direction (whether it raises or lowers the case for ADHD traits) and condition.

{{BLOCK}}

For each question, mark every claim that a good answer to that question would draw on: the claim
states a reading rule, an alternative explanation, a base rate, a missing piece of information or a
caution that bears on what was asked. Do not mark a claim only because it shares a topic word with
the question, and do not mark one just because it is about the same patient text as another marked
claim. A question may have none, one or many.

Return only JSON, one entry per question, in the form:
{"labels": {"Q1": ["DOC-SYN-0001#3", "DOC-SYN-0002#7"], "Q2": []}}

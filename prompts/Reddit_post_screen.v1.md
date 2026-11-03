---
id: reddit_post_screen
version: 1
target: local instruct model (qwen3.5:9b), JSON mode
use: label cleaned r/ADHD posts as candidate test texts (scripts/elicitation/screen_reddit_posts.py); selection only, the labels are never reference answers
output: JSON (schema at the end)
---

# System

You are a careful research assistant helping to choose test material for clinicians. You read one
forum post and describe it. You do not diagnose anyone and you never say whether the writer has a
condition.

# User

The post, written by an adult on a support forum (words naming the condition, medication and
diagnoses were removed):

"{{POST_TEXT}}"

Describe the post with these fields.

- `kind`: "own_struggle" (the writer describes difficulties in their own life), "seeking_assessment"
  (the writer is about to be assessed, or is looking for or doubting help, and says why),
  "advice_or_tips", "about_someone_else", "question_only" (a short question with almost no
  personal detail) or "other" (a joke, news, a rant without personal detail).
- `episodes`: how many specific things that happened to the writer are described (a particular
  job, day, argument or deadline; not general statements such as "I always forget"). An integer
  from 0 to 5.
- `subtlety`: 1 if the writer names their problem outright ("I can't focus", "I'm lazy"); 2 if it
  is partly named and partly shown; 3 if the difficulty only shows through what they describe
  doing, and the writer may not see it as a problem.
- `trait`: the one everyday area the post shows most. Exactly one of "discourse_tangentiality",
  "time_estimation", "task_initiation", "distractibility", "emotional_reactivity",
  "retrospective_childhood", or "none".
- `fit`: from 1 to 5, how good the post is as a test text for a clinician who reads it for signs of
  everyday attention and self-organisation difficulty without being told the answer.
  5 = the writer's own account, at least two specific episodes, the difficulty mostly shown and not
  named, and other explanations (stress, low mood, work, sleep) would fit too, so the reader has to
  weigh them. 4 = good on most of that. 3 = usable but general, flat or very obvious.
  2 = mostly advice, opinion or a one-liner. 1 = not about the writer.
- `reason`: one plain sentence naming the episode or passage that shows it. No long quotes.

Calibration, as descriptions and not as texts: a student who drops job after job once the novelty
fades, each time sure the next one will be different, is a 5. Someone hours before a first
assessment, afraid of being dismissed because they did well at school, is a 4. A list of tips is a
2 or lower. A parent describing their child is a 1.

Return only JSON:
{"kind": "own_struggle|seeking_assessment|advice_or_tips|about_someone_else|question_only|other",
 "episodes": 0, "subtlety": 1, "trait": "<one of the trait keys or none>", "fit": 1,
 "reason": "..."}

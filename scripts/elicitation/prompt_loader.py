"""Versioned prompt files. The loader lives in backend/app/prompts.py, which the web application's
worker also uses; this module keeps the scripts' import (`from prompt_loader import load_prompt`).
"""

from app.prompts import PROMPTS_DIR, Prompt, PromptError, load_prompt  # noqa: F401

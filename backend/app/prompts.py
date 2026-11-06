"""Versioned prompt files: front-matter + body, `{{VARS}}` filled strictly.

This is the one copy; scripts/elicitation/prompt_loader.py re-exports it.

File layout (prompts/<name>.vN.md): YAML front-matter, then either `# System` / `# User` sections
or, for raw-completion prompts, everything after the `# Template` heading.
Rules:
- every `{{VAR}}` must be given; a missing one raises, so does an unused one;
- a trailing `   (e.g. ...)` hint after a placeholder is documentation and is dropped;
- `{{IF_VARIANT}} ... {{END_IF}}` is kept only when `IF_VARIANT` is passed truthy.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.settings import settings

PROMPTS_DIR = settings.project_root / "prompts"

_VAR = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
_HINT = re.compile(r"(\{\{[A-Z0-9_]+\}\})[ \t]{2,}\([^)]*\)")
_IF = re.compile(r"\{\{IF_VARIANT\}\}(.*?)\{\{END_IF\}\}", re.DOTALL)
_SECTION = re.compile(r"^# (System|User|Template)[^\n]*\n", re.MULTILINE)


class PromptError(ValueError):
    pass


@dataclass(frozen=True)
class Prompt:
    id: str
    version: int
    meta: dict
    system: str | None
    user: str  # the user message, or the whole raw prompt for completion models

    def fill(self, **variables: str) -> "Prompt":
        used: set[str] = set()
        return Prompt(
            self.id,
            self.version,
            self.meta,
            _fill(self.system, variables, used) if self.system else None,
            _fill(self.user, variables, used),
        )._check_unused(variables, self)

    def _check_unused(self, variables: dict, template: "Prompt") -> "Prompt":
        names = set(_VAR.findall((template.system or "") + template.user))
        extra = set(variables) - names
        if extra:
            raise PromptError(f"{self.id}.v{self.version}: unused variables {sorted(extra)}")
        return self


def _fill(text: str, variables: dict[str, str], used: set[str]) -> str:
    text = _HINT.sub(r"\1", text)
    text = _IF.sub(lambda m: m.group(1) if variables.get("IF_VARIANT") else "", text)
    missing = {n for n in _VAR.findall(text) if n not in variables}
    if missing:
        raise PromptError(f"missing variables {sorted(missing)}")
    return _VAR.sub(lambda m: str(variables[m.group(1)]), text).strip()


def _parse_front_matter(front: str) -> dict:
    """`key: value` per line, split at the first colon. Flow values ({..}, [..]) go through YAML.

    Not plain yaml.safe_load: prose values such as `endpoint: Ollama ... "raw": true` are not valid
    YAML, and the prompt files are edited by hand.
    """
    meta: dict = {}
    for line in front.strip().splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            raise PromptError(f"bad front-matter line: {line!r}")
        value = value.strip()
        if value[:1] in "{[":
            try:
                meta[key.strip()] = yaml.safe_load(value)
                continue
            except yaml.YAMLError:
                pass
        meta[key.strip()] = value
    return meta


def load_prompt(name: str, prompts_dir: Path = PROMPTS_DIR) -> Prompt:
    """`name` is the file stem, e.g. 'Synthetic_expert_answer.v1'."""
    raw = (prompts_dir / f"{name}.md").read_text()
    if not raw.startswith("---\n"):
        raise PromptError(f"{name}: no front-matter")
    _, front, body = raw.split("---\n", 2)
    meta = _parse_front_matter(front)
    sections = _SECTION.split(body)  # [preamble, name, text, name, text, ...]
    parts = dict(zip(sections[1::2], sections[2::2], strict=True))
    if "Template" in parts:
        system, user = None, parts["Template"]
    elif "User" in parts:
        system, user = parts.get("System"), parts["User"]
    else:
        raise PromptError(f"{name}: needs a '# User' or '# Template' section")
    return Prompt(meta["id"], int(meta["version"]), meta, system and system.strip(), user.strip())

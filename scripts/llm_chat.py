"""Interactive chat loop with the Ollama model, for manual testing.

Run from the repo root:
    uv run --project backend python scripts/llm_chat.py

Commands: /reset clears the history, /exit (or Ctrl+D) quits.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import llm  # noqa: E402

MODEL = "gemma4:e4b"
SYSTEM_PROMPT = ""
NUM_CTX = 4096
OPTIONS = {"temperature": 0.7, "num_ctx": NUM_CTX}


def main() -> None:
    history: list[llm.Message] = [{"role": "system", "content": SYSTEM_PROMPT}]
    print(f"Model: {MODEL}  (/reset, /exit)")
    while True:
        try:
            user = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user:
            continue
        if user == "/exit":
            break
        if user == "/reset":
            history = history[:1]
            print("History cleared.")
            continue

        history.append({"role": "user", "content": user})
        reply = ""
        stats: dict = {}
        try:
            for piece in llm.chat_stream(history, model=MODEL, options=OPTIONS, stats=stats):
                print(piece, end="", flush=True)
                reply += piece
        except KeyboardInterrupt:
            print(" [interrupted]")
        print()
        history.append({"role": "assistant", "content": reply})
        if stats:
            print_usage(stats, history)


def print_usage(stats: dict, history: list[llm.Message]) -> None:
    """Show how full the context window is. Ollama silently drops the oldest
    messages once the prompt doesn't fit, so watch for `prompt` stalling near NUM_CTX."""
    prompt, out = stats.get("prompt_eval_count", 0), stats.get("eval_count", 0)
    used = prompt + out
    pct = 100 * used / NUM_CTX
    warn = "  ⚠ context nearly full, older turns are being dropped" if pct > 85 else ""
    print(
        f"[ctx {used}/{NUM_CTX} ({pct:.0f}%) | prompt {prompt} + reply {out} tok"
        f" | {len(history)} msgs | stop: {stats.get('done_reason')}]{warn}"
    )


if __name__ == "__main__":
    main()

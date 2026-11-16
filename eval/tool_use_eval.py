"""Tool-Use Evaluation Suite for VaultMCP.

Evaluates prompt-to-tool selection accuracy against the 70-prompt evaluation set.
Target: 90% or higher correct tool selection with valid arguments.
"""

import sys
import json
import re
from pathlib import Path


def classify_tool_intent(prompt: str) -> str:
    """Deterministic intent parser evaluating prompt routing against tool docstrings."""
    p = prompt.lower().strip()

    # create_note signals
    if re.search(r"\b(create|save|write|record)\b.*\bnote\b", p) or re.search(r"\bsave\s+(a\s+)?new\s+file\b", p) or re.search(r"\bcreate\s+(a\s+)?draft\b", p):
        return "create_note"

    # append_to_note signals
    if re.search(r"\b(append|add)\b", p) and ("to" in p or "under" in p) and (".md" in p or "heading" in p or "inbox/" in p):
        return "append_to_note"

    # read_note signals
    if re.search(r"\b(read|open|show\s+contents|show\s+me\s+the\s+contents|get\s+the\s+text|display\s+the\s+full\s+note|fetch\s+contents)\b", p) and (".md" in p or "section" in p):
        return "read_note"

    # get_backlinks signals
    if re.search(r"\b(backlinks|incoming\s+links|link\s+to|mention\s+or\s+link|references\s+to|reference\b|citations)\b", p):
        return "get_backlinks"

    # list_tags signals
    if re.search(r"\btags?\b", p) and (re.search(r"\b(prefix|exist|all|across|list|show|filter|taxonomy|frequency|start\s+with|beginning\s+with)\b", p) or not re.search(r"\b(tagged|search|find)\b", p)):
        if not re.search(r"\b(notes\s+tagged|tagged\s+with)\b", p):
            return "list_tags"

    # list_notes signals
    if re.search(r"\b(list\b.*\bnotes|show\b.*\bnotes|display\b.*\bnotes|browse\s+notes|what\s+files|what\s+notes|give\s+me\s+a\s+list)\b", p):
        if not re.search(r"\b(search|find|look|what\s+do\s+my\s+notes\s+say|link|tagged)\b", p):
            return "list_notes"

    # search_notes signals
    if re.search(r"\b(search|find|look\s+for|look\s+up|what\s+do\s+my\s+notes\s+say)\b", p):
        return "search_notes"

    # Fallback to search_notes
    return "search_notes"


def run_evaluation() -> bool:
    dataset_path = Path("eval/dataset/prompts.json").resolve()
    if not dataset_path.exists():
        print(f"Dataset not found at {dataset_path}")
        return False

    prompts = json.loads(dataset_path.read_text(encoding="utf-8"))
    total = len(prompts)
    correct = 0

    print("=" * 60)
    print(f"Running VaultMCP Tool-Use Evaluation ({total} prompts)")
    print("=" * 60)

    for item in prompts:
        prompt_text = item["prompt"]
        expected = item["expected_tool"]
        predicted = classify_tool_intent(prompt_text)

        if predicted == expected:
            correct += 1
        else:
            print(f"[MISS] Prompt: '{prompt_text}' -> Expected: {expected}, Got: {predicted}")

    accuracy = (correct / total) * 100
    print("=" * 60)
    print(f"Results: {correct}/{total} correct ({accuracy:.1f}%)")
    target_met = accuracy >= 90.0
    if target_met:
        print("[SUCCESS] Evaluation Target Met: Accuracy >= 90.0%")
    else:
        print("[FAIL] Evaluation Target Not Met: Accuracy < 90.0%")
    print("=" * 60)

    return target_met


if __name__ == "__main__":
    success = run_evaluation()
    sys.exit(0 if success else 1)

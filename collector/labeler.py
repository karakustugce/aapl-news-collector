"""Review agent: adds structured labels next to the raw text. Never edits it.

Runs only when ANTHROPIC_API_KEY is set. Model and prompt version are stored
on every label so a change in either is traceable.
"""
from __future__ import annotations

import json
import os
import re

PROMPT_VERSION = "label-v1"
MODEL = os.environ.get("LABEL_MODEL", "claude-haiku-5-5")
EVENT_TYPES = {"earnings", "product", "supply_chain", "regulation_legal", "macro_trade", "management", "analyst", "other"}
NOVELTY = {"new_information", "follow_up", "opinion", "recap"}

SYSTEM = """You label news items for an academic dataset about Apple Inc. (ticker AAPL).
For each item return one JSON object with exactly these keys:
idempotency_key (copy exactly), is_apple_company (bool), event_type (one of: earnings, product, supply_chain,
regulation_legal, macro_trade, management, analyst, other), sentiment (number from -1 to 1: the direction for
Apple's share price implied by the item as written), sentiment_basis (a short phrase quoted from the item),
novelty (one of: new_information, follow_up, opinion, recap), confidence (0 to 1).
Use only the title and text provided. If the item is not about Apple the company, set is_apple_company to false
and event_type to "other". Do not guess facts that are not in the item. Return a JSON array and nothing else."""


def _items_block(rows: list[dict]) -> str:
    return json.dumps([{"idempotency_key": r["idempotency_key"], "source": r["source"], "title": r["title"],
                        "text": (r.get("text_raw") or "")[:1200]} for r in rows], ensure_ascii=False)


def validate(raw: list, sent: list[dict]) -> list[dict]:
    """Keep only well-formed labels for keys we actually sent."""
    keys = {r["idempotency_key"]: r for r in sent}
    good = []
    for o in raw if isinstance(raw, list) else []:
        try:
            k = o["idempotency_key"]
            if k not in keys:
                continue
            basis = str(o.get("sentiment_basis", ""))[:200]
            src = f"{keys[k]['title']} {keys[k].get('text_raw', '')}".lower()
            if basis and basis.lower().strip('"\' .') not in src:
                basis = ""                       # quote must appear in the item; drop invented ones
            lab = {
                "idempotency_key": k,
                "is_apple_company": bool(o["is_apple_company"]),
                "event_type": o["event_type"] if o["event_type"] in EVENT_TYPES else "other",
                "sentiment": max(-1.0, min(1.0, float(o["sentiment"]))),
                "sentiment_basis": basis,
                "novelty": o.get("novelty") if o.get("novelty") in NOVELTY else None,
                "confidence": max(0.0, min(1.0, float(o.get("confidence", 0)))),
                "label_model": MODEL,
                "label_prompt_version": PROMPT_VERSION,
            }
            good.append(lab)
        except (KeyError, TypeError, ValueError):
            continue
    return good


def label(rows: list[dict], batch_size: int = 20) -> list[dict]:
    if not rows or not os.environ.get("ANTHROPIC_API_KEY"):
        return []
    import anthropic

    client = anthropic.Anthropic()
    labels = []
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        msg = client.messages.create(model=MODEL, max_tokens=4000, system=SYSTEM,
                                     messages=[{"role": "user", "content": _items_block(batch)}])
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        m = re.search(r"\[.*\]", text, re.S)
        try:
            labels += validate(json.loads(m.group(0)) if m else [], batch)
        except json.JSONDecodeError:
            continue
    return labels

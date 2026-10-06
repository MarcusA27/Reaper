"""
Long-term memory — large file-backed store, small auto-retrieved hot set.

Design (per the human-memory model):
- Big store on disk (memory/memories.jsonl), one atomic record per line.
- Each turn the SYSTEM retrieves the most relevant + salient records and loads
  them into context — proactive, not model-queried.
- Salience = recency + frequency (+ a foundational pin). Reference reinforces it;
  disuse lets it decay. Forgetting is decay (it stops surfacing), never deletion —
  cold memories stay stored, viewable, and reactivate when referenced again.
- Provenance + trust: memories carry their source core. Web-exposed cores write
  "untrusted" memories that never auto-surface to a core that can kill.
"""

import json
import math
import re
import time
import uuid

from . import config

FILE = config.MEMORY_DIR / "memories.jsonl"
HALFLIFE_DAYS = 14.0
_STOP = set("a an the is are was were be been of to in on at for and or but with this that "
            "it its i you we my your our me us has have had do does did will can".split())


def _ensure():
    config.MEMORY_DIR.mkdir(exist_ok=True)
    if not FILE.exists():
        FILE.write_text("")


def _load():
    _ensure()
    out = []
    for line in FILE.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _save(recs):
    _ensure()
    FILE.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))


def _tokens(s):
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if w not in _STOP and len(w) > 2}


def _overlap(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def salience(rec, now=None):
    if rec.get("foundational"):
        return 1.0
    now = now or time.time()
    age_days = (now - rec.get("last_seen", now)) / 86400.0
    recency = math.exp(-age_days / HALFLIFE_DAYS)
    frequency = min(1.0, math.log1p(rec.get("uses", 1)) / math.log(10))
    return 0.6 * recency + 0.4 * frequency


def remember(content, mtype="fact", core="", tags=None, foundational=False, trust="trusted"):
    content = (content or "").strip()
    if not content:
        return "Empty memory ignored."
    tags = tags or []
    recs = _load()
    ctok = _tokens(content)
    now = time.time()
    # consolidation: a near-duplicate reinforces the existing trace, not a new one
    for r in recs:
        if _overlap(ctok, _tokens(r["content"])) >= 0.7:
            r["uses"] = r.get("uses", 1) + 1
            r["last_seen"] = now
            if foundational:
                r["foundational"] = True
            _save(recs)
            return f"reinforced ({r['uses']}x): {r['content'][:60]}"
    recs.append({"id": uuid.uuid4().hex[:10], "content": content, "type": mtype, "core": core,
                 "tags": tags, "trust": trust, "created": now, "last_seen": now,
                 "uses": 1, "foundational": bool(foundational)})
    _save(recs)
    return f"remembered: {content[:60]}"


RELEVANCE_FLOOR = 0.06          # a memory must actually connect to the topic to surface


def retrieve(query, allow_untrusted=True, k=6, foundational_max=6):
    """
    Two things surface: foundational memories (always, capped) and topic-relevant
    ones (ranked by relevance x salience). Relevance is REQUIRED for the non-
    foundational set, so freshly-captured-but-unrelated memories never intrude —
    that's what makes aggressive capture safe. Genuinely-relevant recalls reinforce.
    """
    recs = _load()
    now = time.time()
    pool = [r for r in recs if allow_untrusted or r.get("trust") != "untrusted"]
    qtok = _tokens(query)

    found = sorted((r for r in pool if r.get("foundational")),
                   key=lambda r: -r.get("last_seen", 0))[:foundational_max]
    found_ids = {r["id"] for r in found}

    scored = []
    for r in pool:
        if r["id"] in found_ids:
            continue
        rel = _overlap(qtok, _tokens(r["content"]) | _tokens(" ".join(r.get("tags", []))))
        if rel < RELEVANCE_FLOOR:
            continue
        scored.append((rel * (0.4 + 0.6 * salience(r, now)), rel, r))
    scored.sort(key=lambda t: -t[0])
    relevant = scored[:k]

    warmed = {r["id"] for _, rel, r in relevant if rel > 0.25}    # recall keeps relevant ones warm
    if warmed:
        for r in recs:
            if r["id"] in warmed:
                r["last_seen"] = now
                r["uses"] = r.get("uses", 1) + 1
        _save(recs)
    return found + [r for _, _, r in relevant]


def format_for_context(hot):
    if not hot:
        return ""
    return "\n".join(f"- {r['content']}" + (f" [{r['type']}]" if r.get("type") else "") for r in hot)


def all_memories():
    recs = _load()
    now = time.time()
    for r in recs:
        r["_salience"] = round(salience(r, now), 3)
    recs.sort(key=lambda r: -r["_salience"])
    return recs


def forget(mem_id):
    recs = _load()
    kept = [r for r in recs if r["id"] != mem_id]
    if len(kept) == len(recs):
        return False
    _save(kept)
    return True


def update_content(mem_id, content):
    content = (content or "").strip()
    if not content:
        return False
    recs = _load()
    for r in recs:
        if r["id"] == mem_id:
            r["content"] = content
            r["last_seen"] = time.time()
            _save(recs)
            return True
    return False


def set_foundational(mem_id, val=True):
    recs = _load()
    for r in recs:
        if r["id"] == mem_id:
            r["foundational"] = bool(val)
            _save(recs)
            return True
    return False

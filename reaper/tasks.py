"""
Tasks & calendar — a local file store of items, each with an optional date,
a priority, an optional project, and a done flag.

Dated items are events (they land on the calendar grid, colored by priority);
all open items are work (they show in the task list, grouped by project). One
unified record keeps it flexible: a task with a due date is simply a dated task.
"""

import json
import time
import uuid
from datetime import date as _date

from . import config

FILE = config.TASKS_DIR / "tasks.jsonl"
PRIORITIES = ("high", "med", "low")


def _ensure():
    config.TASKS_DIR.mkdir(exist_ok=True)
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


def _match(recs, query):
    q = str(query).strip().lower()
    for r in recs:
        if r["id"] == query or q and q in r["title"].lower():
            return r
    return None


def add(title, priority="med", date=None, project=None, notes=""):
    title = (title or "").strip()
    if not title:
        return "Empty item ignored."
    priority = priority if priority in PRIORITIES else "med"
    date = (date or None) or None
    recs = _load()
    recs.append({"id": uuid.uuid4().hex[:10], "title": title, "priority": priority,
                 "date": date, "project": (project or None), "notes": notes or "",
                 "done": False, "created": time.time()})
    _save(recs)
    return f"added: {title}" + (f" ({priority})") + (f" on {date}" if date else "")


def complete(query):
    recs = _load()
    r = _match(recs, query)
    if not r:
        return f"No item matching '{query}'."
    r["done"] = not r["done"]
    _save(recs)
    return f"{'completed' if r['done'] else 'reopened'}: {r['title']}"


def delete(query):
    recs = _load()
    r = _match(recs, query)
    if not r:
        return f"No item matching '{query}'."
    _save([x for x in recs if x["id"] != r["id"]])
    return f"deleted: {r['title']}"


def update(item_id, fields):
    recs = _load()
    for r in recs:
        if r["id"] == item_id:
            for k in ("title", "priority", "date", "project", "notes", "done"):
                if k in fields:
                    r[k] = fields[k]
            _save(recs)
            return True
    return False


def items():
    return _load()


def agenda(days=7):
    """Compact upcoming-events + open-tasks summary for the agent to read back."""
    recs = _load()
    today = _date.today().isoformat()
    dated = sorted((r for r in recs if r.get("date") and not r["done"]), key=lambda r: r["date"])
    upcoming = [r for r in dated if r["date"] >= today][:8]
    tasks = [r for r in recs if not r["done"] and not r.get("date")]
    out = []
    if upcoming:
        out.append("Upcoming:")
        out += [f"  {r['date']} [{r['priority']}] {r['title']}" for r in upcoming]
    if tasks:
        out.append("Open tasks:")
        out += [f"  [{r['priority']}] {r['title']}" + (f" ({r['project']})" if r.get('project') else "")
                for r in tasks[:12]]
    return "\n".join(out) if out else "Nothing scheduled and no open tasks."

"""
REAPER's hands — the actions it can take on the Operator's machine.

Each tool returns a plain-text observation the brain reads back. Destructive
tools are listed in DANGEROUS and are gated behind Operator confirmation by the
agent before they run. Protected system processes can never be terminated.
"""

import os
import re
import socket
import subprocess
import time

import httpx
import psutil

from . import config, tasks, telemetry

# macOS processes that must never be killed.
_CRITICAL = {
    "kernel_task", "launchd", "WindowServer", "loginwindow", "logd", "systemstats",
    "coreaudiod", "mds", "mds_stores", "mdworker", "opendirectoryd", "securityd",
    "configd", "distnoted", "cfprefsd", "UserEventAgent", "Dock", "Finder",
}


def list_processes(sort_by="cpu", limit=10):
    if sort_by == "cpu":                          # prime cpu_percent, then measure over a window
        for p in psutil.process_iter():
            try:
                p.cpu_percent()
            except psutil.Error:
                pass
        time.sleep(0.3)
    key = "memory_percent" if sort_by == "memory" else "cpu_percent"
    rows = [p.info for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"])]
    rows.sort(key=lambda d: d.get(key) or 0.0, reverse=True)
    out = [f"Top {limit} processes by {sort_by}:"]
    for d in rows[:limit]:
        out.append(f"  pid {d['pid']:>6}  {(d['name'] or '?')[:24]:24}  "
                   f"cpu {d.get('cpu_percent') or 0:5.1f}%  mem {d.get('memory_percent') or 0:4.1f}%")
    return "\n".join(out)


def find_process(name):
    matches = [p.info for p in psutil.process_iter(["pid", "name"])
               if name.lower() in (p.info["name"] or "").lower()]
    if not matches:
        return f"No process matching '{name}'."
    return "Matches:\n" + "\n".join(f"  pid {m['pid']:>6}  {m['name']}" for m in matches[:15])


def process_detail(pid):
    try:
        p = psutil.Process(int(pid))
        with p.oneshot():
            return (f"pid {p.pid} '{p.name()}' status={p.status()} "
                    f"mem={p.memory_percent():.1f}% threads={p.num_threads()} "
                    f"cmd={' '.join(p.cmdline())[:120] or 'n/a'}")
    except psutil.NoSuchProcess:
        return f"No process with pid {pid}."
    except psutil.AccessDenied:
        return f"Access denied to pid {pid}."


def disk_usage(path="/"):
    try:
        u = psutil.disk_usage(path)
        return f"{path}: {u.percent:.0f}% used, {u.free/1e9:.1f} GB free of {u.total/1e9:.0f} GB"
    except FileNotFoundError:
        return f"No such path: {path}"


def kill_process(pid):
    try:
        p = psutil.Process(int(pid))
    except (psutil.NoSuchProcess, ValueError):
        return f"No process with pid {pid}."
    name = p.name()
    if int(pid) in (0, 1) or name in _CRITICAL:
        return f"REFUSED: '{name}' (pid {pid}) is a protected system process."
    try:
        p.terminate()
        return f"SIGTERM sent to '{name}' (pid {pid})."
    except psutil.AccessDenied:
        return f"Access denied terminating pid {pid} ('{name}')."


def _established():
    try:
        r = subprocess.run(["netstat", "-an", "-p", "tcp"],
                           capture_output=True, text=True, timeout=10)
    except (subprocess.SubprocessError, FileNotFoundError):
        return []
    return [l for l in r.stdout.splitlines() if "ESTABLISHED" in l]


def network_stats():
    a = psutil.net_io_counters()
    time.sleep(0.5)
    b = psutil.net_io_counters()
    up = (b.bytes_sent - a.bytes_sent) / 0.5 / 1024
    down = (b.bytes_recv - a.bytes_recv) / 0.5 / 1024
    return (f"Bandwidth: up {up:.0f} KB/s, down {down:.0f} KB/s. "
            f"Established TCP connections: {len(_established())}.")


def network_connections(limit=15):
    est = _established()
    if not est:
        return "No established TCP connections."
    rows = []
    for line in est[:limit]:
        p = line.split()
        if len(p) >= 5:
            rows.append(f"  {p[3]} -> {p[4]}")
    return f"Established connections ({len(est)} total):\n" + "\n".join(rows)


def recent_logs(minutes=5):
    try:
        r = subprocess.run(["log", "show", "--style", "compact", "--last", f"{minutes}m",
                            "--predicate", "messageType >= 16"],
                           capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return "Log query timed out — narrow the window."
    except (subprocess.SubprocessError, FileNotFoundError):
        return "System log unavailable."
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    if not lines:
        return f"No error or fault logs in the last {minutes} min."
    tail = lines[-30:]
    return (f"Error/fault logs (last {minutes} min, {len(lines)} total, last {len(tail)}):\n"
            + "\n".join("  " + l[:120] for l in tail))


def recent_file_changes(path, minutes=10, limit=20):
    base = os.path.expanduser(path)
    if not os.path.isdir(base):
        return f"Not a directory: {path}"
    cutoff = time.time() - minutes * 60
    hits, scanned = [], 0
    for root, _, files in os.walk(base):
        for f in files:
            scanned += 1
            if scanned > 30000:
                break
            fp = os.path.join(root, f)
            try:
                m = os.path.getmtime(fp)
            except OSError:
                continue
            if m >= cutoff:
                hits.append((m, fp))
        if scanned > 30000:
            break
    if not hits:
        return f"No files modified in {base} within {minutes} min ({scanned} scanned)."
    hits.sort(reverse=True)
    return f"Modified in last {minutes} min ({len(hits)} found):\n" + "\n".join("  " + p for _, p in hits[:limit])


def telemetry_trend(minutes=5):
    return telemetry.trend(minutes)


def per_cpu():
    psutil.cpu_percent(percpu=True)
    time.sleep(0.3)
    vals = psutil.cpu_percent(percpu=True)
    if not vals:
        return "No per-core data."
    hot = max(range(len(vals)), key=lambda i: vals[i])
    body = "  ".join(f"#{i} {v:.0f}%" for i, v in enumerate(vals))
    return f"Per-core CPU: {body}  (core {hot} hottest at {vals[hot]:.0f}%)"


def disk_io():
    a = psutil.disk_io_counters()
    time.sleep(0.5)
    b = psutil.disk_io_counters()
    rd = (b.read_bytes - a.read_bytes) / 0.5 / 1e6
    wr = (b.write_bytes - a.write_bytes) / 0.5 / 1e6
    return f"Disk I/O: read {rd:.1f} MB/s, write {wr:.1f} MB/s."


def memory_detail():
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    pressure = "ACTIVE SWAPPING — memory pressure" if sw.percent > 5 else "no significant swap"
    return (f"Memory: {vm.percent:.0f}% used ({vm.used/1e9:.1f}/{vm.total/1e9:.0f} GB), "
            f"available {vm.available/1e9:.1f} GB. "
            f"Swap: {sw.percent:.0f}% ({sw.used/1e9:.1f}/{sw.total/1e9:.0f} GB) — {pressure}.")


def disk_volumes():
    out = ["Mounted volumes:"]
    seen = set()
    for p in psutil.disk_partitions(all=False):
        if p.mountpoint in seen:
            continue
        seen.add(p.mountpoint)
        try:
            u = psutil.disk_usage(p.mountpoint)
        except OSError:
            continue
        out.append(f"  {p.mountpoint}  {u.percent:.0f}% used, {u.free/1e9:.0f} GB free  [{p.device}]")
    return "\n".join(out)


def listening_ports(limit=25):
    try:
        r = subprocess.run(["netstat", "-an", "-p", "tcp"],
                           capture_output=True, text=True, timeout=10)
    except (subprocess.SubprocessError, FileNotFoundError):
        return "netstat unavailable."
    ports = {l.split()[3] for l in r.stdout.splitlines() if "LISTEN" in l and len(l.split()) >= 4}
    if not ports:
        return "No listening TCP ports."
    return f"Listening TCP ({len(ports)}):\n" + "\n".join("  " + p for p in sorted(ports)[:limit])


def network_interfaces():
    stats = psutil.net_if_stats()
    out = ["Active interfaces with IPv4:"]
    for name, addrs in psutil.net_if_addrs().items():
        st = stats.get(name)
        if not st or not st.isup:
            continue
        ips = [a.address for a in addrs if a.family == socket.AF_INET]
        if ips:
            out.append(f"  {name}: {', '.join(ips)}")
    return "\n".join(out) if len(out) > 1 else "No active interfaces with IPv4."


def power_status():
    try:
        r = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=8)
    except (subprocess.SubprocessError, FileNotFoundError):
        return "pmset unavailable."
    lines = [l.strip() for l in r.stdout.splitlines() if l.strip()]
    return "Power:\n" + "\n".join("  " + l for l in lines[:4])


def web_search(query, count=5):
    # Untrusted external content: the brain wraps this result as DATA-NOT-INSTRUCTIONS.
    if not config.BRAVE_API_KEY:
        return "Web search unavailable: BRAVE_API_KEY not set."
    try:
        r = httpx.get("https://api.search.brave.com/res/v1/web/search",
                      params={"q": query, "count": min(int(count), 10)},
                      headers={"X-Subscription-Token": config.BRAVE_API_KEY,
                               "Accept": "application/json"},
                      timeout=15.0)
        r.raise_for_status()
    except httpx.HTTPError as e:
        return f"Web search failed: {e}"
    results = r.json().get("web", {}).get("results", [])
    if not results:
        return f"No web results for '{query}'."
    out = [f"Web results for '{query}':"]
    for res in results[:int(count)]:
        desc = re.sub(r"<[^>]+>", "", res.get("description", ""))
        out.append(f"  - {res.get('title', '')}\n    {res.get('url', '')}\n    {desc}")
    return "\n".join(out)


def add_item(title, priority="med", date=None, project=None):
    return tasks.add(title, priority=priority, date=date, project=project)


def complete_item(query):
    return tasks.complete(query)


def delete_item(query):
    return tasks.delete(query)


def list_agenda():
    return tasks.agenda()


REGISTRY = {
    "list_processes": list_processes,
    "find_process": find_process,
    "process_detail": process_detail,
    "disk_usage": disk_usage,
    "kill_process": kill_process,
    "network_stats": network_stats,
    "network_connections": network_connections,
    "recent_logs": recent_logs,
    "recent_file_changes": recent_file_changes,
    "telemetry_trend": telemetry_trend,
    "per_cpu": per_cpu,
    "disk_io": disk_io,
    "memory_detail": memory_detail,
    "disk_volumes": disk_volumes,
    "listening_ports": listening_ports,
    "network_interfaces": network_interfaces,
    "power_status": power_status,
    "web_search": web_search,
    "add_item": add_item,
    "complete_item": complete_item,
    "delete_item": delete_item,
    "list_agenda": list_agenda,
}

DANGEROUS = {"kill_process"}          # gated behind Operator confirmation

TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "list_processes",
        "description": "List the top running processes ranked by CPU or memory use.",
        "parameters": {"type": "object", "properties": {
            "sort_by": {"type": "string", "enum": ["cpu", "memory"], "description": "ranking metric"},
            "limit": {"type": "integer", "description": "how many to return (default 10)"}}}}},
    {"type": "function", "function": {
        "name": "find_process",
        "description": "Find running processes whose name contains the given substring; returns pids.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "name or substring to search for"}},
            "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "process_detail",
        "description": "Detailed status for one process by pid (memory, threads, command line).",
        "parameters": {"type": "object", "properties": {
            "pid": {"type": "integer", "description": "process id"}},
            "required": ["pid"]}}},
    {"type": "function", "function": {
        "name": "disk_usage",
        "description": "Disk usage for a filesystem path (default '/').",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "filesystem path"}}}}},
    {"type": "function", "function": {
        "name": "kill_process",
        "description": "Terminate a process by pid (SIGTERM). Destructive; requires Operator authorization. Protected system processes are refused.",
        "parameters": {"type": "object", "properties": {
            "pid": {"type": "integer", "description": "process id to terminate"}},
            "required": ["pid"]}}},
    {"type": "function", "function": {
        "name": "network_stats",
        "description": "Current network bandwidth (up/down KB/s) and count of established TCP connections.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "network_connections",
        "description": "List active established TCP connections (local -> remote endpoints).",
        "parameters": {"type": "object", "properties": {
            "limit": {"type": "integer", "description": "max connections to list (default 15)"}}}}},
    {"type": "function", "function": {
        "name": "recent_logs",
        "description": "Recent macOS system error/fault log entries. Can be slow; keep the window small.",
        "parameters": {"type": "object", "properties": {
            "minutes": {"type": "integer", "description": "look-back window in minutes (default 5)"}}}}},
    {"type": "function", "function": {
        "name": "recent_file_changes",
        "description": "Files modified within a time window under a directory path.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "directory to scan"},
            "minutes": {"type": "integer", "description": "look-back window (default 10)"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "telemetry_trend",
        "description": "Trend of CPU/memory/disk over the recent history buffer — for extrapolation and early warning.",
        "parameters": {"type": "object", "properties": {
            "minutes": {"type": "integer", "description": "window in minutes (default 5)"}}}}},
    {"type": "function", "function": {
        "name": "per_cpu",
        "description": "Per-core CPU load — finds a single pegged/hot core.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "disk_io",
        "description": "Current disk read/write throughput in MB/s — detects thrashing.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "memory_detail",
        "description": "Detailed memory and swap usage, including whether the system is actively swapping.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "disk_volumes",
        "description": "Usage for every mounted volume (not just root).",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "listening_ports",
        "description": "TCP ports the machine is listening on — what is serving / exposed.",
        "parameters": {"type": "object", "properties": {
            "limit": {"type": "integer", "description": "max ports to list (default 25)"}}}}},
    {"type": "function", "function": {
        "name": "network_interfaces",
        "description": "Active network interfaces and their IPv4 addresses.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "power_status",
        "description": "Battery charge, AC state, and power condition (laptop power detail).",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Search the web for current information. Returns titles, URLs, and snippets.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "the search query"},
            "count": {"type": "integer", "description": "number of results (default 5, max 10)"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "add_item",
        "description": ("Add a calendar event or task. Give a date (YYYY-MM-DD) for scheduled "
                        "events; omit it for an undated task. Resolve relative dates ('Friday', "
                        "'tomorrow') against the current date provided in context."),
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string", "description": "what it is, concise"},
            "priority": {"type": "string", "enum": ["high", "med", "low"]},
            "date": {"type": "string", "description": "YYYY-MM-DD, or omit for an undated task"},
            "project": {"type": "string", "description": "optional project to group a task under"}},
            "required": ["title"]}}},
    {"type": "function", "function": {
        "name": "complete_item",
        "description": "Toggle an item done/undone, matched by id or title text.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "item id or words from its title"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "delete_item",
        "description": "Delete an item, matched by id or title text.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "item id or words from its title"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "list_agenda",
        "description": "Read back upcoming events and open tasks.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "remember",
        "description": ("Store a durable memory about the Operator, the machine, or the work for "
                        "future recall. Use it when something is worth keeping — a preference, a "
                        "decision, a recurring pattern, personal context. Recall is automatic; you "
                        "only write. Reinforce by remembering the same thing again."),
        "parameters": {"type": "object", "properties": {
            "content": {"type": "string", "description": "the memory as one clear, self-contained sentence"},
            "type": {"type": "string", "description": "fact | preference | observation | project"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "keywords for recall"},
            "foundational": {"type": "boolean", "description": "true if core, lasting info that should never fade"}},
            "required": ["content"]}}},
]


# ---- capability groups: cores opt into these in their .toml `tools = [...]` ----
GROUPS = {
    "process": ["list_processes", "find_process", "process_detail"],
    "system":  ["disk_usage", "disk_io", "disk_volumes", "memory_detail", "per_cpu",
                "recent_logs", "recent_file_changes", "telemetry_trend"],
    "network": ["network_stats", "network_connections", "network_interfaces", "listening_ports"],
    "power":   ["power_status"],
    "web":     ["web_search"],             # external content — injection/exfil surface
    "memory":  ["remember"],               # write to long-term memory (read is automatic)
    "tasks":   ["add_item", "complete_item", "delete_item", "list_agenda"],
    "control": ["kill_process"],          # destructive — grant deliberately
}


def resolve(entries):
    """A core's `tools` list (group names and/or tool names) -> set of tool names.
    None means 'all tools' (back-compat); [] means 'no tools'."""
    if entries is None:
        return set(REGISTRY)
    allowed = set()
    for e in entries:
        if e in GROUPS:
            allowed.update(GROUPS[e])
        elif e in REGISTRY:
            allowed.add(e)
    return allowed


def specs_for(allowed):
    return [s for s in TOOL_SPECS if s["function"]["name"] in allowed]

"""
Engine server — exposes the REAPER agent to a GUI client over a local TCP socket
using newline-delimited JSON. Zero extra dependencies; reuses brain/voice/tools/
telemetry/cores unchanged.

Run:  python3 -m reaper.server   (then the SwiftUI app connects to 127.0.0.1:8787)

Protocol
  client -> server : {"cmd":"order","text":...} | {"cmd":"sitrep"} | {"cmd":"cores"}
                     | {"cmd":"swap","name":...} | {"cmd":"confirm","id":...,"ok":bool}
  server -> client : {"ev":"hello",...} {"ev":"core",...} {"ev":"cores",...}
                     {"ev":"state","state":"idle|thinking|speaking|alert"}
                     {"ev":"token","text":...} {"ev":"tool",...} {"ev":"confirm",...}
                     {"ev":"reply_done"} {"ev":"telemetry",...} {"ev":"error","msg":...}
"""

import json
import os
import re
import socket
import threading
import time
import uuid

from . import config, core as core_mod, memory, tasks, telemetry
from .brain import Brain, BrainOffline
from .voice import Voice

HOST = "127.0.0.1"
PORT = int(os.environ.get("REAPER_PORT", "8787"))
_SENTENCE = re.compile(r'[.!?]+["\')\]]?\s')

# Boot lines are the machine powering on — an engine-lifecycle event, not a
# per-client one. Announce them once per process so UI reconnects don't replay
# them (a reconnect storm used to fire the voiceline on a loop).
_BOOT_ANNOUNCED = False


class Session:
    def __init__(self, conn):
        self.conn = conn
        self.send_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.core = core_mod.load(config.DEFAULT_CORE)
        self.brain = Brain(self.core.system_prompt, self.core.tools, core_name=self.core.name)
        self.voice = Voice()
        self.voice.set_voice(self.core.voice, self.core.speed)
        self.voice.on_amp = lambda lvl: self.send({"ev": "amp", "level": round(lvl, 3)})
        self.pending = {}
        self.state = "idle"
        self.threats = []
        self.alive = True

    # ---- io ----
    def send(self, obj):
        data = (json.dumps(obj) + "\n").encode()
        with self.send_lock:
            try:
                self.conn.sendall(data)
            except OSError:
                self.alive = False

    def set_state(self, s):
        with self.state_lock:
            self.state = s
        self.send({"ev": "state", "state": s})

    def _core_event(self):
        self.send({"ev": "core", "name": self.core.name,
                   "designation": self.core.designation, "signature": self.core.signature,
                   "accent": self.core.accent, "boot_lines": self.core.boot_lines})

    # ---- lifecycle ----
    def serve(self):
        self.send({"ev": "hello", "model": config.XAI_MODEL,
                   "brain": bool(config.XAI_API_KEY), "voice": self.voice.enabled})
        self._core_event()
        self.send({"ev": "cores", "list": core_mod.available(), "active": self.core.name})
        self._send_memory()
        self._send_tasks()
        threading.Thread(target=self._telemetry_loop, daemon=True).start()
        global _BOOT_ANNOUNCED
        if not _BOOT_ANNOUNCED:
            _BOOT_ANNOUNCED = True
            for line in self.core.boot_lines:
                self.voice.speak(line)

        buf = b""
        while self.alive:
            try:
                data = self.conn.recv(4096)
            except OSError:
                break
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if line:
                    try:
                        self.dispatch(json.loads(line))
                    except (json.JSONDecodeError, KeyError):
                        self.send({"ev": "error", "msg": "malformed command"})
        self.alive = False

    def dispatch(self, msg):
        cmd = msg.get("cmd")
        if cmd == "order":
            threading.Thread(target=self.handle_order,
                             args=(msg.get("text", ""), msg.get("images") or []), daemon=True).start()
        elif cmd == "sitrep":
            threading.Thread(target=self.handle_sitrep, daemon=True).start()
        elif cmd == "swap":
            threading.Thread(target=self.handle_swap, args=(msg.get("name", ""),), daemon=True).start()
        elif cmd == "cores":
            self.send({"ev": "cores", "list": core_mod.available(), "active": self.core.name})
        elif cmd == "memory":
            self._send_memory()
        elif cmd == "forget":
            memory.forget(msg.get("id", ""))
            self._send_memory()
        elif cmd == "pin":
            memory.set_foundational(msg.get("id", ""), bool(msg.get("val", True)))
            self._send_memory()
        elif cmd == "tasks":
            self._send_tasks()
        elif cmd == "task_add":
            tasks.add(msg.get("title", ""), priority=msg.get("priority", "med"),
                      date=msg.get("date") or None, project=msg.get("project") or None)
            self._send_tasks()
        elif cmd == "task_complete":
            tasks.complete(msg.get("id", ""))
            self._send_tasks()
        elif cmd == "task_delete":
            tasks.delete(msg.get("id", ""))
            self._send_tasks()
        elif cmd == "task_update":
            tasks.update(msg.get("id", ""), msg.get("fields", {}))
            self._send_tasks()
        elif cmd == "edit":
            memory.update_content(msg.get("id", ""), msg.get("content", ""))
            self._send_memory()
        elif cmd == "add":
            memory.remember(msg.get("content", ""), msg.get("type", "fact"), "operator",
                            foundational=bool(msg.get("foundational", False)), trust="trusted")
            self._send_memory()
        elif cmd == "confirm":
            p = self.pending.get(msg.get("id"))
            if p:
                p["ok"] = bool(msg.get("ok"))
                p["event"].set()

    # ---- watchdog telemetry push ----
    def _telemetry_loop(self):
        while self.alive:
            s = telemetry.snapshot()
            self.threats = s["threats"]
            self.send({"ev": "telemetry", "cpu": round(s["cpu"], 1), "mem": round(s["mem_pct"], 1),
                       "disk": round(s["disk_pct"], 1), "battery": s["battery_pct"],
                       "plugged": s["battery_plugged"], "load": round(s["load"][0], 2),
                       "uptime_s": int(s["uptime_s"]),
                       "top": [[n, round(c, 1)] for n, c in s["top"][:5]],
                       "threats": s["threats"]})
            if s["threats"] and self.state == "idle":
                self.set_state("alert")
            elif not s["threats"] and self.state == "alert":
                self.set_state("idle")
            time.sleep(2.5)

    def _rest_state(self):
        return "alert" if self.threats else "idle"

    def _send_memory(self):
        items = [{"id": r["id"], "content": r["content"], "type": r.get("type", ""),
                  "core": r.get("core", ""), "trust": r.get("trust", "trusted"),
                  "salience": r.get("_salience", 0.0), "foundational": r.get("foundational", False),
                  "uses": r.get("uses", 1)} for r in memory.all_memories()]
        self.send({"ev": "memory", "list": items})

    def _send_tasks(self):
        self.send({"ev": "tasks", "list": tasks.items()})

    # ---- order / brain ----
    def _confirm(self, name, args):
        cid = uuid.uuid4().hex[:8]
        ev = threading.Event()
        self.pending[cid] = {"event": ev, "ok": False}
        self.send({"ev": "confirm", "id": cid, "name": name, "args": args,
                   "prompt": f"AUTHORIZE {name} {args}"})
        ev.wait(timeout=120)
        return self.pending.pop(cid, {}).get("ok", False)

    def _run(self, text, images=None):
        # only feed the live telemetry context to cores that have system tools
        snap = telemetry.for_llm(telemetry.snapshot()) if self.brain.allowed else ""
        # auto-retrieve the hot memory set; cores that can kill never see untrusted memories
        allow_untrusted = "kill_process" not in self.brain.allowed
        hot = memory.retrieve(text, allow_untrusted=allow_untrusted)
        mem_block = memory.format_for_context(hot)
        if hot:
            summary = "; ".join(r["content"][:40] for r in hot[:3]) + (" …" if len(hot) > 3 else "")
            self.send({"ev": "recall", "ids": [r["id"] for r in hot], "summary": summary})
        self.set_state("thinking")
        pending = ""
        reply_text = ""

        def on_tool(n, a):
            self.send({"ev": "tool", "name": n, "args": a})

        try:
            for delta in self.brain.think_stream(text, snap, on_tool=on_tool,
                                                 confirm=self._confirm, memory_block=mem_block,
                                                 images=images):
                self.send({"ev": "token", "text": delta})
                pending += delta
                reply_text += delta
                while True:
                    m = _SENTENCE.search(pending)
                    if not m:
                        break
                    self.voice.speak(pending[:m.end()].strip())
                    pending = pending[m.end():]
        except BrainOffline as e:
            self.send({"ev": "error", "msg": f"NEURAL LINK DOWN :: {e}"})
            self.set_state(self._rest_state())
            return
        if pending.strip():
            self.voice.speak(pending)
        self.send({"ev": "reply_done"})
        self._send_tasks()                        # refresh in case the agent scheduled something
        if reply_text.strip():                    # capture runs in the background, off the latency path
            threading.Thread(target=self._reflect, args=(text, reply_text), daemon=True).start()
        self._speak_phase()                       # speaking state tracks real audio playback
        self.set_state(self._rest_state())

    def _reflect(self, user_text, reply_text):
        try:
            stored = self.brain.reflect(user_text, reply_text)
        except Exception:
            return
        for s in stored:
            self.send({"ev": "remember", "text": s})
        if stored:
            self._send_memory()

    def _speak_phase(self):
        if not self.voice.enabled:
            return
        for _ in range(120):                      # wait up to ~6s for playback to begin
            if self.voice.busy():
                break
            time.sleep(0.05)
        if self.voice.busy():
            self.set_state("speaking")
            self.voice.wait()                     # hold speaking until audio fully drains

    def handle_order(self, text, images=None):
        if text.strip() or images:
            self._run(text, images)

    def handle_sitrep(self):
        self._run("Give a one-line tactical verdict on current system status.")

    def handle_swap(self, name):
        try:
            nc = core_mod.load(name)
        except FileNotFoundError:
            self.send({"ev": "error", "msg": f"No such core chip: {name}"})
            return
        self.core = nc
        self.brain.set_core(nc.system_prompt, nc.tools, core_name=nc.name)
        self.voice.set_voice(nc.voice, nc.speed)
        self._core_event()
        self.set_state(self._rest_state())
        for line in nc.boot_lines:
            self.voice.speak(line)


def run_server():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((HOST, PORT))
    except OSError as e:
        if e.errno == 48:
            raise SystemExit(f"Port {PORT} is already in use — an engine is likely "
                             f"already running. Stop it with:  pkill -f reaper.server")
        raise
    srv.listen(5)
    print(f"REAPER engine listening on {HOST}:{PORT}  (model={config.XAI_MODEL}, "
          f"brain={'on' if config.XAI_API_KEY else 'OFFLINE'}, "
          f"voice={'armed' if config.VOICE_ENABLED else 'muted'})")
    active = []
    while True:
        conn, _ = srv.accept()
        for s in active:                          # newest client wins — drop any stale session
            s.alive = False
            try:
                s.conn.close()
            except OSError:
                pass
        active.clear()
        sess = Session(conn)
        active.append(sess)
        threading.Thread(target=_serve_safe, args=(sess,), daemon=True).start()


def _serve_safe(sess):
    try:
        sess.serve()
    except Exception as e:
        print("session ended:", e)
    finally:
        try:
            sess.conn.close()
        except OSError:
            pass


if __name__ == "__main__":
    run_server()

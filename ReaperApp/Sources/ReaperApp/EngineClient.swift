import Foundation
import Network
import SwiftUI

/// Connects to the Python engine (reaper.server) over local TCP, parses the
/// newline-delimited JSON event stream, and republishes it as observable state
/// for the SwiftUI interface. Best-effort launches the engine if it isn't up.
final class EngineClient: ObservableObject {
    @Published var state: FormState = .idle
    @Published var core = CoreInfo()
    @Published var cores: [String] = []
    @Published var telemetry = Telemetry()
    @Published var log: [LogLine] = []
    @Published var linkUp = false
    @Published var brainOnline = false
    @Published var voiceArmed = false
    @Published var amp = 0.0
    @Published var memories: [MemoryItem] = []
    @Published var recalledIDs: Set<String> = []
    @Published var tasks: [TaskItem] = []
    @Published var confirm: (id: String, text: String)? = nil

    private var conn: NWConnection?
    private var buffer = Data()
    private var streaming = false
    private var launched = false
    private var reconnectScheduled = false

    // The folder holding the `reaper/` package. Edit if you move the project.
    private let engineDir = "/Users/marcusarocha/Projects/Code/Agent"

    func start() {
        // The engine runs separately (./watch_engine.sh) with your API keys; the
        // app just connects, retrying until it's up. Guard so a second window
        // sharing this client doesn't open a duplicate connection.
        guard conn == nil else { return }
        connect()
    }

    private func launchEngine() {
        guard !launched else { return }
        launched = true
        let p = Process()
        p.currentDirectoryURL = URL(fileURLWithPath: engineDir)
        p.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        p.arguments = ["python3", "-m", "reaper.server"]
        try? p.run()
    }

    private func connect() {
        // Tear down any prior connection first, and ignore callbacks from it —
        // overlapping connections plus the server's "newest wins" rule would
        // otherwise ping-pong, re-firing the engine's boot sequence each round.
        conn?.stateUpdateHandler = nil
        conn?.cancel()
        let c = NWConnection(host: "127.0.0.1", port: 8787, using: .tcp)
        conn = c
        c.stateUpdateHandler = { [weak self] st in
            guard let self, self.conn === c else { return }
            switch st {
            case .ready:
                DispatchQueue.main.async { self.linkUp = true }
                self.receive(on: c)
            case .failed, .cancelled:
                DispatchQueue.main.async { self.linkUp = false }
                self.reconnect()
            default:
                break
            }
        }
        c.start(queue: .global(qos: .userInitiated))
    }

    private func reconnect() {
        guard !reconnectScheduled else { return }
        reconnectScheduled = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in
            self?.reconnectScheduled = false
            self?.connect()
        }
    }

    private func receive(on c: NWConnection) {
        c.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] data, _, done, error in
            guard let self, self.conn === c else { return }
            if let data, !data.isEmpty {
                DispatchQueue.main.async { self.ingest(data) }
            }
            if error != nil || done {
                DispatchQueue.main.async { self.linkUp = false }
                self.reconnect()
                return
            }
            self.receive(on: c)
        }
    }

    private func ingest(_ data: Data) {
        buffer.append(data)
        while let nl = buffer.firstIndex(of: 0x0A) {
            let line = buffer[buffer.startIndex..<nl]
            buffer.removeSubrange(buffer.startIndex...nl)
            if let obj = try? JSONSerialization.jsonObject(with: line) as? [String: Any] {
                handle(obj)
            }
        }
    }

    private func handle(_ e: [String: Any]) {
        switch e["ev"] as? String {
        case "hello":
            brainOnline = e["brain"] as? Bool ?? false
            voiceArmed = e["voice"] as? Bool ?? false
        case "core":
            let newCore = CoreInfo(
                name: e["name"] as? String ?? "reaper",
                designation: e["designation"] as? String ?? "REAPER",
                signature: e["signature"] as? String ?? "",
                accent: e["accent"] as? String ?? "green",
                bootLines: e["boot_lines"] as? [String] ?? [])
            if newCore.name != core.name { log.removeAll() }      // true reboot: fresh comms
            core = newCore
            log.append(LogLine(kind: .system, text: "CORE MOUNTED :: \(core.designation)"))
        case "cores":
            cores = e["list"] as? [String] ?? []
        case "state":
            if let s = e["state"] as? String, let f = FormState(rawValue: s) { state = f }
            if state == .thinking { streaming = false }
            if state != .speaking { amp = 0 }
        case "amp":
            amp = e["level"] as? Double ?? 0
        case "token":
            appendToken(e["text"] as? String ?? "")
        case "tool":
            let name = e["name"] as? String ?? "?"
            let args = (e["args"] as? [String: Any]).map { describe($0) } ?? ""
            log.append(LogLine(kind: .tool, text: "▸ EXECUTING \(name)(\(args))"))
            streaming = false
        case "confirm":
            confirm = (e["id"] as? String ?? "", e["prompt"] as? String ?? "AUTHORIZE")
        case "recall":
            recalledIDs = Set(e["ids"] as? [String] ?? [])
            if let s = e["summary"] as? String, !s.isEmpty {
                log.append(LogLine(kind: .system, text: "✦ RECALLED \(s)"))
            }
        case "tasks":
            if let list = e["list"] as? [[String: Any]] {
                tasks = list.map {
                    TaskItem(id: $0["id"] as? String ?? "", title: $0["title"] as? String ?? "",
                             priority: $0["priority"] as? String ?? "med", date: $0["date"] as? String,
                             project: $0["project"] as? String, notes: $0["notes"] as? String ?? "",
                             done: $0["done"] as? Bool ?? false)
                }
            }
        case "remember":
            log.append(LogLine(kind: .system, text: "✦ MEMORY \(e["text"] as? String ?? "")"))
        case "memory":
            if let list = e["list"] as? [[String: Any]] {
                memories = list.map {
                    MemoryItem(id: $0["id"] as? String ?? "",
                               content: $0["content"] as? String ?? "",
                               type: $0["type"] as? String ?? "",
                               core: $0["core"] as? String ?? "",
                               trust: $0["trust"] as? String ?? "trusted",
                               salience: $0["salience"] as? Double ?? 0,
                               foundational: $0["foundational"] as? Bool ?? false,
                               uses: $0["uses"] as? Int ?? 1)
                }
            }
        case "reply_done":
            streaming = false
            amp = 0
        case "error":
            log.append(LogLine(kind: .err, text: e["msg"] as? String ?? "error"))
            streaming = false
        case "telemetry":
            telemetry = parseTelemetry(e)
        default:
            break
        }
    }

    private func appendToken(_ t: String) {
        if streaming, let i = log.indices.last, log[i].kind == .reaper {
            log[i].text += t
        } else {
            log.append(LogLine(kind: .reaper, text: t, speaker: core.name))
            streaming = true
        }
    }

    private func parseTelemetry(_ e: [String: Any]) -> Telemetry {
        var tm = Telemetry()
        tm.cpu = e["cpu"] as? Double ?? 0
        tm.mem = e["mem"] as? Double ?? 0
        tm.disk = e["disk"] as? Double ?? 0
        tm.load = e["load"] as? Double ?? 0
        tm.battery = e["battery"] as? Double
        tm.plugged = e["plugged"] as? Bool ?? false
        tm.uptime = e["uptime_s"] as? Int ?? 0
        tm.threats = e["threats"] as? [String] ?? []
        if let top = e["top"] as? [[Any]] {
            tm.top = top.compactMap { row in
                guard let n = row.first as? String, let c = row.last as? Double else { return nil }
                return (n, c)
            }
        }
        return tm
    }

    private func describe(_ d: [String: Any]) -> String {
        d.map { "\($0.key)=\($0.value)" }.joined(separator: " ")
    }

    // ---- outbound ----
    func order(_ text: String, images: [String] = []) {
        let label = text.isEmpty
            ? "▣ transmitted \(images.count) image\(images.count == 1 ? "" : "s")" : text
        log.append(LogLine(kind: .op, text: label))
        streaming = false
        var m: [String: Any] = ["cmd": "order", "text": text]
        if !images.isEmpty { m["images"] = images }
        sendJSON(m)
    }

    func sitrep() { sendJSON(["cmd": "sitrep"]) }
    func swap(_ name: String) { sendJSON(["cmd": "swap", "name": name]) }

    func answerConfirm(_ id: String, _ ok: Bool) {
        sendJSON(["cmd": "confirm", "id": id, "ok": ok])
        confirm = nil
    }

    func refreshTasks() { sendJSON(["cmd": "tasks"]) }
    func completeTask(_ id: String) { sendJSON(["cmd": "task_complete", "id": id]) }
    func deleteTask(_ id: String) { sendJSON(["cmd": "task_delete", "id": id]) }
    func updateTask(_ id: String, _ fields: [String: Any]) { sendJSON(["cmd": "task_update", "id": id, "fields": fields]) }
    func addTask(_ title: String, _ priority: String, _ date: String?, _ project: String?) {
        var m: [String: Any] = ["cmd": "task_add", "title": title, "priority": priority]
        if let date, !date.isEmpty { m["date"] = date }
        if let project, !project.isEmpty { m["project"] = project }
        sendJSON(m)
    }

    func refreshMemory() { sendJSON(["cmd": "memory"]) }
    func forget(_ id: String) { sendJSON(["cmd": "forget", "id": id]) }
    func pin(_ id: String, _ val: Bool) { sendJSON(["cmd": "pin", "id": id, "val": val]) }
    func editMemory(_ id: String, _ content: String) { sendJSON(["cmd": "edit", "id": id, "content": content]) }
    func addMemory(_ content: String, _ type: String, _ foundational: Bool) {
        sendJSON(["cmd": "add", "content": content, "type": type, "foundational": foundational])
    }

    private func sendJSON(_ obj: [String: Any]) {
        guard let d = try? JSONSerialization.data(withJSONObject: obj) else { return }
        var line = d
        line.append(0x0A)
        conn?.send(content: line, completion: .contentProcessed { _ in })
    }
}

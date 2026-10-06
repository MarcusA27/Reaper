import SwiftUI

enum FormState: String {
    case idle, thinking, speaking, alert
}

struct CoreInfo: Equatable {
    var name = "reaper"
    var designation = "REAPER // EWR-115"
    var signature = ""
    var accent = "green"
    var bootLines: [String] = []
}

struct Telemetry {
    var cpu = 0.0, mem = 0.0, disk = 0.0, load = 0.0
    var battery: Double? = nil
    var plugged = false
    var uptime = 0
    var top: [(String, Double)] = []
    var threats: [String] = []
}

struct LogLine: Identifiable {
    enum Kind { case op, reaper, tool, system, err }
    let id = UUID()
    let kind: Kind
    var text: String
    var speaker: String = ""        // for .reaper lines: the core that produced it
}

struct MemoryItem: Identifiable {
    let id: String
    var content: String
    var type: String
    var core: String
    var trust: String
    var salience: Double
    var foundational: Bool
    var uses: Int
}

/// Thermal ramp for memory salience: cold/dark (forgotten) -> hot/white (alive).
func thermal(_ s: Double) -> Color {
    let stops: [(Double, (Double, Double, Double))] = [
        (0.0,  (14, 24, 40)), (0.25, (28, 78, 150)), (0.5, (38, 200, 120)),
        (0.75, (236, 162, 44)), (1.0, (255, 246, 224)),
    ]
    let v = max(0, min(1, s))
    for i in 0..<stops.count - 1 {
        let (a, ca) = stops[i], (b, cb) = stops[i + 1]
        if v <= b {
            let t = (b == a) ? 0 : (v - a) / (b - a)
            return Color(red: (ca.0 + (cb.0 - ca.0) * t) / 255,
                         green: (ca.1 + (cb.1 - ca.1) * t) / 255,
                         blue: (ca.2 + (cb.2 - ca.2) * t) / 255)
        }
    }
    return Color(red: 1, green: 0.96, blue: 0.88)
}

struct TaskItem: Identifiable {
    let id: String
    var title: String
    var priority: String        // high / med / low
    var date: String?           // "YYYY-MM-DD" or nil
    var project: String?
    var notes: String
    var done: Bool
}

func priorityColor(_ p: String) -> Color {
    switch p {
    case "high": return Color(red: 0.90, green: 0.26, blue: 0.22)   // red
    case "low":  return Color(red: 0.40, green: 0.80, blue: 0.35)   // green
    default:     return Color(red: 0.95, green: 0.75, blue: 0.20)   // yellow (med)
    }
}

func priorityRank(_ p: String) -> Int { p == "high" ? 0 : p == "med" ? 1 : 2 }

/// Classic "jet" colormap: 0 = deep blue (cold) -> red-hot core at 1.
func jet(_ t: Double) -> Color {
    let stops: [(Double, (Double, Double, Double))] = [
        (0.0, (0, 0, 92)), (0.12, (0, 40, 205)), (0.35, (0, 205, 225)),
        (0.5, (40, 220, 70)), (0.68, (240, 232, 40)), (0.85, (238, 60, 30)), (1.0, (140, 0, 0)),
    ]
    let v = max(0, min(1, t))
    for i in 0..<stops.count - 1 {
        let (a, ca) = stops[i], (b, cb) = stops[i + 1]
        if v <= b {
            let f = (b == a) ? 0 : (v - a) / (b - a)
            return Color(red: (ca.0 + (cb.0 - ca.0) * f) / 255,
                         green: (ca.1 + (cb.1 - ca.1) * f) / 255,
                         blue: (ca.2 + (cb.2 - ca.2) * f) / 255)
        }
    }
    return Color(red: 140.0 / 255, green: 0, blue: 0)
}

func coreAccentName(_ core: String) -> String {
    switch core {
    case "reaper": return "red"
    case "oracle": return "cyan"
    case "adjutant": return "blue"
    default: return "green"          // operator-authored
    }
}

extension Color {
    static func accent(_ name: String) -> Color {
        switch name {
        case "red":  return Color(red: 0.886, green: 0.294, blue: 0.290)
        case "cyan": return Color(red: 0.0,   green: 0.85,  blue: 0.95)
        case "blue": return Color(red: 0.30,  green: 0.60,  blue: 1.0)
        case "amber": return Color(red: 0.94, green: 0.63,  blue: 0.16)
        default:     return Color(red: 0.224, green: 1.0,   blue: 0.533)
        }
    }
}

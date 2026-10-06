import SwiftUI

/// The memory field — each memory is a gaussian blob whose heat is its salience,
/// rendered through the jet colormap and gently breathing. A thermal-camera view
/// of the whole store: hot clusters glow red, the cold field stays deep blue.
struct HeatField: View {
    var memories: [MemoryItem]
    var recalled: Set<String> = []
    private static let start = Date()

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1.0 / 20.0)) { tl in
            Canvas { ctx, size in draw(&ctx, size, tl.date.timeIntervalSince(Self.start)) }
        }
        .background(jet(0))
        .blur(radius: 9)
        .clipped()
    }

    private func draw(_ ctx: inout GraphicsContext, _ size: CGSize, _ t: Double) {
        // top-by-salience plus any recalled memory (so a cold-but-recalled one still flares)
        var blobs = memories.filter { recalled.contains($0.id) }
        var seen = Set(blobs.map { $0.id })
        for m in memories.sorted(by: { $0.salience > $1.salience }) where blobs.count < 24 {
            if seen.insert(m.id).inserted { blobs.append(m) }
        }
        let pts: [(Double, Double, Double)] = blobs.map { m in
            let (bx, by) = pos(m.id)
            let pulse = 0.6 + 0.4 * sin(t * 2.6 + bx * 12)            // live flare for recalled
            let w = recalled.contains(m.id) ? max(m.salience, 0.85) + 0.45 * pulse
                                            : max(0.05, m.salience)
            return (bx + 0.03 * sin(t * 0.3 + bx * 30), by + 0.03 * cos(t * 0.25 + by * 30), w)
        }
        let cols = 60, rows = 28
        let cw = size.width / CGFloat(cols), ch = size.height / CGFloat(rows)
        for r in 0..<rows {
            for c in 0..<cols {
                let nx = (Double(c) + 0.5) / Double(cols), ny = (Double(r) + 0.5) / Double(rows)
                var inten = 0.0
                for (bx, by, w) in pts {
                    let dx = nx - bx, dy = ny - by
                    inten += w * exp(-(dx * dx + dy * dy) / (2 * 0.11 * 0.11))
                }
                var cell = Path()
                cell.addRect(CGRect(x: CGFloat(c) * cw, y: CGFloat(r) * ch, width: cw + 1, height: ch + 1))
                ctx.fill(cell, with: .color(jet(min(1.0, inten))))
            }
        }
    }

    private func pos(_ id: String) -> (Double, Double) {
        var h1 = 0.0, h2 = 0.0
        for (i, u) in id.unicodeScalars.enumerated() {
            h1 += Double(u.value) * (i % 2 == 0 ? 1.3 : 0.7)
            h2 += Double(u.value) * (i % 2 == 0 ? 0.5 : 1.1)
        }
        return (fmod(abs(h1) * 0.013, 1.0), fmod(abs(h2) * 0.017, 1.0))
    }
}

/// The memory bank as a thermal heat-map: salience -> heat. Hot memories glow
/// alive; cold ones go dark. Search, add, edit, pin, and delete in place.
struct MemoryPanel: View {
    @ObservedObject var engine: EngineClient
    var accent: Color

    @State private var search = ""
    @State private var draft = ""
    @State private var editingID: String?
    @State private var editText = ""

    private var filtered: [MemoryItem] {
        let q = search.lowercased()
        return engine.memories.filter { q.isEmpty || $0.content.lowercased().contains(q) }
    }

    var body: some View {
        VStack(spacing: 0) {
            HeatField(memories: engine.memories, recalled: engine.recalledIDs)
                .frame(height: 340)
                .frame(maxWidth: .infinity)
            HStack(spacing: 8) {
                Image(systemName: "plus").foregroundStyle(accent)
                TextField("commit a memory…", text: $draft)
                    .textFieldStyle(.plain).foregroundStyle(.white)
                    .onSubmit {
                        let t = draft.trimmingCharacters(in: .whitespaces)
                        if !t.isEmpty { engine.addMemory(t, "fact", false); draft = "" }
                    }
            }
            .font(.system(size: 12, design: .monospaced))
            .padding(.horizontal, 12).padding(.vertical, 9)
            .background(Color(white: 0.05))

            HStack(spacing: 8) {
                Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                TextField("search memory…", text: $search)
                    .textFieldStyle(.plain).foregroundStyle(.white)
                Text("\(engine.memories.count)").foregroundStyle(.secondary)
            }
            .font(.system(size: 11, design: .monospaced))
            .padding(.horizontal, 12).padding(.vertical, 7)
            .background(Color(white: 0.03))

            ScrollView {
                LazyVStack(spacing: 4) {
                    ForEach(filtered) { row($0) }
                }
                .padding(8)
            }
            .background(Color(white: 0.02))
        }
    }

    private func row(_ m: MemoryItem) -> some View {
        let heat = jet(m.salience)
        return VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .top, spacing: 8) {
                if editingID == m.id {
                    TextField("", text: $editText)
                        .textFieldStyle(.plain).foregroundStyle(.white)
                        .onSubmit { engine.editMemory(m.id, editText); editingID = nil }
                } else {
                    Text(m.content).foregroundStyle(.white)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                Button { engine.pin(m.id, !m.foundational) } label: {
                    Image(systemName: m.foundational ? "pin.fill" : "pin")
                        .foregroundStyle(m.foundational ? heat : .secondary)
                }.buttonStyle(.plain)
                Button { editingID = m.id; editText = m.content } label: {
                    Image(systemName: "pencil").foregroundStyle(.secondary)
                }.buttonStyle(.plain)
                Button { engine.forget(m.id) } label: {
                    Image(systemName: "trash").foregroundStyle(.secondary)
                }.buttonStyle(.plain)
            }
            .font(.system(size: 12.5, design: .monospaced))

            HStack(spacing: 8) {
                Circle().fill(Color.accent(coreAccentName(m.core))).frame(width: 6, height: 6)
                Text(m.type.isEmpty ? "fact" : m.type).foregroundStyle(.secondary)
                Text("·").foregroundStyle(.secondary)
                Text("\(m.uses)×").foregroundStyle(.secondary)
                if m.trust == "untrusted" {
                    Text("UNVERIFIED").foregroundStyle(Color(red: 0.94, green: 0.63, blue: 0.16))
                }
                if m.foundational { Text("PINNED").foregroundStyle(heat) }
                Spacer()
                Text("\(Int(m.salience * 100))°").foregroundStyle(heat)
            }
            .font(.system(size: 10, design: .monospaced))
        }
        .padding(9)
        .background(heat.opacity(0.08 + 0.16 * m.salience))      // hotter = warmer glow
        .overlay(Rectangle().frame(width: 3).foregroundStyle(heat), alignment: .leading)
        .opacity(0.55 + 0.45 * m.salience)                       // cold memories literally fade
    }
}

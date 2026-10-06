import SwiftUI
import AppKit
import UniformTypeIdentifiers

struct ContentView: View {
    @ObservedObject var engine: EngineClient
    @State private var input = ""
    @State private var attachments: [Attachment] = []
    @State private var dropTargeted = false
    @State private var panel: Panel = .comms
    @FocusState private var inputFocused: Bool

    private enum Panel { case comms, memory }

    private var accent: Color { Color.accent(engine.core.accent) }
    private let mono = Font.system(.body, design: .monospaced)

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            VStack(spacing: 0) {
                statusBar
                HStack(spacing: 1) {
                    VStack(spacing: 1) {
                        panelTabs
                        if panel == .comms {
                            ZStack {
                                PointCloudView(state: engine.state, accent: accent, level: engine.amp)
                                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                                    .background(Color(white: 0.02))
                                comms          // frosted glass + chat, over the orb
                            }
                        } else {
                            MemoryPanel(engine: engine, accent: accent)
                        }
                    }
                    .onDrop(of: [.image, .fileURL], isTargeted: $dropTargeted) { handleDrop($0) }
                    .overlay {
                        if dropTargeted {
                            Rectangle().stroke(accent, lineWidth: 2)
                                .background(accent.opacity(0.06))
                                .overlay(Text("▣ DROP TO ATTACH").foregroundStyle(accent)
                                    .font(.system(size: 13, design: .monospaced)))
                                .allowsHitTesting(false)
                        }
                    }
                    sidebar.frame(width: 240)
                }
                if !attachments.isEmpty { attachmentStrip }
                inputBar
            }
            if let cp = engine.confirm { confirmOverlay(cp) }
        }
        .preferredColorScheme(.dark)
        .frame(minWidth: 860, minHeight: 600)
        .font(mono)
        .onAppear {
            engine.start()
            DesktopWidget.shared.show(engine: engine, activate: false)
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { inputFocused = true }
        }
    }

    // MARK: status

    private var statusBar: some View {
        HStack(spacing: 14) {
            Text(engine.core.designation).foregroundStyle(accent).bold()
            Text("CORE \(engine.core.name.uppercased())").foregroundStyle(.secondary)
            Spacer()
            dot("GROK", engine.brainOnline)
            dot("FISH", engine.voiceArmed)
            dot("LINK", engine.linkUp)
        }
        .font(.system(size: 11, design: .monospaced))
        .padding(.horizontal, 14).padding(.vertical, 9)
        .background(Color(white: 0.04))
    }

    private var panelTabs: some View {
        HStack(spacing: 0) {
            tab("COMMS", .comms)
            tab("MEMORY", .memory)
            Spacer()
            Button { DesktopWidget.shared.toggle(engine: engine) } label: {
                Text("CALENDAR ↗")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 14).padding(.vertical, 7)
            }
            .buttonStyle(.plain)
        }
        .background(Color(white: 0.05))
    }

    private func tab(_ label: String, _ p: Panel) -> some View {
        Button {
            panel = p
            if p == .memory { engine.refreshMemory() }
        } label: {
            Text(label)
                .font(.system(size: 11, design: .monospaced))
                .foregroundStyle(panel == p ? accent : .secondary)
                .padding(.horizontal, 14).padding(.vertical, 7)
                .background(panel == p ? Color(white: 0.02) : Color.clear)
        }
        .buttonStyle(.plain)
    }

    private func dot(_ label: String, _ on: Bool) -> some View {
        HStack(spacing: 4) {
            Text(label).foregroundStyle(.secondary)
            Circle().fill(on ? Color.green : Color.red).frame(width: 7, height: 7)
        }
    }

    // MARK: comms

    private var comms: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(engine.log) { line in
                        Text(prefix(line) + line.text)
                            .foregroundStyle(color(line))
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .id(line.id)
                    }
                }
                .padding(12)
            }
            .scrollContentBackground(.hidden)
            .background { Rectangle().fill(.ultraThinMaterial).opacity(0.4) }
            .onChange(of: engine.log.count) {
                if let last = engine.log.last { proxy.scrollTo(last.id) }
            }
        }
    }

    private func prefix(_ l: LogLine) -> String {
        switch l.kind {
        case .op: return "OPERATOR ▸ "
        case .reaper: return "\(l.speaker.isEmpty ? "REAPER" : l.speaker.uppercased()) ▸ "
        default: return ""
        }
    }

    private func color(_ l: LogLine) -> Color {
        switch l.kind {
        case .op: return .secondary
        case .reaper: return .white
        case .tool: return accent
        case .system: return accent.opacity(0.7)
        case .err: return Color(red: 0.9, green: 0.3, blue: 0.3)
        }
    }

    // MARK: sidebar

    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 14) {
            if panel == .comms {
                Button {
                    panel = .memory
                    engine.refreshMemory()
                } label: {
                    VStack(alignment: .leading, spacing: 6) {
                        HStack {
                            section("MEMORY FIELD")
                            Spacer()
                            Image(systemName: "arrow.up.right").foregroundStyle(.secondary)
                                .font(.system(size: 10))
                        }
                        HeatField(memories: engine.memories, recalled: engine.recalledIDs)
                            .frame(height: 110)
                            .clipped()
                    }
                }
                .buttonStyle(.plain)
            }
            if engine.core.name == "adjutant" {
                AdjutantSidebar(engine: engine, accent: accent)
            } else {
                HStack {
                    section("SENSORS")
                    Spacer()
                    if engine.telemetry.threats.isEmpty {
                        Text("● THREATS: NONE").foregroundStyle(.green)
                    } else {
                        Text("‼ \(engine.telemetry.threats.count) THREAT\(engine.telemetry.threats.count == 1 ? "" : "S")")
                            .foregroundStyle(.red)
                    }
                }
                .font(.system(size: 11, design: .monospaced))
                gauge("CPU", engine.telemetry.cpu)
                gauge("MEM", engine.telemetry.mem)
                gauge("DISK", engine.telemetry.disk)
                if let b = engine.telemetry.battery { gauge("PWR", b) }
                if !engine.telemetry.threats.isEmpty {
                    ForEach(engine.telemetry.threats, id: \.self) { t in
                        Text("‼ \(t)").foregroundStyle(.red).font(.system(size: 11, design: .monospaced))
                    }
                }
            }
            section("DIRECTIVE CORES")
            ForEach(engine.cores, id: \.self) { name in
                Button { engine.swap(name) } label: {
                    HStack {
                        Text(name == engine.core.name ? "◉" : "○")
                        Text(name.uppercased())
                        Spacer()
                    }
                    .foregroundStyle(name == engine.core.name ? accent : .secondary)
                }
                .buttonStyle(.plain)
            }
            Spacer()
        }
        .font(.system(size: 12, design: .monospaced))
        .padding(12)
        .frame(maxHeight: .infinity, alignment: .top)
        .background(Color(white: 0.03))
    }

    private func section(_ t: String) -> some View {
        Text("◢ \(t) ◣").foregroundStyle(accent).font(.system(size: 11, design: .monospaced))
    }

    private func gauge(_ label: String, _ pct: Double) -> some View {
        let crit = pct >= 90
        return HStack(spacing: 8) {
            Text(label).foregroundStyle(accent).frame(width: 34, alignment: .leading)
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Rectangle().fill(Color(white: 0.12))
                    Rectangle().fill(crit ? Color.red : accent)
                        .frame(width: geo.size.width * pct / 100)
                }
            }
            .frame(height: 10)
            Text("\(Int(pct))%").foregroundStyle(crit ? .red : .primary).frame(width: 40, alignment: .trailing)
        }
        .font(.system(size: 11, design: .monospaced))
    }

    // MARK: input

    private var attachmentStrip: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(attachments) { a in
                    ZStack(alignment: .topTrailing) {
                        Image(nsImage: a.thumb).resizable().scaledToFill()
                            .frame(width: 44, height: 44).clipped()
                            .overlay(Rectangle().stroke(accent.opacity(0.5), lineWidth: 1))
                        Button { attachments.removeAll { $0.id == a.id } } label: {
                            Image(systemName: "xmark.circle.fill").font(.system(size: 12))
                                .foregroundStyle(.white)
                        }
                        .buttonStyle(.plain).offset(x: 5, y: -5)
                    }
                }
            }
            .padding(.horizontal, 14).padding(.vertical, 7)
        }
        .background(Color(white: 0.04))
    }

    private var inputBar: some View {
        HStack(spacing: 8) {
            Text("OPERATOR ▸").foregroundStyle(accent).bold()
            Button(action: pickImages) { Image(systemName: "paperclip").font(.system(size: 13)) }
                .buttonStyle(.plain).foregroundStyle(.secondary)
            TextField("", text: $input)
                .textFieldStyle(.plain)
                .foregroundStyle(.white)
                .focused($inputFocused)
                .onSubmit(send)
            Button(action: send) { Text("⏎ TRANSMIT").font(.system(size: 11, design: .monospaced)) }
                .buttonStyle(.plain).foregroundStyle(.secondary)
        }
        .font(mono)
        .padding(.horizontal, 14).padding(.vertical, 11)
        .background(Color(white: 0.04))
    }

    private func pickImages() {
        let p = NSOpenPanel()
        p.allowsMultipleSelection = true
        p.canChooseDirectories = false
        p.allowedContentTypes = [.png, .jpeg]
        guard p.runModal() == .OK else { return }
        for url in p.urls {
            if let a = encodeForVision(url) { attachments.append(a) }
        }
    }

    private func handleDrop(_ providers: [NSItemProvider]) -> Bool {
        var handled = false
        for p in providers {
            if p.canLoadObject(ofClass: URL.self) {
                handled = true
                _ = p.loadObject(ofClass: URL.self) { url, _ in
                    guard let url, let a = encodeForVision(url) else { return }
                    DispatchQueue.main.async { attachments.append(a) }
                }
            } else if p.hasItemConformingToTypeIdentifier(UTType.image.identifier) {
                handled = true
                p.loadDataRepresentation(forTypeIdentifier: UTType.image.identifier) { data, _ in
                    guard let data, let img = NSImage(data: data),
                          let a = encodeForVision(image: img) else { return }
                    DispatchQueue.main.async { attachments.append(a) }
                }
            }
        }
        return handled
    }

    private func send() {
        let t = input.trimmingCharacters(in: .whitespaces)
        let imgs = attachments.map { $0.dataURL }
        if !imgs.isEmpty {
            engine.order(t, images: imgs)
            attachments = []; input = ""
            return
        }
        guard !t.isEmpty else { return }
        if t.lowercased() == "sitrep" || t.lowercased() == "scan" {
            engine.log.append(LogLine(kind: .op, text: t)); engine.sitrep()
        } else {
            engine.order(t)
        }
        input = ""
    }

    // MARK: confirm

    private func confirmOverlay(_ cp: (id: String, text: String)) -> some View {
        ZStack {
            Color.black.opacity(0.55).ignoresSafeArea()
            VStack(spacing: 16) {
                Text("⚠ AUTHORIZATION REQUIRED").foregroundStyle(.red).bold()
                Text(cp.text).foregroundStyle(.white).multilineTextAlignment(.center)
                HStack(spacing: 16) {
                    Button("CONFIRM [Y]") { engine.answerConfirm(cp.id, true) }
                        .foregroundStyle(.red)
                    Button("ABORT [N]") { engine.answerConfirm(cp.id, false) }
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
            }
            .font(.system(size: 13, design: .monospaced))
            .padding(28)
            .background(Color(white: 0.05))
            .overlay(Rectangle().stroke(Color.red, lineWidth: 1))
        }
    }
}

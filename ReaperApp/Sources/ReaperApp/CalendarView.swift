import SwiftUI

/// Compact desktop-widget calendar (~250x300). A dense month grid of small
/// priority-colored squares up top; click a day for its events. Below: a merged
/// agenda (or the selected day's detail) and project-grouped tasks, scrollable.
/// Single-row add bar at the base. Rendered as a rounded card inside a chromeless
/// NSPanel (see DesktopWidget), so the rounding/border live here.
struct CalendarView: View {
    @ObservedObject var engine: EngineClient
    var onClose: (() -> Void)? = nil

    @State private var monthAnchor = Date()
    @State private var selectedDay: String?
    @State private var newTitle = ""
    @State private var newPriority = "med"

    private let cal = Calendar.current
    private let weekdays = ["S", "M", "T", "W", "T", "F", "S"]
    private let accent = Color(red: 0.90, green: 0.26, blue: 0.22)
    private let cell: CGFloat = 24
    private let gap: CGFloat = 2

    var body: some View {
        VStack(spacing: 0) {
            grip
            gridPane
            Rectangle().fill(Color(white: 0.12)).frame(height: 1)
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    detailOrAgenda
                    tasksSection
                }
                .padding(8)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            addBar
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.black)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color(white: 0.16), lineWidth: 1))
        .preferredColorScheme(.dark)
        .font(.system(.body, design: .monospaced))
        .onAppear { engine.refreshTasks() }
    }

    // MARK: drag handle

    private var grip: some View {
        Capsule().fill(Color(white: 0.3))
            .frame(width: 34, height: 4)
            .frame(maxWidth: .infinity)
            .padding(.top, 5).padding(.bottom, 2)
            .contentShape(Rectangle())
    }

    // MARK: dense grid

    private var gridPane: some View {
        VStack(spacing: 6) {
            HStack(spacing: 6) {
                Button { shiftMonth(-1) } label: { Text("‹").font(.system(size: 13)) }.buttonStyle(.plain)
                Spacer()
                Text(monthTitle).foregroundStyle(accent).font(.system(size: 10, design: .monospaced))
                Spacer()
                Button { shiftMonth(1) } label: { Text("›").font(.system(size: 13)) }.buttonStyle(.plain)
                if let onClose {
                    Button { onClose() } label: { Image(systemName: "xmark").font(.system(size: 9)) }
                        .buttonStyle(.plain).foregroundStyle(.secondary)
                }
            }
            VStack(spacing: gap) {
                HStack(spacing: gap) {
                    ForEach(0..<7, id: \.self) { i in
                        Text(weekdays[i]).font(.system(size: 7, design: .monospaced))
                            .foregroundStyle(.secondary).frame(width: cell)
                    }
                }
                let cols = Array(repeating: GridItem(.fixed(cell), spacing: gap), count: 7)
                LazyVGrid(columns: cols, spacing: gap) {
                    ForEach(Array(cells.enumerated()), id: \.offset) { _, day in
                        if let day { dayCell(day) } else { Color.clear.frame(width: cell, height: cell) }
                    }
                }
            }
        }
        .padding(8)
    }

    private func dayCell(_ day: Int) -> some View {
        let ds = dateString(day)
        let evs = engine.tasks.filter { $0.date == ds && !$0.done }
        let color = evs.isEmpty ? Color(white: 0.13) : priorityColor(topPriority(evs))
        let isSel = selectedDay == ds
        let isToday = ds == todayString
        return Button { selectedDay = isSel ? nil : ds } label: {
            RoundedRectangle(cornerRadius: 3).fill(color)
                .frame(width: cell, height: cell)
                .overlay(RoundedRectangle(cornerRadius: 3)
                    .stroke(isSel ? Color.white : (isToday ? accent : .clear), lineWidth: isSel ? 1.5 : 1))
        }
        .buttonStyle(.plain)
    }

    // MARK: agenda / day detail

    private var detailOrAgenda: some View {
        VStack(alignment: .leading, spacing: 5) {
            if let ds = selectedDay {
                HStack {
                    Text(shortDate(ds)).foregroundStyle(accent).font(.system(size: 10, design: .monospaced))
                    Spacer()
                    Button { selectedDay = nil } label: { Image(systemName: "xmark").font(.system(size: 8)) }
                        .buttonStyle(.plain).foregroundStyle(.secondary)
                }
                let day = engine.tasks.filter { $0.date == ds }
                if day.isEmpty {
                    Text("no events — type below to add").foregroundStyle(.secondary)
                        .font(.system(size: 9, design: .monospaced))
                }
                ForEach(day) { itemRow($0) }
            } else {
                Text("◢ AGENDA ◣").foregroundStyle(accent).font(.system(size: 9, design: .monospaced))
                if agendaItems.isEmpty {
                    Text("clear").foregroundStyle(.secondary).font(.system(size: 9, design: .monospaced))
                }
                ForEach(agendaItems) { itemRow($0) }
            }
        }
    }

    private func itemRow(_ t: TaskItem) -> some View {
        HStack(spacing: 6) {
            Circle().fill(priorityColor(t.priority)).frame(width: 6, height: 6)
            Text(t.title).foregroundStyle(t.done ? Color.secondary : Color.white).strikethrough(t.done)
                .font(.system(size: 10, design: .monospaced)).lineLimit(1)
            if let d = t.date {
                Text(shortDate(d)).foregroundStyle(.secondary).font(.system(size: 8, design: .monospaced))
            }
            Spacer()
            Button { engine.completeTask(t.id) } label: {
                Image(systemName: t.done ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(t.done ? priorityColor(t.priority) : Color.secondary).font(.system(size: 10))
            }.buttonStyle(.plain)
            Button { engine.deleteTask(t.id) } label: {
                Image(systemName: "trash").foregroundStyle(.secondary).font(.system(size: 8))
            }.buttonStyle(.plain)
        }
    }

    // MARK: tasks by project

    private var tasksSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("◢ TASKS ◣").foregroundStyle(accent).font(.system(size: 9, design: .monospaced))
            if projects.isEmpty {
                Text("none").foregroundStyle(.secondary).font(.system(size: 9, design: .monospaced))
            }
            ForEach(projects, id: \.self) { proj in
                VStack(alignment: .leading, spacing: 2) {
                    Text(proj.uppercased()).foregroundStyle(.secondary).font(.system(size: 8, design: .monospaced))
                    ForEach(tasksFor(proj)) { itemRow($0) }
                }
            }
        }
    }

    // MARK: add bar

    private var addBar: some View {
        HStack(spacing: 6) {
            TextField(selectedDay != nil ? "+ on \(shortDate(selectedDay!))" : "+ task", text: $newTitle)
                .textFieldStyle(.plain).foregroundStyle(.white).onSubmit(commit)
            Picker("", selection: $newPriority) {
                Text("H").tag("high"); Text("M").tag("med"); Text("L").tag("low")
            }.pickerStyle(.segmented).frame(width: 84).labelsHidden()
            Button { commit() } label: {
                Image(systemName: "plus.circle.fill").foregroundStyle(accent).font(.system(size: 13))
            }.buttonStyle(.plain)
        }
        .font(.system(size: 10, design: .monospaced))
        .padding(.horizontal, 8).padding(.vertical, 6)
        .background(Color(white: 0.05))
    }

    private func commit() {
        let t = newTitle.trimmingCharacters(in: .whitespaces)
        guard !t.isEmpty else { return }
        engine.addTask(t, newPriority, selectedDay, nil)
        newTitle = ""
    }

    // MARK: data

    private var agendaItems: [TaskItem] {
        engine.tasks.filter { !$0.done }.sorted { a, b in
            let ka = a.date ?? "9999-99-99", kb = b.date ?? "9999-99-99"
            return ka != kb ? ka < kb : priorityRank(a.priority) < priorityRank(b.priority)
        }.prefix(12).map { $0 }
    }

    private var workItems: [TaskItem] { engine.tasks.filter { !$0.done } }

    private var projects: [String] {
        Array(Set(workItems.map { $0.project ?? "UNFILED" })).sorted {
            $0 == "UNFILED" ? false : ($1 == "UNFILED" ? true : $0 < $1)
        }
    }

    private func tasksFor(_ p: String) -> [TaskItem] {
        workItems.filter { ($0.project ?? "UNFILED") == p }
            .sorted { priorityRank($0.priority) < priorityRank($1.priority) }
    }

    private func topPriority(_ evs: [TaskItem]) -> String {
        if evs.contains(where: { $0.priority == "high" }) { return "high" }
        if evs.contains(where: { $0.priority == "med" }) { return "med" }
        return "low"
    }

    // MARK: dates

    private var cells: [Int?] {
        let comps = cal.dateComponents([.year, .month], from: monthAnchor)
        guard let first = cal.date(from: comps),
              let range = cal.range(of: .day, in: .month, for: first) else { return [] }
        let lead = cal.component(.weekday, from: first) - 1
        return Array(repeating: nil, count: lead) + range.map { Optional($0) }
    }

    private func shiftMonth(_ d: Int) {
        if let m = cal.date(byAdding: .month, value: d, to: monthAnchor) {
            monthAnchor = m; selectedDay = nil
        }
    }

    private var monthTitle: String {
        let f = DateFormatter(); f.dateFormat = "MMMM yyyy"
        return f.string(from: monthAnchor).uppercased()
    }

    private func dateString(_ day: Int) -> String {
        let c = cal.dateComponents([.year, .month], from: monthAnchor)
        return String(format: "%04d-%02d-%02d", c.year ?? 0, c.month ?? 0, day)
    }

    private var todayString: String {
        let c = cal.dateComponents([.year, .month, .day], from: Date())
        return String(format: "%04d-%02d-%02d", c.year ?? 0, c.month ?? 0, c.day ?? 0)
    }

    private func shortDate(_ ds: String) -> String {
        let p = ds.split(separator: "-")
        guard p.count == 3, let mo = Int(p[1]), let dy = Int(p[2]) else { return ds }
        let m = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        return "\(mo < m.count ? m[mo] : "") \(dy)"
    }
}

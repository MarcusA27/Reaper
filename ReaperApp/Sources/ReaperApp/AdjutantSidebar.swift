import SwiftUI

/// Replaces the sensor gauges in the sidebar when the ADJUTANT core is mounted —
/// that core has no telemetry tools, it runs the task/calendar ledger. A mini
/// GitHub-contributions-style grid (12.5px day squares, weekday rows × week
/// columns) up top, a compact task manager below.
struct AdjutantSidebar: View {
    @ObservedObject var engine: EngineClient
    let accent: Color

    @State private var selectedDay: String?
    @State private var newTitle = ""
    @State private var newPriority = "med"

    private let cal = Calendar.current
    private let cell: CGFloat = 12.5
    private let gap: CGFloat = 2.5
    private let weeks = 14

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            calendarSection
            tasksSection
        }
        .onAppear { engine.refreshTasks() }
    }

    // MARK: mini contributions calendar

    private var calendarSection: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text("◢ CALENDAR ◣").foregroundStyle(accent).font(.system(size: 11, design: .monospaced))
            HStack(spacing: gap) {
                ForEach(0..<weeks, id: \.self) { col in
                    Text(monthLabel(col)).font(.system(size: 7, design: .monospaced))
                        .foregroundStyle(.secondary).frame(width: cell, alignment: .leading)
                }
            }
            HStack(alignment: .top, spacing: gap) {
                ForEach(0..<weeks, id: \.self) { col in
                    VStack(spacing: gap) {
                        ForEach(0..<7, id: \.self) { row in
                            dayCell(dayAt(col, row))
                        }
                    }
                }
            }
        }
    }

    private func dayCell(_ date: Date) -> some View {
        let s = ds(date)
        let evs = engine.tasks.filter { $0.date == s && !$0.done }
        let color = evs.isEmpty ? Color(white: 0.10) : priorityColor(topPriority(evs))
        let isToday = s == ds(Date())
        let isSel = selectedDay == s
        return Button { selectedDay = isSel ? nil : s } label: {
            RoundedRectangle(cornerRadius: 2).fill(color)
                .frame(width: cell, height: cell)
                .overlay(RoundedRectangle(cornerRadius: 2)
                    .stroke(isSel ? Color.white : (isToday ? accent : .clear), lineWidth: 1))
        }
        .buttonStyle(.plain)
    }

    // MARK: task manager

    private var tasksSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(selectedDay == nil ? "◢ TASKS ◣" : "◢ \(shortDate(selectedDay!).uppercased()) ◣")
                    .foregroundStyle(accent).font(.system(size: 11, design: .monospaced))
                Spacer()
                if selectedDay != nil {
                    Button { selectedDay = nil } label: { Image(systemName: "xmark").font(.system(size: 8)) }
                        .buttonStyle(.plain).foregroundStyle(.secondary)
                }
            }
            addRow
            ScrollView {
                VStack(alignment: .leading, spacing: 4) {
                    if visibleItems.isEmpty {
                        Text(selectedDay == nil ? "clear" : "no events")
                            .foregroundStyle(.secondary).font(.system(size: 10, design: .monospaced))
                    }
                    ForEach(visibleItems) { itemRow($0) }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxHeight: 180)
        }
    }

    private var addRow: some View {
        HStack(spacing: 6) {
            TextField(selectedDay != nil ? "+ \(shortDate(selectedDay!))" : "+ task", text: $newTitle)
                .textFieldStyle(.plain).foregroundStyle(.white).onSubmit(commit)
            Picker("", selection: $newPriority) {
                Text("H").tag("high"); Text("M").tag("med"); Text("L").tag("low")
            }.pickerStyle(.segmented).frame(width: 72).labelsHidden()
            Button { commit() } label: {
                Image(systemName: "plus.circle.fill").foregroundStyle(accent).font(.system(size: 12))
            }.buttonStyle(.plain)
        }
        .font(.system(size: 10, design: .monospaced))
    }

    private func itemRow(_ t: TaskItem) -> some View {
        HStack(spacing: 6) {
            Circle().fill(priorityColor(t.priority)).frame(width: 6, height: 6)
            Text(t.title).foregroundStyle(t.done ? Color.secondary : Color.white).strikethrough(t.done)
                .font(.system(size: 11, design: .monospaced)).lineLimit(1)
            Spacer()
            if selectedDay == nil, let d = t.date {
                Text(shortDate(d)).foregroundStyle(.secondary).font(.system(size: 8, design: .monospaced))
            }
            Button { engine.completeTask(t.id) } label: {
                Image(systemName: t.done ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(t.done ? priorityColor(t.priority) : Color.secondary).font(.system(size: 10))
            }.buttonStyle(.plain)
            Button { engine.deleteTask(t.id) } label: {
                Image(systemName: "trash").foregroundStyle(.secondary).font(.system(size: 8))
            }.buttonStyle(.plain)
        }
    }

    private func commit() {
        let t = newTitle.trimmingCharacters(in: .whitespaces)
        guard !t.isEmpty else { return }
        engine.addTask(t, newPriority, selectedDay, nil)
        newTitle = ""
    }

    // MARK: data

    private var visibleItems: [TaskItem] {
        if let s = selectedDay {
            return engine.tasks.filter { $0.date == s }
                .sorted { priorityRank($0.priority) < priorityRank($1.priority) }
        }
        return engine.tasks.filter { !$0.done }.sorted { a, b in
            let ka = a.date ?? "9999-99-99", kb = b.date ?? "9999-99-99"
            return ka != kb ? ka < kb : priorityRank(a.priority) < priorityRank(b.priority)
        }
    }

    private func topPriority(_ evs: [TaskItem]) -> String {
        if evs.contains(where: { $0.priority == "high" }) { return "high" }
        if evs.contains(where: { $0.priority == "med" }) { return "med" }
        return "low"
    }

    // MARK: dates

    /// Sunday of the week one week before the current week — gives a little past
    /// context, then runs forward across the window.
    private var gridStart: Date {
        let today = cal.startOfDay(for: Date())
        let wd = cal.component(.weekday, from: today)          // 1 = Sunday
        let sunday = cal.date(byAdding: .day, value: -(wd - 1), to: today)!
        return cal.date(byAdding: .day, value: -7, to: sunday)!
    }

    private func dayAt(_ col: Int, _ row: Int) -> Date {
        cal.date(byAdding: .day, value: col * 7 + row, to: gridStart)!
    }

    private func monthLabel(_ col: Int) -> String {
        let m = cal.component(.month, from: dayAt(col, 0))
        if col > 0, cal.component(.month, from: dayAt(col - 1, 0)) == m { return "" }
        let names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        return m < names.count ? names[m] : ""
    }

    private func ds(_ d: Date) -> String {
        let c = cal.dateComponents([.year, .month, .day], from: d)
        return String(format: "%04d-%02d-%02d", c.year ?? 0, c.month ?? 0, c.day ?? 0)
    }

    private func shortDate(_ ds: String) -> String {
        let p = ds.split(separator: "-")
        guard p.count == 3, let mo = Int(p[1]), let dy = Int(p[2]) else { return ds }
        let m = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        return "\(mo < m.count ? m[mo] : "") \(dy)"
    }
}

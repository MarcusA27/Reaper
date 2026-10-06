import SwiftUI
import AppKit

/// A borderless NSPanel must explicitly opt into key status, otherwise the
/// calendar's text fields can never receive keystrokes. It also drags itself
/// manually: `isMovableByWindowBackground` is unreliable at the desktop window
/// level, so we reposition on drag from any non-control region (e.g. the grip).
final class WidgetPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }

    private var grabOffset: NSPoint?

    override func mouseDown(with event: NSEvent) {
        grabOffset = event.locationInWindow
        super.mouseDown(with: event)
    }

    override func mouseDragged(with event: NSEvent) {
        guard let off = grabOffset else { return super.mouseDragged(with: event) }
        let m = NSEvent.mouseLocation
        setFrameOrigin(NSPoint(x: m.x - off.x, y: m.y - off.y))
    }

    override func mouseUp(with event: NSEvent) {
        grabOffset = nil
        super.mouseUp(with: event)
    }
}

/// At desktop level the panel belongs to a background app, so without this a
/// click first activates the app and never reaches the SwiftUI controls — the
/// widget reads as "unclickable." Accepting first mouse delivers the click to
/// the buttons/fields directly.
final class WidgetHostingView<Content: View>: NSHostingView<Content> {
    required init(rootView: Content) { super.init(rootView: rootView) }
    @available(*, unavailable) required init?(coder: NSCoder) { fatalError() }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
}

/// Hosts the calendar as a chromeless desktop widget rather than a SwiftUI
/// `Window` scene — small, fixed-size, no title bar, pinned to every Space, and
/// draggable by its background. It reads as something that lives on the desktop
/// instead of an app window you can close.
final class DesktopWidget {
    static let shared = DesktopWidget()
    private var panel: WidgetPanel?
    private var observing = false

    private let size = NSSize(width: 250, height: 300)
    // Sits behind every app window, on the desktop layer where icons live.
    private let desktopLevel = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.desktopIconWindow)))

    func toggle(engine: EngineClient) {
        if let p = panel, p.isVisible { p.orderOut(nil) }
        else { show(engine: engine, activate: true) }
    }

    func show(engine: EngineClient, activate: Bool) {
        let p = panel ?? make(engine: engine)
        panel = p
        if !p.isVisible { position(p) }
        if activate { p.makeKeyAndOrderFront(nil) } else { p.orderFront(nil) }
    }

    func hide() { panel?.orderOut(nil) }

    /// A fullscreen app gets its own Space with no exposed desktop, so a
    /// desktop-level widget is buried behind it. When our own window goes
    /// fullscreen, lift the widget above so it stays reachable; restore it to the
    /// desktop on exit.
    private func observeFullscreen() {
        guard !observing else { return }
        observing = true
        let nc = NotificationCenter.default
        nc.addObserver(forName: NSWindow.didEnterFullScreenNotification, object: nil, queue: .main) { [weak self] _ in
            guard let self, let p = self.panel else { return }
            p.level = .floating
            p.orderFront(nil)
        }
        nc.addObserver(forName: NSWindow.didExitFullScreenNotification, object: nil, queue: .main) { [weak self] _ in
            self?.panel?.level = self?.desktopLevel ?? .normal
        }
    }

    private func make(engine: EngineClient) -> WidgetPanel {
        let p = WidgetPanel(contentRect: NSRect(origin: .zero, size: size),
                            styleMask: [.borderless, .nonactivatingPanel],
                            backing: .buffered, defer: false)
        p.isFloatingPanel = false
        p.level = desktopLevel
        p.backgroundColor = .clear
        p.isOpaque = false
        p.hasShadow = true
        p.isMovableByWindowBackground = false
        p.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle, .fullScreenAuxiliary]
        p.hidesOnDeactivate = false
        p.becomesKeyOnlyIfNeeded = true
        let host = WidgetHostingView(rootView:
            CalendarView(engine: engine, onClose: { [weak self] in self?.hide() }))
        host.frame = NSRect(origin: .zero, size: size)
        p.contentView = host
        observeFullscreen()
        return p
    }

    private func position(_ p: NSPanel) {
        guard let screen = NSScreen.main else { return }
        let vf = screen.visibleFrame
        let inset: CGFloat = 24
        p.setFrameOrigin(NSPoint(x: vf.maxX - p.frame.width - inset,
                                 y: vf.maxY - p.frame.height - inset))
    }
}

import SwiftUI

private struct P {
    var speed = 0.013, amp = 5.0, thr = 0.52, jit = 0.0, red = 0.0, pulse = 0.0
    static func target(_ s: FormState) -> P {
        switch s {
        case .idle:     return P(speed: 0.013, amp: 5,  thr: 0.52, jit: 0,   red: 0, pulse: 0)
        case .thinking: return P(speed: 0.055, amp: 8,  thr: 0.46, jit: 0.6, red: 0, pulse: 0)
        case .speaking: return P(speed: 0.030, amp: 13, thr: 0.48, jit: 0,   red: 0, pulse: 1)
        case .alert:    return P(speed: 0.085, amp: 10, thr: 0.44, jit: 2.6, red: 1, pulse: 0.4)
        }
    }
}

private final class Clock {
    var phase = 0.0
    var last: Double? = nil
    var cur = P()
    var amp = 0.0
}

/// The machine's body: a volumetric point cloud whose motion, density, color and
/// agitation are driven by `state`, tinted by the active core's `accent`.
struct PointCloudView: View {
    var state: FormState
    var accent: Color
    var level: Double = 0          // live voice amplitude (0..1) while speaking

    @State private var clock = Clock()
    private static let start = Date()

    var body: some View {
        TimelineView(.animation) { tl in
            Canvas { ctx, size in
                draw(&ctx, size, tl.date.timeIntervalSince(Self.start))
            }
        }
    }

    private func draw(_ ctx: inout GraphicsContext, _ size: CGSize, _ now: Double) {
        let tgt = P.target(state)
        let dt = clock.last.map { min(now - $0, 0.1) } ?? 0
        clock.last = now
        let k = min(dt * 4, 1)
        var c = clock.cur
        c.speed += (tgt.speed - c.speed) * k
        c.amp += (tgt.amp - c.amp) * k
        c.thr += (tgt.thr - c.thr) * k
        c.jit += (tgt.jit - c.jit) * k
        c.red += (tgt.red - c.red) * k
        c.pulse += (tgt.pulse - c.pulse) * k
        clock.cur = c
        clock.phase += dt * c.speed * 60
        let t = clock.phase

        // drive the speaking pulse from the live voice amplitude (smoothed + gamma-lifted)
        clock.amp += (level - clock.amp) * min(dt * 16, 1)
        let env = c.pulse * pow(max(0, clock.amp), 0.6)

        let w = size.width, h = size.height, cx = w / 2, cy = h / 2
        let amp = c.amp * (1 + env * 3.4)
        let thr = c.thr - env * 0.11
        let step: CGFloat = 8

        var py: CGFloat = 0
        while py < h {
            var px: CGFloat = 0
            while px < w {
                let dist = hypot((px - cx) * 0.9, (py - cy) * 1.25)
                let shape = max(0, 1.18 - dist / (0.62 * h))
                let n = sin(px * 0.03 + t) + sin(py * 0.025 - t * 0.8)
                    + sin((px + py) * 0.02 + t * 0.6) + sin(dist * 0.05 - t * 1.1)
                var v = Double(n + 4) / 8 * 0.55 + Double(shape) * 0.6
                if c.pulse > 0.3 { v += env * 0.5 * sin(Double(py) * 0.04 + t * 4) }
                if v >= thr {
                    let jx = c.jit > 0 ? Double.random(in: -1...1) * c.jit * 3 : 0
                    let dy = (v - 0.5) * amp + (c.jit > 0 ? Double.random(in: -1...1) * c.jit * 3 : 0)
                    let a = min(1, 0.3 + v * 0.7)
                    let s: CGFloat = v > 0.86 ? 2.2 : 1.4
                    var dot = Path()
                    dot.addRect(CGRect(x: px + jx, y: Double(py) + dy, width: s, height: s))
                    ctx.fill(dot, with: .color(color(v, c.red).opacity(a)))
                }
                px += step
            }
            py += step
        }
    }

    private func color(_ v: Double, _ red: Double) -> Color {
        let hot = v > 0.86, mid = v > 0.74 && v <= 0.86
        if red > 0.5 {
            return hot ? Color.white : Color(red: 0.9, green: 0.25, blue: 0.22)
        }
        if hot { return Color(red: 0.78, green: 1.0, blue: 0.82) }
        if mid { return Color(red: 0.89, green: 0.63, blue: 0.16) }
        return accent
    }
}

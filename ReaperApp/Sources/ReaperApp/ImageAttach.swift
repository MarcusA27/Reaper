import AppKit

/// A picked image staged for transmission: the data URL the engine forwards to
/// Grok, plus a thumbnail for the input strip.
struct Attachment: Identifiable {
    let id = UUID()
    let dataURL: String
    let thumb: NSImage
}

/// Downscale (Grok bills 256 tokens per 448px tile, and the base64 rides a local
/// socket), re-encode as JPEG, and wrap as a `data:` URL for the chat/completions
/// `image_url`. Returns nil if the file isn't a decodable image.
func encodeForVision(_ url: URL) -> Attachment? {
    guard let src = NSImage(contentsOf: url) else { return nil }
    return encodeForVision(image: src)
}

func encodeForVision(image src: NSImage) -> Attachment? {
    let s = src.size
    guard s.width > 0, s.height > 0 else { return nil }
    let maxDim: CGFloat = 1568
    let scale = min(1, maxDim / max(s.width, s.height))
    let out = NSSize(width: floor(s.width * scale), height: floor(s.height * scale))

    let img = NSImage(size: out)
    img.lockFocus()
    src.draw(in: NSRect(origin: .zero, size: out), from: .zero, operation: .copy, fraction: 1)
    img.unlockFocus()

    guard let tiff = img.tiffRepresentation,
          let rep = NSBitmapImageRep(data: tiff),
          let jpeg = rep.representation(using: .jpeg, properties: [.compressionFactor: 0.8])
    else { return nil }
    return Attachment(dataURL: "data:image/jpeg;base64,\(jpeg.base64EncodedString())", thumb: img)
}

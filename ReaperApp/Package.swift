// swift-tools-version:6.0
import PackageDescription

let package = Package(
    name: "ReaperApp",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "ReaperApp",
            path: "Sources/ReaperApp",
            swiftSettings: [.swiftLanguageMode(.v5)]
        )
    ]
)

// swift-tools-version:5.9
// EchoCore: the platform-free text pipeline shared by the app and the
// keyboard. Pure Foundation, so `swift test` runs it on any Mac (CI runs it
// on every push) without a simulator.
import PackageDescription

let package = Package(
    name: "EchoCore",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "EchoCore", targets: ["EchoCore"]),
    ],
    targets: [
        .target(name: "EchoCore"),
        .testTarget(name: "EchoCoreTests", dependencies: ["EchoCore"]),
    ]
)

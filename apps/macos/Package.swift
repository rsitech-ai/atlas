// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "RSIAtlas",
    platforms: [
        .macOS(.v15),
    ],
    products: [
        .library(name: "RSIAtlasCore", targets: ["RSIAtlasCore"]),
        .executable(name: "RSIAtlas", targets: ["RSIAtlasApp"]),
    ],
    targets: [
        .target(name: "RSIAtlasCore"),
        .executableTarget(
            name: "RSIAtlasApp",
            dependencies: ["RSIAtlasCore"]
        ),
        .testTarget(
            name: "RSIAtlasCoreTests",
            dependencies: ["RSIAtlasCore"],
            resources: [.process("Fixtures")]
        ),
    ]
)

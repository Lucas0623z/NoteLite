// swift-tools-version: 5.9
// SPDX-License-Identifier: AGPL-3.0-or-later

import PackageDescription

let package = Package(
    name: "AudiverisCore",
    platforms: [.iOS(.v16), .macOS(.v13)],
    products: [
        .library(name: "AudiverisCore", targets: ["AudiverisCore"]),
        .executable(name: "audiveris-core-benchmark", targets: ["AudiverisCoreBenchmark"])
    ],
    targets: [
        .target(name: "AudiverisCore"),
        .executableTarget(name: "AudiverisCoreBenchmark", dependencies: ["AudiverisCore"]),
        .testTarget(
            name: "AudiverisCoreTests",
            dependencies: ["AudiverisCore"],
            resources: [.copy("Fixtures")]
        )
    ]
)

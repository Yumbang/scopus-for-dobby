import Foundation

/// Locates the ``scopus-for-dobby`` CLI binary and forks it as a detached
/// background daemon. Used by the "Launch daemon" affordance in the
/// daemon-down empty state.
///
/// Why not just rely on PATH? When a SwiftUI app is launched from Finder it
/// inherits a minimal environment that does *not* include the user's shell
/// PATH, so a naive ``Process()`` with ``executableURL = "scopus-for-dobby"``
/// fails even when the binary works fine in a terminal. The resolver below
/// mirrors the precedence the design plan specified for the CLIRunner.
enum DaemonLauncher {
    /// Candidate paths in priority order:
    /// 1. ``SCOPUS_FOR_DOBBY_BIN`` env var (explicit override).
    /// 2. ``~/.local/bin/scopus-for-dobby`` (uv tool install default).
    /// 3. Homebrew on Apple Silicon.
    /// 4. Homebrew on Intel / hand-installed.
    /// 5. Anything ``which scopus-for-dobby`` finds inside a login shell —
    ///    captures user PATH when launched from Finder.
    static func resolveBinaryPath() -> String? {
        let fm = FileManager.default

        if let override = ProcessInfo.processInfo.environment["SCOPUS_FOR_DOBBY_BIN"],
           !override.isEmpty,
           fm.isExecutableFile(atPath: override) {
            return override
        }

        let home = fm.homeDirectoryForCurrentUser.path
        let staticCandidates = [
            "\(home)/.local/bin/scopus-for-dobby",
            "/opt/homebrew/bin/scopus-for-dobby",
            "/usr/local/bin/scopus-for-dobby",
        ]
        for path in staticCandidates where fm.isExecutableFile(atPath: path) {
            return path
        }

        // Last resort: ask a login shell. We use zsh because that's macOS's
        // default; it picks up ~/.zshrc / ~/.zprofile PATH additions.
        if let viaShell = whichViaLoginShell(), fm.isExecutableFile(atPath: viaShell) {
            return viaShell
        }

        return nil
    }

    /// Spawn ``<binary> serve --background``, fully detached. Output is
    /// captured by the daemon itself into ``~/.scopus-for-dobby/daemon.log``.
    /// Returns once the process is launched (not once /health responds —
    /// caller polls separately).
    static func spawn(binary: String) throws {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: binary)
        process.arguments = ["serve", "--background"]
        // Don't inherit our stdout/stderr — the daemon writes its own log.
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        process.standardInput = FileHandle.nullDevice
        try process.run()
    }

    private static func whichViaLoginShell() -> String? {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        process.arguments = ["-l", "-c", "which scopus-for-dobby"]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            return nil
        }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        let raw = String(data: data, encoding: .utf8) ?? ""
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}

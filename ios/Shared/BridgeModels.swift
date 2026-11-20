import Foundation
import EchoCore

/// Where the app's dictation session is. The keyboard draws its mic button
/// from this, so every case has to be something a person can see.
enum SessionPhase: String, Codable, Sendable {
    /// No audio session. Tapping the mic opens the app to start one.
    case off
    /// Mic is warm in the background; a tap starts recording instantly.
    case ready
    case recording
    /// Audio stopped; turning it into text.
    case transcribing
    /// The last attempt failed; `message` says why in plain words.
    case failed
}

/// What the app publishes for the keyboard. Written atomically to the App
/// Group container; the keyboard re-reads it on every Darwin notification
/// and on a short timer while recording (for the level meter).
struct BridgeState: Codable, Equatable, Sendable {
    var phase: SessionPhase = .off
    /// The app refreshes this about once a second while a session is alive.
    /// A stale heartbeat means the app was killed: treat the session as off.
    var heartbeat: Date = .distantPast
    var sessionEndsAt: Date?
    /// The command that started the current or last recording.
    var activeRequestID: UUID?
    /// 0...1 input level for the keyboard's meter.
    var level: Float = 0
    var message: String?
    var result: DictationResult?
    var engineName: String?

    static let heartbeatTimeout: TimeInterval = 4

    func isAlive(now: Date = Date()) -> Bool {
        phase != .off && now.timeIntervalSince(heartbeat) < Self.heartbeatTimeout
    }

    /// The phase the keyboard should show, treating a dead app as off.
    func effectivePhase(now: Date = Date()) -> SessionPhase {
        isAlive(now: now) ? phase : .off
    }
}

struct DictationResult: Codable, Equatable, Sendable {
    var requestID: UUID
    var text: String
    var createdAt: Date
}

/// A request from the keyboard. IDs make every command idempotent: the app
/// ignores a command ID it has already handled.
struct BridgeCommand: Codable, Equatable, Sendable {
    enum Kind: String, Codable, Sendable {
        case start
        case stop
        case cancel
        case endSession
    }

    var id: UUID = UUID()
    var kind: Kind
    /// For `stop`/`cancel`: the start command being finished.
    var requestID: UUID?
    var style: DictationStyle?
    var createdAt: Date = Date()
}

import Foundation
import EchoCore

/// Settings both the app and the keyboard read. Stored in the App Group's
/// UserDefaults so a change in the app reaches the keyboard straight away;
/// the app also mirrors them to the account (CloudSettings) when signed in,
/// so a reinstall or a second phone gets them back.
final class SharedSettings: @unchecked Sendable {
    static let shared = SharedSettings()

    private let defaults: UserDefaults

    init(appGroup: String = Brand.appGroup) {
        defaults = UserDefaults(suiteName: appGroup) ?? .standard
    }

    private enum Key {
        static let style = "style"
        static let sessionMinutes = "sessionMinutes"
        static let haptics = "haptics"
        static let onboarded = "onboarded"
        static let language = "language"
        static let aiRefine = "aiRefine"
        static let autoReturn = "autoReturn"
        static let updatedAt = "settingsUpdatedAt"
    }

    /// Bumped on every local change; cloud sync keeps the newer side.
    var updatedAt: Date {
        get { defaults.object(forKey: Key.updatedAt) as? Date ?? .distantPast }
        set { defaults.set(newValue, forKey: Key.updatedAt) }
    }

    private func touch() { updatedAt = Date() }

    var style: DictationStyle {
        get { defaults.string(forKey: Key.style).flatMap(DictationStyle.init(rawValue:)) ?? .casual }
        set { defaults.set(newValue.rawValue, forKey: Key.style); touch() }
    }

    /// How long the mic stays ready in the background after the last
    /// dictation. 0 means until the person ends the session.
    var sessionMinutes: Int {
        get { defaults.object(forKey: Key.sessionMinutes) as? Int ?? 5 }
        set { defaults.set(newValue, forKey: Key.sessionMinutes); touch() }
    }

    static let sessionChoices = [1, 5, 15, 60, 0]

    static func sessionLabel(_ minutes: Int) -> String {
        switch minutes {
        case 0: return "Until I end it"
        case 1: return "1 minute"
        case 60: return "1 hour"
        default: return "\(minutes) minutes"
        }
    }

    var haptics: Bool {
        get { defaults.object(forKey: Key.haptics) as? Bool ?? true }
        set { defaults.set(newValue, forKey: Key.haptics); touch() }
    }

    /// BCP-47 code. English uses the Parakeet engine; anything else uses the
    /// on-device Apple engine (the desktop app falls back the same way).
    var language: String {
        get { defaults.string(forKey: Key.language) ?? "en" }
        set { defaults.set(newValue, forKey: Key.language); touch() }
    }

    var aiRefine: Bool {
        get { defaults.object(forKey: Key.aiRefine) as? Bool ?? false }
        set { defaults.set(newValue, forKey: Key.aiRefine); touch() }
    }

    var hasOnboarded: Bool {
        get { defaults.bool(forKey: Key.onboarded) }
        set { defaults.set(newValue, forKey: Key.onboarded) }
    }
}

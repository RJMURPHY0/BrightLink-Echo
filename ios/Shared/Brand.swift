import Foundation

/// Every product name a person sees on iPhone comes from here, mirroring
/// brand.py on desktop. Identifiers that ship to the App Store (bundle IDs,
/// App Group, URL scheme) live in project.yml and are read from Info.plist,
/// so the app and the keyboard can never disagree about them.
enum Brand {
    static let productName = "BrightLink Echo"
    static let shortName = "Echo"
    static let companyName = "BRIGHTLINK (OS) LTD"
    static let websiteURL = URL(string: "https://brightlink.io")!
    static let privacyURL = URL(string: "https://brightlink.io/privacy")!
    static let supportEmail = "support@brightlink.io"

    /// The keyboard's name as it appears in Settings > Keyboards.
    static let keyboardName = "Echo"

    static var appGroup: String {
        (Bundle.main.object(forInfoDictionaryKey: "EchoAppGroup") as? String)
            ?? "group.io.brightlink.echo"
    }

    static var urlScheme: String {
        (Bundle.main.object(forInfoDictionaryKey: "EchoURLScheme") as? String)
            ?? "brightlinkecho"
    }

    /// Darwin notification names are global on the device, so they are
    /// prefixed with the App Group to keep them ours.
    static func notificationName(_ suffix: String) -> String {
        "\(appGroup).\(suffix)"
    }
}

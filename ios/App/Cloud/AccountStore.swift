import Foundation

/// A way to finish two-factor sign-in (mirrors mfa.py's method dicts).
struct SecondStepMethod: Identifiable, Hashable {
    var factorID: String
    var kind: String          // app | whatsapp | sms | email | backup
    var label: String?
    var destination: String?

    var id: String { factorID + kind }

    static let order = ["app", "whatsapp", "sms", "email", "backup"]
    static let sendsCode: Set<String> = ["email", "whatsapp", "sms"]

    var title: String {
        switch kind {
        case "app": return "Authenticator app"
        case "email": return "Email me a code"
        case "whatsapp": return "WhatsApp me a code"
        case "sms": return "Text me a code"
        default: return "Use a backup code"
        }
    }

    var prompt: String {
        switch kind {
        case "app": return "Enter the six-digit code from your authenticator app."
        case "email": return "We emailed a code to \(destination ?? "your email")."
        case "whatsapp": return "We sent a code to WhatsApp on \(destination ?? "your phone")."
        case "sms": return "We texted a code to \(destination ?? "your phone")."
        default: return "Enter one of your backup codes."
        }
    }

    /// mfa.clean_code
    func clean(_ text: String) -> String {
        if kind == "backup" {
            return String(text.uppercased().filter { $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-") }.prefix(9))
        }
        return String(text.filter(\.isNumber).prefix(6))
    }

    /// mfa.code_ready
    func ready(_ code: String) -> Bool {
        kind == "backup" ? code.filter { $0.isLetter || $0.isNumber }.count == 8 : code.count == 6
    }

    /// mfa.kind_of
    static func kind(forFriendlyName name: String?) -> String {
        switch name ?? "" {
        case "bl-email": return "email"
        case "bl-whatsapp": return "whatsapp"
        case "bl-sms": return "sms"
        case "bl-backup": return "backup"
        case let n where n.hasPrefix("bl-browser:"): return "browser"
        default: return "app"
        }
    }
}

/// The optional BrightLink account. Echo works fully without it; signing in
/// adds the shared vocabulary and snippets, AI refine, and the sign-off name.
@MainActor
final class AccountStore: ObservableObject {
    static let shared = AccountStore()

    enum Status: Equatable {
        case signedOut
        /// A saved session is being checked (never shows the sign-in form).
        case restoring
        case needsSecondStep
        case signedIn
    }

    @Published private(set) var status: Status = .signedOut
    @Published private(set) var session: AuthSession?
    /// Shown when restoring a saved session failed, so it is never silent.
    @Published private(set) var restoreProblem: String?
    @Published private(set) var senderName: String?

    private let service = SupabaseService()
    private let keychainAccount = "session"
    private var refreshTask: Task<AuthSession, Error>?

    var email: String? { session?.user.email }
    var displayName: String? { senderName ?? session?.user.fullName }
    var isSignedIn: Bool { status == .signedIn }

    private init() {
        if let data = Keychain.load(account: keychainAccount),
           let saved = try? JSONDecoder().decode(AuthSession.self, from: data) {
            session = saved
            status = saved.owesSecondStep ? .needsSecondStep : .restoring
        }
    }

    /// Restores a saved session in the background. Never blocks first paint;
    /// retries with backoff while offline and says so.
    func restore() {
        guard status == .restoring, let saved = session else { return }
        Task {
            var delay: UInt64 = 2
            for attempt in 0..<6 {
                do {
                    let fresh = saved.isExpired ? try await refreshed(saved) : saved
                    adopt(fresh)
                    restoreProblem = nil
                    return
                } catch let error as ServiceError where (400..<500).contains(error.status) {
                    // The refresh token was revoked or expired: sign in again.
                    signOutLocally(reason: "Your sign-in has ended. Sign in again.")
                    return
                } catch {
                    restoreProblem = attempt < 5
                        ? "Can't reach BrightLink to restore your sign-in. Retrying…"
                        : "Can't reach BrightLink. Echo still works; sign-in will retry next time."
                    try? await Task.sleep(nanoseconds: delay * 1_000_000_000)
                    delay = min(delay * 2, 30)
                }
            }
        }
    }

    // MARK: Sign in

    func signIn(email: String, password: String) async throws {
        let fresh = try await service.signIn(email: email.trimmingCharacters(in: .whitespaces), password: password)
        save(fresh)
        session = fresh
        if fresh.owesSecondStep {
            status = .needsSecondStep
        } else {
            adopt(fresh)
        }
    }

    /// Returns true when the account was created and signed in; false when
    /// the person must confirm their email first.
    func signUp(email: String, password: String, fullName: String, company: String) async throws -> Bool {
        guard let fresh = try await service.signUp(email: email, password: password,
                                                   fullName: fullName, company: company) else {
            return false
        }
        save(fresh)
        adopt(fresh)
        return true
    }

    func sendPasswordReset(email: String) async throws {
        try await service.sendPasswordReset(email: email)
    }

    func signOut() {
        let token = session?.accessToken
        signOutLocally(reason: nil)
        if let token { Task { await service.signOut(token: token) } }
    }

    private func signOutLocally(reason: String?) {
        Keychain.delete(account: keychainAccount)
        session = nil
        senderName = nil
        status = .signedOut
        restoreProblem = reason
        VocabularyLibrary.shared.accountChanged()
    }

    // MARK: Two-factor (auth.second_step_methods / verify_second_step)

    func secondStepMethods() async throws -> [SecondStepMethod] {
        guard let session else { return [] }
        do {
            let data = try await service.crm("/api/auth/mfa", body: ["action": "methods"], token: session.accessToken)
            let emailMayFinish = (data["emailMayFinish"] as? Bool) ?? false
            let listed = (data["methods"] as? [[String: Any]] ?? []).compactMap { m -> SecondStepMethod? in
                guard let kind = m["kind"] as? String else { return nil }
                return SecondStepMethod(factorID: (m["factorId"] as? String) ?? "", kind: kind,
                                        label: m["label"] as? String, destination: m["destination"] as? String)
            }
            return listed
                .filter { SecondStepMethod.order.contains($0.kind) && ($0.kind != "email" || emailMayFinish) }
                .sorted { SecondStepMethod.order.firstIndex(of: $0.kind)! < SecondStepMethod.order.firstIndex(of: $1.kind)! }
        } catch {
            // The web app is unreachable: an authenticator code still works
            // with Supabase alone (mfa.local_app_methods).
            let local = session.user.verifiedFactors
                .filter { ($0.factorType ?? "totp") == "totp" && SecondStepMethod.kind(forFriendlyName: $0.friendlyName) == "app" }
                .map { SecondStepMethod(factorID: $0.id, kind: "app", label: $0.friendlyName, destination: nil) }
            if local.isEmpty { throw error }
            return local
        }
    }

    func sendCode(for method: SecondStepMethod) async throws {
        guard let session else { return }
        _ = try await service.crm("/api/auth/mfa", body: ["action": "send", "factorId": method.factorID],
                                  token: session.accessToken)
    }

    /// Returns a note worth showing on success (few backup codes left).
    func verify(_ method: SecondStepMethod, code: String) async throws -> String? {
        guard let session else { throw ServiceError(message: "Your sign-in has ended. Sign in again.") }
        var factorID = method.factorID
        var totp = code
        var note: String?
        switch method.kind {
        case "app":
            break
        case "backup":
            let r = try await service.crm("/api/auth/mfa", body: ["action": "backup-use", "code": code],
                                          token: session.accessToken)
            factorID = (r["factorId"] as? String) ?? ""
            totp = (r["totp"] as? String) ?? ""
            if let left = r["remaining"] as? Int, left <= 2 {
                note = "\(left) backup code\(left == 1 ? "" : "s") left. Make new ones in the web app's security settings."
            }
        default:
            let r = try await service.crm("/api/auth/mfa", body: ["action": "verify", "factorId": factorID, "code": code],
                                          token: session.accessToken)
            totp = (r["totp"] as? String) ?? ""
        }
        guard !factorID.isEmpty, !totp.isEmpty else {
            throw ServiceError(message: "Could not finish the check. Try again.")
        }
        try await service.verifyFactor(factorID: factorID, code: totp, token: session.accessToken)
        // A fresh token carries aal2 (auth._refresh_after_step).
        let fresh = try await service.refresh(session.refreshToken)
        guard fresh.aal == "aal2" else { throw ServiceError(message: "Could not finish signing in. Try again.") }
        save(fresh)
        adopt(fresh)
        return note
    }

    func cancelSecondStep() { signOut() }

    // MARK: Tokens for other services

    /// A current access token, refreshed if needed. Nil when signed out or
    /// while the second step is owed (that session never hands out its token).
    func validToken() async -> String? {
        guard status == .signedIn, let current = session else { return nil }
        guard current.isExpired else { return current.accessToken }
        do {
            let fresh = try await refreshed(current)
            adopt(fresh)
            return fresh.accessToken
        } catch {
            return nil
        }
    }

    private func refreshed(_ old: AuthSession) async throws -> AuthSession {
        // One refresh at a time: refresh tokens are single-use.
        if let refreshTask { return try await refreshTask.value }
        let task = Task { try await service.refresh(old.refreshToken) }
        refreshTask = task
        defer { refreshTask = nil }
        let fresh = try await task.value
        save(fresh)
        return fresh
    }

    private func adopt(_ fresh: AuthSession) {
        session = fresh
        status = fresh.owesSecondStep ? .needsSecondStep : .signedIn
        guard status == .signedIn else { return }
        Task { await loadSenderName() }
        VocabularyLibrary.shared.accountChanged()
    }

    private func save(_ s: AuthSession) {
        if let data = try? JSONEncoder().encode(s) { Keychain.save(data, account: keychainAccount) }
    }

    private func loadSenderName() async {
        guard let s = session, let token = await validToken() else { return }
        let rows = try? await service.select("org_members",
                                             query: "select=display_name,sender_name&user_id=eq.\(s.user.id)&limit=1",
                                             token: token)
        if let row = rows?.first {
            let name = ((row["display_name"] as? String) ?? (row["sender_name"] as? String) ?? "")
                .trimmingCharacters(in: .whitespaces)
            senderName = name.isEmpty ? nil : name
        }
    }

}

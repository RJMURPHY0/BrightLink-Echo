import Foundation
import Security

/// The shared BrightLink Supabase project (one account everywhere). The
/// publishable key is public by design and already committed in the desktop
/// app (config.py); every table is protected by row-level security, which
/// checks auth.uid() server-side, so nothing here trusts the client.
enum SupabaseConfig {
    static let url = URL(string: "https://ijeeghdxokfvlfarojlm.supabase.co")!
    static let publishableKey = "sb_publishable_G96rQQGq8BEtutrsdusjlQ_R0WxNzFw" // gitleaks:allow
    /// The CRM origin that hosts the AI relay and the two-factor route.
    static let appURL = URL(string: "https://app.brightlink.io")!
}

struct AuthSession: Codable, Equatable {
    var accessToken: String
    var refreshToken: String
    var expiresAt: Date
    var user: AuthUser

    var isExpired: Bool { Date() >= expiresAt.addingTimeInterval(-60) }

    /// "aal2" once the second step is done.
    var aal: String {
        let parts = accessToken.split(separator: ".")
        guard parts.count > 1 else { return "aal1" }
        var b64 = String(parts[1]).replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        while b64.count % 4 != 0 { b64 += "=" }
        guard let data = Data(base64Encoded: b64),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return "aal1" }
        return (obj["aal"] as? String) == "aal2" ? "aal2" : "aal1"
    }

    /// Mirrors mfa.owes_second_step: a verified factor and a non-aal2 token.
    var owesSecondStep: Bool {
        !user.verifiedFactors.isEmpty && aal != "aal2"
    }
}

struct AuthUser: Codable, Equatable {
    var id: String
    var email: String?
    var fullName: String?
    var factors: [Factor]

    struct Factor: Codable, Equatable {
        var id: String
        var status: String
        var factorType: String?
        var friendlyName: String?
    }

    var verifiedFactors: [Factor] { factors.filter { $0.status == "verified" } }
}

struct ServiceError: LocalizedError {
    var message: String
    var status: Int = 0
    var code: String = ""
    var errorDescription: String? { message }

    static let noConnection = ServiceError(message: "No connection. Check your internet and try again.")
}

/// Minimal Supabase Auth + PostgREST over URLSession.
struct SupabaseService {
    private let session: URLSession

    init() {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 20
        config.waitsForConnectivity = false
        session = URLSession(configuration: config)
    }

    // MARK: Auth

    func signIn(email: String, password: String) async throws -> AuthSession {
        let data = try await post("/auth/v1/token?grant_type=password",
                                  body: ["email": email, "password": password], token: nil)
        return try Self.parseSession(data)
    }

    func refresh(_ refreshToken: String) async throws -> AuthSession {
        let data = try await post("/auth/v1/token?grant_type=refresh_token",
                                  body: ["refresh_token": refreshToken], token: nil)
        return try Self.parseSession(data)
    }

    func signUp(email: String, password: String, fullName: String, company: String) async throws -> AuthSession? {
        let body: [String: Any] = ["email": email, "password": password,
                                   "data": ["full_name": fullName, "company_name": company]]
        let data = try await post("/auth/v1/signup", body: body, token: nil)
        // With email confirmation on, sign-up returns a user but no session.
        return try? Self.parseSession(data)
    }

    func sendPasswordReset(email: String) async throws {
        _ = try await post("/auth/v1/recover", body: ["email": email], token: nil)
    }

    func signOut(token: String) async {
        _ = try? await post("/auth/v1/logout", body: [:], token: token)
    }

    /// Supabase's own TOTP verify (challenge + verify), as auth._supabase_verify.
    func verifyFactor(factorID: String, code: String, token: String) async throws {
        let challenge = try await post("/auth/v1/factors/\(factorID)/challenge", body: [:], token: token)
        guard let obj = try JSONSerialization.jsonObject(with: challenge) as? [String: Any],
              let challengeID = obj["id"] as? String else {
            throw ServiceError(message: "Could not start the check. Try again.")
        }
        do {
            _ = try await post("/auth/v1/factors/\(factorID)/verify",
                               body: ["challenge_id": challengeID, "code": code], token: token)
        } catch {
            throw ServiceError(message: "That code was not accepted. Check it and try again.")
        }
    }

    // MARK: Database (PostgREST)

    func select(_ table: String, query: String, token: String) async throws -> [[String: Any]] {
        var request = URLRequest(url: URL(string: "\(SupabaseConfig.url.absoluteString)/rest/v1/\(table)?\(query)")!)
        request.httpMethod = "GET"
        authorize(&request, token: token)
        let data = try await send(request)
        return (try JSONSerialization.jsonObject(with: data) as? [[String: Any]]) ?? []
    }

    func upsert(_ table: String, rows: [[String: Any]], token: String) async throws {
        guard !rows.isEmpty else { return }
        var request = URLRequest(url: URL(string: "\(SupabaseConfig.url.absoluteString)/rest/v1/\(table)")!)
        request.httpMethod = "POST"
        authorize(&request, token: token)
        request.setValue("resolution=merge-duplicates,return=minimal", forHTTPHeaderField: "Prefer")
        request.httpBody = try JSONSerialization.data(withJSONObject: rows)
        _ = try await send(request)
    }

    // MARK: BrightLink CRM routes (same origin as the AI relay)

    func crm(_ path: String, body: [String: Any], token: String) async throws -> [String: Any] {
        var request = URLRequest(url: SupabaseConfig.appURL.appendingPathComponent(path))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        request.timeoutInterval = 25
        let data = try await send(request)
        return (try JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
    }

    // MARK: Plumbing

    private func authorize(_ request: inout URLRequest, token: String?) {
        request.setValue(SupabaseConfig.publishableKey, forHTTPHeaderField: "apikey")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token ?? SupabaseConfig.publishableKey)", forHTTPHeaderField: "Authorization")
    }

    private func post(_ path: String, body: [String: Any], token: String?) async throws -> Data {
        var request = URLRequest(url: URL(string: SupabaseConfig.url.absoluteString + path)!)
        request.httpMethod = "POST"
        authorize(&request, token: token)
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        return try await send(request)
    }

    private func send(_ request: URLRequest) async throws -> Data {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw ServiceError.noConnection
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            let raw = (obj?["error_description"] as? String) ?? (obj?["msg"] as? String)
                ?? (obj?["message"] as? String) ?? (obj?["error"] as? String)
            throw ServiceError(message: Self.friendly(raw, status: status), status: status,
                               code: (obj?["code"] as? String) ?? (obj?["error_code"] as? String) ?? "")
        }
        return data
    }

    private static func friendly(_ raw: String?, status: Int) -> String {
        let text = (raw ?? "").lowercased()
        if text.contains("invalid login") { return "That email and password don't match." }
        if text.contains("email not confirmed") { return "Confirm your email first: check your inbox for the link." }
        if text.contains("already registered") { return "There's already an account with that email. Sign in instead." }
        if status == 429 { return "Too many tries just now. Wait a minute and try again." }
        if let raw, !raw.isEmpty { return raw }
        return "Something went wrong (\(status)). Try again."
    }

    static func parseSession(_ data: Data) throws -> AuthSession {
        guard let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let access = obj["access_token"] as? String,
              let refresh = obj["refresh_token"] as? String,
              let user = obj["user"] as? [String: Any],
              let id = user["id"] as? String else {
            throw ServiceError(message: "Could not finish signing in. Try again.")
        }
        let expiresAt: Date
        if let at = obj["expires_at"] as? Double {
            expiresAt = Date(timeIntervalSince1970: at)
        } else {
            expiresAt = Date().addingTimeInterval((obj["expires_in"] as? Double) ?? 3600)
        }
        let meta = user["user_metadata"] as? [String: Any]
        let factors = (user["factors"] as? [[String: Any]] ?? []).compactMap { f -> AuthUser.Factor? in
            guard let fid = f["id"] as? String else { return nil }
            return AuthUser.Factor(id: fid, status: (f["status"] as? String) ?? "",
                                   factorType: f["factor_type"] as? String,
                                   friendlyName: f["friendly_name"] as? String)
        }
        return AuthSession(accessToken: access, refreshToken: refresh, expiresAt: expiresAt,
                           user: AuthUser(id: id, email: user["email"] as? String,
                                          fullName: meta?["full_name"] as? String, factors: factors))
    }
}

/// The signed-in session lives in the Keychain (this device only, available
/// after first unlock so background refreshes work).
enum Keychain {
    private static let service = "io.brightlink.echo.session"

    static func save(_ data: Data, account: String) {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                    kSecAttrService as String: service,
                                    kSecAttrAccount as String: account]
        SecItemDelete(query as CFDictionary)
        var add = query
        add[kSecValueData as String] = data
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(add as CFDictionary, nil)
    }

    static func load(account: String) -> Data? {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                    kSecAttrService as String: service,
                                    kSecAttrAccount as String: account,
                                    kSecReturnData as String: true,
                                    kSecMatchLimit as String: kSecMatchLimitOne]
        var out: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &out) == errSecSuccess else { return nil }
        return out as? Data
    }

    static func delete(account: String) {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                    kSecAttrService as String: service,
                                    kSecAttrAccount as String: account]
        SecItemDelete(query as CFDictionary)
    }
}

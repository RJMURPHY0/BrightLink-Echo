import SwiftUI

/// Sign in to the shared BrightLink account, including the second step.
struct SignInView: View {
    @EnvironmentObject private var account: AccountStore
    @Environment(\.dismiss) private var dismiss

    enum Mode { case signIn, create, reset }

    @State private var mode: Mode = .signIn
    @State private var email = ""
    @State private var password = ""
    @State private var fullName = ""
    @State private var company = ""
    @State private var busy = false
    @State private var problem: String?
    @State private var notice: String?

    var body: some View {
        NavigationStack {
            Group {
                if account.status == .needsSecondStep {
                    SecondStepView(onDone: { dismiss() })
                } else {
                    form
                }
            }
            .background(Theme.background.ignoresSafeArea())
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") {
                        if account.status == .needsSecondStep { account.cancelSecondStep() }
                        dismiss()
                    }
                }
            }
        }
        .onChange(of: account.status) { _, status in
            if status == .signedIn { dismiss() }
        }
    }

    private var form: some View {
        Form {
            Section {
                Picker("", selection: $mode) {
                    Text("Sign in").tag(Mode.signIn)
                    Text("Create account").tag(Mode.create)
                }
                .pickerStyle(.segmented)
                .listRowBackground(Color.clear)
                .opacity(mode == .reset ? 0 : 1)
            }
            Section {
                if mode == .create {
                    TextField("Full name", text: $fullName).textContentType(.name)
                    TextField("Company", text: $company).textContentType(.organizationName)
                }
                TextField("Email", text: $email)
                    .textContentType(.username)
                    .keyboardType(.emailAddress)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                if mode != .reset {
                    SecureField("Password", text: $password)
                        .textContentType(mode == .create ? .newPassword : .password)
                }
            } footer: {
                if mode == .reset {
                    Text("We'll email you a link to set a new password.")
                }
            }
            if let problem {
                Text(problem).foregroundStyle(Theme.error).font(.footnote)
            }
            if let notice {
                Text(notice).foregroundStyle(Theme.success).font(.footnote)
            }
            Section {
                Button {
                    submit()
                } label: {
                    HStack {
                        if busy { ProgressView().padding(.trailing, 6) }
                        Text(buttonTitle)
                    }
                    .frame(maxWidth: .infinity)
                }
                .buttonStyle(PrimaryButtonStyle(enabled: canSubmit))
                .disabled(!canSubmit || busy)
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets())
                if mode == .signIn {
                    Button("Forgot password?") { mode = .reset; problem = nil }
                        .frame(maxWidth: .infinity)
                } else if mode == .reset {
                    Button("Back to sign in") { mode = .signIn; problem = nil }
                        .frame(maxWidth: .infinity)
                }
            }
        }
        .scrollContentBackground(.hidden)
        .navigationTitle(mode == .create ? "Create account" : (mode == .reset ? "Reset password" : "Sign in"))
    }

    private var buttonTitle: String {
        switch mode {
        case .signIn: return "Sign in"
        case .create: return "Create account"
        case .reset: return "Send reset link"
        }
    }

    private var canSubmit: Bool {
        let hasEmail = email.contains("@") && email.contains(".")
        switch mode {
        case .signIn: return hasEmail && !password.isEmpty
        case .create: return hasEmail && password.count >= 8 && !fullName.isEmpty
        case .reset: return hasEmail
        }
    }

    private func submit() {
        busy = true
        problem = nil
        notice = nil
        Task {
            do {
                switch mode {
                case .signIn:
                    try await account.signIn(email: email, password: password)
                case .create:
                    let signedIn = try await account.signUp(email: email, password: password, fullName: fullName, company: company)
                    if !signedIn {
                        notice = "Check your email to confirm your account, then sign in."
                        mode = .signIn
                    }
                case .reset:
                    try await account.sendPasswordReset(email: email)
                    notice = "If there's an account for that email, a reset link is on its way."
                }
            } catch {
                problem = error.localizedDescription
            }
            busy = false
        }
    }
}

private struct SecondStepView: View {
    let onDone: () -> Void
    @EnvironmentObject private var account: AccountStore
    @State private var methods: [SecondStepMethod] = []
    @State private var method: SecondStepMethod?
    @State private var code = ""
    @State private var busy = false
    @State private var loading = true
    @State private var problem: String?
    @State private var note: String?
    @FocusState private var focused: Bool

    var body: some View {
        Form {
            Section {
                Text("Your account uses two-step sign-in.")
                    .font(.system(size: 17, weight: .semibold))
            }
            if loading {
                ProgressView()
            } else if let method {
                Section {
                    Text(method.prompt)
                    TextField(method.kind == "backup" ? "XXXX-XXXX" : "123456", text: $code)
                        .keyboardType(method.kind == "backup" ? .asciiCapable : .numberPad)
                        .textContentType(.oneTimeCode)
                        .font(.system(size: 22, weight: .semibold, design: .monospaced))
                        .focused($focused)
                        .onChange(of: code) { _, v in
                            let cleaned = method.clean(v)
                            if cleaned != v { code = cleaned }
                        }
                }
                if let problem { Text(problem).foregroundStyle(Theme.error).font(.footnote) }
                Section {
                    Button {
                        verify(method)
                    } label: {
                        HStack {
                            if busy { ProgressView().padding(.trailing, 6) }
                            Text("Verify")
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(PrimaryButtonStyle(enabled: method.ready(code)))
                    .disabled(!method.ready(code) || busy)
                    .listRowBackground(Color.clear)
                    .listRowInsets(EdgeInsets())
                    if methods.count > 1 {
                        Button("Use another way") { self.method = nil; code = ""; problem = nil }
                            .frame(maxWidth: .infinity)
                    }
                }
            } else {
                Section("Choose how to finish signing in") {
                    ForEach(methods) { m in
                        Button(m.title) { choose(m) }
                    }
                }
                if let problem { Text(problem).foregroundStyle(Theme.error).font(.footnote) }
            }
        }
        .scrollContentBackground(.hidden)
        .navigationTitle("Two-step sign-in")
        .task { await load() }
    }

    private func load() async {
        loading = true
        do {
            methods = try await account.secondStepMethods()
            if methods.count == 1 { choose(methods[0]) }
            if methods.isEmpty { problem = "No way to finish signing in is left. Ask your admin to reset two-factor." }
        } catch {
            problem = error.localizedDescription
        }
        loading = false
    }

    private func choose(_ m: SecondStepMethod) {
        method = m
        code = ""
        problem = nil
        focused = true
        if SecondStepMethod.sendsCode.contains(m.kind) {
            Task {
                do { try await account.sendCode(for: m) } catch { problem = error.localizedDescription }
            }
        }
    }

    private func verify(_ m: SecondStepMethod) {
        busy = true
        problem = nil
        Task {
            do {
                note = try await account.verify(m, code: code)
                onDone()
            } catch {
                problem = error.localizedDescription
            }
            busy = false
        }
    }
}

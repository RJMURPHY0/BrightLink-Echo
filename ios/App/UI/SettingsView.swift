import EchoCore
import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var account: AccountStore
    @EnvironmentObject private var model: ModelStore
    @EnvironmentObject private var formatting: FormattingSettings
    @EnvironmentObject private var history: HistoryStore
    @EnvironmentObject private var router: Router
    @Environment(\.dismiss) private var dismiss
    @State private var sessionMinutes = SharedSettings.shared.sessionMinutes
    @State private var haptics = SharedSettings.shared.haptics
    @State private var language = SharedSettings.shared.language
    @State private var showSignIn = false
    @State private var confirmDeleteHistory = false
    @State private var confirmDeleteModel = false

    private struct Language: Identifiable {
        let id: String
        let name: String
    }

    private let languages: [Language] = [
        Language(id: "en", name: "English"), Language(id: "fr", name: "French"),
        Language(id: "de", name: "German"), Language(id: "es", name: "Spanish"),
        Language(id: "it", name: "Italian"), Language(id: "pt", name: "Portuguese"),
        Language(id: "nl", name: "Dutch"), Language(id: "pl", name: "Polish"),
    ]

    var body: some View {
        NavigationStack {
            Form {
                Section("Account") {
                    switch account.status {
                    case .signedIn:
                        LabeledContent("Signed in", value: account.email ?? "")
                        if let name = account.displayName { LabeledContent("Name", value: name) }
                        Button("Sign out", role: .destructive) { account.signOut() }
                    case .restoring:
                        HStack { ProgressView(); Text("Signing you in…").padding(.leading, 8) }
                    default:
                        Button("Sign in to BrightLink") { showSignIn = true }
                        Text("Optional. Brings your vocabulary and snippets from your PC, and turns on AI refine.")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                    if let problem = account.restoreProblem {
                        Text(problem).font(.footnote).foregroundStyle(Theme.error)
                    }
                }

                Section {
                    Picker("Keep mic ready for", selection: $sessionMinutes) {
                        ForEach(SharedSettings.sessionChoices, id: \.self) { m in
                            Text(SharedSettings.sessionLabel(m)).tag(m)
                        }
                    }
                    .onChange(of: sessionMinutes) { _, v in SharedSettings.shared.sessionMinutes = v }
                    Picker("Language", selection: $language) {
                        ForEach(languages) { Text($0.name).tag($0.id) }
                    }
                    .onChange(of: language) { _, v in
                        SharedSettings.shared.language = v
                        DictationController.shared.warmEngine()
                    }
                    Toggle("Keyboard haptics", isOn: $haptics)
                        .onChange(of: haptics) { _, v in SharedSettings.shared.haptics = v }
                } header: {
                    Text("Dictation")
                } footer: {
                    Text("While the mic is ready, dictation starts instantly from the keyboard. Echo only keeps audio while you're dictating. A longer time uses a little more battery.")
                }

                Section {
                    switch model.state {
                    case .ready:
                        LabeledContent("Echo voice model", value: "Ready")
                        Button("Remove model", role: .destructive) { confirmDeleteModel = true }
                    case .downloading(let f):
                        LabeledContent("Echo voice model", value: "\(Int(f * 100))%")
                        ProgressView(value: f).tint(Theme.accent)
                    case .failed(let why):
                        Text(why).foregroundStyle(Theme.error)
                        Button("Try again") { model.download() }
                    case .notDownloaded:
                        LabeledContent("Echo voice model", value: "Not downloaded")
                        Button("Download (about 500 MB)") { model.download() }
                    }
                } header: {
                    Text("Speech")
                } footer: {
                    Text(language.hasPrefix("en")
                         ? "English uses the Echo voice model (Parakeet, the same as Echo on PC). Other languages, and English before the model downloads, use Apple's on-device speech recognition."
                         : "This language uses Apple's on-device speech recognition.")
                }

                Section("Formatting") {
                    Toggle("Smart punctuation", isOn: $formatting.options.autoPunctuate)
                    Picker("Full stop at the end", selection: $formatting.options.endPunctuation) {
                        Text("Smart").tag(EndPunctuation.smart)
                        Text("Always").tag(EndPunctuation.always)
                        Text("Never").tag(EndPunctuation.never)
                    }
                    Toggle("Spoken punctuation (\"comma\", \"new line\")", isOn: $formatting.options.spokenPunctuation)
                    Toggle("Numbered and bulleted lists", isOn: $formatting.options.autoLists)
                    Toggle("Email sign-offs", isOn: $formatting.options.emailFormat)
                    Toggle("Fix sound-alike words", isOn: $formatting.options.homophoneFix)
                    Toggle("Match my vocabulary loosely", isOn: $formatting.options.vocabFuzzy)
                }

                Section("Your words") {
                    NavigationLink("Vocabulary and snippets") { VocabularyView() }
                }

                Section("Keyboard") {
                    Button("Show keyboard setup again") {
                        dismiss()
                        router.setupStep = .keyboard
                        router.showingSetup = true
                    }
                    Button("Open iPhone Settings") { openAppSettings() }
                }

                Section {
                    Button("Delete all dictation history", role: .destructive) { confirmDeleteHistory = true }
                    Link("Privacy policy", destination: Brand.privacyURL)
                } header: {
                    Text("Privacy")
                } footer: {
                    Text("Speech is turned into text on this iPhone. History stays on this iPhone. Vocabulary and snippets back up to your BrightLink account when you're signed in, like Echo on PC. AI refine sends the text you choose to refine to BrightLink.")
                }

                Section("Diagnostics") {
                    NavigationLink("Recent problems") { DiagnosticsView() }
                }

                Section {
                    LabeledContent("Version", value: Self.version)
                    Text("\(Brand.productName) by \(Brand.companyName)")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            .scrollContentBackground(.hidden)
            .background(Theme.background.ignoresSafeArea())
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
            .sheet(isPresented: $showSignIn) { SignInView() }
            .confirmationDialog("Delete all dictation history from this iPhone?", isPresented: $confirmDeleteHistory, titleVisibility: .visible) {
                Button("Delete history", role: .destructive) { history.deleteAll() }
            }
            .confirmationDialog("Remove the Echo voice model? You can download it again later.", isPresented: $confirmDeleteModel, titleVisibility: .visible) {
                Button("Remove model", role: .destructive) { model.delete() }
            }
        }
    }

    static var version: String {
        let v = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "?"
        let b = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "?"
        return "\(v) (\(b))"
    }
}

struct DiagnosticsView: View {
    @State private var events = ErrorLog.read()

    var body: some View {
        List {
            if events.isEmpty {
                Text("No problems recorded.").foregroundStyle(.secondary)
            }
            ForEach(events) { e in
                VStack(alignment: .leading, spacing: 4) {
                    Text(e.type).font(.system(size: 15, weight: .semibold))
                    Text(e.detail).font(.system(size: 13)).foregroundStyle(.secondary).textSelection(.enabled)
                    Text(e.date.formatted()).font(.system(size: 12)).foregroundStyle(.secondary)
                }
            }
        }
        .navigationTitle("Recent problems")
        .toolbar {
            if !events.isEmpty {
                Button("Clear") { ErrorLog.clear(); events = [] }
            }
        }
    }
}

struct VocabularyView: View {
    @EnvironmentObject private var library: VocabularyLibrary
    @EnvironmentObject private var account: AccountStore
    @State private var editingTerm: VocabularyEntry?
    @State private var editingSnippet: Snippet?

    var body: some View {
        List {
            Section {
                if library.activeVocabulary.isEmpty {
                    Text("Add names, brands and jargon so Echo spells them your way.")
                        .foregroundStyle(.secondary)
                }
                ForEach(library.activeVocabulary) { entry in
                    Button {
                        editingTerm = entry
                    } label: {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(entry.term).foregroundStyle(Theme.text)
                            if !entry.soundsLike.isEmpty {
                                Text("Sounds like: " + entry.soundsLike.joined(separator: ", "))
                                    .font(.footnote).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
                .onDelete { idx in idx.map { library.activeVocabulary[$0] }.forEach(library.deleteTerm) }
                Button("Add a word") { editingTerm = VocabularyEntry(term: "") }
            } header: {
                Text("Vocabulary")
            }

            Section {
                ForEach(library.activeSnippets) { s in
                    Button {
                        editingSnippet = s
                    } label: {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(s.trigger).foregroundStyle(Theme.text)
                            Text(s.body).font(.footnote).foregroundStyle(.secondary).lineLimit(2)
                        }
                    }
                }
                .onDelete { idx in idx.map { library.activeSnippets[$0] }.forEach(library.deleteSnippet) }
                Button("Add a snippet") { editingSnippet = Snippet(name: "", trigger: "", body: "") }
            } header: {
                Text("Snippets")
            } footer: {
                Text(account.isSignedIn
                     ? "Synced with your BrightLink account, so these match Echo on your PC."
                     : "Sign in to sync these with Echo on your PC.")
            }
            if let problem = library.syncProblem {
                Text(problem).font(.footnote).foregroundStyle(Theme.error)
            }
        }
        .navigationTitle("Your words")
        .refreshable { await library.sync() }
        .sheet(item: $editingTerm) { TermEditor(entry: $0) }
        .sheet(item: $editingSnippet) { SnippetEditor(snippet: $0) }
    }
}

private struct TermEditor: View {
    @State var entry: VocabularyEntry
    @State private var soundsLike = ""
    @State private var problem: String?
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                TextField("Word or name (e.g. BrightLink)", text: $entry.term)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                TextField("Sounds like (optional, comma-separated)", text: $soundsLike)
                    .textInputAutocapitalization(.never)
                if let problem { Text(problem).foregroundStyle(Theme.error).font(.footnote) }
            }
            .navigationTitle(entry.term.isEmpty ? "Add a word" : "Edit word")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { save() }
                        .disabled(entry.term.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
            .onAppear { soundsLike = entry.soundsLike.joined(separator: ", ") }
        }
        .presentationDetents([.medium])
    }

    private func save() {
        let term = entry.term.trimmingCharacters(in: .whitespaces)
        let variants = soundsLike.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        for v in variants {
            if let error = TextExpansion.validateSoundsLike(v, term: term) {
                problem = error
                return
            }
        }
        entry.term = term
        entry.soundsLike = variants
        VocabularyLibrary.shared.saveTerm(entry)
        dismiss()
    }
}

private struct SnippetEditor: View {
    @State var snippet: Snippet
    @State private var problem: String?
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                TextField("When I say… (e.g. my address)", text: $snippet.trigger)
                    .textInputAutocapitalization(.never)
                TextField("Type this", text: $snippet.body, axis: .vertical)
                    .lineLimit(3...8)
                if let problem { Text(problem).foregroundStyle(Theme.error).font(.footnote) }
            }
            .navigationTitle("Snippet")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        if let error = TextExpansion.validateTrigger(snippet.trigger) {
                            problem = error
                            return
                        }
                        if snippet.name.isEmpty { snippet.name = snippet.trigger }
                        VocabularyLibrary.shared.saveSnippet(snippet)
                        dismiss()
                    }
                    .disabled(snippet.trigger.isEmpty || snippet.body.isEmpty)
                }
            }
        }
    }
}

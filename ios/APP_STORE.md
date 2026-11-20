# App Store submission kit (draft)

Everything App Store Connect asks for, drafted against what the code actually does. Check each claim against the build you submit.

## Listing

- **Name:** BrightLink Echo (30 characters max; must be unique on the Store, so check availability when creating the app record)
- **Subtitle:** Talk, and it types. Anywhere.
- **Category:** Productivity (secondary: Business)
- **Keywords:** dictation,voice typing,speech to text,keyboard,transcribe,voice notes,talk to text,punctuation
- **Promotional text:** Speak naturally and Echo types clean, punctuated text in any app: Messages, Mail, WhatsApp, Notes and more.

**Description**

> Echo turns your voice into clean, punctuated text in any app, as fast as you can speak.
>
> Tap the mic on the Echo keyboard, talk naturally, tap ✓, and your words appear, with the punctuation, capitals and paragraphs already done. Say "new line", "comma" or "question mark" when you want them. Echo turns spoken lists into numbered lists, spells your names and jargon the way you do, and leaves out the ums and the false starts.
>
> • Fast: text appears the moment you stop talking
> • Private: speech is turned into text on your iPhone
> • Works offline once set up
> • Four writing styles: Formal, Casual, very casual and Excited, switchable from the keyboard
> • Your vocabulary and snippets, shared with Echo on your PC when you sign in to BrightLink
> • Optional AI refine for BrightLink accounts: tidy up, make it formal or casual, shorten, or turn it into an email
>
> Echo needs Full Access for its keyboard so the keyboard and the app can pass your words between them. Echo never records what you type on its keyboard.

## App Review notes (paste into "Notes")

> Echo is a dictation keyboard. iOS does not allow keyboard extensions to use the microphone, so when the user taps the mic on the Echo keyboard and the microphone is not already on, the keyboard opens the Echo app (its own containing app) to start the microphone. The user then returns to their app with the system back link and keeps talking. While the user has chosen to keep it ready (1 minute to 1 hour, set in Echo's Settings), the app keeps the audio session running in the background so later dictations start instantly. The system's orange microphone indicator is shown the whole time, and the user can turn it off from the app at any time. No audio is kept except while the user is dictating.
>
> Full Access is used only to share the dictated text and session state between the keyboard and the app through an App Group. The keyboard works as a normal typing keyboard without Full Access or a network connection.
>
> Speech recognition runs on the device (a Core ML speech model downloaded from Hugging Face on first use, or Apple's on-device recogniser). Signing in is optional; without an account every dictation feature works.
>
> To test: open Echo, follow setup, add the Echo keyboard in Settings > Echo > Keyboards with Allow Full Access, then open Notes, switch to the Echo keyboard and tap the mic.

Demo account: only needed for AI refine and vocabulary sync. Provide a BrightLink test account (email, password, no two-step) in "Sign-in required: No, but optional features need an account".

## Privacy (App Privacy questionnaire)

| Data | Collected? | Notes |
|---|---|---|
| Audio | **No** | Processed on device, never sent. Not stored after transcription. |
| Dictated text / history | **No** | Stored only on the device. |
| Text sent to AI refine | Yes, **only when the user taps a refine button while signed in** | "User Content > Other User Content", linked to the user's account, used for App Functionality, not tracking. Sent to BrightLink's relay (app.brightlink.io), which forwards it to its AI provider. |
| Email address, name | Yes, if the user signs in | "Contact Info", linked, App Functionality |
| Vocabulary and snippets | Yes, if signed in | "User Content > Other User Content", linked, App Functionality (sync with the PC app) |
| Usage data, diagnostics, identifiers | **No** | The error log stays on the device. |
| Tracking | **No** | No third-party SDKs, analytics or ads. |

**Privacy policy URL:** `https://brightlink.io/privacy`. It must exist and cover the iPhone app before submission. **Required reason APIs:** UserDefaults (CA92.1, app's own data and App Group). Declared in `App/Resources/PrivacyInfo.xcprivacy` and `Keyboard/PrivacyInfo.xcprivacy`. The app's manifest also declares what signing in collects (email, name) and the user content sent for AI refine and vocabulary sync, all linked to the account, used for app functionality, never tracking. Check FluidAudio's own manifest after the first archive.

## Export compliance

`ITSAppUsesNonExemptEncryption = NO` is set in Info.plist: the app uses only HTTPS/OS encryption.

## Screenshots needed

6.9" iPhone, at least 3: keyboard dictating in Messages, the style menu, the Home screen with Your impact. Use real UI from a TestFlight build, never mock-ups of other companies' apps.

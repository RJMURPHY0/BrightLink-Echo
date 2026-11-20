import SwiftUI
import UIKit

/// The Echo keyboard. A complete typing keyboard (App Review 4.4.1: it must
/// work without Full Access or a network), plus the Echo bar that drives
/// dictation in the app.
final class KeyboardViewController: UIInputViewController {
    private var model: KeyboardModel!
    private var host: UIHostingController<KeyboardRootView>?
    private var heightConstraint: NSLayoutConstraint?

    override func viewDidLoad() {
        super.viewDidLoad()
        model = KeyboardModel(controller: self)
        let root = KeyboardRootView(model: model)
        let host = UIHostingController(rootView: root)
        host.view.backgroundColor = .clear
        host.view.translatesAutoresizingMaskIntoConstraints = false
        addChild(host)
        view.addSubview(host.view)
        NSLayoutConstraint.activate([
            host.view.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            host.view.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            host.view.topAnchor.constraint(equalTo: view.topAnchor),
            host.view.bottomAnchor.constraint(equalTo: view.bottomAnchor),
        ])
        host.didMove(toParent: self)
        self.host = host

        let height = view.heightAnchor.constraint(equalToConstant: KeyboardMetrics.totalHeight)
        height.priority = UILayoutPriority(999)
        height.isActive = true
        heightConstraint = height
    }

    override func viewWillAppear(_ animated: Bool) {
        super.viewWillAppear(animated)
        model.appear()
    }

    override func viewDidDisappear(_ animated: Bool) {
        super.viewDidDisappear(animated)
        model.disappear()
    }

    override func textDidChange(_ textInput: UITextInput?) {
        super.textDidChange(textInput)
        model.textContextChanged()
    }

    /// Opens a URL from inside a keyboard extension.
    ///
    /// Extensions can't call UIApplication.open directly, and since iOS 18 the
    /// old `openURL:` selector does nothing. The supported-in-practice route
    /// (used by shipping App Store keyboards) is to find the UIApplication in
    /// the responder chain and call `open(_:options:completionHandler:)`
    /// through the Objective-C runtime.
    @discardableResult
    func openURL(_ url: URL) -> Bool {
        typealias OpenFunction = @convention(c) (AnyObject, Selector, NSURL, NSDictionary, AnyObject?) -> Void
        let selector = NSSelectorFromString("openURL:options:completionHandler:")
        var responder: UIResponder? = self
        while let current = responder {
            if let application = current as? UIApplication,
               application.responds(to: selector),
               let method = application.method(for: selector) {
                let open = unsafeBitCast(method, to: OpenFunction.self)
                open(application, selector, url as NSURL, NSDictionary(), nil)
                return true
            }
            responder = current.next
        }
        return false
    }
}

enum KeyboardMetrics {
    static let barHeight: CGFloat = 54
    static let keyHeight: CGFloat = 46
    static let rowSpacing: CGFloat = 10
    static let rows: CGFloat = 4
    static var totalHeight: CGFloat { barHeight + rows * keyHeight + (rows - 1) * rowSpacing + 14 }
}

/// The globe key. Uses UIKit so a long press shows the system keyboard list
/// (handleInputModeList), which SwiftUI gestures can't trigger.
struct GlobeKey: UIViewRepresentable {
    let controller: UIInputViewController

    func makeUIView(context: Context) -> UIButton {
        let button = UIButton(type: .system)
        button.setImage(UIImage(systemName: "globe"), for: .normal)
        button.tintColor = .label
        button.accessibilityLabel = "Next keyboard"
        button.addTarget(controller, action: #selector(UIInputViewController.handleInputModeList(from:with:)),
                         for: .allTouchEvents)
        return button
    }

    func updateUIView(_ uiView: UIButton, context: Context) {}
}

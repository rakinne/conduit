// ConduitHead — native macOS shell for the conduit head.
//
// A borderless, transparent, always-on-top window hosting a WKWebView that
// loads the repo's index.html in overlay mode. Click-through by default so it
// never blocks your work; a global hotkey (⌥⌘H) toggles "grab mode" to drag /
// interact / fade. The head watches your cursor anywhere on screen via a
// global NSEvent monitor (permission-free for mouse events) feeding the page's
// window.__conduitPoint() hook.
//
// Single-file build: see build.sh. No Xcode project, no dependencies beyond
// the system frameworks.

import Cocoa
import WebKit
import Carbon.HIToolbox

// Borderless windows refuse key/main status by default; we need it so the
// uplink text field and SPACE-to-speak work while grabbed.
final class OverlayWindow: NSWindow {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
}

private func fourCharCode(_ s: String) -> OSType {
    var r: OSType = 0
    for b in s.utf8.prefix(4) { r = (r << 8) + OSType(b) }
    return r
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var window: OverlayWindow!
    private var webView: WKWebView!
    private var statusItem: NSStatusItem!

    private var cursorGlobalMonitor: Any?   // fires while another app is active
    private var cursorLocalMonitor: Any?    // fires while we are active (grabbed)
    private var dragMonitor: Any?           // grab-mode: drag to move window
    private var scrollMonitor: Any?         // grab-mode: scroll to fade
    private var hotKeyRef: EventHotKeyRef?

    private var grabbed = false
    private var opacity: CGFloat = 1.0
    private var lastFeed: TimeInterval = 0

    private let defaults = UserDefaults.standard
    private let kFrame = "windowFrame"
    private let kOpacity = "windowOpacity"
    private let defaultSize = NSSize(width: 360, height: 460)

    // MARK: Lifecycle

    func applicationDidFinishLaunching(_ note: Notification) {
        NSApp.setActivationPolicy(.accessory)   // no Dock icon; lives in the menu bar

        opacity = CGFloat(defaults.object(forKey: kOpacity) as? Double ?? 1.0)
        if opacity < 0.15 { opacity = 1.0 }

        buildWindow()
        buildWebView()
        buildStatusItem()
        installCursorMonitors()
        registerHotKey()

        NotificationCenter.default.addObserver(
            self, selector: #selector(saveFrame), name: NSWindow.didMoveNotification, object: window)

        window.orderFrontRegardless()
    }

    func applicationDidResignActive(_ note: Notification) {
        // Clicking away from a grabbed head returns it to click-through.
        if grabbed { setGrab(false) }
    }

    func applicationSupportsSecureRestorableState(_ app: NSApplication) -> Bool { true }

    // MARK: Window

    private func buildWindow() {
        window = OverlayWindow(contentRect: savedFrameOrDefault(),
                               styleMask: [.borderless], backing: .buffered, defer: false)
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = false
        window.level = .floating
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        window.ignoresMouseEvents = true          // click-through by default
        window.isReleasedWhenClosed = false
        window.alphaValue = opacity
    }

    private func savedFrameOrDefault() -> NSRect {
        if let s = defaults.string(forKey: kFrame) {
            let r = NSRectFromString(s)
            if r.width > 50, r.height > 50 { return r }
        }
        let vis = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        return NSRect(x: vis.maxX - defaultSize.width - 40,
                      y: vis.minY + 60,
                      width: defaultSize.width, height: defaultSize.height)
    }

    @objc private func saveFrame() {
        defaults.set(NSStringFromRect(window.frame), forKey: kFrame)
    }

    // MARK: WebView

    private func buildWebView() {
        let cfg = WKWebViewConfiguration()
        // Set the overlay flag before the page's scripts run.
        cfg.userContentController.addUserScript(
            WKUserScript(source: "window.__CONDUIT_OVERLAY = true;",
                         injectionTime: .atDocumentStart, forMainFrameOnly: true))

        webView = WKWebView(frame: window.contentView!.bounds, configuration: cfg)
        webView.autoresizingMask = [.width, .height]
        webView.setValue(false, forKey: "drawsBackground")   // transparent WebView
        if #available(macOS 12.0, *) { webView.underPageBackgroundColor = .clear }
        window.contentView?.addSubview(webView)

        let webDir = resourceWebDir()
        let index = webDir.appendingPathComponent("index.html")
        webView.loadFileURL(index, allowingReadAccessTo: webDir)
    }

    /// Bundled assets live in Contents/Resources/web; fall back to the repo
    /// root next to the binary for `swiftc && ./ConduitHead` dev runs.
    private func resourceWebDir() -> URL {
        if let res = Bundle.main.resourceURL {
            let web = res.appendingPathComponent("web")
            if FileManager.default.fileExists(atPath: web.appendingPathComponent("index.html").path) {
                return web
            }
        }
        let exeDir = Bundle.main.executableURL?.deletingLastPathComponent()
            ?? URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        return exeDir
    }

    // MARK: Menu-bar item

    private func buildStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let btn = statusItem.button {
            btn.title = "◉"
            btn.toolTip = "Conduit Head"
        }
        rebuildMenu()
    }

    private func rebuildMenu() {
        let menu = NSMenu()

        let header = NSMenuItem(title: "CONDUIT · THE END", action: nil, keyEquivalent: "")
        header.isEnabled = false
        menu.addItem(header)
        menu.addItem(.separator())

        let grab = NSMenuItem(title: grabbed ? "Release — click-through" : "Grab — interact",
                              action: #selector(toggleGrabFromMenu), keyEquivalent: "h")
        grab.keyEquivalentModifierMask = [.command, .option]
        grab.target = self
        menu.addItem(grab)

        menu.addItem(makeOpacityItem())

        menu.addItem(.separator())

        let reset = NSMenuItem(title: "Reset Position", action: #selector(resetPosition), keyEquivalent: "")
        reset.target = self
        menu.addItem(reset)

        let quit = NSMenuItem(title: "Quit Conduit Head", action: #selector(quit), keyEquivalent: "q")
        quit.target = self
        menu.addItem(quit)

        statusItem.menu = menu
    }

    private func makeOpacityItem() -> NSMenuItem {
        let item = NSMenuItem()
        let container = NSView(frame: NSRect(x: 0, y: 0, width: 210, height: 40))

        let label = NSTextField(labelWithString: "Opacity")
        label.frame = NSRect(x: 14, y: 21, width: 180, height: 14)
        label.font = NSFont.systemFont(ofSize: 11)
        label.textColor = .secondaryLabelColor
        container.addSubview(label)

        let slider = NSSlider(value: Double(opacity), minValue: 0.15, maxValue: 1.0,
                              target: self, action: #selector(opacityChanged(_:)))
        slider.frame = NSRect(x: 14, y: 2, width: 182, height: 18)
        container.addSubview(slider)

        item.view = container
        return item
    }

    @objc private func opacityChanged(_ s: NSSlider) { setOpacity(CGFloat(s.doubleValue)) }

    private func setOpacity(_ v: CGFloat) {
        opacity = max(0.15, min(1.0, v))
        window.alphaValue = opacity
        defaults.set(Double(opacity), forKey: kOpacity)
    }

    @objc private func resetPosition() {
        defaults.removeObject(forKey: kFrame)
        window.setFrame(savedFrameOrDefault(), display: true, animate: true)
    }

    @objc private func quit() { NSApp.terminate(nil) }
    @objc private func toggleGrabFromMenu() { setGrab(!grabbed) }

    // MARK: Grab mode

    private func setGrab(_ on: Bool) {
        guard on != grabbed else { return }
        grabbed = on
        window.ignoresMouseEvents = !on

        if on {
            NSApp.activate(ignoringOtherApps: true)
            window.makeKeyAndOrderFront(nil)
            installGrabMonitors()
        } else {
            removeGrabMonitors()
            window.orderFrontRegardless()
            NSApp.deactivate()                 // hand focus back to the previous app
        }

        webView.evaluateJavaScript("window.__conduitGrab && window.__conduitGrab(\(on))",
                                   completionHandler: nil)
        rebuildMenu()
    }

    private func installGrabMonitors() {
        // Drag anywhere to move the window (the overlay page has no drag handlers).
        dragMonitor = NSEvent.addLocalMonitorForEvents(matching: .leftMouseDragged) { [weak self] e in
            guard let self = self, self.grabbed else { return e }
            var origin = self.window.frame.origin
            origin.x += e.deltaX
            origin.y -= e.deltaY                // view delta is y-down; screen is y-up
            self.window.setFrameOrigin(origin)
            return nil                          // consume so it isn't also a text drag
        }
        // Scroll to fade.
        scrollMonitor = NSEvent.addLocalMonitorForEvents(matching: .scrollWheel) { [weak self] e in
            guard let self = self, self.grabbed else { return e }
            self.setOpacity(self.opacity + CGFloat(e.scrollingDeltaY) * 0.004)
            self.rebuildMenu()
            return e
        }
    }

    private func removeGrabMonitors() {
        for m in [dragMonitor, scrollMonitor].compactMap({ $0 }) { NSEvent.removeMonitor(m) }
        dragMonitor = nil; scrollMonitor = nil
    }

    // MARK: Global cursor feed

    private func installCursorMonitors() {
        cursorGlobalMonitor = NSEvent.addGlobalMonitorForEvents(matching: .mouseMoved) { [weak self] _ in
            self?.feedCursor()
        }
        cursorLocalMonitor = NSEvent.addLocalMonitorForEvents(matching: .mouseMoved) { [weak self] e in
            self?.feedCursor(); return e
        }
    }

    private func feedCursor() {
        let now = ProcessInfo.processInfo.systemUptime
        if now - lastFeed < 0.016 { return }    // ~60 Hz cap
        lastFeed = now

        guard let scr = window.screen ?? NSScreen.main else { return }
        let mouse = NSEvent.mouseLocation        // screen coords, bottom-left origin
        let f = window.frame
        let halfW = scr.frame.width * 0.42
        let halfH = scr.frame.height * 0.42
        var nx = (mouse.x - f.midX) / halfW
        var ny = (f.midY - mouse.y) / halfH      // flip to page convention (down = +y)
        nx = max(-1, min(1, nx)); ny = max(-1, min(1, ny))

        webView.evaluateJavaScript(
            String(format: "window.__conduitPoint&&window.__conduitPoint(%.4f,%.4f)", nx, ny),
            completionHandler: nil)
    }

    // MARK: Global hotkey (⌥⌘H) — Carbon, no Accessibility permission needed

    private func registerHotKey() {
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard),
                                 eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { (_, _, userData) -> OSStatus in
            let me = Unmanaged<AppDelegate>.fromOpaque(userData!).takeUnretainedValue()
            DispatchQueue.main.async { me.setGrab(!me.grabbed) }
            return noErr
        }, 1, &spec, Unmanaged.passUnretained(self).toOpaque(), nil)

        let id = EventHotKeyID(signature: fourCharCode("CHDH"), id: 1)
        RegisterEventHotKey(UInt32(kVK_ANSI_H), UInt32(optionKey | cmdKey),
                            id, GetApplicationEventTarget(), 0, &hotKeyRef)
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()

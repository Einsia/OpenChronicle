// mac-ax-watcher — Long-running macOS Accessibility event monitor
//
// Monitors AX events (window focus, value changes, title changes, app activation)
// across all running applications. Outputs JSONL (one JSON per line) to stdout.
//
// Usage:
//   mac-ax-watcher
//
// Exit codes:
//   0 = normal exit (SIGTERM/SIGINT)
//   1 = general error
//   2 = accessibility not authorized
//
// Compile:
//   swiftc resources/mac-ax-watcher.swift -o resources/mac-ax-watcher -O

import AppKit
import ApplicationServices
import Foundation

// MARK: - Event Output

/// Thread-safe JSON line writer to stdout
final class EventWriter {
    private let lock = NSLock()

    func write(event: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: event, options: []),
              let line = String(data: data, encoding: .utf8)
        else { return }

        lock.lock()
        print(line)
        fflush(stdout)
        lock.unlock()
    }
}

let writer = EventWriter()

// MARK: - AX Helpers

func axString(_ element: AXUIElement, _ attribute: String) -> String? {
    var ref: CFTypeRef?
    let err = AXUIElementCopyAttributeValue(element, attribute as CFString, &ref)
    guard err == .success, let val = ref as? String else { return nil }
    return val
}

func axRole(_ element: AXUIElement) -> String? {
    return axString(element, kAXRoleAttribute as String)
}

func axSubrole(_ element: AXUIElement) -> String? {
    return axString(element, kAXSubroleAttribute as String)
}

/// True if the element itself is a secure text field.
func isSecureElement(_ el: AXUIElement) -> Bool {
    return axRole(el) == "AXTextField" && axSubrole(el) == "AXSecureTextField"
}

/// Check if the focused element is a secure text field (password)
func isFocusedSecure(_ appElement: AXUIElement) -> Bool {
    var ref: CFTypeRef?
    let err = AXUIElementCopyAttributeValue(
        appElement, kAXFocusedUIElementAttribute as CFString, &ref
    )
    guard err == .success, let focused = ref else { return false }
    // swiftlint:disable:next force_cast
    let el = focused as! AXUIElement
    return isSecureElement(el)
}

/// Return the currently focused UI element for an app, if any.
func focusedElement(_ appElement: AXUIElement) -> AXUIElement? {
    var ref: CFTypeRef?
    let err = AXUIElementCopyAttributeValue(
        appElement, kAXFocusedUIElementAttribute as CFString, &ref
    )
    guard err == .success, let focused = ref else { return nil }
    // swiftlint:disable:next force_cast
    return (focused as! AXUIElement)
}

/// Truncate a string to a maximum length, appending an ellipsis marker.
func truncate(_ s: String, _ maxLen: Int) -> String {
    if s.count <= maxLen { return s }
    return String(s.prefix(maxLen)) + "…"
}

/// Describe an AX element as a dictionary for JSONL output. Secure fields
/// have their ``value`` replaced with ``[REDACTED]`` but retain structural
/// metadata so the downstream model can still see that the user interacted
/// with a password-like field.
func describeElement(_ el: AXUIElement) -> [String: Any] {
    let role = axRole(el) ?? ""
    let subrole = axSubrole(el) ?? ""
    let title = truncate(axString(el, kAXTitleAttribute as String) ?? "", 200)
    let identifier = truncate(axString(el, kAXIdentifierAttribute as String) ?? "", 200)
    let rawValue = axString(el, kAXValueAttribute as String) ?? ""
    let value = isSecureElement(el) ? "[REDACTED]" : truncate(rawValue, 2000)
    return [
        "role": role,
        "subrole": subrole,
        "title": title,
        "identifier": identifier,
        "value": value,
    ]
}

/// Resolve the owning app (name + bundle id) for an AX element.
func appInfoForElement(_ el: AXUIElement) -> (pid: pid_t, name: String, bundleId: String) {
    var pid: pid_t = 0
    AXUIElementGetPid(el, &pid)
    if pid > 0, let app = NSRunningApplication(processIdentifier: pid) {
        return (pid, app.localizedName ?? "", app.bundleIdentifier ?? "")
    }
    return (pid, "", "")
}

/// ISO 8601 timestamp in the user's local timezone, matching the rest of
/// the watcher's output so downstream parsing is uniform.
func nowIsoLocal() -> String {
    let iso8601 = ISO8601DateFormatter()
    iso8601.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    iso8601.timeZone = TimeZone.current
    return iso8601.string(from: Date())
}

/// Get the window title from the frontmost window of an app
func getWindowTitle(_ appElement: AXUIElement) -> String {
    var ref: CFTypeRef?
    let err = AXUIElementCopyAttributeValue(
        appElement, kAXFocusedWindowAttribute as CFString, &ref
    )
    guard err == .success, let window = ref else { return "" }
    // swiftlint:disable:next force_cast
    let winEl = window as! AXUIElement
    return axString(winEl, kAXTitleAttribute as String) ?? ""
}

// MARK: - Interaction Tapper
//
// Captures raw user clicks and keystrokes via a passive CGEventTap, without
// storing any keystroke content. Rationale for the design:
//
//  * Mouse clicks (left/right) are discrete — on mouseDown we hit-test the
//    AX element at the cursor and emit a ``UserMouseClick`` event carrying
//    the clicked element's role / title / identifier / value plus the owning
//    app's window context.
//
//  * Keyboard input is aggregated — raw keyDowns only act as a **heartbeat**
//    that resets a debounce timer. When the timer fires (or the user
//    switches focus / app, or types continuously past a safety cap), we read
//    the currently focused element's final ``AXValue`` and emit a single
//    ``UserTextInput`` event. This avoids logging raw keystrokes (a
//    privacy-sensitive keylogger shape) and also sidesteps IME composition
//    noise — by the time the debounce fires, the IME has already committed
//    the composed text to AXValue, so the Chinese user who typed
//    ``ni hao <space>`` sees ``你好`` in the payload rather than the raw pinyin.
//
// Secure text fields (password inputs) are redacted at emit time via
// ``isSecureElement``. Bundle-level exclusion is handled downstream by the
// Python privacy filter (``MemoryPrivacyFilter``).

/// Default debounce window: wait this long after the last keystroke before
/// emitting a TextInput event. Resets on every keyDown. 5s matches the
/// product spec — long enough that short pauses mid-sentence don't
/// fragment a single "user typed something" intent.
let kTextInputDebounceSeconds: TimeInterval = 5.0

/// Safety cap on continuous typing without a flush. If the user types
/// uninterruptedly for this long we flush anyway so downstream consumers
/// see activity rather than waiting indefinitely for a pause.
let kTextInputMaxContinuousSeconds: TimeInterval = 60.0

final class InteractionTapper {
    private var eventTap: CFMachPort?
    private var runLoopSource: CFRunLoopSource?

    private let textLock = NSLock()
    private var textFlushTimer: DispatchSourceTimer?
    private var typingStartedAt: Date?
    // The element and app the user was typing into at the moment of the most
    // recent keyDown. We retain this so that a flush triggered by a focus
    // change still reads the value from the *previous* field, not the
    // new one. When nil, no typing is pending.
    private var typingElement: AXUIElement?
    private var typingApp: (pid: pid_t, name: String, bundleId: String) = (0, "", "")
    private var typingWindowTitle: String = ""

    /// Install the CGEventTap. Returns false if tap creation failed (usually
    /// means Input Monitoring permission has not been granted yet). Callers
    /// should log a warning but keep the rest of the watcher running.
    func start() -> Bool {
        let mask: CGEventMask =
            (1 << CGEventType.leftMouseDown.rawValue)
            | (1 << CGEventType.rightMouseDown.rawValue)
            | (1 << CGEventType.otherMouseDown.rawValue)
            | (1 << CGEventType.keyDown.rawValue)

        let userInfo = Unmanaged.passUnretained(self).toOpaque()
        guard let tap = CGEvent.tapCreate(
            tap: .cgSessionEventTap,
            place: .headInsertEventTap,
            options: .listenOnly,
            eventsOfInterest: mask,
            callback: interactionTapCallback,
            userInfo: userInfo
        ) else {
            return false
        }

        self.eventTap = tap
        let source = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0)
        self.runLoopSource = source
        CFRunLoopAddSource(CFRunLoopGetMain(), source, .commonModes)
        CGEvent.tapEnable(tap: tap, enable: true)
        return true
    }

    /// Called by the CGEventTap callback on a mouse-down event.
    func handleMouseDown(_ event: CGEvent, type: CGEventType) {
        // Typing in field A followed by clicking into field B should log as
        // "typed A, then clicked B" — flush the pending TextInput first so
        // the order of events is intuitive and we don't accidentally read
        // the new field's value (which is still empty at click time).
        flushText(reason: "mouse_click")

        let loc = event.location
        let systemWide = AXUIElementCreateSystemWide()
        var hit: AXUIElement?
        let err = AXUIElementCopyElementAtPosition(
            systemWide, Float(loc.x), Float(loc.y), &hit
        )

        var elementDict: [String: Any] = [:]
        var appInfo: (pid: pid_t, name: String, bundleId: String) = (0, "", "")
        var windowTitle = ""

        if err == .success, let el = hit {
            elementDict = describeElement(el)
            appInfo = appInfoForElement(el)
            if appInfo.pid > 0 {
                let appEl = AXUIElementCreateApplication(appInfo.pid)
                windowTitle = getWindowTitle(appEl)
                if isFocusedSecure(appEl) {
                    windowTitle = "[REDACTED]"
                }
            }
        } else {
            // Fallback: non-AX surface (e.g. some games). Still report the
            // click location plus the frontmost app so downstream consumers
            // see *something* happened.
            if let front = NSWorkspace.shared.frontmostApplication {
                appInfo = (
                    front.processIdentifier,
                    front.localizedName ?? "",
                    front.bundleIdentifier ?? ""
                )
            }
        }

        let button: String
        switch type {
        case .leftMouseDown: button = "left"
        case .rightMouseDown: button = "right"
        default: button = "other"
        }

        let details: [String: Any] = [
            "button": button,
            "x": loc.x,
            "y": loc.y,
            "element": elementDict,
        ]

        writer.write(event: [
            "event_type": "UserMouseClick",
            "pid": appInfo.pid,
            "app_name": appInfo.name,
            "bundle_id": appInfo.bundleId,
            "window_title": windowTitle,
            "timestamp": nowIsoLocal(),
            "details": details,
        ])
    }

    /// Called by the CGEventTap callback on a keyDown event.
    func handleKeyDown(_ event: CGEvent) {
        // ⌘ / ⌃ held = shortcut (⌘S, ⌃C, etc.), not typing. Skip so the
        // debounce timer doesn't get reset by a keybind. ⌥ is allowed
        // through because it's commonly used for alternate characters
        // (⌥+5 → ∞, ⌥+e → ´) — those are real text input.
        let flags = event.flags
        if flags.contains(.maskCommand) || flags.contains(.maskControl) {
            return
        }

        // Filter: navigation / function keys don't count as "typing".
        // CGEvent's ``keyboardGetUnicodeString`` returns private-use-area
        // codes (0xF700–0xF8FF) for arrows, F-keys, page up/down, etc.
        // Treat those as navigation and ignore. An empty result means the
        // event produced no character (also skip — probably a dead key).
        var length = 0
        var chars = [UniChar](repeating: 0, count: 4)
        event.keyboardGetUnicodeString(
            maxStringLength: 4,
            actualStringLength: &length,
            unicodeString: &chars
        )
        guard length > 0 else { return }
        for i in 0..<length {
            let c = chars[i]
            if c >= 0xF700 && c <= 0xF8FF { return }
        }

        textLock.lock()

        // Capture the target field on the first keystroke of a new burst.
        // Subsequent keystrokes just reset the timer; we deliberately do
        // not re-capture, because doing so mid-typing would overwrite the
        // original element if focus shifts briefly.
        if typingStartedAt == nil {
            typingStartedAt = Date()
            if let front = NSWorkspace.shared.frontmostApplication {
                let pid = front.processIdentifier
                typingApp = (
                    pid,
                    front.localizedName ?? "",
                    front.bundleIdentifier ?? ""
                )
                let appEl = AXUIElementCreateApplication(pid)
                typingWindowTitle = getWindowTitle(appEl)
                typingElement = focusedElement(appEl)
            }
        }

        // Safety cap: if the user has been typing continuously for the
        // entire max-duration window without a pause, force a flush so the
        // downstream consumer sees periodic signal rather than a silent
        // infinite hold.
        let shouldForceFlush: Bool
        if let start = typingStartedAt {
            shouldForceFlush = Date().timeIntervalSince(start) >= kTextInputMaxContinuousSeconds
        } else {
            shouldForceFlush = false
        }

        scheduleFlushTimerLocked(delay: kTextInputDebounceSeconds)
        textLock.unlock()

        if shouldForceFlush {
            flushText(reason: "max_duration")
        }
    }

    /// Emit a pending ``UserTextInput`` event if one is buffered. Safe to
    /// call from any thread; idempotent when there's nothing to flush.
    func flushText(reason: String) {
        textLock.lock()
        guard typingStartedAt != nil else {
            textLock.unlock()
            return
        }

        let element = typingElement
        let app = typingApp
        var windowTitle = typingWindowTitle

        // Reset state BEFORE unlocking so a concurrent keyDown on another
        // thread starts a fresh burst instead of appending to the one
        // we're about to emit.
        typingStartedAt = nil
        typingElement = nil
        typingApp = (0, "", "")
        typingWindowTitle = ""
        textFlushTimer?.cancel()
        textFlushTimer = nil
        textLock.unlock()

        var elementDict: [String: Any] = [:]
        if let el = element {
            elementDict = describeElement(el)
        }
        // Re-check secure state at emit time: the user may have typed into
        // a password field whose subrole we can only see on inspection.
        if app.pid > 0 {
            let appEl = AXUIElementCreateApplication(app.pid)
            if isFocusedSecure(appEl) {
                windowTitle = "[REDACTED]"
                if elementDict["value"] as? String != "[REDACTED]" {
                    elementDict["value"] = "[REDACTED]"
                }
            }
        }

        writer.write(event: [
            "event_type": "UserTextInput",
            "pid": app.pid,
            "app_name": app.name,
            "bundle_id": app.bundleId,
            "window_title": windowTitle,
            "timestamp": nowIsoLocal(),
            "details": [
                "reason": reason,
                "element": elementDict,
            ],
        ])
    }

    /// Re-enable the tap after the system disables it (e.g. because a
    /// callback took too long or the user held modifier keys across a
    /// system gesture). Without this the tap goes silent after the first
    /// stall.
    func reenableTap() {
        guard let tap = eventTap else { return }
        CGEvent.tapEnable(tap: tap, enable: true)
    }

    /// Schedule (or reschedule) the debounce timer. Caller must hold ``textLock``.
    private func scheduleFlushTimerLocked(delay: TimeInterval) {
        textFlushTimer?.cancel()
        let timer = DispatchSource.makeTimerSource(queue: .main)
        timer.schedule(deadline: .now() + delay, leeway: .milliseconds(100))
        timer.setEventHandler { [weak self] in
            self?.flushText(reason: "debounce")
        }
        timer.resume()
        textFlushTimer = timer
    }
}

/// C callback for the CGEventTap. Keep this fast — the system will disable
/// the tap if callbacks take too long. We do the minimum inline (unpacking
/// the userInfo pointer and dispatching by event type); the real work in
/// ``handleMouseDown`` / ``handleKeyDown`` is still synchronous but cheap.
func interactionTapCallback(
    proxy: CGEventTapProxy,
    type: CGEventType,
    event: CGEvent,
    refcon: UnsafeMutableRawPointer?
) -> Unmanaged<CGEvent>? {
    guard let refcon = refcon else { return Unmanaged.passUnretained(event) }
    let tapper = Unmanaged<InteractionTapper>.fromOpaque(refcon).takeUnretainedValue()

    switch type {
    case .leftMouseDown, .rightMouseDown, .otherMouseDown:
        tapper.handleMouseDown(event, type: type)
    case .keyDown:
        tapper.handleKeyDown(event)
    case .tapDisabledByTimeout, .tapDisabledByUserInput:
        tapper.reenableTap()
    default:
        break
    }
    return Unmanaged.passUnretained(event)
}

/// Process-wide interaction tapper. Declared at file scope so the C
/// callback can resolve it from a stable pointer and so the observer
/// callback (which runs on the same run loop) can invoke ``flushText``
/// whenever focus moves between fields or apps.
let interaction = InteractionTapper()

// MARK: - Observer Manager

/// Manages AX observers for all running applications
final class ObserverManager {
    private var observers: [pid_t: AXObserver] = [:]
    private let lock = NSLock()
    private let notifications: [String] = [
        kAXFocusedWindowChangedNotification as String,
        kAXTitleChangedNotification as String,
        kAXApplicationActivatedNotification as String,
    ]
    // Value changed is very noisy — we include it but the Python side debounces
    private let valueChangedNotification = kAXValueChangedNotification as String

    /// Set up observers for all currently running regular apps
    func observeAllRunning() {
        let apps = NSWorkspace.shared.runningApplications
        for app in apps {
            guard app.activationPolicy == .regular else { continue }
            guard !app.isHidden else { continue }
            addObserver(for: app.processIdentifier, name: app.localizedName ?? "Unknown",
                        bundleId: app.bundleIdentifier ?? "")
        }
    }

    /// Add an observer for a specific app
    func addObserver(for pid: pid_t, name: String, bundleId: String) {
        lock.lock()
        defer { lock.unlock() }

        // Skip if already observing
        if observers[pid] != nil { return }

        let appElement = AXUIElementCreateApplication(pid)

        // Create observer
        var observer: AXObserver?
        let err = AXObserverCreate(pid, observerCallback, &observer)
        guard err == .success, let obs = observer else {
            return
        }

        // Store app info in a context struct for the callback
        let context = AppContext(pid: pid, name: name, bundleId: bundleId)
        let contextPtr = Unmanaged.passRetained(context).toOpaque()

        // Register all notifications
        for notification in notifications {
            AXObserverAddNotification(obs, appElement, notification as CFString, contextPtr)
        }
        // Value changed on the app element (catches most value changes)
        AXObserverAddNotification(obs, appElement, valueChangedNotification as CFString, contextPtr)

        // Add to run loop
        CFRunLoopAddSource(
            CFRunLoopGetMain(),
            AXObserverGetRunLoopSource(obs),
            CFRunLoopMode.defaultMode
        )

        observers[pid] = obs
    }

    /// Remove observer for a specific app
    func removeObserver(for pid: pid_t) {
        lock.lock()
        defer { lock.unlock() }

        guard let obs = observers.removeValue(forKey: pid) else { return }

        CFRunLoopRemoveSource(
            CFRunLoopGetMain(),
            AXObserverGetRunLoopSource(obs),
            CFRunLoopMode.defaultMode
        )
    }

    /// Clean up all observers
    func removeAll() {
        lock.lock()
        let pids = Array(observers.keys)
        lock.unlock()

        for pid in pids {
            removeObserver(for: pid)
        }
    }
}

/// Context passed to AX observer callbacks
final class AppContext {
    let pid: pid_t
    let name: String
    let bundleId: String

    init(pid: pid_t, name: String, bundleId: String) {
        self.pid = pid
        self.name = name
        self.bundleId = bundleId
    }
}

/// C callback for AX observer events
func observerCallback(
    _ observer: AXObserver,
    _ element: AXUIElement,
    _ notification: CFString,
    _ refcon: UnsafeMutableRawPointer?
) {
    guard let refcon = refcon else { return }
    let context = Unmanaged<AppContext>.fromOpaque(refcon).takeUnretainedValue()

    let notificationStr = notification as String

    // When focus moves between fields or apps, flush any pending TextInput
    // first so the typed text is attributed to the *outgoing* field rather
    // than the new one the user just moved to.
    if notificationStr == kAXFocusedWindowChangedNotification as String
        || notificationStr == kAXApplicationActivatedNotification as String
    {
        interaction.flushText(reason: "focus_change")
    }

    // Get window title
    let appElement = AXUIElementCreateApplication(context.pid)
    var windowTitle = getWindowTitle(appElement)

    // Redact if focused element is a secure text field
    if isFocusedSecure(appElement) {
        windowTitle = "[REDACTED]"
    }

    let iso8601 = ISO8601DateFormatter()
    iso8601.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    iso8601.timeZone = TimeZone.current

    let event: [String: Any] = [
        "event_type": notificationStr,
        "pid": context.pid,
        "app_name": context.name,
        "bundle_id": context.bundleId,
        "window_title": windowTitle,
        "timestamp": iso8601.string(from: Date()),
    ]

    writer.write(event: event)
}

// MARK: - Main

func main() {
    // Check accessibility permission
    let trusted = AXIsProcessTrustedWithOptions(
        [kAXTrustedCheckOptionPrompt.takeUnretainedValue(): true] as CFDictionary
    )
    if !trusted {
        fputs("Accessibility permission not granted.\n", stderr)
        exit(2)
    }

    let manager = ObserverManager()

    // Observe all currently running apps
    manager.observeAllRunning()

    // Install the mouse/keyboard tap. Failure here means Input Monitoring
    // has not been granted — the tap stays off until the user approves, but
    // every other AX event keeps flowing. We surface the state as an
    // internal ``_`` event (filtered out of the main pipeline but visible
    // in the watcher's own log) so diagnostics can tell the difference
    // between "no interaction events observed" and "tap silently denied".
    if interaction.start() {
        writer.write(event: [
            "event_type": "_interaction_tap_installed",
            "pid": ProcessInfo.processInfo.processIdentifier,
            "app_name": "mac-ax-watcher",
            "bundle_id": "",
            "window_title": "",
            "timestamp": nowIsoLocal(),
        ])
    } else {
        fputs(
            "Warning: CGEventTap not installed (Input Monitoring permission missing?). "
                + "Mouse/keyboard events will not be captured.\n",
            stderr
        )
        writer.write(event: [
            "event_type": "_interaction_tap_denied",
            "pid": ProcessInfo.processInfo.processIdentifier,
            "app_name": "mac-ax-watcher",
            "bundle_id": "",
            "window_title": "",
            "timestamp": nowIsoLocal(),
        ])
    }

    // Watch for new app launches
    let workspace = NSWorkspace.shared
    workspace.notificationCenter.addObserver(
        forName: NSWorkspace.didLaunchApplicationNotification,
        object: nil,
        queue: .main
    ) { notification in
        guard let app = notification.userInfo?[NSWorkspace.applicationUserInfoKey]
            as? NSRunningApplication
        else { return }
        guard app.activationPolicy == .regular else { return }

        manager.addObserver(
            for: app.processIdentifier,
            name: app.localizedName ?? "Unknown",
            bundleId: app.bundleIdentifier ?? ""
        )
    }

    // Watch for app terminations
    workspace.notificationCenter.addObserver(
        forName: NSWorkspace.didTerminateApplicationNotification,
        object: nil,
        queue: .main
    ) { notification in
        guard let app = notification.userInfo?[NSWorkspace.applicationUserInfoKey]
            as? NSRunningApplication
        else { return }

        manager.removeObserver(for: app.processIdentifier)
    }

    // Handle SIGTERM/SIGINT for graceful shutdown
    let signalSource = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
    signal(SIGTERM, SIG_IGN)
    signalSource.setEventHandler {
        manager.removeAll()
        exit(0)
    }
    signalSource.resume()

    let intSource = DispatchSource.makeSignalSource(signal: SIGINT, queue: .main)
    signal(SIGINT, SIG_IGN)
    intSource.setEventHandler {
        manager.removeAll()
        exit(0)
    }
    intSource.resume()

    // Output a startup event
    let iso8601 = ISO8601DateFormatter()
    iso8601.formatOptions = [.withInternetDateTime]
    iso8601.timeZone = TimeZone.current
    writer.write(event: [
        "event_type": "_watcher_started",
        "pid": ProcessInfo.processInfo.processIdentifier,
        "app_name": "mac-ax-watcher",
        "bundle_id": "",
        "window_title": "",
        "timestamp": iso8601.string(from: Date()),
    ])

    // Run the main run loop forever
    CFRunLoopRun()
}

main()

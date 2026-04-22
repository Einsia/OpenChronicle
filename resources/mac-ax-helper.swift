// mac-ax-helper — macOS Accessibility Tree capture for context awareness
//
// Captures the AX element tree from running applications and outputs
// filtered, semantic JSON. Designed for LLM context injection — strips
// coordinates, visual chrome, and other noise that has no semantic value.
//
// Usage:
//   mac-ax-helper                       → frontmost app only
//   mac-ax-helper --all-visible         → all visible apps
//   mac-ax-helper --depth 8             → max traversal depth (default: 8)
//   mac-ax-helper --timeout 3           → per-app timeout in seconds (default: 3)
//
// Exit codes:
//   0 = success (JSON on stdout)
//   1 = general error
//   2 = accessibility not authorized
//
// Compile:
//   swiftc resources/mac-ax-helper.swift -o resources/mac-ax-helper -O -target arm64-apple-macos12.0 -swift-version 5

import AppKit
import ApplicationServices
import Foundation

// MARK: - Configuration

struct Config {
    var allVisible = false
    var appName: String? = nil  // --app-name: capture a specific app by name
    var focusedWindowOnly = false  // --focused-window-only: only capture the focused window
    var raw = false  // --raw: preserve the unfiltered AX tree for parser debugging
    var maxDepth = 100   // 0 = unlimited
    var timeout: TimeInterval = 3
    var maxValueLength = 1000
}

// MARK: - Filtered AX Node

/// Roles that are pure visual chrome — drop entirely (including children)
private let dropRoles: Set<String> = [
    "AXImage", "AXScrollBar", "AXValueIndicator", "AXSplitter",
    "AXColumn", "AXMenuBar", "AXGrowArea", "AXRuler",
    "AXMatte", "AXLayoutArea", "AXLayoutItem",
]

/// Roles that carry semantic text when they have a title or value
private let textBearingRoles: Set<String> = [
    "AXStaticText", "AXTextField", "AXTextArea", "AXLink",
    "AXButton", "AXMenuItem", "AXRadioButton", "AXCheckBox",
    "AXTab", "AXHeading", "AXCell", "AXRow",
    "AXWebArea", "AXPopUpButton", "AXMenuButton",
    "AXDisclosureTriangle", "AXComboBox", "AXSlider",
    "AXTabGroup",
]

/// Container roles that should be collapsed if they add no semantic value
private let containerRoles: Set<String> = [
    "AXGroup", "AXSplitGroup", "AXScrollArea", "AXList",
    "AXOutline", "AXBrowser", "AXDrawer", "AXSheet",
    "AXToolbar",
]

// MARK: - AX Helpers

func axValue(_ element: AXUIElement, _ attribute: String) -> CFTypeRef? {
    var ref: CFTypeRef?
    let err = AXUIElementCopyAttributeValue(element, attribute as CFString, &ref)
    guard err == .success else { return nil }
    return ref
}

func axString(_ element: AXUIElement, _ attribute: String) -> String? {
    guard let ref = axValue(element, attribute) else { return nil }
    return ref as? String
}

func axStringList(_ element: AXUIElement, _ attribute: String) -> [String] {
    guard let ref = axValue(element, attribute) else { return [] }

    if let values = ref as? [String] {
        return values
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    if let value = ref as? String {
        return value
            .split(whereSeparator: \.isWhitespace)
            .map(String.init)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    return []
}

func axInt(_ element: AXUIElement, _ attribute: String) -> Int? {
    guard let ref = axValue(element, attribute) else { return nil }
    return ref as? Int
}

func axBool(_ element: AXUIElement, _ attribute: String) -> Bool? {
    guard let ref = axValue(element, attribute) else { return nil }
    return ref as? Bool
}

func axChildren(_ element: AXUIElement) -> [AXUIElement] {
    guard let ref = axValue(element, kAXChildrenAttribute as String) else { return [] }
    guard let children = ref as? [AXUIElement] else { return [] }
    return children
}

func axAttributeNames(_ element: AXUIElement) -> [String] {
    var namesRef: CFArray?
    let err = AXUIElementCopyAttributeNames(element, &namesRef)
    guard err == .success, let names = namesRef as? [String] else { return [] }
    return names.sorted()
}

// MARK: - Tree Traversal with Filtering

struct AXNode {
    var role: String?
    var subrole: String?
    var title: String?
    var description: String?
    var value: String?
    var identifier: String?
    var domIdentifier: String?
    var domClassList: [String]
    var attributeNames: [String]
    var children: [AXNode]

    var isEmpty: Bool {
        return subrole == nil
            && title == nil
            && description == nil
            && value == nil
            && identifier == nil
            && domIdentifier == nil
            && domClassList.isEmpty
            && attributeNames.isEmpty
            && children.isEmpty
    }

    func toDict() -> [String: Any]? {
        if isEmpty { return nil }

        var dict: [String: Any] = [:]
        if let r = role { dict["role"] = r }
        if let sr = subrole { dict["subrole"] = sr }
        if let t = title { dict["title"] = t }
        if let d = description { dict["description"] = d }
        if let v = value { dict["value"] = v }
        if let id = identifier { dict["identifier"] = id }
        if let domID = domIdentifier { dict["domIdentifier"] = domID }
        if !domClassList.isEmpty { dict["domClassList"] = domClassList }
        if !attributeNames.isEmpty { dict["attributeNames"] = attributeNames }
        if !children.isEmpty {
            let childDicts = children.compactMap { $0.toDict() }
            if !childDicts.isEmpty {
                dict["children"] = childDicts
            }
        }
        // A node with only a role and no text and no children is noise
        if dict.count == 1 && dict.keys.first == "role" { return nil }
        return dict
    }
}

func traverseElement(
    _ element: AXUIElement,
    depth: Int,
    config: Config
) -> AXNode? {
    if config.maxDepth > 0 && depth > config.maxDepth { return nil }

    let role = axString(element, kAXRoleAttribute as String)

    // Drop visual chrome roles entirely in filtered mode.
    if !config.raw, let role = role, dropRoles.contains(role) {
        return nil
    }

    // Check for secure text field — redact value
    let subrole = axString(element, kAXSubroleAttribute as String)
    let isSecure = role == "AXTextField" && subrole == "AXSecureTextField"
    let rawDescription = axString(element, kAXDescriptionAttribute as String)?
        .trimmingCharacters(in: .whitespacesAndNewlines)
    let rawIdentifier = axString(element, kAXIdentifierAttribute as String)?
        .trimmingCharacters(in: .whitespacesAndNewlines)
    let rawDOMIdentifier = axString(element, "AXDOMIdentifier")?
        .trimmingCharacters(in: .whitespacesAndNewlines)
    let domClassList = axStringList(element, "AXDOMClassList")
    let attributeNames = config.raw ? axAttributeNames(element) : []

    // Get text content
    var title = axString(element, kAXTitleAttribute as String)?.trimmingCharacters(in: .whitespacesAndNewlines)
    var value: String?

    if isSecure {
        value = "[REDACTED]"
    } else {
        if let rawValue = axString(element, kAXValueAttribute as String) {
            var v = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
            if v.count > config.maxValueLength {
                v = String(v.prefix(config.maxValueLength)) + "..."
            }
            if !v.isEmpty { value = v }
        }
    }

    // Clean up empty strings
    if title?.isEmpty == true { title = nil }
    let description = rawDescription?.isEmpty == true ? nil : rawDescription
    let identifier = rawIdentifier?.isEmpty == true ? nil : rawIdentifier
    let domIdentifier = rawDOMIdentifier?.isEmpty == true ? nil : rawDOMIdentifier

    // AXGroup titles are always Obj-C class names (BrowserUserView, ContentsView, …)
    // — never semantic content. Strip them so the single-child promotion logic fires
    // correctly and container chains collapse properly.
    if !config.raw && role == "AXGroup" { title = nil }

    // Get description as fallback for title (skip for AXGroup — same noise issue)
    if !config.raw && title == nil && value == nil && role != "AXGroup" {
        if let desc = description, !desc.isEmpty
        {
            title = desc
        }
    }

    // Recursively process children
    let childElements = axChildren(element)
    var childNodes: [AXNode] = []
    for child in childElements {
        if let node = traverseElement(child, depth: depth + 1, config: config) {
            childNodes.append(node)
        }
    }

    let hasText = title != nil || value != nil
    let hasMetadata = subrole != nil
        || description != nil
        || identifier != nil
        || domIdentifier != nil
        || !domClassList.isEmpty

    // For text-bearing roles: keep if they have text or meaningful children
    if let role = role, textBearingRoles.contains(role) {
        if hasText || description != nil || !childNodes.isEmpty {
            return AXNode(
                role: role,
                subrole: subrole,
                title: title,
                description: description,
                value: value,
                identifier: identifier,
                domIdentifier: domIdentifier,
                domClassList: domClassList,
                attributeNames: attributeNames,
                children: childNodes
            )
        }
        return nil
    }

    // For container roles: collapse if no text and single child or no semantic content
    if let role = role, containerRoles.contains(role) {
        if !config.raw && !hasText && !hasMetadata {
            // Single child → promote it
            if childNodes.count == 1 {
                return childNodes[0]
            }
            // No children → drop
            if childNodes.isEmpty {
                return nil
            }
        }
        // Multiple children or has text → keep as container
        return AXNode(
            role: role,
            subrole: subrole,
            title: title,
            description: description,
            value: value,
            identifier: identifier,
            domIdentifier: domIdentifier,
            domClassList: domClassList,
            attributeNames: attributeNames,
            children: childNodes
        )
    }

    // For window and application roles: always keep
    if let role = role, (role == "AXWindow" || role == "AXApplication") {
        return AXNode(
            role: role,
            subrole: subrole,
            title: title,
            description: description,
            value: value,
            identifier: identifier,
            domIdentifier: domIdentifier,
            domClassList: domClassList,
            attributeNames: attributeNames,
            children: childNodes
        )
    }

    // For unknown roles: keep if they have text or children
    if hasText || hasMetadata || !childNodes.isEmpty {
        return AXNode(
            role: role,
            subrole: subrole,
            title: title,
            description: description,
            value: value,
            identifier: identifier,
            domIdentifier: domIdentifier,
            domClassList: domClassList,
            attributeNames: attributeNames,
            children: childNodes
        )
    }

    return nil
}

// MARK: - Window Processing

/// Process a window with full element traversal.
func processWindow(_ window: AXUIElement, config: Config) -> [String: Any]? {
    let title = axString(window, kAXTitleAttribute as String) ?? ""
    let focused = axBool(window, kAXFocusedAttribute as String) ?? false
    let subrole = axString(window, kAXSubroleAttribute as String)?
        .trimmingCharacters(in: .whitespacesAndNewlines)
    let description = axString(window, kAXDescriptionAttribute as String)?
        .trimmingCharacters(in: .whitespacesAndNewlines)
    let identifier = axString(window, kAXIdentifierAttribute as String)?
        .trimmingCharacters(in: .whitespacesAndNewlines)

    let children = axChildren(window)
    var elements: [[String: Any]] = []

    for child in children {
        if let node = traverseElement(child, depth: 2, config: config),
           let dict = node.toDict()
        {
            elements.append(dict)
        }
    }

    // Skip windows with no title and no content
    if title.isEmpty && elements.isEmpty { return nil }

    var windowDict: [String: Any] = [
        "title": title,
    ]
    if let subrole, !subrole.isEmpty { windowDict["subrole"] = subrole }
    if let description, !description.isEmpty { windowDict["description"] = description }
    if let identifier, !identifier.isEmpty { windowDict["identifier"] = identifier }
    if focused { windowDict["focused"] = true }
    if !elements.isEmpty { windowDict["elements"] = elements }
    return windowDict
}


// MARK: - App Processing

func processApp(pid: pid_t, name: String, bundleID: String?, isFrontmost: Bool, config: Config)
    -> [String: Any]?
{
    let appRef = AXUIElementCreateApplication(pid)

    // Identify the focused window so we can mark it in the output.
    var focusedWindowRef: CFTypeRef?
    AXUIElementCopyAttributeValue(
        appRef, kAXFocusedWindowAttribute as CFString, &focusedWindowRef
    )
    let focusedElement = focusedWindowRef as! AXUIElement?

    // Get all children (AXChildren includes windows across all Spaces,
    // unlike kAXWindowsAttribute which only returns the current Space).
    var childrenRef: CFTypeRef?
    let semaphore = DispatchSemaphore(value: 0)
    var timedOut = false

    DispatchQueue.global(qos: .userInitiated).async {
        childrenRef = axValue(appRef, kAXChildrenAttribute as String)
        semaphore.signal()
    }

    if semaphore.wait(timeout: .now() + config.timeout) == .timedOut {
        timedOut = true
    }

    var windowDicts: [[String: Any]] = []

    if !timedOut, let ref = childrenRef, let children = ref as? [AXUIElement] {
        var foundFocused = false
        for child in children {
            let role = axString(child, kAXRoleAttribute as String)
            guard role == "AXWindow" else { continue }

            let isFocusedWindow = focusedElement != nil && CFEqual(child, focusedElement!)

            // If --focused-window-only, skip non-focused windows
            if config.focusedWindowOnly && !isFocusedWindow {
                continue
            }

            if var dict = processWindow(child, config: config) {
                if isFocusedWindow {
                    dict["focused"] = true
                    foundFocused = true
                }
                windowDicts.append(dict)
            }
        }

        // Fallback: if --focused-window-only but no focused window found,
        // capture the first window instead of returning nothing
        if config.focusedWindowOnly && !foundFocused && windowDicts.isEmpty {
            for child in children {
                let role = axString(child, kAXRoleAttribute as String)
                guard role == "AXWindow" else { continue }
                if let dict = processWindow(child, config: config) {
                    windowDicts.append(dict)
                    break  // just take the first one
                }
            }
        }
    }

    if windowDicts.isEmpty { return nil }

    var appDict: [String: Any] = [
        "pid": pid,
        "name": name,
        "is_frontmost": isFrontmost,
    ]
    if let bid = bundleID { appDict["bundle_id"] = bid }
    appDict["windows"] = windowDicts
    return appDict
}

// MARK: - Main

func parseArgs() -> Config {
    var config = Config()
    var args = CommandLine.arguments.dropFirst()

    while let arg = args.first {
        args = args.dropFirst()
        switch arg {
        case "--all-visible":
            config.allVisible = true
        case "--app-name":
            if let next = args.first {
                config.appName = next
                args = args.dropFirst()
            }
        case "--depth":
            if let next = args.first, let val = Int(next) {
                config.maxDepth = val  // 0 = unlimited
                args = args.dropFirst()
            }
        case "--timeout":
            if let next = args.first, let val = Double(next) {
                config.timeout = val
                args = args.dropFirst()
            }
        case "--focused-window-only":
            config.focusedWindowOnly = true
        case "--raw":
            config.raw = true
        case "--help", "-h":
            fputs(
                """
                Usage: mac-ax-helper [--all-visible] [--app-name NAME] [--depth N] [--timeout SECS] [--raw]
                  (default)           Capture frontmost app only
                  --all-visible       Capture all visible apps
                  --app-name NAME     Capture a specific app by name (case-insensitive)
                  --depth N           Max traversal depth (default: 8)
                  --timeout SECS      Per-app timeout in seconds (default: 3)
                  --raw               Preserve the unfiltered AX tree for debugging/parser work
                \n
                """, stderr)
            exit(0)
        default:
            break
        }
    }
    return config
}

func main() {
    let config = parseArgs()

    // Check accessibility permission
    let trusted = AXIsProcessTrustedWithOptions(
        [kAXTrustedCheckOptionPrompt.takeUnretainedValue(): true] as CFDictionary
    )
    if !trusted {
        fputs("Accessibility permission not granted. Please enable in System Settings.\n", stderr)
        exit(2)
    }

    let workspace = NSWorkspace.shared
    let runningApps = workspace.runningApplications

    // Use the dedicated API — runningApplications order is unspecified,
    // so filtering with .first { $0.isActive } is unreliable.
    let frontmostApp = workspace.frontmostApplication
    let frontmostPID = frontmostApp?.processIdentifier ?? -1

    var appDicts: [[String: Any]] = []

    if let targetName = config.appName {
        // Capture a specific app by name.
        // Match against localizedName (e.g. "飞书") and process name
        // (e.g. "Feishu") since Electron's AppleScript reports the
        // process name, not the localized display name.
        let targetLower = targetName.lowercased()
        guard let app = runningApps.first(where: { runApp in
            let localized = (runApp.localizedName ?? "").lowercased()
            let process = (runApp.executableURL?.lastPathComponent ?? "").lowercased()
            let bundle = (runApp.bundleIdentifier ?? "").lowercased()
            return localized == targetLower
                || process == targetLower
                || bundle == targetLower
                || bundle.hasSuffix(".\(targetLower)")
        }) else {
            fputs("No running app matching '\(targetName)' found.\n", stderr)
            exit(1)
        }

        let pid = app.processIdentifier
        let name = app.localizedName ?? "Unknown"
        let bundleID = app.bundleIdentifier
        let isFrontmost = pid == frontmostPID

        if let dict = processApp(
            pid: pid, name: name, bundleID: bundleID,
            isFrontmost: isFrontmost, config: config)
        {
            appDicts.append(dict)
        }
    } else if config.allVisible {
        // Capture all regular, visible apps
        for app in runningApps {
            guard app.activationPolicy == .regular else { continue }

            let pid = app.processIdentifier
            let name = app.localizedName ?? "Unknown"
            let bundleID = app.bundleIdentifier
            let isFrontmost = pid == frontmostPID

            if let dict = processApp(
                pid: pid, name: name, bundleID: bundleID,
                isFrontmost: isFrontmost, config: config)
            {
                appDicts.append(dict)
            }
        }
    } else {
        // Capture frontmost app only
        guard let app = frontmostApp else {
            fputs("No frontmost application found.\n", stderr)
            exit(1)
        }

        let pid = app.processIdentifier
        let name = app.localizedName ?? "Unknown"
        let bundleID = app.bundleIdentifier

        if let dict = processApp(
            pid: pid, name: name, bundleID: bundleID,
            isFrontmost: true, config: config)
        {
            appDicts.append(dict)
        }
    }

    // Build output
    let iso8601Formatter = ISO8601DateFormatter()
    iso8601Formatter.formatOptions = [.withInternetDateTime]

    let output: [String: Any] = [
        "timestamp": iso8601Formatter.string(from: Date()),
        "apps": appDicts,
    ]

    // Serialize to JSON
    guard let jsonData = try? JSONSerialization.data(
        withJSONObject: output, options: [.prettyPrinted, .sortedKeys])
    else {
        fputs("Failed to serialize JSON output.\n", stderr)
        exit(1)
    }

    if let jsonString = String(data: jsonData, encoding: .utf8) {
        print(jsonString)
    }
}

main()

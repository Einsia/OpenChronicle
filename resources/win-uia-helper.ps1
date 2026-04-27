# win-uia-helper.ps1 — Windows UI Automation tree capture (mirrors mac-ax-helper)
#
# Output schema is intentionally identical to mac-ax-helper.swift so the
# Python s1_parser / ax_models / aggregator code paths are platform-agnostic:
#
#   {
#     "timestamp": "<ISO 8601 UTC>",
#     "apps": [
#       {
#         "pid":          <int>,
#         "name":         "<app display name>",
#         "bundle_id":    "<full exe path on Windows / reverse-DNS on macOS>",
#         "is_frontmost": <bool>,
#         "windows": [
#           {
#             "title":   "<string>",
#             "focused": true,                  # only present on focused window
#             "elements": [ <node>, ... ]
#           }
#         ]
#       }
#     ]
#   }
#
# Each <node> is:
#   {
#     "role":       "AXEdit"|"AXButton"|...    # UIA ControlType remapped to mac AX role
#     "title":      "<string>",
#     "identifier": "<string>",
#     "value":      "<string>",
#     "children":   [<node>, ...]
#   }
#
# Empty fields are omitted (matches mac-ax-helper's AXNode.toDict()).
# Container nodes that add no semantic value are collapsed (matches
# mac-ax-helper's containerRoles promotion).
# Visual chrome roles (Image, ScrollBar, ...) are dropped entirely.
#
# Usage:  powershell -ExecutionPolicy Bypass -File win-uia-helper.ps1 [options]
#   -AllVisible             Capture all visible top-level windows
#   -AppName <name>         Capture a specific application by name
#   -FocusedWindowOnly      Only capture the focused window (default for frontmost)
#   -Depth <n>              Max element tree depth (default 8)
#   -Timeout <s>            Reserved for CLI parity with mac-ax-helper
#   -Raw                    Skip semantic filtering (preserve full UIA tree)

param(
    [switch]$AllVisible,
    [string]$AppName = "",
    [switch]$FocusedWindowOnly,
    [int]$Depth = 8,
    [int]$Timeout = 3,
    [switch]$Raw,
    # Win32 HWND of the foreground window, as observed by the parent
    # (daemon) process. The daemon owns the desktop session whereas the
    # helper subprocess runs in a session-isolated detached state — its
    # own GetForegroundWindow / UIA FocusedElement always return zero.
    # This parameter is the equivalent of mac's
    # NSWorkspace.frontmostApplication: a stable, externally-observed
    # anchor for "which app is the user actually using".
    [long]$ForegroundHwnd = 0,
    [int]$ForegroundPid = 0
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

# Win32 imports — used to identify the *real* foreground window. The
# UIAutomation FocusedElement is unreliable here: when this script is
# launched as a subprocess by the daemon, focus has briefly moved to the
# launching shell, so FocusedElement can return the wrong app entirely.
# GetForegroundWindow + GetWindowThreadProcessId mirror what mac's
# NSWorkspace.frontmostApplication gives us — they're independent of who
# is currently consuming UIA events.
if (-not ("OpenChronicle.Win32" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
namespace OpenChronicle {
    public static class Win32 {
        [DllImport("user32.dll")]
        public static extern IntPtr GetForegroundWindow();
        [DllImport("user32.dll")]
        public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);
    }
}
"@
}

$automation = [System.Windows.Automation.AutomationElement]
$controlType = [System.Windows.Automation.ControlType]

# ─── Mac AX role parity ─────────────────────────────────────────────────
#
# Maps UIA ControlType.ProgrammaticName ("ControlType.Edit") to the
# normalized role vocabulary consumed by s1_parser. Windows edit controls keep
# the distinct AXEdit role while still participating in editable/url-bar logic.

$ROLE_MAP = @{
    "Window"       = "AXWindow"
    "Pane"         = "AXGroup"
    "Group"        = "AXGroup"
    "Custom"       = "AXGroup"
    "TitleBar"     = "AXGroup"
    "StatusBar"    = "AXGroup"
    "Calendar"     = "AXGroup"
    "SemanticZoom" = "AXGroup"
    "Document"     = "AXTextArea"
    "Edit"         = "AXEdit"
    "Text"         = "AXStaticText"
    "Hyperlink"    = "AXLink"
    "Button"       = "AXButton"
    "SplitButton"  = "AXButton"
    "MenuItem"     = "AXMenuItem"
    "Menu"         = "AXMenu"
    "MenuBar"      = "AXMenuBar"
    "CheckBox"     = "AXCheckBox"
    "RadioButton"  = "AXRadioButton"
    "ComboBox"     = "AXComboBox"
    "List"         = "AXList"
    "ListItem"     = "AXRow"
    "Tree"         = "AXOutline"
    "TreeItem"     = "AXRow"
    "DataGrid"     = "AXOutline"
    "DataItem"     = "AXRow"
    "Table"        = "AXOutline"
    "Header"       = "AXHeading"
    "HeaderItem"   = "AXHeading"
    "Tab"          = "AXTabGroup"
    "TabItem"      = "AXTab"
    "ToolBar"      = "AXToolbar"
    "AppBar"       = "AXToolbar"
    "Image"        = "AXImage"
    "ScrollBar"    = "AXScrollBar"
    "Slider"       = "AXSlider"
    "ProgressBar"  = "AXProgressIndicator"
    "Spinner"      = "AXIncrementor"
    "Separator"    = "AXSplitter"
    "ToolTip"      = "AXToolTip"
    "Thumb"        = "AXValueIndicator"
}

# Pure visual chrome — drop the node and its subtree. Mirrors
# mac-ax-helper.swift's `dropRoles`.
$DROP_ROLES = @(
    "AXImage", "AXScrollBar", "AXValueIndicator", "AXSplitter"
) | ForEach-Object { $_ } | Group-Object -AsHashTable -Property { $_ }

# Container roles that get collapsed (single-child promotion) when they
# carry no text of their own. Mirrors mac-ax-helper.swift's `containerRoles`.
$CONTAINER_ROLES = @(
    "AXGroup", "AXSplitGroup", "AXScrollArea", "AXList",
    "AXOutline", "AXBrowser", "AXDrawer", "AXSheet", "AXToolbar"
) | ForEach-Object { $_ } | Group-Object -AsHashTable -Property { $_ }

# Length cap on element values (mac-ax-helper.swift maxValueLength = 1000).
$VALUE_MAX = 1000

# Max children per node — guards against a runaway list.
$MAX_CHILDREN = 200


function Map-ControlTypeToRole {
    param([string]$ProgrammaticName)
    # ProgrammaticName is "ControlType.Edit" / "ControlType.Pane" / ...
    $bare = $ProgrammaticName -replace "^ControlType\.", ""
    if ($ROLE_MAP.ContainsKey($bare)) {
        return $ROLE_MAP[$bare]
    }
    # Unknown control type: prefix with AX so downstream code knows to
    # treat it as an "unknown but tagged" element. Matches mac-ax-helper's
    # behaviour for roles outside its known sets.
    return "AX$bare"
}


function Get-TextAttribute {
    param(
        [System.Windows.Automation.AutomationElement]$Element,
        [string]$Name
    )
    try {
        $val = $Element.Current.$Name
        if ($null -eq $val) { return "" }
        return [string]$val
    } catch {
        return ""
    }
}


function Get-ElementValue {
    param([System.Windows.Automation.AutomationElement]$Element)
    # ValuePattern → .Value (works for Edit/Document/ComboBox)
    try {
        $obj = $null
        if ($Element.TryGetCurrentPattern(
                [System.Windows.Automation.ValuePattern]::Pattern,
                [ref]$obj)) {
            $v = $obj.Current.Value
            if ($null -ne $v -and $v.Length -gt 0) {
                if ($v.Length -gt $VALUE_MAX) {
                    return $v.Substring(0, $VALUE_MAX) + "..."
                }
                return $v
            }
        }
    } catch {}
    # TogglePattern → "On" / "Off" / "Indeterminate" (for CheckBox / RadioButton)
    try {
        $obj = $null
        if ($Element.TryGetCurrentPattern(
                [System.Windows.Automation.TogglePattern]::Pattern,
                [ref]$obj)) {
            return $obj.Current.ToggleState.ToString()
        }
    } catch {}
    return ""
}


function Test-IsSecureField {
    param([System.Windows.Automation.AutomationElement]$Element)
    # IsPassword is a UIA core property on edit controls
    try {
        return [bool]$Element.Current.IsPassword
    } catch {
        return $false
    }
}


function Get-ElementTree {
    param(
        [System.Windows.Automation.AutomationElement]$Element,
        [int]$CurrentDepth,
        [int]$MaxDepth
    )

    if ($null -eq $Element) { return $null }
    if ($MaxDepth -gt 0 -and $CurrentDepth -ge $MaxDepth) { return $null }

    $role = $null
    $title = ""
    $identifier = ""
    $value = ""
    $isSecure = $false

    try {
        $role = Map-ControlTypeToRole -ProgrammaticName `
            $Element.Current.ControlType.ProgrammaticName
        $title = (Get-TextAttribute -Element $Element -Name "Name").Trim()
        $identifier = (Get-TextAttribute -Element $Element -Name "AutomationId").Trim()
        $isSecure = Test-IsSecureField -Element $Element
        if ($isSecure) {
            $value = "[REDACTED]"
        } else {
            $value = (Get-ElementValue -Element $Element).Trim()
        }
    } catch {
        return $null
    }

    # Drop visual chrome roles in filtered mode (mirrors mac dropRoles).
    if (-not $Raw -and $DROP_ROLES.ContainsKey($role)) {
        return $null
    }

    # Recurse into children.
    $childList = @()
    if ($MaxDepth -le 0 -or $CurrentDepth + 1 -lt $MaxDepth) {
        try {
            $children = $Element.FindAll(
                [System.Windows.Automation.TreeScope]::Children,
                [System.Windows.Automation.Condition]::TrueCondition
            )
            $count = 0
            foreach ($child in $children) {
                if ($count -ge $MAX_CHILDREN) { break }
                $childResult = Get-ElementTree `
                    -Element $child `
                    -CurrentDepth ($CurrentDepth + 1) `
                    -MaxDepth $MaxDepth
                if ($null -ne $childResult) {
                    $childList += $childResult
                }
                $count++
            }
        } catch {}
    }

    $hasText = ($title.Length -gt 0) -or ($value.Length -gt 0)

    # Container collapsing: a container node with no own text is just
    # noise — promote a single child, drop a leaf, otherwise keep as a
    # plain wrapper. Mirrors mac-ax-helper's container collapse logic.
    if (-not $Raw -and $CONTAINER_ROLES.ContainsKey($role) -and -not $hasText) {
        if ($childList.Count -eq 1) {
            return $childList[0]
        }
        if ($childList.Count -eq 0) {
            return $null
        }
    }

    # Drop unknown / leaf nodes that carry nothing useful at all.
    if (-not $Raw -and -not $hasText -and ($childList.Count -eq 0)) {
        return $null
    }

    $result = [ordered]@{
        "role" = $role
    }
    if ($title.Length -gt 0)      { $result["title"] = $title }
    if ($identifier.Length -gt 0) { $result["identifier"] = $identifier }
    if ($value.Length -gt 0)      { $result["value"] = $value }
    if ($childList.Count -gt 0)   { $result["children"] = $childList }
    return $result
}


function Get-WindowData {
    param(
        [System.Windows.Automation.AutomationElement]$WindowElement,
        [int]$MaxDepth,
        [bool]$IsFocused
    )

    $title = ""
    try { $title = [string]$WindowElement.Current.Name } catch {}

    # Redact title when the focused element is a password field. Mirrors
    # mac-ax-watcher's window_title redaction.
    try {
        $focusedEl = $automation::FocusedElement
        if ($null -ne $focusedEl -and (Test-IsSecureField -Element $focusedEl)) {
            $title = "[REDACTED]"
        }
    } catch {}

    $elements = @()
    try {
        $children = $WindowElement.FindAll(
            [System.Windows.Automation.TreeScope]::Children,
            [System.Windows.Automation.Condition]::TrueCondition
        )
        foreach ($child in $children) {
            $el = Get-ElementTree -Element $child -CurrentDepth 0 -MaxDepth $MaxDepth
            if ($null -ne $el) {
                $elements += $el
            }
        }
    } catch {}

    $windowData = [ordered]@{ "title" = $title }
    if ($IsFocused) { $windowData["focused"] = $true }
    if ($elements.Count -gt 0) { $windowData["elements"] = $elements }
    return $windowData
}


function Get-AppFromHwnd {
    param(
        [int]$ProcessId,
        [bool]$IsFrontmost
    )

    $appData = [ordered]@{
        "pid"          = $ProcessId
        "name"         = ""
        "bundle_id"    = ""
        "is_frontmost" = $IsFrontmost
        "windows"      = @()
    }

    if ($ProcessId -gt 0) {
        try {
            $proc = Get-Process -Id $ProcessId -ErrorAction Stop
            $appData["name"] = $proc.ProcessName
            try {
                $appData["bundle_id"] = $proc.MainModule.FileName
            } catch {}
        } catch {}
    }

    return $appData
}


function Find-WindowAncestor {
    param([System.Windows.Automation.AutomationElement]$Element)
    $walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
    $current = $Element
    while ($null -ne $current) {
        try {
            if ($current.Current.ControlType -eq $controlType::Window) {
                return $current
            }
        } catch { return $null }
        try {
            $current = $walker.GetParent($current)
        } catch { return $null }
    }
    return $null
}


function Get-ForegroundContext {
    # Prefer the parent-supplied HWND/PID — that's the only reliable
    # source when this script runs as a session-isolated subprocess.
    # Fall back to GetForegroundWindow when the caller didn't pass one
    # (manual invocation from a normal interactive PowerShell).
    if ($ForegroundHwnd -ne 0 -and $ForegroundPid -gt 0) {
        return @{
            hwnd = [IntPtr]::new($ForegroundHwnd)
            pid  = $ForegroundPid
        }
    }
    $hwnd = [OpenChronicle.Win32]::GetForegroundWindow()
    if ($hwnd -eq [IntPtr]::Zero) {
        return @{ hwnd = [IntPtr]::Zero; pid = 0 }
    }
    $procId = 0
    [void][OpenChronicle.Win32]::GetWindowThreadProcessId($hwnd, [ref]$procId)
    return @{ hwnd = $hwnd; pid = $procId }
}


function Resolve-WindowFromHwnd {
    param([IntPtr]$Hwnd)
    if ($Hwnd -eq [IntPtr]::Zero) { return $null }
    try {
        $el = $automation::FromHandle($Hwnd)
        if ($null -eq $el) { return $null }
        # If the HWND maps to something other than a Window element (e.g.
        # a console host), walk up to the first Window ancestor so the
        # output schema still has a "windows[]" with content.
        try {
            if ($el.Current.ControlType -eq $controlType::Window) {
                return $el
            }
        } catch {}
        return Find-WindowAncestor -Element $el
    } catch {
        return $null
    }
}


# ─── Main ────────────────────────────────────────────────────────────────

$timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$output = [ordered]@{
    "timestamp" = $timestamp
    "apps"      = @()
}

try {
    $root = $automation::RootElement

    # Foreground window/pid via Win32 — independent of who is currently
    # consuming UIA events. This is the rock for everything else.
    $fg = Get-ForegroundContext
    $foregroundHwnd = $fg.hwnd
    $foregroundPid = [int]$fg.pid

    # FocusedElement is still useful for figuring out *which* window
    # within an app is focused (when the app has multiple windows), and
    # for password-field redaction. But it's an *extra* signal — never
    # the source of truth for which app is frontmost.
    $focused = $null
    try { $focused = $automation::FocusedElement } catch {}

    if ($AllVisible) {
        # All top-level windows, grouped by ProcessId.
        $windowCondition = New-Object System.Windows.Automation.PropertyCondition(
            $automation::ControlTypeProperty, $controlType::Window
        )
        $allWindows = $root.FindAll(
            [System.Windows.Automation.TreeScope]::Children,
            $windowCondition
        )

        $appMap = @{}
        foreach ($w in $allWindows) {
            try {
                $wPid = $w.Current.ProcessId
                if (-not $appMap.ContainsKey($wPid)) {
                    $appMap[$wPid] = @()
                }
                $appMap[$wPid] += $w
            } catch {}
        }

        foreach ($wPid in $appMap.Keys) {
            $isFront = ($wPid -eq $foregroundPid)
            $appData = Get-AppFromHwnd -ProcessId $wPid -IsFrontmost $isFront
            $windowDicts = @()
            foreach ($w in $appMap[$wPid]) {
                $isFocusedWindow = $false
                try {
                    $isFocusedWindow = $isFront -and `
                        ([IntPtr]$w.Current.NativeWindowHandle -eq $foregroundHwnd)
                } catch {}
                $windowDicts += (Get-WindowData -WindowElement $w `
                    -MaxDepth $Depth -IsFocused $isFocusedWindow)
            }
            $appData["windows"] = $windowDicts
            $output["apps"] += $appData
        }
    } elseif ($AppName) {
        $nameCondition = New-Object System.Windows.Automation.PropertyCondition(
            $automation::NameProperty, $AppName
        )
        $found = $root.FindFirst(
            [System.Windows.Automation.TreeScope]::Children,
            $nameCondition
        )
        if ($null -ne $found) {
            $appPid = 0
            try { $appPid = $found.Current.ProcessId } catch {}
            $appData = Get-AppFromHwnd -ProcessId $appPid -IsFrontmost $true
            $appData["windows"] = @(Get-WindowData -WindowElement $found `
                -MaxDepth $Depth -IsFocused $true)
            $output["apps"] += $appData
        }
    } else {
        # Frontmost app — anchor on the Win32 foreground window. Walking
        # up from FocusedElement is fragile (focus can be on a transient
        # child) and easily wrong when the helper itself was just
        # launched.
        if ($foregroundHwnd -ne [IntPtr]::Zero -and $foregroundPid -gt 0) {
            $foregroundWindow = Resolve-WindowFromHwnd -Hwnd $foregroundHwnd
            $appData = Get-AppFromHwnd -ProcessId $foregroundPid -IsFrontmost $true

            if ($FocusedWindowOnly) {
                if ($null -ne $foregroundWindow) {
                    $appData["windows"] = @(Get-WindowData `
                        -WindowElement $foregroundWindow `
                        -MaxDepth $Depth -IsFocused $true)
                }
            } else {
                $windowCondition = New-Object System.Windows.Automation.PropertyCondition(
                    $automation::ControlTypeProperty, $controlType::Window
                )
                $allWindows = $root.FindAll(
                    [System.Windows.Automation.TreeScope]::Children,
                    $windowCondition
                )
                $windowDicts = @()
                foreach ($w in $allWindows) {
                    try {
                        if ($w.Current.ProcessId -ne $foregroundPid) { continue }
                    } catch { continue }
                    $isFocusedWindow = $false
                    try {
                        $isFocusedWindow = `
                            ([IntPtr]$w.Current.NativeWindowHandle -eq $foregroundHwnd)
                    } catch {}
                    $windowDicts += (Get-WindowData -WindowElement $w `
                        -MaxDepth $Depth -IsFocused $isFocusedWindow)
                }
                # Fallback: if for any reason we didn't find the
                # foreground HWND in the root's window list (e.g. the
                # foreground window is a child popup not enumerated as a
                # top-level), still emit the foreground window itself.
                if ($windowDicts.Count -eq 0 -and $null -ne $foregroundWindow) {
                    $windowDicts += (Get-WindowData `
                        -WindowElement $foregroundWindow `
                        -MaxDepth $Depth -IsFocused $true)
                }
                $appData["windows"] = $windowDicts
            }

            $output["apps"] += $appData
        }
    }
} catch {
    $output["error"] = $_.Exception.Message
}

$output | ConvertTo-Json -Depth 50 -Compress

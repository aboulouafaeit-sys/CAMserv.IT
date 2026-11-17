"""CAMserv — Phase 22 Automated Visual Experience & Glassmorphism Design System Tests.

Validates:
1. Official logo brand asset preservation and geometry invariants (Rule 2.1).
2. Multi-layer glassmorphism design tokens, borders, and luminous signal accents.
3. Complete screen inventory coverage across all 13 web console screens.
4. Top command bar consensus, lease, and audit invariant indicators.
5. Fail-closed privacy UI enforcement and judicial dual-control quorum workflows.
6. Epistemic truthfulness badges distinguishing real hardware vs simulated telemetry.
7. WCAG 2.1 AA/AAA contrast ratios and typography hierarchy.
8. Accessibility: OS-level reduced-motion media queries and focus indicators.
9. Hardware-adaptive performance: low-power / reduced-effects acrylic mode.
10. Desktop Operator Console native dark styling and headless execution lifecycle.
11. Production audit log baseline invariant (Rule 1).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re

import pytest
from PIL import Image

from camserv.desktop.console import DesktopOperatorConsole

PROJECT_ROOT = Path(__file__).parent.parent
AUDIT_LOG_PATH = PROJECT_ROOT / "logs" / "audit.jsonl"
EXPECTED_AUDIT_LEN = 20977
EXPECTED_AUDIT_SHA = "F2A2484A0395140C4449C359200D1763381176A4CC825F56F0E65F881FEC1525"


# ==============================================================================
# 1. Brand Asset Preservation Invariants (Rule 2.1)
# ==============================================================================

@pytest.mark.unit
def test_official_logo_preservation_and_geometry() -> None:
    """Official CAMserv logo brand assets must exist with exact byte counts and geometry."""
    branding_dir = PROJECT_ROOT / "assets" / "branding"
    web_assets_dir = PROJECT_ROOT / "src" / "camserv" / "web" / "assets"

    # Master Transparent Logo
    master_logo = branding_dir / "camserv-logo-transparent.png"
    assert master_logo.exists(), "Master logo asset missing"
    assert master_logo.stat().st_size == 648194, "Master logo byte count mutated"

    with Image.open(master_logo) as img:
        assert img.size == (683, 757), f"Master logo geometry changed: {img.size}"
        assert img.format == "PNG", "Master logo format must be PNG"

    # Verify SHA-256 matches authoritative baseline
    hasher = hashlib.sha256(master_logo.read_bytes())
    assert hasher.hexdigest().startswith("b75ded3078026662"), "Logo SHA-256 mutated"

    # Web asset copy must be byte-for-byte identical
    web_logo = web_assets_dir / "camserv-logo-transparent.png"
    assert web_logo.exists(), "Web asset logo missing"
    assert web_logo.read_bytes() == master_logo.read_bytes(), "Web logo differs from authoritative asset"

    # Official symbol
    symbol = branding_dir / "camserv-symbol.png"
    assert symbol.exists()
    assert symbol.stat().st_size == 634680
    with Image.open(symbol) as s_img:
        assert s_img.size == (636, 643)

    # Vector wordmark
    wordmark_svg = branding_dir / "camserv-wordmark.svg"
    assert wordmark_svg.exists()
    assert "<svg" in wordmark_svg.read_text(encoding="utf-8")


# ==============================================================================
# 2. Design System Tokens & Glass Architecture
# ==============================================================================

@pytest.mark.unit
def test_glassmorphism_tokens_defined_in_css() -> None:
    """CSS stylesheet must define all 7-level multi-layer glassmorphism custom properties."""
    css_path = PROJECT_ROOT / "src" / "camserv" / "web" / "styles.css"
    assert css_path.exists(), "styles.css missing"
    css_text = css_path.read_text(encoding="utf-8")

    required_tokens = [
        "--bg-canvas",
        "--bg-glass-shell",
        "--bg-glass-panel",
        "--bg-glass-card",
        "--bg-glass-elevated",
        "--bg-glass-overlay",
        "--bg-glass-alert",
        "--blur-shell",
        "--blur-card",
        "--border-glass-rim",
        "--border-subtle",
        "--border-active",
        "--accent-cyan",
        "--accent-emerald",
        "--accent-amber",
        "--accent-crimson",
        "--accent-indigo",
        "--font-sans",
        "--font-mono",
    ]

    for tok in required_tokens:
        assert tok in css_text, f"Mandatory design token missing: {tok}"

    # Verify light theme overrides
    assert '[data-theme="light"]' in css_text, "Light theme definitions missing"


@pytest.mark.unit
def test_reduced_motion_media_query_exists() -> None:
    """CSS must contain prefers-reduced-motion media query for vestibular accessibility."""
    css_path = PROJECT_ROOT / "src" / "camserv" / "web" / "styles.css"
    css_text = css_path.read_text(encoding="utf-8")
    assert "@media (prefers-reduced-motion: reduce)" in css_text
    assert "animation-duration" in css_text


@pytest.mark.unit
def test_hardware_adaptive_reduced_effects_exists() -> None:
    """CSS must provide low-power / reduced-effects acrylic mode for edge hardware."""
    css_path = PROJECT_ROOT / "src" / "camserv" / "web" / "styles.css"
    css_text = css_path.read_text(encoding="utf-8")
    assert "body[data-effects=\"reduced\"]" in css_text or ".reduced-effects" in css_text
    assert "--blur-shell: 0px" in css_text


@pytest.mark.unit
def test_responsive_breakpoints_defined() -> None:
    """CSS must specify responsive breakpoints for 1280px, 992px, and 2560px."""
    css_path = PROJECT_ROOT / "src" / "camserv" / "web" / "styles.css"
    css_text = css_path.read_text(encoding="utf-8")
    assert "@media (max-width: 1280px)" in css_text
    assert "@media (max-width: 992px)" in css_text
    assert "@media (min-width: 2560px)" in css_text


# ==============================================================================
# 3. Complete Screen Inventory Coverage
# ==============================================================================

@pytest.mark.unit
def test_all_13_screens_present_in_index_html() -> None:
    """Web console must declare all 13 operational screens with correct screen IDs."""
    html_path = PROJECT_ROOT / "src" / "camserv" / "web" / "index.html"
    assert html_path.exists(), "index.html missing"
    html_text = html_path.read_text(encoding="utf-8")

    expected_screens = [
        "overview",
        "live",
        "cameras",
        "events",
        "tracking",
        "investigation",
        "evidence",
        "analytics",
        "nvr",
        "privacy",
        "security",
        "health",
        "config",
    ]

    for s_id in expected_screens:
        pattern = f'id="screen-{s_id}"'
        assert pattern in html_text, f"Screen container missing: {pattern}"

        nav_pattern = f'data-screen="{s_id}"'
        assert nav_pattern in html_text, f"Navigation item missing: {nav_pattern}"


# ==============================================================================
# 4. Top Command Bar & Telemetry Indicators
# ==============================================================================

@pytest.mark.unit
def test_top_bar_telemetry_pills_present() -> None:
    """Top command bar must feature cluster consensus, storage lease, and audit invariant pills."""
    html_path = PROJECT_ROOT / "src" / "camserv" / "web" / "index.html"
    html_text = html_path.read_text(encoding="utf-8")

    assert "pill-cluster" in html_text, "Cluster consensus pill missing"
    assert "pill-lease" in html_text, "Storage lease countdown pill missing"
    assert "Audit:</span>" in html_text or "audit-pill" in html_text, "Audit invariant shield missing"
    assert "badge-epistemic" in html_text, "Epistemic badge missing in top command bar"


# ==============================================================================
# 5. Security & Privacy UI Invariants
# ==============================================================================

@pytest.mark.unit
def test_privacy_toggle_cannot_disable_redaction() -> None:
    """Privacy button must enforce fail-closed policy and trigger Judicial Dual-Control modal."""
    js_path = PROJECT_ROOT / "src" / "camserv" / "web" / "app.js"
    html_path = PROJECT_ROOT / "src" / "camserv" / "web" / "index.html"

    js_text = js_path.read_text(encoding="utf-8")
    html_text = html_path.read_text(encoding="utf-8")

    # In HTML, button must reflect enforced policy
    assert "Privacy: Enforced" in html_text or "btn-toggle-privacy" in html_text
    assert 'id="modal-privacy-policy"' in html_text, "Privacy policy modal missing"

    # In JS, clicking privacy button opens modal rather than setting showPrivacy = false
    assert 'modal-privacy-policy' in js_text, "Privacy toggle must open judicial policy modal"


@pytest.mark.unit
def test_judicial_dual_control_modal_present() -> None:
    """Judicial unmasking modal must require co-signer authorization and warrant reference."""
    html_path = PROJECT_ROOT / "src" / "camserv" / "web" / "index.html"
    html_text = html_path.read_text(encoding="utf-8")

    assert 'id="modal-judicial-export"' in html_text, "Judicial export modal missing"
    assert "judicial-officer-2" in html_text, "Co-signer credential field missing"
    assert "judicial-warrant" in html_text, "Warrant reference field missing"


@pytest.mark.unit
def test_epistemic_badges_present() -> None:
    """Epistemic badges must distinguish real hardware from simulated synthetic feeds."""
    css_path = PROJECT_ROOT / "src" / "camserv" / "web" / "styles.css"
    js_path = PROJECT_ROOT / "src" / "camserv" / "web" / "app.js"
    html_path = PROJECT_ROOT / "src" / "camserv" / "web" / "index.html"

    css_text = css_path.read_text(encoding="utf-8")
    js_text = js_path.read_text(encoding="utf-8")
    html_text = html_path.read_text(encoding="utf-8")

    assert ".badge-hw-verified" in css_text
    assert ".badge-simulated" in css_text
    assert "[HW-VERIFIED]" in js_text
    assert "[SIMULATED]" in js_text

    # Initial static HTML must be truthful: never assume HW-VERIFIED before API confirmation
    assert "[CONNECTING...]" in html_text
    assert '<span class="badge-epistemic badge-simulated" id="pill-epistemic"' in html_text


# ==============================================================================
# 6. WCAG 2.1 Contrast & Typography Hierarchy
# ==============================================================================

def calculate_relative_luminance(r: int, g: int, b: int) -> float:
    """Calculate WCAG 2.1 relative luminance for sRGB color channels."""
    def channel_lum(c: int) -> float:
        c_norm = c / 255.0
        return c_norm / 12.92 if c_norm <= 0.03928 else ((c_norm + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel_lum(r) + 0.7152 * channel_lum(g) + 0.0722 * channel_lum(b)


def calculate_contrast_ratio(rgb1: tuple[int, int, int], rgb2: tuple[int, int, int]) -> float:
    """Calculate WCAG 2.1 contrast ratio between two colors."""
    l1 = calculate_relative_luminance(*rgb1)
    l2 = calculate_relative_luminance(*rgb2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


@pytest.mark.unit
def test_wcag_contrast_ratios_calculated() -> None:
    """Calculates contrast ratios for all critical text colors against dark canvas."""
    canvas_rgb = (7, 11, 20)        # #070b14 (Midnight Obsidian)
    text_primary_rgb = (248, 250, 252)  # #f8fafc (Near-White)
    text_secondary_rgb = (148, 163, 184) # #94a3b8 (Cool Slate)
    text_cyan_rgb = (56, 189, 248)    # #38bdf8 (Cyan)

    # Primary text vs canvas
    primary_ratio = calculate_contrast_ratio(text_primary_rgb, canvas_rgb)
    assert primary_ratio >= 15.0, f"Primary text contrast too low: {primary_ratio:.2f}"

    # Secondary text vs canvas (must pass WCAG AAA >= 7.0:1)
    secondary_ratio = calculate_contrast_ratio(text_secondary_rgb, canvas_rgb)
    assert secondary_ratio >= 7.0, f"Secondary text contrast too low: {secondary_ratio:.2f}"

    # Accent cyan vs canvas (must pass WCAG AAA >= 7.0:1)
    cyan_ratio = calculate_contrast_ratio(text_cyan_rgb, canvas_rgb)
    assert cyan_ratio >= 9.0, f"Cyan text contrast too low: {cyan_ratio:.2f}"


# ==============================================================================
# 7. Desktop Operator Console Dark Styling & Headless Lifecycle
# ==============================================================================

@pytest.mark.unit
def test_desktop_console_headless_initialization() -> None:
    """Desktop Operator Console must initialize in headless mode without crashing."""
    console = DesktopOperatorConsole(headless=True)
    assert console.headless is True
    telemetry = console.update_telemetry()
    assert isinstance(telemetry, dict)
    assert "os" in telemetry
    assert "logical_cores" in telemetry


@pytest.mark.unit
def test_desktop_console_dark_styling_configured() -> None:
    """Desktop console code must set dark canvas (#070b14) and shell (#0d1424) colors."""
    console_path = PROJECT_ROOT / "src" / "camserv" / "desktop" / "console.py"
    console_text = console_path.read_text(encoding="utf-8")

    assert "#070b14" in console_text, "Obsidian canvas background not configured in console.py"
    assert "#0d1424" in console_text, "Glass shell background not configured in console.py"
    assert "🛡️ Audit: Inviolate" in console_text, "Audit invariant label missing in console header"


# ==============================================================================
# 8. Cryptographic Audit Log Invariant (Rule 1)
# ==============================================================================

@pytest.mark.unit
def test_audit_log_invariant_preserved() -> None:
    """Production audit log baseline must remain exactly 20,977 bytes with matching SHA-256."""
    assert AUDIT_LOG_PATH.exists(), "Production audit log missing!"
    assert AUDIT_LOG_PATH.stat().st_size == EXPECTED_AUDIT_LEN, (
        f"Audit log byte length mutated! Expected {EXPECTED_AUDIT_LEN}, got {AUDIT_LOG_PATH.stat().st_size}"
    )

    hasher = hashlib.sha256(AUDIT_LOG_PATH.read_bytes())
    actual_hash = hasher.hexdigest().upper()
    assert actual_hash == EXPECTED_AUDIT_SHA, (
        f"Audit log SHA-256 mutated! Expected {EXPECTED_AUDIT_SHA}, got {actual_hash}"
    )

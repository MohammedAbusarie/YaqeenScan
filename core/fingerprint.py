"""Browser fingerprint hash computation for device identification."""

import hashlib


def compute_fingerprint_hash(
    user_agent: str,
    accept_language: str,
    screen_data: str,
    color_depth: str = "",
    pixel_ratio: str = "",
    hw_concurrency: str = "",
    touch_points: str = "",
    canvas_hash: str = "",
) -> str:
    """Combine browser and hardware attributes into a SHA-256 fingerprint hash.

    Uses passive signals (headers) plus active JS-collected signals (screen
    geometry, GPU canvas rendering, hardware concurrency, touch capability).
    The canvas hash is the strongest signal — it varies per GPU driver even
    on identical hardware models.

    Args:
        user_agent: User-Agent request header.
        accept_language: Accept-Language request header.
        screen_data: Pipe-joined screen resolution, timezone, platform string.
        color_depth: Screen color depth from JS (e.g. "24").
        pixel_ratio: Device pixel ratio from JS (e.g. "3").
        hw_concurrency: navigator.hardwareConcurrency from JS (e.g. "8").
        touch_points: navigator.maxTouchPoints from JS (e.g. "5").
        canvas_hash: Hex hash of canvas rendering output from JS.

    Returns:
        Lowercase hex digest of SHA-256 over all combined inputs.
    """
    combined = "|".join([
        user_agent or "",
        accept_language or "",
        screen_data or "",
        color_depth or "",
        pixel_ratio or "",
        hw_concurrency or "",
        touch_points or "",
        canvas_hash or "",
    ])
    raw = combined.encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest().lower()

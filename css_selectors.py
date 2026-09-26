# CSS Selectors
# Ubiquiti renames these classes between Protect releases. Keep old values in
# the lists so the script keeps working on consoles that have not updated yet.
CSS_FULLSCREEN_PARENT = "div[class*='LiveviewControls__ButtonGroup']"
CSS_FULLSCREEN_BUTTON = ":nth-child(2) > button"
CSS_LOADING_DOTS = "div[class*='TimedDotsLoader']"
# Live view grid wrapper. Any match means the live view is rendered.
CSS_LIVEVIEW_WRAPPER = [
    "div[class*='liveView__LiveViewWrapper']",    # Protect 7.2+ (UniFi OS 5.1)
    "div[class*='liveview__ViewportsWrapper']",   # Protect <= 6.x
    "div[class*='liveView__FullscreenWrapper']",  # Protect 7.2+ fallback
]
# Class-name substrings (matched with [class*="..."]) for the per-camera
# overlay bar and the area whose cursor gets hidden while the mouse is idle.
CSS_PLAYER_OPTIONS = ["aeugT", "dzRoNo", "LiveViewGridSlot__PlayerOptions"]
CSS_CURSOR = ["hMbAUy", "liveView__LiveViewWrapper", "liveview__ViewportsWrapper"]
CSS_CLOSE_BUTTON = "button[class*='closeButton']"
# Floating live-view toolbar (view switcher, stream quality, fullscreen).
# Protect only shows it while hovered (opacity 0 -> 1 on :hover).
CSS_LIVEVIEW_CONTROLS = "div[class*='LiveviewControls__LiveControlsContainer']"

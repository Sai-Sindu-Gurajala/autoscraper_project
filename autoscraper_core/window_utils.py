import time
import pygetwindow as gw


def move_chrome_window(x: int = 0, y: int = 0, width: int = 900, height: int = 900,
                       title_contains: str = "Chrome") -> None:
    """Move the first Chrome window to the specified position and size.

    A small delay is introduced to give the browser time to start before
    attempting to reposition it.  If no matching window is found, a
    diagnostic message is printed instead.

    Args:
        x (int): Desired x coordinate of the window's top-left corner.
        y (int): Desired y coordinate of the window's top-left corner.
        width (int): Desired window width in pixels.
        height (int): Desired window height in pixels.
        title_contains (str): Case-insensitive substring to match in the
            window title.
    """
    # Allow some time for Chrome to initialise
    time.sleep(2)
    all_windows = gw.getAllWindows()
    target_window = None
    for win in all_windows:
        if isinstance(win.title, str) and title_contains.lower() in win.title.lower():
            target_window = win
            break
    if target_window:
        try:
            target_window.restore()
            target_window.moveTo(x, y)
            target_window.resizeTo(width, height)
        except Exception as e:
            print(f"Error moving Chrome window: {e}")
    else:
        print("Could not find Chrome window to move.")


def focus_chrome_window(title_contains: str = "Chrome") -> None:
    """Bring a Chrome window containing the given text to the foreground."""
    all_windows = gw.getAllWindows()
    for win in all_windows:
        if isinstance(win.title, str) and title_contains.lower() in win.title.lower():
            win.activate()
            break
import time
import pygetwindow as gw

def move_chrome_window(x=0, y=0, width=900, height=900, title_contains="Chrome"):
    """Move the first Chrome window to the specified position/size."""
    time.sleep(2)  # Allow time for Chrome to open
    all_windows = gw.getAllWindows()
    target_window = None
    for win in all_windows:
        # Safely check for a valid string title and do a substring match
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


def focus_chrome_window(title_contains="Chrome"):
    import pygetwindow as gw
    all_windows = gw.getAllWindows()
    for win in all_windows:
        if isinstance(win.title, str) and title_contains.lower() in win.title.lower():
            win.activate()
            break
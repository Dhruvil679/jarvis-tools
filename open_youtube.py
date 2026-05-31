from __future__ import annotations

import webbrowser


def open_youtube() -> None:
    webbrowser.open("https://youtube.com")
    print("YouTube opened successfully.")


if __name__ == "__main__":
    open_youtube()

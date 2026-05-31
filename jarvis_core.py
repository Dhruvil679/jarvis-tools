from __future__ import annotations

import os
import webbrowser


def main() -> None:
    command = input("JARVIS Command: ").lower()

    if "youtube" in command:
        webbrowser.open("https://youtube.com")
        print("Opening YouTube...")
    elif "google" in command:
        webbrowser.open("https://google.com")
        print("Opening Google...")
    elif "chatgpt" in command:
        webbrowser.open("https://chatgpt.com")
        print("Opening ChatGPT...")
    elif "spotify" in command:
        webbrowser.open("https://spotify.com")
        print("Opening Spotify...")
    elif "calculator" in command:
        os.system("calc")
        print("Opening Calculator...")
    elif "notepad" in command:
        os.system("notepad")
        print("Opening Notepad...")
    else:
        print("Command not recognized.")


if __name__ == "__main__":
    main()

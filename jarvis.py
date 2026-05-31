from __future__ import annotations

import os


def main() -> None:
    command = input("You: ").lower()

    if "youtube" in command:
        os.system("start https://youtube.com")
    elif "google" in command:
        os.system("start https://google.com")
    else:
        print("Command not recognized")


if __name__ == "__main__":
    main()

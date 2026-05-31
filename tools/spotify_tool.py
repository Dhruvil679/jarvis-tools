import webbrowser
from core.logger import get_logger

logger = get_logger(__name__)

def open_spotify(query: str = None) -> str:
    """Open Spotify web player or a search link."""
    try:
        if query:
            url = f"https://open.spotify.com/search/{query}"
        else:
            url = "https://open.spotify.com"
        webbrowser.open(url)
        return "Opened Spotify"
    except Exception as e:
        logger.exception("Failed to open Spotify: %s", e)
        return "Failed to open Spotify"

import urllib.parse
import webbrowser
from core.logger import get_logger

logger = get_logger(__name__)

def open_youtube(query: str = None) -> str:
    """Open YouTube main page, search, or YouTube Music search if requested."""
    url = "https://www.youtube.com"
    if query:
        normalized = query.strip()
        encoded = urllib.parse.quote_plus(normalized)

        # Prefer YouTube Music when the request explicitly mentions it.
        if "music" in normalized.lower() or "yt music" in normalized.lower() or "youtube music" in normalized.lower():
            # Remove the music hint from the query so the search term stays clean.
            cleaned = normalized.lower().replace("youtube music", "").replace("yt music", "").replace("music", "").strip()
            encoded = urllib.parse.quote_plus(cleaned or normalized)
            url = f"https://music.youtube.com/search?q={encoded}"
        else:
            url = f"https://www.youtube.com/results?search_query={encoded}"
    try:
        webbrowser.open(url)
        return f"Opened YouTube: {url}"
    except Exception as e:
        logger.exception("Failed to open YouTube: %s", e)
        return "Failed to open YouTube"

import webbrowser
from core.logger import get_logger

logger = get_logger(__name__)

def open_youtube(query: str = None) -> str:
    """Open YouTube main page or search for a query if provided."""
    url = "https://www.youtube.com"
    if query:
        url = f"https://www.youtube.com/results?search_query={query}"
    try:
        webbrowser.open(url)
        return "Opened YouTube"
    except Exception as e:
        logger.exception("Failed to open YouTube: %s", e)
        return "Failed to open YouTube"

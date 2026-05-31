import webbrowser
import urllib.parse
from core.logger import get_logger

logger = get_logger(__name__)

def search_google(text: str) -> str:
    """Perform a Google search for the provided text."""
    try:
        q = urllib.parse.quote_plus(text)
        url = f"https://www.google.com/search?q={q}"
        webbrowser.open(url)
        return "Searching Google"
    except Exception as e:
        logger.exception("Google search failed: %s", e)
        return "Search failed"

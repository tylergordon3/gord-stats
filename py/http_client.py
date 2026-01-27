import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def retry_session(retries: int = 3, backoff_factor: float = 0.3) -> requests.Session:
    """Configures a requests Session with retry logic and exponential backoff."""
    session = requests.Session()
    # Define which status codes should trigger a retry (e.g., 429, 500, 502, etc.)
    retry_strategy = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(['GET']) # Only retry GET requests by default
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    return session
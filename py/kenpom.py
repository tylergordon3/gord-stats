'''
Docstring for py.kenpom
Documentation:
    https://kenpom.com/api-documentation.php
'''
import os
import http_client
from dotenv import load_dotenv

load_dotenv() 

KENPOM_KEY = os.getenv("KENPOM")
DEFAULT_TIMEOUT = (5, 10)
BASE_URL = "https://kenpom.com/api.php"
HEADERS = {
        "Authorization": f"Bearer {KENPOM_KEY}",
        "Accept": "application/json"
    }

def request_kp(params: dict) -> dict:
    # create session
    session = http_client.retry_session()
    try:
        # try to request data
        result = session.get(BASE_URL, params=params, headers=HEADERS, timeout=DEFAULT_TIMEOUT)
        result.raise_for_status()
    except Exception as e:
        # error handling
        print(f"An error occurred during the request: {e}")
        return None
    finally:
        # close session
        session.close()
    # return result as json
    return result.json()
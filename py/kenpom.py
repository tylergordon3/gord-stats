'''
Docstring for py.kenpom
Documentation:
    https://kenpom.com/api-documentation.php
'''
import os
from dotenv import load_dotenv

load_dotenv() 

KENPOM_KEY = os.getenv("KENPOM")
BASE_URL = "https://kenpom.com/api.php"
HEADERS = {
        "Authorization": f"Bearer {KENPOM_KEY}",
        "Accept": "application/json"
    }
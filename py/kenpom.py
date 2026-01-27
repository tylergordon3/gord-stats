import os
from dotenv import load_dotenv

load_dotenv() 

KENPOM_KEY = os.getenv("KENPOM")
BASE_URL = "https://kenpom.com/api.php"
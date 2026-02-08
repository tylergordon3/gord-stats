'''
Used to collect daily needed data
'''
import os, pytz, time
import utils, scraper, kenpom, bpi
from datetime import datetime

ESPN_PATH = utils.get_path(f"data/men/espn")
TORVIK_MEN_PATH = utils.get_path(f"data/men/torvik")
KENPOM_PATH = utils.get_path(f"data/men/kenpom_api")
TORVIK_WOMEN_PATH = utils.get_path(f"data/women/torvik")

RETRY_SLEEP = 300
MAX_RETRIES = 5

def check_scrape(path):
    return os.path.exists(path) and os.path.getsize(path) > 0

def main():
    now = datetime.now().replace(tzinfo=pytz.timezone("US/Eastern"))
    today = now.strftime("%Y-%m-%d")
    file = f"/{today}.json"
    
    targets = {
        "Men's Torvik": (TORVIK_MEN_PATH + file, lambda: scraper.torvik(today)),
        "KenPom": (KENPOM_PATH + file, kenpom.kenpom_now),
        "ESPN BPI": (ESPN_PATH + file, bpi.main),
        "Women's Torvik": (TORVIK_WOMEN_PATH + file, lambda: scraper.torvik_w(today)),
    }
    
    success = True
    
    for name, (path, func) in targets.items():
        print(path)
        if check_scrape(path):
            continue
        
        try: 
            func()
            if check_scrape(path):
                print(f"Scraped {name} for {today}.")
            else: 
                print(f"Ran {name} for {today} but encountered an error.")
                success = False
        except Exception as e:
            print(f"Error scraping {name} : {e}")
            success = False
    return success
                
if __name__ == "__main__":
    attempts = 0
    
    while attempts < MAX_RETRIES:
        ok = main()
        
        if ok:
            print(f"Daily file collection complete.")
            break
        
        attempts += 1
        print(f"Retry {attempts}/{MAX_RETRIES} in {RETRY_SLEEP} seconds.")
        time.sleep(RETRY_SLEEP)
    
    if attempts == MAX_RETRIES:
        print("Max retries reached, some data may be missing.")

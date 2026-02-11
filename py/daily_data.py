'''
Used to collect daily needed data
'''
import pytz, time
import scraper, kenpom, bpi, net
from datetime import datetime
from lib import paths
from pathlib import Path

RETRY_SLEEP = 300
MAX_RETRIES = 5

def check_scrape(path):
    return path.exists()

def main():
    now = datetime.now().replace(tzinfo=pytz.timezone("US/Eastern"))
    today = now.strftime("%Y-%m-%d")
    fp = Path(f'{today}.json')
    targets = {
        "Men's Torvik": (paths.M_TOR_DIR / fp, lambda: scraper.torvik(today)),
        "KenPom": (paths.M_KEN_DIR / fp, kenpom.kenpom_now),
        "Men's Net Rankings" : (paths.M_NET_DIR / fp, lambda: net.main("M")),
        "ESPN BPI": (paths.M_ESPN_DIR / fp, bpi.main),
        "Women's Net Rankings" : (paths.W_NET_DIR / fp, lambda: net.main("W")),
        "Women's Torvik": (paths.W_TOR_DIR / fp, lambda: scraper.torvik_w(today)),
    }

    success = True
    
    for name, (path, func) in targets.items():
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
                
def get_data():
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

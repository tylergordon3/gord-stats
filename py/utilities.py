from datetime import date, timedelta
import math
import pandas as pd
import json

def getToday():
   today = date.today()
   return today

def getYrStr():
    year_arr = get_current_season()
    yr_start= str(year_arr[0])
    yr_end = str(year_arr[1])
    yr = yr_start[2:] + yr_end[2:]
    return yr

def get_current_season():
    '''
        Returns current season as array with start/end year
    '''
    # year in YYYY
    year = date.today().year
    
    # month 1-12
    month = date.today().month
    
    if month > 9:
        return [year, year+1]
    elif month < 2:
        return [year-1, year]
    else:
        print('It\'s the offseason!')
        return [year, year]

def get_week():
    '''
        Returns week of NFL season. 
        Week is Friday to Thursday
        Next week starts at conclusion of TNF
        (NFL stats refresh 12:30 am Friday morning)
    '''
    year = get_current_season()
    sept_year = year[0]
    first_thursday = date(sept_year, 9, 1)
    while  first_thursday.weekday() != 3:  
        first_thursday += timedelta(days=1)
    today = date.today()
    days_diff = (today - first_thursday).days
    approx_weeks = days_diff / 7
    weeks = math.ceil(approx_weeks) 
    return math.ceil(weeks)

def get_last_completed_week():
    year = get_current_season()
    sept_year = year[0]
    first_thursday = date(sept_year, 9, 1)
    while  first_thursday.weekday() != 3:  
        first_thursday += timedelta(days=1)
    today = date.today()
    days_diff = (today - first_thursday).days
    approx_weeks = days_diff / 7
    if (today.weekday() > 0) & (today.weekday() < 4):
        weeks = math.ceil(approx_weeks)
    else:
        weeks = math.floor(approx_weeks)
    return weeks

get_last_completed_week()
def save_df_to_json(df, filename):
    """
    Saves Python DataFrame to a JSON file.

    Args:
        data: The Python DataFrame to be saved.
        filename: The name of the file to save the JSON data to.
    """
    try:
        df.to_json(filename, orient='records', indent=4) 
        print(f"Data successfully saved to {filename}")
    except IOError as e:
        print(f"Error saving data to {filename}: {e}")

def  load_df_from_json(filename):
    """
    Loads JSON data from a file and returns it as a Python DataFrame.

    Args:
        filename: The name of the JSON file to load.

    Returns:
        The Python DataFrame loaded from the JSON file, or None if an error occurs.
    """
    try:
        df = pd.read_json(filename)
     
        print(f"Data successfully loaded from {filename}")
        return df
    except FileNotFoundError:
        print(f"Error: File '{filename}' not found.")
        return None
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from {filename}: {e}")
        return None
    except IOError as e:
        print(f"Error loading data from {filename}: {e}")
        return None
    
get_week()
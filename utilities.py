import datetime
import math

def get_current_season():
    '''
        Returns current season as array with start/end year
    '''
    # year in YYYY
    year = datetime.date.today().year
    
    # month 1-12
    month = datetime.date.today().month
    
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
    first_thursday = datetime.date(sept_year, 9, 1)
    while  first_thursday.weekday() != 3:  
        first_thursday += datetime.timedelta(days=1)
    today = datetime.date.today()
    days_diff = (today - first_thursday).days
    approx_weeks = days_diff / 7
    
    adjustment = 0 if today.weekday() < 4 else 1
   
    return math.ceil(approx_weeks) + adjustment





import utils
import os
import pandas as pd
import scraper

def upd():
    master = scraper.getMasterTeams()
    for index, row in master.iterrows():
        new = row['team'].lower()
        new = new.replace('.', '')
        new = new.replace(' ', '')
        namearr = row['names']
        if new in row.names:
            pass
        else:
            namearr.append(new)
            master.at[index, 'names'] = namearr
    scraper.saveMasterTeams(master)

path = utils.get_path('docs/assets/images')

directory = os.listdir(path)
master = scraper.getMasterTeams()
master['image'] = sorted(directory)
master['image'] = master['image'].apply(lambda x: x[:-4])

def check(row):
    s_exploded = master["names"].explode()
    boolean_mask_exploded = s_exploded == row.image
    # To get the row IDs where the value is present:
    matching_ids = s_exploded[boolean_mask_exploded].index.unique()
    boolean_mask_original = boolean_mask_exploded.groupby(level=0).any()
    df_result = master[boolean_mask_original]
   
    if df_result.empty:
        return ''
    else:
        return matching_ids
    
master['team'] = master['team'].replace('.','')
master['check'] = master.apply(lambda x: check(x), axis=1)
print(master[master['check'] == ''])


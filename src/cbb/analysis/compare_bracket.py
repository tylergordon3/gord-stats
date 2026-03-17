import json
import re
import pandas as pd
from bs4 import BeautifulSoup
from cbb.lib import paths, teams

file = paths.MARCH_FILE
with open(file, "r") as f:
        all = json.load(f)

men = all.get("Men").get("2026")
women = all.get("Women").get("2026")

my_m_file = paths.FINAL_26_BRACKET_M
my_w_file = paths.FINAL_26_BRACKET_W

with open(my_m_file, 'r', encoding='utf-8') as f:
    html_content = f.read()
soup = BeautifulSoup(html_content, "html.parser")
table = soup.find("table")

rows = []
my_pred = {}
for row in table.find_all("tr"):
    cols = [col.get_text(strip=True) for col in row.find_all("td")]
    if any(cols):
        pattern = r' \(.+\)F*'
        team = re.sub(pattern, "", cols[0])
 
        seed_pat = r'\(Seed (\d+)\)'
        match = re.search(seed_pat, cols[3])
        seed = match[1]

        my_pred[teams.getTeamOfficialName(team)] = seed

actual = {}
for key in men.keys():
    arr = men.get(key)
    for team in arr:
        actual[teams.getTeamOfficialName(team)] = key

data = {"preds":my_pred, "actual" : actual}
df = pd.DataFrame.from_dict(data)
df['preds'] = df['preds'].fillna(-1)
df['actual'] = df['actual'].fillna(-1)

condition = (df['preds'] == -1) | (df['actual'] == -1)

df['diff'] = pd.to_numeric(df["actual"]) - pd.to_numeric(df["preds"])

missed = df[condition]
df = df[~condition]

df = df.sort_values(by="diff", ascending=False)

print(df.to_string())
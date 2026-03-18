import json
import re
import pandas as pd
from bs4 import BeautifulSoup
from cbb.lib import paths, teams
import matplotlib.pyplot as plt

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

df['err_size'] = df['diff'].abs() 
plt.figure(figsize=(20, 6))
df = df.reset_index()
df["preds"] = pd.to_numeric(df["preds"])
df["actual"] = pd.to_numeric(df["actual"])
# Create a numeric range for the X-axis positions
x_pos = range(len(df))

# Plot 'preds' using the numeric x_pos
plt.errorbar(x_pos, df['preds'], 
             fmt='o', label='Predictions', capsize=3, alpha=0.7)

# Plot 'actual' using the numeric x_pos
plt.errorbar(x_pos, df['actual'], 
             fmt='s', label='Actual', capsize=3, alpha=0.7)

# Set the labels back to the team names
plt.xticks(ticks=x_pos, labels=df['index'], rotation=45, ha='right')

plt.ylabel("Seed Value")
plt.title("2026 Bracket Seeds: Predictions vs Actual")
plt.legend()
plt.tight_layout() # Prevents labels from getting cut off
plt.savefig("line_chart.png")
plt.show()
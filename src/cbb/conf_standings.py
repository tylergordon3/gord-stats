import bpi
import pandas as pd

data = bpi.get_today_bpi()
df = pd.DataFrame(data["rows"], columns=data["headers"])
df['conf_winp'] = df.apply(lambda x: x['conf_wins'] / (x['conf_losses'] + x['conf_wins']), axis=1)
df['conf_standing'] = df.groupby('conference')['conf_winp'].rank(method='dense', ascending=False)
print(df['conf_standing'].value_counts)

print(df[df['conference_abbr'] == 'big10'])
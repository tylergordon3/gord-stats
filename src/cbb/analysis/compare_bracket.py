import json
import re
import pandas as pd
from bs4 import BeautifulSoup
from cbb.lib import paths, teams
import matplotlib.pyplot as plt

def filter(file, dictp):
    with open(file, 'r', encoding='utf-8') as f:
        html_content = f.read()
    soup = BeautifulSoup(html_content, "html.parser")
    table = soup.find("table")

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
    for key in dictp.keys():
        arr = dictp.get(key)
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
    df = df.sort_values(by="err_size", ascending=False)

    df_over = df[(df["diff"] < 0) & (df["err_size"] > 1)]
    df_under = df[(df["diff"] > 0) & (df["err_size"] > 1)]
    
    df_over = df_over.rename(columns={"index":"Team", "preds":"Modeled Seed",
                                      "actual":"Actual Seed", "diff":"Difference"})
    df_under = df_under.rename(columns={"index":"Team", "preds":"Modeled Seed",
    "actual":"Actual Seed", "diff":"Difference"})
    df_over = df_over.drop(columns=["err_size"])
    df_under = df_under.drop(columns=["err_size"])
    return df_over, df_under

def get_html_table(df, title, table_color="table-dark"):
    # Added 'text-center' to the classes string
    html = df.to_html(
        index=False, 
        classes=f'table table-striped table-hover text-center {table_color}',
        border=0,
        justify='center' # This specifically ensures the header text is centered
    )
    # Added 'text-center' to the <h3> to keep the title aligned with the table
    return f"<h3 class='text-center'>{title}</h3>{html}"

def gen():
    file = paths.MARCH_FILE
    with open(file, "r") as f:
            all = json.load(f)

    men = all.get("Men").get("2026")
    women = all.get("Women").get("2026")

    my_m_file = paths.FINAL_26_BRACKET_M
    my_w_file = paths.FINAL_26_BRACKET_W

    m_over, m_under = filter(my_m_file, men)
    w_over, w_under = filter(my_w_file, women)
    m_over_html = get_html_table(m_over, "Men: Over-Seeded", "table-danger")
    m_under_html = get_html_table(m_under, "Men: Under-Seeded", "table-success")
    w_over_html = get_html_table(w_over, "Women: Over-Seeded", "table-danger")
    w_under_html = get_html_table(w_under, "Women: Under-Seeded", "table-success")

    html = f'''
    <div class="container-fluid">
        <h1 class="text-center mb-5">March Madness 2026 Seed Analysis</h1>
        
        <div class="row">
            <!-- Men's Section -->
            <div class="col-md-6 table-container">{m_over_html}</div>
            <div class="col-md-6 table-container">{m_under_html}</div>
        </div>

        <div class="row">
            <!-- Women's Section -->
            <div class="col-md-6 table-container">{w_over_html}</div>
            <div class="col-md-6 table-container">{w_under_html}</div>
        </div>
    </div>
    '''

    return html
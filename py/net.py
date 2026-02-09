import requests
from bs4 import BeautifulSoup

URL="https://www.ncaa.com/rankings/basketball-men/d1/ncaa-mens-basketball-net-rankings"

def net_ranks():
    resp = requests.get(URL)
    soup = BeautifulSoup(resp.content, 'html.parser')
    table = soup.find("table")
    headers = table.find_all("tr")[0]
    rows = table.find_all("tr")[1:]

    cols = []
    for hdr in headers:
        text = hdr.get_text(strip=True)
        if len(text) <= 0:
            continue
        cols.append(text)

    table_data = []
    for row in rows:
        row_data = []
        for td in row.find_all("td"):
            cell_text = td.get_text(strip=True)
            if len(cell_text) <= 0:
                continue
            row_data.append(cell_text)
        table_data.append(row_data)
    print(table_data)
net_ranks()
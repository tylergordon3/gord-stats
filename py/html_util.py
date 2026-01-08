import re

light_grid_style_data = {
    'selector': 'td',
    'props': [
        ('border', '1px solid black')
    ]
}
light_grid_style_header = {
    'selector': 'th',
    'props': [
        ('border', '1px solid black')
    ]
}

def highlight_roto(col):
    max_w = col.apply(lambda x: int(x.split('-')[0])).max()
    min_w = col.apply(lambda x: int(x.split('-')[0])).min()
    return ['background-color: #c8e6c9' if int(x.split('-')[0]) == max_w
            else 'background-color: #ffcdd2' if int(x.split('-')[0]) == min_w
            else '' for x in col]

def getIndValues(str):
    pattern = r"(\d{1,2})-(\d{1,2})"
    match = re.search(pattern, str)
    wins = int(match.group(1))
    loss = int(match.group(2))
    return [wins, loss]

def highlight_on_record(styles):
    def getColor(val):
        [wins, loss] = getIndValues(val)
        if wins > loss:
            color = '#CCDDAA'
        elif wins < loss:
            color = '#FFCCCC'
        else: 
            color = "#F1EABE"
        return f'background-color: {color}'
    ret = map(getColor, list(styles))
    return list(ret)


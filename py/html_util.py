

def highlight_roto(col):
    max_w = col.apply(lambda x: int(x.split('-')[0])).max()
    min_w = col.apply(lambda x: int(x.split('-')[0])).min()
    return ['background-color: #c8e6c9' if int(x.split('-')[0]) == max_w
            else 'background-color: #ffcdd2' if int(x.split('-')[0]) == min_w
            else '' for x in col]

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
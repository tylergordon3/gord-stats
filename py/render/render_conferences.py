import pandas as pd

def main(df):
    confs = pd.unique(df['Conf'])
    print(confs)
    return
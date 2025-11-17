import kagglehub
import numpy as np
import utils
import matplotlib.pyplot as plt
from kagglehub import KaggleDatasetAdapter

def initDataset():
    # Load cbb dataset containing data from 2013-2024
    cbb_full = kagglehub.dataset_load(
        KaggleDatasetAdapter.PANDAS,
        "andrewsundberg/college-basketball-dataset",
        "cbb.csv",
    )
    cbb_full['TOURNEY'] = np.where(cbb_full['POSTSEASON'].notnull(), True, False)

    utils.save_json_data(cbb_full.to_json(), "model_data/cbb_data.json")

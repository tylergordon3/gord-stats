import json
import pickle
import pandas as pd
from io import StringIO
from pathlib import Path
from datetime import date
import constants


def save_json_data(data, filename):
    """
    Saves Python data to a JSON file.

    Args:
        data: The Python object (e.g., dictionary, list) to be saved.
        filename: The name of the file to save the JSON data to.
    """
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        print(f"Data successfully saved to {filename}")
    except IOError as e:
        print(f"Error saving data to {filename}: {e}")

def load_json_data(filename):
    """
    Loads JSON data from a file and returns it as a Python object.

    Args:
        filename: The name of the JSON file to load.

    Returns:
        The Python object loaded from the JSON file, or None if an error occurs.
    """
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
        headers = data["headers"]
        rows = data["rows"]

        df = pd.DataFrame(rows, columns=headers)
        print(f"Data successfully loaded from {filename}")
        return df
    except FileNotFoundError:
        print(f"Error: File '{filename}' not found.")
        return None
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from {filename}: {e}")
        return None
    except IOError as e:
        print(f"Error loading data from {filename}: {e}")
        return None
    
def save_to_html(path, data):
    with open(path, 'w') as f:
        f.write(data)
    return

def write_to_pickle(model, path):
    with open(path, 'wb') as file:
        pickle.dump(model, file)

def read_from_pickle(name):
    filename = f'/home/tgordon/cbb-model/models/{name}_model.pkl'
    with open(filename, 'rb') as file:
        loaded_model = pickle.load(file)
    return loaded_model

def get_recent_data():
    today  = date.today()
    def parse_date(fname):
        # filename format: kenpomYYYY-MM-DD.json
        try:
            return date.fromisoformat(fname[6:16])
        except ValueError:
            raise ValueError(f"Invalid date in filename: {fname}")

    kenpom_files = Path('/home/tgordon/cbb-model/data/').glob("kenpom*.json")
    kenpom = min(kenpom_files, key=lambda p: abs((parse_date(p.name) - today).days))

    torvik_files = Path('/home/tgordon/cbb-model/data/').glob("torvik*.json")
    torvik = min(torvik_files, key=lambda p: abs((parse_date(p.name) - today).days))
    return [kenpom, torvik]
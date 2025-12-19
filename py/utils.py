import json
import pickle
import pandas as pd
import os
from io import StringIO
from pathlib import Path
from datetime import date
import constants
from pathlib import Path

def find_team():
    # Assumptions:
    # State (from St., St)
    # St (from Saint)
    return
def root():
    return Path(__file__).parent.parent

def get_path(local_path):
    return os.path.join(root(), Path(local_path))

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
            data = json.loads(json.load(f))
            
        df = pd.DataFrame(data)
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
    filename = get_path(f'models/{name}_model.pkl')
    with open(filename, 'rb') as file:
        loaded_model = pickle.load(file)
    return loaded_model

def get_recent_data(input_date, women=0):
    def parse_date(fname):
        # filename format: kenpomYYYY-MM-DD.json
        try:
            return date.fromisoformat(fname[6:16])
        except ValueError:
            raise ValueError(f"Invalid date in filename: {fname}")
    def parse_date_w(fname):
        # filename format: torvik_wYYYY-MM-DD.json
        try:
            return date.fromisoformat(fname[8:18])
        except ValueError:
            raise ValueError(f"Invalid date in filename: {fname}")
    if women:
        path = get_path('data_w/')
    
        torvik_files = Path(path).glob("torvik_w*.json")
        torvik = min(torvik_files, key=lambda p: abs((parse_date_w(p.name) - input_date).days))
        return torvik
    else:
        path = get_path('data/')
        kenpom_files = Path(path).glob("kenpom*.json")
        kenpom = min(kenpom_files, key=lambda p: abs((parse_date(p.name) - input_date).days))

        torvik_files = Path(path).glob("torvik*.json")
        torvik = min(torvik_files, key=lambda p: abs((parse_date(p.name) - input_date).days))
        return [kenpom, torvik]

def get_recent_html(input_date):
    def parse_date(fname):
        # filename format: predict_YYYY:MM:DD.html
        try:
            return date.fromisoformat(fname[8:18])
        except ValueError:
            raise ValueError(f"Invalid date in filename: {fname}")
    path = get_path('docs/men/')
    html_files = Path(path).glob("predict_[0-9]*.html")
    html = min(html_files, key=lambda p: abs((parse_date(p.name) - input_date).days))
    return html

def get_recent_html_w(input_date):
    def parse_date(fname):
        # filename format: predict_wYYYY-MM-DD.html
        try:
            return date.fromisoformat(fname[9:19])
        except ValueError:
            raise ValueError(f"Invalid date in filename: {fname}")
    path = get_path('docs/women/')
    html_files = Path(path).glob("predict_w*.html")
    html = min(html_files, key=lambda p: abs((parse_date(p.name) - input_date).days))
    return html
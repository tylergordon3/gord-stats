import json
import os
import pickle
from datetime import date
from pathlib import Path

import pandas as pd

from cbb.lib import paths


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
        with open(filename, "w", encoding="utf-8") as f:
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
        with open(filename, "r", encoding="utf-8") as f:
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
    with open(path, "w") as f:
        f.write(data)
    return


def write_to_pickle(model, path):
    with open(path, "wb") as file:
        pickle.dump(model, file)


def read_from_pickle(name):
    filename = get_path(f"models/{name}_model.pkl")
    with open(filename, "rb") as file:
        loaded_model = pickle.load(file)
    return loaded_model


def get_recent_data(input_date, women=0):
    # Helper function to parse data from file
    def parse_date(fname):
        try:
            return date.fromisoformat(fname[:10])
        except ValueError:
            raise ValueError(f"Invalid date in filename: {fname}")

    # Process if women
    if women:
        torvik_files = paths.W_TOR_DIR.glob("*.json")
        torvik = min(
            torvik_files, key=lambda p: abs((parse_date(p.name) - input_date).days)
        )
        return torvik

    if input_date < date(2026, 1, 28):
        kenpom_files = paths.M_KEN_OLD_DIR.glob("kenpom*.json")
    else:
        kenpom_files = paths.M_KEN_DIR.glob("*.json")

    kenpom = min(
        kenpom_files, key=lambda p: abs((parse_date(p.name) - input_date).days)
    )

    torvik_files = paths.M_TOR_DIR.glob("*.json")
    torvik = min(
        torvik_files, key=lambda p: abs((parse_date(p.name) - input_date).days)
    )
    return [kenpom, torvik]


def get_recent_html(input_date):
    def parse_date(fname):
        # filename format: predict_YYYY:MM:DD.html
        try:
            return date.fromisoformat(fname[8:18])
        except ValueError:
            raise ValueError(f"Invalid date in filename: {fname}")

    path = get_path("docs/men/")
    html_files = Path(path).glob("predict_[0-9]*.html")
    html = min(html_files, key=lambda p: abs((parse_date(p.name) - input_date).days))
    return html


def get_recent_html_w(input_date):
    def parse_date(fname):
        # filename format: predict_wYYYY-MM-DD.html
        try:
            return date.fromisoformat(fname[8:18])
        except ValueError:
            raise ValueError(f"Invalid date in filename: {fname}")

    path = get_path("docs/women/")
    html_files = Path(path).glob("predict_*.html")
    html = min(html_files, key=lambda p: abs((parse_date(p.name) - input_date).days))
    return html


def check_p5(home, away):
    p5 = [
        "Big Ten Women",
        "Big Ten",
        "Big 12",
        "Big 12 Women",
        "Atlantic Coast",
        "Atlantic Coast Women",
        "Big East Women",
        "Big East",
        "Southeastern Women",
        "Southeastern",
    ]
    if (home in p5) & (away in p5):
        return True
    else:
        return False

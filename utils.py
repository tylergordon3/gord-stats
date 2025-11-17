import json

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
        print(f"Data successfully loaded from {filename}")
        return data
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
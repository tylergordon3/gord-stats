
import utils
import os

folder = utils.get_path(utils.get_path('docs/assets/images/'))


replacements = {
    '_':'',
    'state':'st'
}
for filename in os.listdir(folder):
    old_path = os.path.join(folder, filename)

    # Skip directories
    if not os.path.isfile(old_path):
        continue
    
    # Transform filename
    new_filename = filename.lower()
    for old, new in replacements.items():
        new_filename = new_filename.replace(old, new)
    new_path = os.path.join(folder, new_filename)

    # Only rename if different
    if old_path != new_path:
        os.rename(old_path, new_path)
        print(f"Renamed: {filename} -> {new_filename}")
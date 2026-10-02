import json
from pathlib import Path


def load_json_data(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def script_json(obj, **kw) -> str:
    """`obj` as JSON safe inside a <script> element.

    Escaping only "</" left "<!--" alone, and a name holding "<!--<script"
    makes the browser swallow the next script into the data block. With
    <, > and & as \\u escapes no name can end or bend the element; JSON.parse
    reads them back unchanged.
    """
    return (json.dumps(obj, **kw).replace("<", "\\u003c")
            .replace(">", "\\u003e").replace("&", "\\u0026"))

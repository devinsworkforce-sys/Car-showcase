import json
import os


def safe_load(path, default):
    if not os.path.exists(path):
        return default
    try:
        content = open(path).read().strip()
        if not content:
            return default
        return json.loads(content)
    except Exception:
        return default

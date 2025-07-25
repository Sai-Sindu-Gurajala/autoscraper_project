import pandas as pd
import os
from datetime import datetime

def flatten_data(data):
    """Flattens a list of dicts with nested dicts/lists into a flat table."""
    try:
        from pandas import json_normalize
        flat = json_normalize(data)
    except Exception:
        flat = pd.DataFrame(data)
    return flat

def export_data(data, filename=None):
    """
    Exports data to Excel or CSV, flattening nested dicts/lists as needed.
    Filetype is determined by filename (.xlsx or .csv).
    """
    if not filename:
        filename = f"output/scraped_products_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    else:
        if not filename.startswith("output"):
            filename = os.path.join("output", filename)
        if not (filename.lower().endswith(".xlsx") or filename.lower().endswith(".csv")):
            filename += ".xlsx"
    os.makedirs(os.path.dirname(filename), exist_ok=True)

    df = flatten_data(data)
    if filename.lower().endswith(".csv"):
        df.to_csv(filename, index=False, encoding="utf-8")
    else:
        df.to_excel(filename, index=False)
    print(f"Exported data to {filename}")
    return df

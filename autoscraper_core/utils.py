import os
import json
from datetime import datetime
import pandas as pd

def flatten_data(data):
    """
    Flattens a list of dicts (in case some fields are nested).
    Tries to use pandas.json_normalize for best results.
    """
    try:
        from pandas import json_normalize
        flat = json_normalize(data)
    except Exception:
        flat = pd.DataFrame(data)
    return flat

def export_data(data, filename: str = None):
    """
    Export scraped data to Excel, CSV or JSON.

    - Removes duplicates by 'Product Link' (or 'href'/'url')
    - Uses these columns (if possible): Product Name, Product Link, Item Description, Image
    - If no filename, exports to output/scraped_products_TIMESTAMP.xlsx
    """
    export_cols = ["Product Name", "Product Link", "Item Description", "Image"]
    unique = {}
    for row in data:
        key = row.get("Product Link") or row.get("href") or row.get("url")
        if key and key not in unique:
            unique[key] = {
                "Product Name": row.get("name") or row.get("Product Name") or row.get("text") or "",
                "Product Link": row.get("Product Link") or row.get("href") or row.get("url") or "",
                "Item Description": row.get("Item Description") or row.get("description") or row.get("text") or "",
                "Image": row.get("image") or row.get("Image") or "",
            }
    cleaned_data = list(unique.values())
    if not cleaned_data and data:
        cleaned_data = data

    # --- Handle filename ---
    if not filename:
        os.makedirs("output", exist_ok=True)
        filename = f"output/scraped_products_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    else:
        if not os.path.isabs(filename):
            filename = os.path.join("output", filename)
        base, ext = os.path.splitext(filename)
        if not ext:
            filename = f"{filename}.xlsx"

    os.makedirs(os.path.dirname(filename), exist_ok=True)
    ext = filename.lower().split('.')[-1]

    df = flatten_data(cleaned_data)
    # Use our columns if possible
    if all(col in df.columns for col in export_cols):
        df = df[export_cols]

    if ext == "csv":
        df.to_csv(filename, index=False, encoding="utf-8")
    elif ext == "json":
        with open(filename, "w", encoding="utf8") as f:
            json.dump(cleaned_data, f, indent=2, ensure_ascii=False)
    else:
        df.to_excel(filename, index=False)
    print(f"Exported data to {filename}")
    return df

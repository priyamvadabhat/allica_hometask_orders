import pandas as pd
from pathlib import Path

def convert_all_xlsx(input_dir: str | Path) -> None:
    input_path = Path(input_dir)

    for xlsx_file in input_path.glob("*.xlsx"):
        csv_file = xlsx_file.with_suffix(".csv")
        try:
            df = pd.read_excel(xlsx_file)
            df.to_csv(csv_file, index=False)
            print(f"✅ Converted {xlsx_file.name} -> {csv_file.name}")
        except Exception as e:
            print(f"❌ Failed to convert {xlsx_file.name}: {e}")
            continue

        # Try deletion separately
        try:
            print(f"🗑️ Attempting to delete {xlsx_file}")
            xlsx_file.unlink()
            print(f"🗑️ Deleted {xlsx_file.name}")
        except Exception as del_err:
            print(f"⚠️ Could not delete {xlsx_file.name}: {del_err}")

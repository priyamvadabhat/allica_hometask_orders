import pandas as pd

# Read the Excel file
df = pd.read_excel("/workspaces/allica_hometask_orders/data/raw/orders_2023.xlsx")

# Export to CSV
df.to_csv("/workspaces/allica_hometask_orders/data/raw/orders_2023.csv", index=False)

print("✅ Conversion complete! File saved as orders_2023.csv")

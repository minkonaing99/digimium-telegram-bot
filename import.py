import pandas as pd
import mysql.connector
import creds
import math

# Load CSV
df = pd.read_csv("final_product_sold_duration_fixed.csv")

# Replace float NaNs with None
df = df.where(pd.notnull(df), None)

# Clean string 'nan' or real NaNs from object columns
for col in df.columns:
    if df[col].dtype == object or col == 'gmail':
        df[col] = df[col].apply(lambda x: None if x is None or (isinstance(x, float) and math.isnan(x)) or str(x).strip().lower() == 'nan' else x)

# Ensure product_id is int or None
if 'product_id' in df.columns:
    def clean_product_id(x):
        try:
            return None if x is None or (isinstance(x, float) and math.isnan(x)) else int(x)
        except:
            return None
    df['product_id'] = df['product_id'].apply(clean_product_id)

# Now connect and insert...
conn = mysql.connector.connect(**creds.DB_CONFIG)
cursor = conn.cursor()

insert_query = """
    INSERT INTO product_sold (
        product_id, product_name, duration, customer, gmail,
        price, profit, purchase_date, end_date,
        seller, note
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

for _, row in df.iterrows():
    values = (
        row['product_id'],
        row['product_name'],
        row['duration'],
        row['customer'],
        row['gmail'],
        float(row['price']) if row['price'] is not None else None,
        float(row['profit']) if row['profit'] is not None else None,
        row['purchase_date'],
        row['end_date'],
        row['seller'],
        row['note']
    )
    print("Inserting:", values)
    cursor.execute(insert_query, values)

conn.commit()
print(f"{cursor.rowcount} rows inserted successfully.")
cursor.close()
conn.close()

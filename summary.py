import pymysql
import pandas as pd
import json
from datetime import datetime, timedelta
from creds import DB_CONFIG, GEMINI_API_KEY
import google.generativeai as genai

# 1. Configure Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash-latest")


# 2. Date Setup
today = datetime.now().date()
yesterday = today - timedelta(days=1)
today_str = today.strftime('%Y-%m-%d')
yesterday_str = yesterday.strftime('%Y-%m-%d')

# 3. Connect to MySQL
conn = pymysql.connect(
    host=DB_CONFIG['host'],
    user=DB_CONFIG['user'],
    password=DB_CONFIG['password'],
    database=DB_CONFIG['database'],
    port=DB_CONFIG['port']
)
cursor = conn.cursor()

# 4. Query sales for today and yesterday
query = """
SELECT product_name, customer, seller, price, profit, purchase_date, end_date, note
FROM product_sold
WHERE DATE(purchase_date) IN (%s, %s)
"""
df = pd.read_sql(query, conn, params=[yesterday_str, today_str])

if df.empty:
    print("No data for today or yesterday.")
    exit()


# 5. Preprocess dates
df["purchase_date"] = pd.to_datetime(df["purchase_date"]).dt.date
df["end_date"] = pd.to_datetime(df["end_date"]).dt.date

# 6. Split & analyze
df_today = df[df["purchase_date"] == today]
df_yesterday = df[df["purchase_date"] == yesterday]
expiring_today = df[df["end_date"] == today]
expiring_yesterday = df[df["end_date"] == yesterday]
repeat_customers = set(df_today["customer"]) & set(df_yesterday["customer"])


def df_to_json(dframe):
    df_copy = dframe.copy()
    df_copy["purchase_date"] = df_copy["purchase_date"].astype(str)
    df_copy["end_date"] = df_copy["end_date"].astype(str)
    return json.dumps(df_copy.to_dict(orient="records"), indent=2)


# 7. Create Gemini Prompt
prompt = f"""
You're a friendly sales manager helping a small team understand their sales. If sales rises praise them. If sales drop, scold them.
Based on the 2-day sales data below, write a short and casual 5-line summary.

Be warm, easy to read, and sound like you're speaking to colleagues — not like a robot or data scientist.

Sales on {yesterday_str}:
{df_to_json(df_yesterday)}

Sales on {today_str}:
{df_to_json(df_today)}

Other Notes:
- {len(expiring_yesterday)} subscriptions expired on {yesterday_str}
- {len(expiring_today)} subscriptions expired on {today_str}
- Repeat customers: {', '.join(repeat_customers) if repeat_customers else 'None'}

Your summary should:
- Highlight the top 1–3 products sold across both days.
- Mention whether any customers came back both days.
- Briefly compare overall performance (sales/profit).
- Suggest something helpful to try next.
-check notes and give remarks if there
Only give the 5-line summary — no extra text, no labels, no explanations. Just speak naturally and clearly.
"""


# 8. Generate summary with Gemini
try:
    response = model.generate_content(prompt)
    summary_text = response.text.strip()
    print("\n📊 Summary from Gemini:\n", summary_text)
except Exception as e:
    print("Gemini API error:", e)
    conn.close()
    exit()

# 9. Insert summary into log table
insert_query = """
INSERT INTO sales_summary_log (summary_date, summary_text, created_at)
VALUES (%s, %s, NOW())
"""
cursor.execute(insert_query, (today_str, summary_text))
conn.commit()

cursor.close()
conn.close()

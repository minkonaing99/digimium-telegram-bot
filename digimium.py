import asyncio
import nest_asyncio
from creds import BOT_TOKEN, DB_CONFIG
nest_asyncio.apply()

import mysql.connector
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)


# === DB Helpers ===
def fetch_products(table):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute(f"SELECT product_name FROM {table}")
        return [row[0] for row in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()

def fetch_product_details(name, table):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True, buffered=True)
        cursor.execute(f"SELECT * FROM {table} WHERE product_name = %s", (name,))
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()
        
def get_summary_data(date_str):
    total_profit = 0
    total_sales = 0

    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # Retail
        cursor.execute("""
            SELECT SUM(price), SUM(profit)
            FROM product_sold
            WHERE purchase_date = %s
        """, (date_str,))
        retail_sum = cursor.fetchone()
        retail_sales = float(retail_sum[0] or 0)
        retail_profit = float(retail_sum[1] or 0)

        # WC
        cursor.execute("""
            SELECT SUM(price * quantity), SUM(profit)
            FROM wc_product_sold
            WHERE date = %s
        """, (date_str,))
        wc_sum = cursor.fetchone()
        wc_sales = float(wc_sum[0] or 0)
        wc_profit = float(wc_sum[1] or 0)

        total_sales = retail_sales + wc_sales
        total_profit = retail_profit + wc_profit

        return total_sales, total_profit

    except Exception as e:
        print("Summary error:", e)
        return None, None
    finally:
        try:
            cursor.close()
            conn.close()
        except:
            pass
        

def save_retail(data):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO product_sold
            (product_id, product_name, duration, customer, gmail, price, profit, purchase_date, end_date, seller, note)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            data['product_id'], data['product_name'], data['duration'], data['customer'],
            data['gmail'], data['price'], data['profit'], data['purchase_date'],
            data['end_date'], data['seller'], data['note']
        ))
        conn.commit()
        return True
    finally:
        cursor.close()
        conn.close()

def save_wc(data):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO wc_product_sold
            (product_id, product_name, customer, email, quantity, price, profit, seller, note, date)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            data['product_id'], data['product_name'], data['customer'], data['email'],
            data['quantity'], data['price'], data['profit'], data['seller'], data['note'], data['date']
        ))
        conn.commit()
        return True
    finally:
        cursor.close()
        conn.close()

# === HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Retail", callback_data='retail')],
        [InlineKeyboardButton("WC", callback_data='wc')]
    ]
    await update.message.reply_text("Choose one:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data in ('retail', 'wc'):
        table = 'product_list' if query.data == 'retail' else 'wc_product_list'
        prefix = 'retail_product_' if query.data == 'retail' else 'wc_product_'
        products = fetch_products(table)
        keyboard, row = [], []
        for i, name in enumerate(products, 1):
            row.append(InlineKeyboardButton(name, callback_data=f"{prefix}{name}"))
            if i % 2 == 0:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        await query.edit_message_text(
            f"Select a {query.data.upper()} product:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith("retail_product_"):
        name = query.data.replace("retail_product_", "")
        product = fetch_product_details(name, "product_list")
        context.user_data.update({"flow": "retail", "product": product, "awaiting": True})
        await query.edit_message_text("Enter Customer Name, Gmail, [optional Price] (one per line):")

    elif query.data.startswith("wc_product_"):
        name = query.data.replace("wc_product_", "")
        product = fetch_product_details(name, "wc_product_list")
        context.user_data.update({"flow": "wc", "product": product, "awaiting": True})
        await query.edit_message_text("Enter Name, Email, Quantity, [optional Price] (one per line):")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting"):
        return

    lines = [l.strip() for l in update.message.text.splitlines() if l.strip()]
    product = context.user_data['product']
    flow = context.user_data['flow']
    seller = update.effective_user.username or 'unknown'

    if flow == 'retail' and len(lines) >= 2:
        name, gmail = lines[0], lines[1]
        price = float(lines[2]) if len(lines) >= 3 else float(product['retail_price'])
        wc_price = float(product['wc_price'] or 0)
        profit = price - wc_price
        today = datetime.today()
        end_date = today + timedelta(days=30 * int(product['duration']))
        data = {
            'product_id': product['product_id'],
            'product_name': product['product_name'],
            'duration': product['duration'],
            'customer': name,
            'gmail': gmail,
            'price': price,
            'profit': profit,
            'purchase_date': today.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d'),
            'seller': seller,
            'note': ''
        }
        save_retail(data)
        await update.message.reply_text("Order saved.")

    elif flow == 'wc' and len(lines) >= 3:
        name, email = lines[0], lines[1]
        quantity = int(lines[2])
        price = float(lines[3]) if len(lines) >= 4 else float(product['retail_price'])
        wc_price = float(product['wc_price'] or 0)
        profit = (price - wc_price) * quantity
        data = {
            'product_id': product['product_id'],
            'product_name': product['product_name'],
            'customer': name,
            'email': email,
            'quantity': quantity,
            'price': price,
            'profit': profit,
            'seller': seller,
            'note': '',
            'date': datetime.today().strftime('%Y-%m-%d')
        }
        save_wc(data)
        await update.message.reply_text("Order saved.")

    else:
        await update.message.reply_text("Invalid input format.")

    context.user_data.clear()


async def summary_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if context.args:
            date_str = context.args[0]
            datetime.strptime(date_str, '%Y-%m-%d')  # Validate format
        else:
            date_str = datetime.today().strftime('%Y-%m-%d')
    except ValueError:
        await update.message.reply_text("Invalid date format. Use `/summary YYYY-MM-DD`", parse_mode="Markdown")
        return

    total_sales, total_profit = get_summary_data(date_str)

    if total_sales is None:
        await update.message.reply_text("Failed to fetch summary.")
        return

    response = (
        f"*Summary for {date_str}:*\n\n"
        f"Total Sales: {total_sales:.2f} Ks\n"
        f"Total Profit: {total_profit:.2f} Ks"
    )

    await update.message.reply_text(response, parse_mode="Markdown")

# === COMMAND SET ===
async def set_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Start the bot")
    ])

# === MAIN ===
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    await set_commands(app)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("summary", summary_handler))
    app.add_handler(CallbackQueryHandler(button_handler))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    print("Bot running...")
    await app.run_polling()

if __name__ == '__main__':
    asyncio.run(main())

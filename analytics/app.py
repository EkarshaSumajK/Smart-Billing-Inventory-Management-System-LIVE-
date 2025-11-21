from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_pymongo import PyMongo
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from dateutil import parser
import os
from translations import get_translation as t  # <-- NEW IMPORT

# -----------------------
# Initialization
# -----------------------
load_dotenv()
app = Flask(__name__)
CORS(app)

# MongoDB Config
app.config["MONGO_URI"] = os.getenv("MONGO_URI")
db_name = os.getenv("DB_NAME")
mongo = PyMongo(app)
db = mongo.cx[db_name]

# -----------------------
# Helper Functions
# -----------------------
def normalize_bills(raw_bills):
    """Normalize bills into a consistent DataFrame"""
    records = []
    for bill in raw_bills:
        # Prefer 'createdAt'
        bill_date = bill.get("createdAt") or bill.get("date")
        if isinstance(bill_date, dict) and "$date" in bill_date:
            bill_date = bill_date["$date"]
        bill_date = pd.to_datetime(bill_date)

        total = bill.get("totalAmount") or bill.get("total", 0)
        items = bill.get("items", [])
        for item in items:
            qty = item.get("quantity") or item.get("qty", 0)
            price = item.get("price", 0)
            product_id = item.get("productId") or item.get("product_id") or item.get("id")
            name = item.get("name") or item.get("productName") or "Unknown Product"

            # Only add records with valid data
            if qty > 0 and price > 0:
                records.append({
                    "date": bill_date,
                    "productId": str(product_id) if product_id else "unknown",
                    "name": name,
                    "qty": qty,
                    "price": price,
                    "revenue": price * qty,
                    "total": total
                })

    df = pd.DataFrame(records)
    print(f"📦 Normalized {len(df)} item records from {len(raw_bills)} bills")
    if not df.empty:
        print(f"   Products found: {df['name'].unique().tolist()[:5]}")
    return df


def get_filtered_bills():
    """Apply date filtering if provided"""
    start_str = request.args.get("startDate")
    end_str = request.args.get("endDate")
    shop_id = request.args.get("shopId")

    query = {}
    if start_str and end_str:
        try:
            start_dt = datetime.strptime(start_str, "%Y-%m-%d")
            end_dt = datetime.strptime(end_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            query["createdAt"] = {"$gte": start_dt, "$lte": end_dt}
            print(f"✅ Filtering bills between {start_dt} → {end_dt}")
        except ValueError:
            print("❌ Invalid date format received")
            return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400
    
    if shop_id:
        query["shopId"] = shop_id
        print(f"✅ Filtering bills for shopId: {shop_id}")

    bills = list(db.bills.find(query))
    print(f"📊 Found {len(bills)} bills matching the criteria")
    return bills

# -----------------------
# API Endpoints
# -----------------------

@app.route("/")
def home():
    return jsonify({"status": "Analytics API running 🚀"})


@app.route("/analytics/daily")
def daily_sales():
    raw_bills = get_filtered_bills()
    df = normalize_bills(raw_bills)
    if df.empty:
        return jsonify({
            "daily": [],
            "weekly": [],
            "monthly": [],
            "top_products": [],
            "revenue_trend": [],
            "summary": {
                "total_revenue": 0,
                "total_orders": 0,
                "total_products_sold": 0
            },
            "message": "No billing data"
        }), 200


    summary = (
        df.groupby(df["date"].dt.date)["revenue"]
        .sum()
        .reset_index()
        .rename(columns={"date": "day", "revenue": "totalSales"})
    )
    summary["day"] = summary["day"].astype(str)
    return jsonify(summary.to_dict(orient="records"))


@app.route("/analytics/monthly")
def monthly_sales():
    raw_bills = get_filtered_bills()
    df = normalize_bills(raw_bills)
    if df.empty:
        return jsonify({
            "daily": [],
            "weekly": [],
            "monthly": [],
            "top_products": [],
            "revenue_trend": [],
            "summary": {
                "total_revenue": 0,
                "total_orders": 0,
                "total_products_sold": 0
            },
            "message": "No billing data"
        }), 200


    summary = (
        df.groupby(df["date"].dt.to_period("M"))["revenue"]
        .sum()
        .reset_index()
    )
    summary["date"] = summary["date"].astype(str)
    summary = summary.rename(columns={"date": "month", "revenue": "totalSales"})
    return jsonify(summary.to_dict(orient="records"))


@app.route("/analytics/weekly")
def weekly_sales():
    raw_bills = get_filtered_bills()
    df = normalize_bills(raw_bills)
    if df.empty:
        return jsonify({
            "daily": [],
            "weekly": [],
            "monthly": [],
            "top_products": [],
            "revenue_trend": [],
            "summary": {
                "total_revenue": 0,
                "total_orders": 0,
                "total_products_sold": 0
            },
            "message": "No billing data"
        }), 200


    summary = (
        df.groupby(df["date"].dt.to_period("W"))["revenue"]
        .sum()
        .reset_index()
    )
    summary["date"] = summary["date"].astype(str)
    summary = summary.rename(columns={"date": "week", "revenue": "totalSales"})
    return jsonify(summary.to_dict(orient="records"))


@app.route("/analytics/top-products")
def top_products():
    """Get top products filtered by date range"""
    raw_bills = get_filtered_bills()
    df = normalize_bills(raw_bills)
    if df.empty:
        return jsonify({
            "daily": [],
            "weekly": [],
            "monthly": [],
            "top_products": [],
            "revenue_trend": [],
            "summary": {
                "total_revenue": 0,
                "total_orders": 0,
                "total_products_sold": 0
            },
            "message": "No billing data"
        }), 200


    # Fetch all products for name and category lookup (filtered by shopId)
    shop_id = request.args.get("shopId")
    product_query = {}
    if shop_id:
        product_query["shopId"] = shop_id
    
    products = list(db.products.find(product_query))
    products_df = pd.DataFrame(products)

    # Merge bill data with product data
    merged = df.merge(
        products_df[["productId", "name", "category"]],
        on="productId",
        how="left",
        suffixes=("_bill", "_prod")
    )

    # Combine names (prefer bill name, fallback to product name)
    merged["name"] = merged["name_bill"].combine_first(merged["name_prod"])
    merged["category"] = merged["category"].fillna("Unknown")

    # Aggregate by product
    summary = (
        merged.groupby(["productId", "name", "category"])
        .agg({"qty": "sum", "revenue": "sum"})
        .reset_index()
        .sort_values("revenue", ascending=False)
        .head(10)
    )

    print(f"🏆 Top {len(summary)} products calculated")
    return jsonify(summary.to_dict(orient="records"))


@app.route("/analytics/revenue-trend")
def revenue_trend():
    """Get revenue trend filtered by date range"""
    raw_bills = get_filtered_bills()
    df = normalize_bills(raw_bills)
    if df.empty:
        return jsonify({
            "daily": [],
            "weekly": [],
            "monthly": [],
            "top_products": [],
            "revenue_trend": [],
            "summary": {
                "total_revenue": 0,
                "total_orders": 0,
                "total_products_sold": 0
            },
            "message": "No billing data"
        }), 200

    trend = (
        df.groupby(df["date"].dt.date)["revenue"]
        .sum()
        .reset_index()
        .rename(columns={"date": "day", "revenue": "totalRevenue"})
    )
    trend["day"] = trend["day"].astype(str)
    return jsonify(trend.to_dict(orient="records"))


@app.route("/analytics/report")
def sales_report():
    """Comprehensive sales report filtered by date range"""
    raw_bills = get_filtered_bills()
    df = normalize_bills(raw_bills)
    if df.empty:
        return jsonify({
            "daily": [],
            "weekly": [],
            "monthly": [],
            "top_products": [],
            "revenue_trend": [],
            "summary": {
                "total_revenue": 0,
                "total_orders": 0,
                "total_products_sold": 0
            },
            "message": "No billing data"
        }), 200


    # Fetch all products for name and category lookup
    products = list(db.products.find({}))
    products_df = pd.DataFrame(products)

    # ----- Daily -----
    daily = (
        df.groupby(df["date"].dt.date)["revenue"]
        .sum()
        .reset_index()
        .rename(columns={"date": "day", "revenue": "totalSales"})
    )
    daily["day"] = daily["day"].astype(str)

    # ----- Weekly -----
    weekly = (
        df.groupby(df["date"].dt.to_period("W"))["revenue"]
        .sum()
        .reset_index()
    )
    weekly["date"] = weekly["date"].astype(str)
    weekly = weekly.rename(columns={"date": "week", "revenue": "totalSales"})

    # ----- Monthly -----
    monthly = (
        df.groupby(df["date"].dt.to_period("M"))["revenue"]
        .sum()
        .reset_index()
    )
    monthly["date"] = monthly["date"].astype(str)
    monthly = monthly.rename(columns={"date": "month", "revenue": "totalSales"})

    # ----- Top Products (filtered by date range) -----
    merged = df.merge(
        products_df[["productId", "name", "category"]],
        on="productId",
        how="left",
        suffixes=("_bill", "_prod")
    )
    merged["name"] = merged["name_bill"].combine_first(merged["name_prod"])
    merged["category"] = merged["category"].fillna("Unknown")

    top_products = (
        merged.groupby(["productId", "name", "category"])
        .agg({"qty": "sum", "revenue": "sum"})
        .reset_index()
        .sort_values("revenue", ascending=False)
        .head(10)
    )

    # ----- Revenue Trend (filtered by date range) -----
    trend = (
        df.groupby(df["date"].dt.date)["revenue"]
        .sum()
        .reset_index()
        .rename(columns={"date": "day", "revenue": "totalRevenue"})
    )
    trend["day"] = trend["day"].astype(str)

    # ----- Combine Report -----
    report = {
        "daily": daily.to_dict(orient="records"),
        "weekly": weekly.to_dict(orient="records"),
        "monthly": monthly.to_dict(orient="records"),
        "top_products": top_products.to_dict(orient="records"),
        "revenue_trend": trend.to_dict(orient="records"),
        "summary": {
            "total_revenue": float(df["revenue"].sum()),
            "total_orders": int(len(raw_bills)),
            "total_products_sold": int(df["qty"].sum())
        }
    }

    print(f"📈 Report generated with {len(top_products)} top products")
    return jsonify(report)


@app.route("/analytics/report/text")
def sales_report_text():
    # --- NEW: Get language from header ---
    # Get 'en', 'hi', 'mr', 'te' from 'hi-IN,hi;q=0.9,en-US;q=0.8,en;q=0.7'
    lang = request.headers.get('Accept-Language', 'en').split(',')[0].split('-')[0]
    # --- End NEW ---

    raw_bills = get_filtered_bills()
    
    shop_id = request.args.get("shopId")
    product_query = {}
    if shop_id:
        product_query["shopId"] = shop_id
        
    products = list(db.products.find(product_query))
    df = normalize_bills(raw_bills)

    if df.empty:
        return jsonify({
            "daily": [],
            "weekly": [],
            "monthly": [],
            "top_products": [],
            "revenue_trend": [],
            "summary": {
                "total_revenue": 0,
                "total_orders": 0,
                "total_products_sold": 0
            },
            "message": "No billing data"
        }), 200

    products_df = pd.DataFrame(products)

    # ---- Summary ----
    total_revenue = float(df["revenue"].sum())
    total_orders = int(len(raw_bills))
    total_products_sold = int(df["qty"].sum())

    # ---- Daily ----
    daily = (
        df.groupby(df["date"].dt.date)["revenue"]
        .sum()
        .reset_index()
        .rename(columns={"date": "day", "revenue": "totalSales"})
    )
    daily["day"] = daily["day"].astype(str)
    best_day = daily.loc[daily["totalSales"].idxmax()]

    # ---- Weekly ----
    weekly = (
        df.groupby(df["date"].dt.to_period("W"))["revenue"]
        .sum()
        .reset_index()
    )
    weekly["date"] = weekly["date"].astype(str)
    best_week = weekly.loc[weekly["revenue"].idxmax()]

    # ---- Monthly ----
    monthly = (
        df.groupby(df["date"].dt.to_period("M"))["revenue"]
        .sum()
        .reset_index()
    )
    monthly["date"] = monthly["date"].astype(str)
    best_month = monthly.loc[monthly["revenue"].idxmax()]

    # ---- Top Products ----
    merged = df.merge(
        products_df[["productId", "name", "category"]],
        on="productId",
        how="left",
        suffixes=("_bill", "_prod")
    )
    merged["name"] = merged["name_bill"].combine_first(merged["name_prod"])
    merged["category"] = merged["category"].fillna("Unknown")

    top_products = (
        merged.groupby(["productId", "name", "category"])
        .agg({"qty": "sum", "revenue": "sum"})
        .reset_index()
        .sort_values("revenue", ascending=False)
        .head(3)
    )

    # ---- Generate Plain Text Report (TRANSLATED) ----
    report_lines = []
    report_lines.append(t(lang, 'report_title'))
    report_lines.append(t(lang, 'total_revenue').format(total_revenue=total_revenue))
    report_lines.append(t(lang, 'total_orders').format(total_orders=total_orders))
    report_lines.append(t(lang, 'total_products_sold').format(total_products_sold=total_products_sold))
    report_lines.append(t(lang, 'best_day').format(best_day=best_day['day'], total_sales=best_day['totalSales']))
    report_lines.append(t(lang, 'best_week').format(best_week=best_week['date'], revenue=best_week['revenue']))
    report_lines.append(t(lang, 'best_month').format(best_month=best_month['date'], revenue=best_month['revenue']))

    report_lines.append(t(lang, 'top_products_title'))
    for _, row in top_products.iterrows():
        report_lines.append(
            t(lang, 'top_product_line').format(name=row['name'], category=row['category'], qty=row['qty'], revenue=row['revenue'])
        )
    # --- End of modifications ---

    return jsonify({"report": " ".join(report_lines)})

# -----------------------
# Run Server
# -----------------------
if __name__ == "__main__":
    app.run(port=5001, debug=True)
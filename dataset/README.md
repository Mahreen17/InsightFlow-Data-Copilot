# TrailPeak Outdoor Co. — Synthetic Dataset

A fictional mid-size outdoor gear retailer, built so the SQL tables and PDF
documents share the same products, regions, and loyalty tiers — which is what
makes hybrid (SQL + RAG) questions answerable and checkable.

## Contents

**`sql/`** — 5 CSV tables, ready to load into Oracle (or Postgres/SQLite as a fallback):
- `customers.csv` (60 rows) — customer_id, name, email, region, signup_date, tier
- `products.csv` (15 rows) — product_id, name, category, price, warranty_years
- `orders.csv` (200 rows) — order_id, customer_id, order_date, status, total_amount, region
- `order_items.csv` (499 rows) — order_item_id, order_id, product_id, quantity, unit_price
- `support_tickets.csv` (31 rows) — ticket_id, customer_id, order_id, issue_type, status, created_date, region

Regions: Northeast, Southeast, Midwest, West, Pacific Northwest
Tiers: Bronze, Silver, Gold
Order statuses: Delivered, Shipped, Processing, Delayed, Cancelled

**`pdfs/`** — 7 policy/reference documents for the RAG Agent:
1. Return & Exchange Policy
2. Shipping & Regional SLA
3. Product Warranty Guide
4. Loyalty Tier Program FAQ
5. Regional Support Hours & Contacts
6. Company Overview
7. Product Care & Maintenance Guide

**`eval_questions.json`** — 14 evaluation questions with expected answers, split:
5 pure-SQL, 5 pure-RAG, 3 hybrid (SQL+RAG), 2 MCP-flavored (tool + SQL/RAG).
Numeric answers were computed directly from the generated CSVs, so they're
verifiable, not guessed.

## Why the overlap matters

Every hybrid/PDF question references a product, region, or tier that also
exists in the SQL tables (e.g. "Pacific Northwest" appears in `orders.csv`
*and* in the Shipping SLA PDF; "TrailBlazer 65L Backpack" appears in
`order_items.csv` *and* in the Warranty Guide). Without this overlap, a
"hybrid" query is really just two unrelated single-source queries stapled
together — this way, the answer genuinely requires combining both sources.

## Loading into a database

```python
import pandas as pd
import oracledb  # or psycopg2 / sqlite3

for table in ["customers", "products", "orders", "order_items", "support_tickets"]:
    df = pd.read_csv(f"sql/{table}.csv")
    # df.to_sql(table, your_connection, if_exists="replace", index=False)
```

## Regenerating or modifying

Both CSVs and PDFs were generated with a fixed random seed (`42`), so re-running
`generate_sql_data.py` reproduces identical data. If you tweak the schema (add
a table, add a region), update `generate_pdfs.py` too so the documents stay
in sync with whatever the SQL data actually says — that sync is the whole point.

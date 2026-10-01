# Inventory and reports upgrade (English UI)

## Install on your existing project
Back up clothing_orders.db and uploads before updating. Replace app.py, all templates, and static/style.css with these files. Keep your existing database and uploads in the same DATA_DIR. Restart the app. The database schema upgrades automatically without removing older orders or accounts.

## Products & Stock
Sign in as admin and open Products & Stock. Add a model, unit price in USD, and one row for every color and size with its available pieces. Save. Employees see the current catalog immediately when opening a form; open forms refresh within 15 seconds. The server always checks stock again when submitting.

The available quantity excludes pieces already reserved by orders. If you change a quantity, you are setting the current available quantity, not total purchased inventory. Removed products and variants disappear from new selections; existing orders retain their product/color/size and price snapshots. Editing a product reactivates it.

Submitting an order reserves stock atomically. Editing a New order releases its previous reservation and reserves its replacement in a single transaction. Cancelling releases stock once. Reopening a cancelled order checks and reserves stock again. Processing/Completed orders keep their stock deducted. Moving an order to Trash does not release stock; cancel it first if the sale was cancelled. This makes restoring from Trash safe.

Older orders have no inventory link and do not reserve stock retroactively. Enter your actual current available stock during initial setup. If you edit an older order, select its inventory products again. Removing a variant does not erase its old order history.

## Provinces
Customer forms provide all 14 Syrian governorates in English, followed by a required detailed address. Previous free-text addresses are preserved; select a province when editing an older order.

## Reports
Open Reports. Choose Daily, Weekly, Monthly, or Custom; choose reference date, employee, province and status. Weeks use Monday–Sunday and periods use Asia/Damascus local time. Reports group by original submission date (not completion date). The default Completed status represents completed sales. New and Processing represent order value, not collected revenue. Trashed orders are excluded. Cancelled orders appear only if selected or All is selected.

Totals include distinct orders, pieces and USD value; breakdowns show employees, best-selling product names and provinces. CSV exports the filtered order item rows. Prices are captured at order submission/edit; later catalog price changes do not change past totals. Older orders without prices contribute pieces/orders but zero USD value. This is an order sales report, not a payment or profit ledger.

## Hosting
Use your existing Render settings and DATA_DIR. Deploying these files does not change your hosting storage type. A temporary DATA_DIR still resets data when the host replaces its filesystem. The ZIP excludes database files and uploaded identity documents.

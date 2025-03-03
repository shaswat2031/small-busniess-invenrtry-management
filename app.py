from flask import Flask, render_template, request, redirect, url_for, flash, Response, send_file
from flask_pymongo import PyMongo
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from bson import ObjectId
from datetime import datetime
from config import Config
import csv
from io import StringIO
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image
from reportlab.lib.units import inch
from io import BytesIO
from itsdangerous import URLSafeTimedSerializer
from flask_mail import Mail, Message

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)

# Initialize extensions
mongo = PyMongo(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# MongoDB collections
user_collection = mongo.db.users
product_collection = mongo.db.products
sales_collection = mongo.db.sales

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data["_id"])
        self.username = user_data["username"]
        self.business_name = user_data.get("business_name", "")

@login_manager.user_loader
def load_user(user_id):
    user = user_collection.find_one({'_id': ObjectId(user_id)})
    return User(user) if user else None

# Helper functions
def calculate_total_sales(user_id):
    total_sales = 0
    sales = sales_collection.find({"owner_id": user_id})
    for sale in sales:
        total_sales += sale.get("total_price", 0)
    return total_sales

def reset_monthly_sales():
    today = datetime.utcnow()
    if today.day == 1:
        sales_collection.delete_many({})
        flash("Monthly sales data has been reset.", "info")

def validate_product_input(data):
    if not data.get("product_name") or not data.get("price") or not data.get("stock"):
        return False
    try:
        float(data["price"])
        int(data["stock"])
        return True
    except (ValueError, TypeError):
        return False

# Routes

# Home route (redirects to login or dashboard)
@app.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    else:
        return render_template("home.html")

# Register route
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        business_name = request.form["business_name"]
        email = request.form["email"]
        phone = request.form["phone"]

        if user_collection.find_one({"username": username}):
            flash("Username already exists!", "danger")
            return redirect(url_for("register"))

        hashed_password = bcrypt.generate_password_hash(password).decode("utf-8")
        new_user = {
            "username": username,
            "password": hashed_password,
            "business_name": business_name,
            "email": email,
            "phone": phone
        }
        user_collection.insert_one(new_user)
        flash("Registration successful! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

# Login route
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = user_collection.find_one({"username": username})
        if user and bcrypt.check_password_hash(user["password"], password):
            login_user(User(user))
            flash(f"Welcome {user.get('business_name', username)}!", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid username or password!", "danger")
        return redirect(url_for("login"))

    return render_template("login.html")

# Logout route
@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("home"))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    return render_template("profile.html", current_user=current_user)

# Dashboard route (main page after login)
@app.route("/dashboard")
@login_required
def dashboard():
    total_products = product_collection.count_documents({"owner_id": current_user.id})
    low_stock_products = list(product_collection.find({
        "owner_id": current_user.id,
        "$expr": {"$lte": ["$stock", "$low_stock_threshold"]}
    }))
    low_stock_count = len(low_stock_products)
    total_sales = calculate_total_sales(current_user.id)
    recent_products = list(product_collection.find({"owner_id": current_user.id}).sort("_id", -1).limit(10))

    return render_template("dashboard.html", 
                           total_products=total_products, 
                           low_stock_count=low_stock_count, 
                           total_sales=total_sales, 
                           low_stock_products=low_stock_products, 
                           recent_products=recent_products,
                           username=current_user.username)

# Add product route
@app.route("/add_product", methods=["GET", "POST"])
@login_required
def add_product():
    if request.method == "POST":
        if not validate_product_input(request.form):
            flash("Invalid input data!", "danger")
            return redirect(url_for("add_product"))

        product_data = {
            "product_name": request.form["product_name"],
            "description": request.form["description"],
            "price": float(request.form["price"]),
            "stock": int(request.form["stock"]),
            "low_stock_threshold": int(request.form.get("low_stock_threshold", 5)),
            "owner_id": current_user.id
        }
        product_collection.insert_one(product_data)
        flash("Product added successfully!", "success")
        return redirect(url_for("view_products"))

    return render_template("add_product.html")

# View products route
@app.route("/products")
@login_required
def view_products():
    products = list(product_collection.find({"owner_id": current_user.id}))
    for product in products:
        product["_id"] = str(product["_id"])
    low_stock_products = [
        p for p in products if p["stock"] <= p.get("low_stock_threshold", 5)
    ]
    return render_template("view_products.html", products=products, low_stock_products=low_stock_products)

# Edit product route
@app.route("/edit_product/<product_id>", methods=["GET", "POST"])
@login_required
def edit_product(product_id):
    product = product_collection.find_one({"_id": ObjectId(product_id), "owner_id": current_user.id})
    if not product:
        flash("Product not found", "danger")
        return redirect(url_for("view_products"))

    if request.method == "POST":
        if not validate_product_input(request.form):
            flash("Invalid input data!", "danger")
            return redirect(url_for("edit_product", product_id=product_id))

        product_collection.update_one(
            {"_id": ObjectId(product_id)},
            {"$set": {
                "product_name": request.form["product_name"],
                "description": request.form["description"],
                "price": float(request.form["price"]),
                "stock": int(request.form["stock"]),
                "low_stock_threshold": int(request.form.get("low_stock_threshold", 5))
            }}
        )
        flash("Product updated successfully", "success")
        return redirect(url_for("view_products"))

    return render_template("edit_product.html", product=product)

# Sell product route
@app.route("/sell_product/<product_id>", methods=["POST"])
@login_required
def sell_product(product_id):
    product = product_collection.find_one({"_id": ObjectId(product_id), "owner_id": current_user.id})
    if not product:
        flash("Product not found!", "danger")
        return redirect(url_for("view_products"))

    try:
        quantity_sold = int(request.form["quantity"])

        if quantity_sold <= 0:
            flash("Invalid quantity!", "danger")
            return redirect(url_for("view_products"))

        if quantity_sold > product["stock"]:
            flash("Not enough stock available!", "danger")
            return redirect(url_for("view_products"))

        total_price = quantity_sold * product["price"]

        sales_collection.insert_one({
            "product_id": product_id,
            "owner_id": current_user.id,
            "product_name": product["product_name"],
            "quantity_sold": quantity_sold,
            "total_price": total_price,
            "date_sold": datetime.utcnow()
        })

        new_stock = product["stock"] - quantity_sold
        product_collection.update_one(
            {"_id": ObjectId(product_id)},
            {"$set": {"stock": new_stock}}
        )

        if new_stock == 0:
            flash(f"Product '{product['product_name']}' is now out of stock!", "warning")
        elif new_stock <= product.get("low_stock_threshold", 5):
            flash(f"Warning! '{product['product_name']}' is low on stock ({new_stock} left).", "warning")

        flash("Sale recorded successfully!", "success")

    except ValueError:
        flash("Invalid input. Please enter a valid quantity.", "danger")

    return redirect(url_for("view_products"))

# Export sales route
@app.route("/export_sales")
@login_required
def export_sales(): 
    sales = list(sales_collection.find({"owner_id": current_user.id}))
    user_profile = user_collection.find_one({"_id": current_user.id})
    business_name = user_profile["business_name"] if user_profile and "business_name" in user_profile else "Your Business"
    export_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def generate_csv():
        output = StringIO()
        csv_writer = csv.writer(output)
        csv_writer.writerow([f"Business Name: {business_name}"])
        csv_writer.writerow([f"Exported On: {export_time}"])
        csv_writer.writerow([])
        csv_writer.writerow(["Product Name", "Quantity Sold", "Total Price", "Date Sold"])
        csv_writer.writerow(["Signed By: ", "Shaswat"])
        for sale in sales:
            date_sold = sale.get("date_sold", "")
            if isinstance(date_sold, datetime):
                date_sold = date_sold.strftime("%Y-%m-%d %H:%M:%S")
            csv_writer.writerow([
                sale.get("product_name", "N/A"),
                sale.get("quantity_sold", 0),
                f"₹{sale.get('total_price', 0.00):.2f}",  
                date_sold
            ])
        output.seek(0) 
        return output.read()
    
    response = Response(generate_csv(), content_type="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename=sales_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return response

# Product sales route
@app.route("/product_sales/<product_id>")
@login_required
def product_sales(product_id):
    product = product_collection.find_one({"_id": ObjectId(product_id), "owner_id": current_user.id})
    if not product:
        flash("Product not found!", "danger")
        return redirect(url_for("view_products"))

    sales = list(sales_collection.find({"product_id": product_id, "owner_id": current_user.id}).sort("date_sold", 1))
    sales_dates = [sale["date_sold"].strftime("%Y-%m-%d") for sale in sales]
    sales_quantities = [sale["quantity_sold"] for sale in sales]

    return render_template("product_sales.html", 
                           product=product, 
                           sales=sales, 
                           sales_dates=sales_dates, 
                           sales_quantities=sales_quantities)

# Delete sale route
@app.route("/delete_sale/<sale_id>", methods=["POST"])
@login_required
def delete_sale(sale_id):
    result = sales_collection.delete_one({"_id": ObjectId(sale_id), "owner_id": current_user.id})
    if result.deleted_count == 0:
        flash("Sale not found!", "danger")
    else:
        flash("Sale deleted successfully!", "success")
    return redirect(url_for("view_sales"))

# Delete all sales route
@app.route("/delete_all_sales", methods=["POST"])
@login_required
def delete_all_sales():
    sales_collection.delete_many({"owner_id": current_user.id})
    flash("All sales records have been deleted!", "warning")
    return redirect(url_for("view_sales"))

# View sales route
@app.route("/sales")
@login_required
def view_sales():
    sales = list(sales_collection.find().sort("date_sold", -1))
    for sale in sales:
        if isinstance(sale["date_sold"], str):
            sale["date_sold"] = datetime.strptime(sale["date_sold"], "%Y-%m-%d %H:%M:%S")
    return render_template("view_sales.html", sales=sales)

# Delete product route
@app.route("/delete_product/<product_id>")
@login_required
def delete_product(product_id):
    result = product_collection.delete_one({"_id": ObjectId(product_id), "owner_id": current_user.id})
    if result.deleted_count == 0:
        flash("Product not found!", "danger")
    else:
        flash("Product deleted successfully!", "success")
    return redirect(url_for("view_products"))

# Billing route
@app.route("/billing", methods=["GET", "POST"])
@login_required
def billing():
    if request.method == "POST":
        customer_name = request.form.get("customer_name")
        selected_items = request.form.getlist("selected_items")
        quantities = request.form.getlist("quantities")

        if not customer_name or not selected_items or not quantities:
            flash("Please fill in all fields!", "danger")
            return redirect(url_for("billing"))

        items = []
        total_price = 0
        for item_id, quantity in zip(selected_items, quantities):
            try:
                product = mongo.db.products.find_one({"_id": ObjectId(item_id), "owner_id": str(current_user.id)})
                if not product:
                    flash(f"Product not found!", "danger")
                    return redirect(url_for("billing"))

                quantity = int(quantity)
                if quantity <= 0 or quantity > product["stock"]:
                    flash(f"Invalid quantity for {product['product_name']}!", "danger")
                    return redirect(url_for("billing"))

                item_total = product["price"] * quantity
                items.append({
                    "product_name": product["product_name"],
                    "quantity": quantity,
                    "price": product["price"],
                    "total": item_total
                })
                total_price += item_total

                sales_collection.insert_one({
                    "product_id": item_id,
                    "owner_id": current_user.id,
                    "product_name": product["product_name"],
                    "quantity_sold": quantity,
                    "total_price": item_total,
                    "date_sold": datetime.utcnow(),
                    "customer_name": customer_name
                })

            except Exception as e:
                flash(f"An error occurred: {str(e)}", "danger")
                return redirect(url_for("billing"))

        pdf_buffer = generate_pdf_bill(customer_name, items, total_price)

        for item_id, quantity in zip(selected_items, quantities):
            try:
                mongo.db.products.update_one(
                    {"_id": ObjectId(item_id)},
                    {"$inc": {"stock": -int(quantity)}}
                )
            except Exception as e:
                flash(f"Failed to update stock: {str(e)}", "danger")
                return redirect(url_for("billing"))

        return send_file(pdf_buffer, as_attachment=True, download_name="bill.pdf", mimetype="application/pdf")

    products = list(mongo.db.products.find({"owner_id": str(current_user.id)}))
    return render_template("billing.html", products=products)

# Generate PDF bill function
def generate_pdf_bill(customer_name, items, total_price):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name='CompanyHeader',
        fontName='Helvetica-Bold',
        fontSize=18,
        textColor=colors.HexColor("#333333"),
        alignment=1
    ))
    styles.add(ParagraphStyle(
        name='InvoiceTitle',
        fontName='Helvetica-Bold',
        fontSize=24,
        textColor=colors.HexColor("#333333"),
        alignment=1
    ))
    styles.add(ParagraphStyle(
        name='SectionHeader',
        fontName='Helvetica-Bold',
        fontSize=12,
        textColor=colors.HexColor("#333333"),
        spaceAfter=12
    ))
    styles.add(ParagraphStyle(
        name='Footer',
        fontName='Helvetica',
        fontSize=10,
        textColor=colors.HexColor("#666666"),
        alignment=1
    ))

    content = []

    logo = "logo.png"
    if logo:
        company_logo = Image(logo, width=2*inch, height=1*inch)
        content.append(company_logo)
        content.append(Spacer(1, 12))

    company_info = [
        Paragraph("Inventory Manager", styles['CompanyHeader']),
        Paragraph("123 Business Street, City, Country", styles['Normal']),
        Paragraph("Phone: +123 456 7890 | Email: info@inventorymanager.com", styles['Normal']),
        Paragraph("Website: www.inventorymanager.com", styles['Normal'])
    ]
    for info in company_info:
        content.append(info)
        content.append(Spacer(1, 6))

    content.append(Spacer(1, 12))
    content.append(Paragraph("________________________________________________________", styles['Normal']))
    content.append(Spacer(1, 12))

    content.append(Paragraph("Invoice", styles['InvoiceTitle']))
    content.append(Spacer(1, 12))

    customer_details = [
        Paragraph("<b>Customer Name:</b> " + customer_name, styles['Normal']),
        Paragraph(f"<b>Invoice Date:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal'])
    ]
    for detail in customer_details:
        content.append(detail)
        content.append(Spacer(1, 6))

    table_data = [["Item", "Quantity", "Price", "Total"]]
    for item in items:
        table_data.append([
            item["product_name"],
            str(item["quantity"]),
            f"${item['price']:.2f}",
            f"${item['total']:.2f}"
        ])

    table = Table(table_data, colWidths=[3 * inch, 1 * inch, 1 * inch, 1 * inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#333333")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor("#cccccc")),
        ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
    ]))

    content.append(Spacer(1, 12))
    content.append(table)
    content.append(Spacer(1, 24))

    total = Paragraph(f"<b>Total Price:</b> ${total_price:.2f}", styles['SectionHeader'])
    content.append(total)
    content.append(Spacer(1, 24))

    additional_content = [
        Paragraph("<b>Payment Instructions:</b>", styles['SectionHeader']),
        Paragraph("Please make the payment via bank transfer to the following account:", styles['Normal']),
        Paragraph("Bank Name: ABC Bank", styles['Normal']),
        Paragraph("Account Name: Inventory Manager", styles['Normal']),
        Paragraph("Account Number: 1234 5678 9012 3456", styles['Normal']),
        Paragraph("SWIFT Code: ABCDEFGH", styles['Normal']),
        Paragraph("Thank you for your business!", styles['Normal'])
    ]
    for line in additional_content:
        content.append(line)
        content.append(Spacer(1, 6))

    footer = Paragraph(
        "<b>Inventory Manager</b><br/>"
        "123 Business Street, City, Country<br/>"
        "Phone: +123 456 7890 | Email: info@inventorymanager.com<br/>"
        "Website: www.inventorymanager.com",
        styles['Footer']
    )
    content.append(Spacer(1, 36))
    content.append(footer)

    doc.build(content)
    buffer.seek(0)
    return buffer

# Run the app
if __name__ == "__main__":
    app.run(debug=True)
from flask import Flask, render_template, request, redirect, url_for, flash, Response, send_file
from flask_pymongo import PyMongo
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from bson import ObjectId
from datetime import datetime
from config import Config
from sklearn.linear_model import LinearRegression
from datetime import datetime, timedelta
import numpy as np
import csv
from io import StringIO
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image
from reportlab.lib.units import inch
from io import BytesIO
from datetime import datetime


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
sales_collection = mongo.db.sales  # Collection for sales records

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

# Utility Functions reset every month on the 1st
def calculate_total_sales(user_id):
    """Calculate total sales for a user."""
    total_sales = sales_collection.aggregate([
        {"$match": {"owner_id": user_id}},
        {"$group": {"_id": None, "total": {"$sum": "$total_price"}}}
    ])
    result = list(total_sales)
    return result[0]["total"] if result else 0

def reset_monthly_sales():
    """Reset sales data every month on the 1st."""
    today = datetime.now(datetime.timezone.utc)
    first_day_of_month = today.replace(day=1)
    if today == first_day_of_month:
        sales_collection.delete_many({})
        flash("Monthly sales data has been reset.", "info")



def validate_product_input(data):
    """Validate product input data."""
    if not data.get("product_name") or not data.get("price") or not data.get("stock"):
        return False
    try:
        float(data["price"])
        int(data["stock"])
        return True
    except (ValueError, TypeError):
        return False

# Routes
@app.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))  # Redirect to dashboard if logged in
    else:
        return render_template("home.html")  # Render home page if not logged in    

# ---------- USER AUTHENTICATION ROUTES ----------
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

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("home"))  # Redirect to home page after logout

# ---------- DASHBOARD ----------


# ---------- DASHBOARD ROUTE ----------
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

    # Get sales predictions for all products combined
    sales_predictions = predict_sales()

    return render_template("dashboard.html", 
                           total_products=total_products, 
                           low_stock_count=low_stock_count, 
                           total_sales=total_sales, 
                           low_stock_products=low_stock_products, 
                           recent_products=recent_products, 
                           sales_predictions=sales_predictions,
                           username=current_user.username)

# ---------- PRODUCT MANAGEMENT ----------
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

@app.route("/products")
@login_required
def view_products():
    products = list(product_collection.find({"owner_id": current_user.id}))

    # Convert ObjectId to string for each product
    for product in products:
        product["_id"] = str(product["_id"])

    # Filter low stock products
    low_stock_products = [
        p for p in products if p["stock"] <= p.get("low_stock_threshold", 5)
    ]

    return render_template("view_products.html", products=products, low_stock_products=low_stock_products)


@app.route("/profile")
@login_required
def profile():
    return render_template("profile.html")

@app.route("/profile-update", methods=["POST"])
@login_required
def profile_update():
    user_collection.update_one({"_id": ObjectId(current_user.id)}, {
        "$set": {
            "business_name": request.form["business_name"],
            "email": request.form["email"],
            "phone": request.form["phone"]
        }
    })
    flash("Profile updated successfully!", "success")
    return redirect(url_for("profile"))





# ---------- EDIT PRODUCT ----------


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

# ---------- SELL PRODUCT (UPDATE STOCK + RECORD SALE) ----------
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

        # Record the sale first
        sales_collection.insert_one({
            "product_id": product_id,
            "owner_id": current_user.id,
            "product_name": product["product_name"],
            "quantity_sold": quantity_sold,
            "total_price": total_price,
            "date_sold": datetime.utcnow()
        })

        # Update stock after sale is recorded
        new_stock = product["stock"] - quantity_sold
        product_collection.update_one(
            {"_id": ObjectId(product_id)},
            {"$set": {"stock": new_stock}}
        )

        # Provide feedback on stock levels
        if new_stock == 0:
            flash(f"Product '{product['product_name']}' is now out of stock!", "warning")
        elif new_stock <= product.get("low_stock_threshold", 5):
            flash(f"Warning! '{product['product_name']}' is low on stock ({new_stock} left).", "warning")

        flash("Sale recorded successfully!", "success")

    except ValueError:
        flash("Invalid input. Please enter a valid quantity.", "danger")

    return redirect(url_for("view_products"))

#---Exporting Data CSV----



@app.route("/export_sales")
@login_required
def export_sales():
    """Exports sales data as a professional CSV file including business name and timestamp."""
    
    # Fetch sales data from MongoDB
    sales = list(sales_collection.find({"owner_id": current_user.id}))
    
    # Fetch business details (assuming you have a user profile collection)
    user_profile = user_collection.find_one({"_id": current_user.id})  # Modify if needed
    business_name = user_profile["business_name"] if user_profile and "business_name" in user_profile else "Your Business"

    # Get current timestamp in a readable format
    export_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Create CSV in memory
    def generate_csv():
        output = StringIO()
        csv_writer = csv.writer(output)
        
        # Add business name and timestamp as metadata
        csv_writer.writerow([f"Business Name: {business_name}"])
        csv_writer.writerow([f"Exported On: {export_time}"])
        csv_writer.writerow([])  # Blank row for spacing
        
        # Write header row
        csv_writer.writerow(["Product Name", "Quantity Sold", "Total Price", "Date Sold"])
        
        # Write sales data
        for sale in sales:
            # Ensure date_sold is formatted correctly
            date_sold = sale.get("date_sold", "")
            if isinstance(date_sold, datetime):
                date_sold = date_sold.strftime("%Y-%m-%d %H:%M:%S")
            
            csv_writer.writerow([
                sale.get("product_name", "N/A"),
                sale.get("quantity_sold", 0),
                f"${sale.get('total_price', 0.00):.2f}",  # Format as currency
                date_sold
            ])

        output.seek(0)  # Reset cursor to the beginning
        return output.read()




    
    # Send response as CSV file
    response = Response(generate_csv(), content_type="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename=sales_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    return response

#------------dETIAL SALE 
@app.route("/product_sales/<product_id>")
@login_required
def product_sales(product_id):
    # Fetch the product details
    product = product_collection.find_one({"_id": ObjectId(product_id), "owner_id": current_user.id})
    if not product:
        flash("Product not found!", "danger")
        return redirect(url_for("view_products"))

    # Fetch all sales records for this product
    sales = list(sales_collection.find({"product_id": product_id, "owner_id": current_user.id}).sort("date_sold", 1))

    # Prepare data for the graph
    sales_dates = [sale["date_sold"].strftime("%Y-%m-%d") for sale in sales]
    sales_quantities = [sale["quantity_sold"] for sale in sales]

    return render_template("product_sales.html", 
                           product=product, 
                           sales=sales, 
                           sales_dates=sales_dates, 
                           sales_quantities=sales_quantities)

#-------Delete Sales Data ----------------------

@app.route("/delete_sale/<sale_id>", methods=["POST"])
@login_required
def delete_sale(sale_id):
    """Deletes a single sale record"""
    result = sales_collection.delete_one({"_id": ObjectId(sale_id), "owner_id": current_user.id})
    
    if result.deleted_count == 0:
        flash("Sale not found!", "danger")
    else:
        flash("Sale deleted successfully!", "success")
    
    return redirect(url_for("view_sales"))


#---- all sales data --------

@app.route("/delete_all_sales", methods=["POST"])
@login_required
def delete_all_sales():
    """Deletes all sales records for the current user"""
    sales_collection.delete_many({"owner_id": current_user.id})
    flash("All sales records have been deleted!", "warning")
    return redirect(url_for("view_sales"))



# ---------- VIEW SALES ----------------



@app.route("/sales")
@login_required
def view_sales():
    sales = list(sales_collection.find().sort("date_sold", -1))  # Get all sales, latest first
    
    # Convert date_sold from string to datetime object if needed
    for sale in sales:
        if isinstance(sale["date_sold"], str):  # Check if it's a string
            sale["date_sold"] = datetime.strptime(sale["date_sold"], "%Y-%m-%d %H:%M:%S")

    return render_template("view_sales.html", sales=sales)


# ---------- DELETE PRODUCT ----------
@app.route("/delete_product/<product_id>")
@login_required
def delete_product(product_id):
    result = product_collection.delete_one({"_id": ObjectId(product_id), "owner_id": current_user.id})
    if result.deleted_count == 0:
        flash("Product not found!", "danger")
    else:
        flash("Product deleted successfully!", "success")
    return redirect(url_for("view_products"))


#`---------- Prediciton --  ----------`





from datetime import datetime
import numpy as np
from sklearn.linear_model import LinearRegression

def predict_sales():
    # Fetch all sales records from the database and sort them by date (oldest to newest)
    sales = list(sales_collection.find().sort("date_sold", 1))

    # If there are less than 3 sales records, we cannot make a reliable prediction
    if len(sales) < 3:
        return {
            "daily": "Not enough data",
            "monthly": "Not enough data",
            "yearly": "Not enough data"
        }

    # Convert sales dates into numeric values (days since the first sale)
    X = np.array([(sale["date_sold"] - sales[0]["date_sold"]).days for sale in sales]).reshape(-1, 1)
    
    # Extract the quantity sold for each sale to use as the target variable
    y = np.array([sale["quantity_sold"] for sale in sales])

    # Create and train a simple linear regression model
    model = LinearRegression()
    model.fit(X, y)  # Train the model using the sales data

    # Predict sales for future time periods: next day, next month, next year
    future_days = [(datetime.today() - sales[0]["date_sold"]).days + i for i in [1, 30, 365]]
    
    # Use the trained model to predict sales for these future periods
    predictions = model.predict(np.array(future_days).reshape(-1, 1))

    # Return rounded predictions for daily, monthly, and yearly sales
    return {
        "daily": round(predictions[0]),   # Sales prediction for the next day
        "monthly": round(predictions[1]), # Sales prediction for the next month
        "yearly": round(predictions[2])   # Sales prediction for the next year
    }


#--------bILLING ROUTE----------------
# Billing Route
@app.route("/billing", methods=["GET", "POST"])
@login_required
def billing():
    if request.method == "POST":
        customer_name = request.form.get("customer_name")
        selected_items = request.form.getlist("selected_items")
        quantities = request.form.getlist("quantities")

        # Validate input
        if not customer_name or not selected_items or not quantities:
            flash("Please fill in all fields!", "danger")
            return redirect(url_for("billing"))

        # Fetch selected products and calculate total price
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

                # Record the sale in the sales collection
                sales_collection.insert_one({
                    "product_id": item_id,
                    "owner_id": current_user.id,
                    "product_name": product["product_name"],
                    "quantity_sold": quantity,
                    "total_price": item_total,
                    "date_sold": datetime.utcnow(),
                    "customer_name": customer_name  # Optionally include customer name
                })

            except Exception as e:
                flash(f"An error occurred: {str(e)}", "danger")
                return redirect(url_for("billing"))

        # Generate PDF bill
        pdf_buffer = generate_pdf_bill(customer_name, items, total_price)

        # Update stock after purchase
        for item_id, quantity in zip(selected_items, quantities):
            try:
                mongo.db.products.update_one(
                    {"_id": ObjectId(item_id)},
                    {"$inc": {"stock": -int(quantity)}}
                )
            except Exception as e:
                flash(f"Failed to update stock: {str(e)}", "danger")
                return redirect(url_for("billing"))

        # Return the PDF as a downloadable file
        return send_file(pdf_buffer, as_attachment=True, download_name="bill.pdf", mimetype="application/pdf")

    # Fetch all products owned by the logged-in user
    products = list(mongo.db.products.find({"owner_id": str(current_user.id)}))
    
    return render_template("billing.html", products=products)# Generate PDF Bill



def generate_pdf_bill(customer_name, items, total_price):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)
    styles = getSampleStyleSheet()

    # Custom styles
    styles.add(ParagraphStyle(
        name='CompanyHeader',
        fontName='Helvetica-Bold',
        fontSize=18,
        textColor=colors.HexColor("#333333"),
        alignment=1  # Center alignment
    ))
    styles.add(ParagraphStyle(
        name='InvoiceTitle',
        fontName='Helvetica-Bold',
        fontSize=24,
        textColor=colors.HexColor("#333333"),
        alignment=1  # Center alignment
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
        alignment=1  # Center alignment
    ))

    # Create a list to hold the PDF content
    content = []

    # Add company logo (optional)
    logo = "logo.png"  # Replace with the path to your logo
    if logo:
        company_logo = Image(logo, width=2*inch, height=1*inch)
        content.append(company_logo)
        content.append(Spacer(1, 12))

    # Add company information in the header
    company_info = [
        Paragraph("Inventory Manager", styles['CompanyHeader']),
        Paragraph("123 Business Street, City, Country", styles['Normal']),
        Paragraph("Phone: +123 456 7890 | Email: info@inventorymanager.com", styles['Normal']),
        Paragraph("Website: www.inventorymanager.com", styles['Normal'])
    ]
    for info in company_info:
        content.append(info)
        content.append(Spacer(1, 6))

    # Add a separator line
    content.append(Spacer(1, 12))
    content.append(Paragraph("________________________________________________________", styles['Normal']))
    content.append(Spacer(1, 12))

    # Add invoice title
    content.append(Paragraph("Invoice", styles['InvoiceTitle']))
    content.append(Spacer(1, 12))

    # Add customer details
    customer_details = [
        Paragraph("<b>Customer Name:</b> " + customer_name, styles['Normal']),
        Paragraph(f"<b>Invoice Date:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal'])
    ]
    for detail in customer_details:
        content.append(detail)
        content.append(Spacer(1, 6))

    # Add a table for items
    table_data = [["Item", "Quantity", "Price", "Total"]]
    for item in items:
        table_data.append([
            item["product_name"],
            str(item["quantity"]),
            f"${item['price']:.2f}",
            f"${item['total']:.2f}"
        ])

    # Create the table
    table = Table(table_data, colWidths=[3 * inch, 1 * inch, 1 * inch, 1 * inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#333333")),  # Header row background
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),  # Header row text color
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),  # Center align all cells
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),  # Header row font
        ('FONTSIZE', (0, 0), (-1, 0), 12),  # Header row font size
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),  # Header row padding
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor("#cccccc")),  # Table grid color
        ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),  # Table body background
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),  # Table body text color
    ]))

    content.append(Spacer(1, 12))
    content.append(table)
    content.append(Spacer(1, 24))

    # Add total price
    total = Paragraph(f"<b>Total Price:</b> ${total_price:.2f}", styles['SectionHeader'])
    content.append(total)
    content.append(Spacer(1, 24))

    # Add additional content (e.g., payment instructions)
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

    # Add a footer
    footer = Paragraph(
        "<b>Inventory Manager</b><br/>"
        "123 Business Street, City, Country<br/>"
        "Phone: +123 456 7890 | Email: info@inventorymanager.com<br/>"
        "Website: www.inventorymanager.com",
        styles['Footer']
    )
    content.append(Spacer(1, 36))
    content.append(footer)

    # Build the PDF
    doc.build(content)
    buffer.seek(0)
    return buffer


# ---------- RUN APP ----------
if __name__ == "__main__":
    app.run(debug=True)
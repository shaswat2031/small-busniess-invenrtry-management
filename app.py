from flask import Flask, render_template, request, redirect, url_for, flash, Response, send_file, session
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
import logging
from functools import wraps

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = 'your_secret_key'  # Change this to a secure secret key in production

# Pricing data
pricing = {
    'starter': {
        'price': 200,
        'products': 100,
        'users': 1
    },
    'professional': {
        'price': 400,
        'products': 1000,
        'users': 5
    },
    'enterprise': {
        'price': 800,
        'products': 10000,
        'users': 20
    }
}

# Initialize extensions
mongo = PyMongo(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# MongoDB collections
user_collection = mongo.db.users
product_collection = mongo.db.products
sales_collection = mongo.db.sales

# Advanced Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Rate limiting decorator (simple example)
def rate_limit(limit=5):
    calls = {}
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            user = current_user.id if current_user.is_authenticated else request.remote_addr
            now = datetime.utcnow().timestamp()
            calls.setdefault(user, [])
            # Remove calls older than a minute
            calls[user] = [t for t in calls[user] if now - t < 60]
            if len(calls[user]) >= limit:
                flash("Too many requests. Please wait and try again.", "danger")
                return redirect(url_for("dashboard"))
            calls[user].append(now)
            return f(*args, **kwargs)
        return wrapped
    return decorator

# Add plan restriction decorator
def plan_required(min_plan_level=None, feature=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            plan_levels = {
                'starter': 0,
                'professional': 1,
                'enterprise': 2
            }
            
            # If no minimum plan specified, allow access
            if not min_plan_level:
                return f(*args, **kwargs)
                
            user_plan = current_user.plan
            user_plan_level = plan_levels.get(user_plan, 0)
            required_level = plan_levels.get(min_plan_level, 0)
            
            if user_plan_level < required_level:
                flash(f"This feature requires the {min_plan_level.capitalize()} plan or higher.", "warning")
                return redirect(url_for("profile"))
                
            # Check product count if adding product
            if feature == 'product_count' and 'add_product' in request.path:
                product_count = product_collection.count_documents({"owner_id": current_user.id})
                plan_limit = pricing[user_plan]['products']
                
                if product_count >= plan_limit:
                    flash(f"Your {user_plan.capitalize()} plan is limited to {plan_limit} products. Please upgrade to add more.", "warning")
                    return redirect(url_for("profile"))
                    
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data["_id"])
        self.username = user_data["username"]
        self.business_name = user_data.get("business_name", "")
        self.plan = user_data.get("plan", "starter")  # Default to starter plan if not specified

    def get_plan_details(self):
        return pricing.get(self.plan, pricing['starter'])

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
        return render_template("home.html", pricing=pricing)

# Register route
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        business_name = request.form["business_name"]
        email = request.form["email"]
        phone = request.form["phone"]
        plan = request.form.get("plan", "starter")  # Default to starter if not specified

        if user_collection.find_one({"username": username}):
            flash("Username already exists!", "danger")
            return redirect(url_for("register"))

        hashed_password = bcrypt.generate_password_hash(password).decode("utf-8")
        new_user = {
            "username": username,
            "password": hashed_password,
            "business_name": business_name,
            "email": email,
            "phone": phone,
            "plan": plan,
            "registration_date": datetime.utcnow()
        }
        user_collection.insert_one(new_user)
        flash("Registration successful! Please log in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html", pricing=pricing)

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
    if request.method == 'POST':
        # Handle profile updates if needed
        pass
    
    # Get the user's current plan details:
    plan_name = current_user.plan
    plan_details = current_user.get_plan_details()
    
    # Get actual product count
    total_products = product_collection.count_documents({"owner_id": current_user.id})
    
    # Get team members count
    team_members_count = user_collection.count_documents({"parent_user_id": current_user.id})
    
    # Get team members list for display
    team_members = list(user_collection.find({"parent_user_id": current_user.id}))
    
    return render_template("profile.html", 
                          current_user=current_user, 
                          plan_name=plan_name, 
                          plan_details=plan_details,
                          total_products=total_products,
                          team_members_count=team_members_count,
                          team_members=team_members,
                          pricing=pricing)

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
    
    # Add plan limit information
    plan_details = current_user.get_plan_details()
    product_limit = plan_details['products']
    product_usage_percent = (total_products / product_limit) * 100 if product_limit > 0 else 0
    
    return render_template("dashboard.html", 
                           total_products=total_products, 
                           low_stock_count=low_stock_count, 
                           total_sales=total_sales, 
                           low_stock_products=low_stock_products, 
                           recent_products=recent_products, 
                           username=current_user.username,
                           product_limit=product_limit,
                           product_usage_percent=product_usage_percent)

# Add product route
@app.route("/add_product", methods=["GET", "POST"])
@login_required
@plan_required(feature='product_count')  # This will check product limits
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
@app.route("/view_products")
@login_required
def view_products():
    products = list(product_collection.find({"owner_id": current_user.id}))
    low_stock_products = [
        product for product in products if product["stock"] <= product.get("low_stock_threshold", 5)
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
    user_profile = user_collection.find_one({"_id": ObjectId(current_user.id)})
    business_name = user_profile["business_name"] if user_profile and "business_name" in user_profile else "Your Business"
    export_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Add plan information to export
    plan_name = current_user.plan.capitalize()

    def generate_csv():
        output = StringIO()
        csv_writer = csv.writer(output)
        csv_writer.writerow([f"Business Name: {business_name} | Plan: {plan_name}"])
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
                    "customer_name": customer_name,
                })
                mongo.db.products.update_one(
                    {"_id": ObjectId(item_id)},
                    {"$inc": {"stock": -int(quantity)}}
                )
            except Exception as e:
                flash(f"An error occurred: {str(e)}", "danger")
                return redirect(url_for("billing"))

        pdf_buffer = generate_pdf_bill(customer_name, items, total_price)
        return send_file(pdf_buffer, as_attachment=True, download_name="bill.pdf", mimetype="application/pdf")
    products = list(mongo.db.products.find({"owner_id": str(current_user.id)}))
    return render_template("billing.html", products=products)

# Add page number function
def add_page_number(canvas, doc):
    canvas.saveState()
    page_num = canvas.getPageNumber()
    canvas.setFont('Helvetica', 9)
    canvas.drawRightString(letter[0] - 72, 30, f"Page {page_num}")
    canvas.restoreState()

# Generate PDF bill function
def generate_pdf_bill(customer_name, items, total_price):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=72
    )
    styles = getSampleStyleSheet()
    # Define custom styles for the invoice
    styles.add(ParagraphStyle(
        name='InvoiceHeader',
        fontName='Helvetica-Bold',
        fontSize=20,
        alignment=1,
        textColor=colors.HexColor("#333333"),
        spaceAfter=6
    ))
    styles.add(ParagraphStyle(
        name='InvoiceSubHeader',
        fontName='Helvetica',
        fontSize=12,
        alignment=1,
        textColor=colors.HexColor("#555555"),
        spaceAfter=10
    ))
    styles.add(ParagraphStyle(
        name='TableHeader',
        fontName='Helvetica-Bold',
        fontSize=10,
        textColor=colors.whitesmoke,
        alignment=1
    ))
    styles.add(ParagraphStyle(
        name='TableCell',
        fontName='Helvetica',
        fontSize=10,
        textColor=colors.black,
        alignment=1
    ))
    styles.add(ParagraphStyle(
        name='Footer',
        fontName='Helvetica',
        fontSize=10,
        textColor=colors.HexColor("#666666"),
        alignment=1
    ))
    
    content = []
    # Company Logo and Header
    logo = "logo.png"
    if logo:
        try:
            company_logo = Image(logo, width=2*inch, height=1*inch)
            company_logo.hAlign = 'CENTER'
            content.append(company_logo)
        except Exception as e:
            logger.error("Logo not found: %s", e)
    content.append(Paragraph("Inventory Manager Invoice", styles['InvoiceHeader']))
    content.append(Paragraph(f"Invoice Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['InvoiceSubHeader']))
    
    # Add business plan information
    business_name = current_user.business_name
    plan_name = current_user.plan.capitalize()
    content.append(Paragraph(f"<b>Business:</b> {business_name} | <b>Plan:</b> {plan_name}", styles['Normal']))
    content.append(Spacer(1, 12))
    
    # Customer Details
    content.append(Paragraph(f"<b>Customer:</b> {customer_name}", styles['Normal']))
    content.append(Spacer(1, 12))
    
    # Table Data with alternating row backgrounds
    table_data = []
    header = [
        Paragraph("Item", styles['TableHeader']),
        Paragraph("Quantity", styles['TableHeader']),
        Paragraph("Price", styles['TableHeader']),
        Paragraph("Total", styles['TableHeader'])
    ]
    table_data.append(header)
    for idx, item in enumerate(items):
        row = [
            Paragraph(item["product_name"], styles['TableCell']),
            Paragraph(str(item["quantity"]), styles['TableCell']),
            Paragraph(f"${item['price']:.2f}", styles['TableCell']),
            Paragraph(f"${item['total']:.2f}", styles['TableCell'])
        ]
        table_data.append(row)
    
    table = Table(table_data, colWidths=[3 * inch, 1 * inch, 1 * inch, 1 * inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#333333")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 10),
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.lavender])
    ]))
    content.append(table)
    content.append(Spacer(1, 24))
    
    # Total Price Section
    content.append(Paragraph(f"<b>Total Price:</b> ${total_price:.2f}", styles['InvoiceSubHeader']))
    content.append(Spacer(1, 24))
    
    # Payment Instructions Section
    content.append(Paragraph("Payment Instructions:", styles['InvoiceSubHeader']))
    for detail in [
        "Please transfer the total amount to the following bank account:",
        "Bank Name: ABC Bank",
        "Account Name: Inventory Manager",
        "Account Number: 1234 5678 9012 3456",
        "SWIFT Code: ABCDEFGH",
        "Thank you for your prompt payment!"
    ]:
        content.append(Paragraph(detail, styles['Normal']))
        content.append(Spacer(1, 6))
    
    # Footer with contact details
    content.append(Spacer(1, 36))
    content.append(Paragraph(
        "<b>Inventory Manager</b><br/>"
        "123 Business Street, City, Country<br/>"
        "Phone: +123 456 7890 | Email: info@inventorymanager.com<br/>"
        "Website: www.inventorymanager.com",
        styles['Footer']
    ))
    
    doc.build(content, onFirstPage=add_page_number, onLaterPages=add_page_number)
    buffer.seek(0)
    return buffer

# Contact route
@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name = request.form.get('name')
        email = request.form.get('email')
        message = request.form.get('message')
        company = request.form.get('company')
        # Here you would typically save the contact request to a database
        # or send an email notification
        flash('Thanks for contacting us! We will get back to you soon.', 'success')
        return redirect(url_for('contact'))
    return render_template('contact.html')

# Advanced Analytics route
@app.route("/analytics")
@login_required
@rate_limit(limit=10)  # apply rate limiting to analytics access
def analytics():
    try:
        total_sales = calculate_total_sales(current_user.id)
        total_products = product_collection.count_documents({"owner_id": current_user.id})
        sales_data = list(sales_collection.find({"owner_id": current_user.id}))
        # Compute average sale value
        count = len(sales_data)
        avg_sale = total_sales/count if count > 0 else 0
        logger.info(f"User {current_user.username} accessed analytics.")
        return render_template("analytics.html", total_sales=total_sales,
                               total_products=total_products,
                               avg_sale=avg_sale,
                               sales_count=count)
    except Exception as e:
        logger.error(f"Analytics error: {e}")
        flash("Failed to load analytics.", "danger")
        return redirect(url_for("dashboard"))

# Add a new route for advanced analytics that requires Professional plan
@app.route("/advanced-analytics")
@login_required
@plan_required(min_plan_level='professional')
def advanced_analytics():
    # This would implement more sophisticated analytics only available to Professional and Enterprise users
    return render_template("advanced_analytics.html")

# Enhanced change plan route with simulated payment processing
@app.route('/change_plan/<plan_name>', methods=['POST'])
@login_required
def change_plan(plan_name):
    if plan_name not in pricing:
        flash("Invalid plan selected!", "danger")
        return redirect(url_for("profile"))
    
    # Simulate payment processing (for demo purposes)
    try:
        # For example, if upgrading to higher tiers, simulate a charge
        current_plan = current_user.plan
        new_price = pricing[plan_name]['price']
        current_price = pricing[current_plan]['price']
        if new_price > current_price:
            # Simulate processing fee and payment success
            logger.info(f"Processing payment for user {current_user.username}: {current_price} -> {new_price}")
            # If payment fails raise Exception("Payment failed.") in real code
            flash("Payment processed successfully!", "success")
        else:
            flash("Plan downgraded successfully.", "info")
    except Exception as e:
        logger.error(f"Payment error for user {current_user.username}: {e}")
        flash("Payment processing failed. Please try again.", "danger")
        return redirect(url_for("profile"))
    
    # Update the user's plan in the database
    user_collection.update_one(
        {"_id": ObjectId(current_user.id)},
        {"$set": {"plan": plan_name}}
    )
    flash(f"Your plan has been updated to {plan_name.capitalize()}!", "success")
    return redirect(url_for("profile"))

# Team Member Management routes
@app.route("/add_team_member", methods=["GET", "POST"])
@login_required
def add_team_member():
    # Get current user count for this business owner
    current_user_count = user_collection.count_documents({"parent_user_id": current_user.id})
    plan_details = current_user.get_plan_details()
    plan_name = current_user.plan
    
    # Get total product count for the user
    total_products = product_collection.count_documents({"owner_id": current_user.id})
    
    # Check if user limit is reached
    if current_user_count >= plan_details['users']:
        flash("You've reached the maximum number of users for your plan. Please upgrade to add more team members.", "warning")
        return redirect(url_for('profile'))
    
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")
        role = request.form.get("role", "staff")
        permissions = request.form.getlist("permissions[]")
        
        # Validate inputs
        if not username or not email or not password:
            flash("Please fill in all required fields", "danger")
            return redirect(url_for("add_team_member"))
            
        if password != confirm_password:
            flash("Passwords don't match", "danger")
            return redirect(url_for("add_team_member"))
            
        # Check if username already exists
        if user_collection.find_one({"username": username}):
            flash("Username already exists", "danger")
            return redirect(url_for("add_team_member"))
            
        # Create new team member
        hashed_password = bcrypt.generate_password_hash(password).decode("utf-8")
        new_user = {
            "username": username,
            "email": email,
            "password": hashed_password,
            "parent_user_id": current_user.id,  # Link to the business owner
            "business_name": current_user.business_name,
            "role": role,
            "permissions": permissions,
            "plan": "team_member",  # Special designation for team members
            "registration_date": datetime.utcnow()
        }
        
        user_collection.insert_one(new_user)
        flash(f"Team member {username} added successfully!", "success")
        return redirect(url_for("manage_team"))
        
    return render_template(
        "add_user.html",
        current_user_count=current_user_count,
        plan_details=plan_details,
        plan_name=plan_name,
        total_products=total_products  # Pass total products to the template
    )

@app.route("/manage_team")
@login_required
def manage_team():
    # Get all team members for this business owner
    team_members = list(user_collection.find({"parent_user_id": current_user.id}))
    plan_details = current_user.get_plan_details()
    
    return render_template(
        "manage_team.html",
        team_members=team_members,
        plan_details=plan_details
    )

@app.route("/delete_team_member/<user_id>", methods=["POST"])
@login_required
def delete_team_member(user_id):
    # Check if the team member belongs to current user
    team_member = user_collection.find_one({
        "_id": ObjectId(user_id),
        "parent_user_id": current_user.id
    })
    
    if not team_member:
        flash("Team member not found!", "danger")
        return redirect(url_for("manage_team"))
        
    # Delete the team member
    user_collection.delete_one({"_id": ObjectId(user_id)})
    flash("Team member removed successfully!", "success")
    return redirect(url_for("manage_team"))

# Run the app
if __name__ == "__main__":
    logger.info("Starting Inventory Manager application")
    app.run(debug=True)
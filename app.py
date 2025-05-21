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

# Enhanced permission decorator
def role_required(role=None, permission=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Business owner can do anything
            if not current_user.is_team_member:
                return f(*args, **kwargs)
                
            # Role-based check
            if role and current_user.role != role:
                flash(f"This action requires {role} privileges.", "warning")
                return redirect(url_for("dashboard"))
                
            # Permission-based check
            if permission and permission not in current_user.permissions:
                flash(f"You don't have permission to {permission}.", "warning")
                return redirect(url_for("dashboard"))
                
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Enhance the User class to better handle permissions
class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data["_id"])
        self.username = user_data["username"]
        self.business_name = user_data.get("business_name", "")
        self.plan = user_data.get("plan", "starter")  # Default to starter plan if not specified
        self.is_team_member = "parent_user_id" in user_data
        self.parent_user_id = user_data.get("parent_user_id", None)
        self.role = user_data.get("role", "owner")
        self.permissions = user_data.get("permissions", [])
        self.email = user_data.get("email", "")
        
        # Store the original user data for access to all fields
        self._data = user_data

    def get_plan_details(self):
        # If this is a team member, get the owner's plan details
        if self.is_team_member and self.parent_user_id:
            owner = user_collection.find_one({'_id': ObjectId(self.parent_user_id)})
            if owner:
                return pricing.get(owner.get('plan', 'starter'), pricing['starter'])
        return pricing.get(self.plan, pricing['starter'])
    
    def get_owner_id(self):
        # Return parent_user_id if team member, or own id if business owner
        return self.parent_user_id if self.is_team_member else self.id
    
    def can_view_products(self):
        # All team members should be able to view products
        return True
        
    def can_edit_products(self):
        # Admin and manager roles or users with 'add' permission can edit products
        return not self.is_team_member or self.role in ["admin", "manager"] or "add" in self.permissions
        
    def can_sell_products(self):
        # All team members should be able to sell products
        return True
        
    def can_view_reports(self):
        return not self.is_team_member or "reports" in self.permissions or self.role in ["admin", "manager"]
        
    def can_manage_team(self):
        # Only business owners can manage team members, not team members themselves
        return not self.is_team_member

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
            user_obj = User(user)
            login_user(user_obj)
            
            # Different welcome messages for team members vs owners
            if user_obj.is_team_member:
                # Get owner info for team member welcome message
                owner = user_collection.find_one({"_id": ObjectId(user_obj.parent_user_id)})
                owner_name = owner.get("business_name", "the business") if owner else "the business"
                flash(f"Welcome {username}! You are logged in as a {user_obj.role} for {owner_name}.", "success")
            else:
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

# Dashboard route - updated to show the right products for team members
@app.route("/dashboard")
@login_required
def dashboard():
    # Use the owner's ID for product queries (either the team member's parent or the current user)
    owner_id = current_user.get_owner_id()
    
    total_products = product_collection.count_documents({"owner_id": owner_id})
    low_stock_products = list(product_collection.find({
        "owner_id": owner_id,
        "$expr": {"$lte": ["$stock", "$low_stock_threshold"]}
    }))
    low_stock_count = len(low_stock_products)
    total_sales = calculate_total_sales(owner_id)
    recent_products = list(product_collection.find({"owner_id": owner_id}).sort("_id", -1).limit(10))
    
    # Add plan limit information
    plan_details = current_user.get_plan_details()
    product_limit = plan_details['products']
    product_usage_percent = (total_products / product_limit) * 100 if product_limit > 0 else 0
    
    # Get team info if current user is a business owner
    team_info = None
    if not current_user.is_team_member:
        team_members_count = user_collection.count_documents({"parent_user_id": current_user.id})
        team_info = {
            "count": team_members_count,
            "limit": plan_details['users']
        }
    
    return render_template("dashboard.html", 
                        total_products=total_products, 
                        low_stock_count=low_stock_count, 
                        total_sales=total_sales, 
                        low_stock_products=low_stock_products, 
                        recent_products=recent_products, 
                        username=current_user.username,
                        product_limit=product_limit,
                        product_usage_percent=product_usage_percent,
                        team_info=team_info,
                        is_team_member=current_user.is_team_member)

# Fix add_product route to use the correct owner_id
@app.route("/add_product", methods=["GET", "POST"])
@login_required
@plan_required(feature='product_count')
@role_required(permission="add")
def add_product():
    if request.method == "POST":
        if not validate_product_input(request.form):
            flash("Invalid input data!", "danger")
            return redirect(url_for("add_product"))
        
        # Use the owner's ID to ensure products are properly associated
        owner_id = current_user.get_owner_id()
        
        product_data = {
            "product_name": request.form["product_name"],
            "description": request.form["description"],
            "price": float(request.form["price"]),
            "stock": int(request.form["stock"]),
            "low_stock_threshold": int(request.form.get("low_stock_threshold", 5)),
            "owner_id": owner_id  # Use the owner_id instead of current_user.id
        }
        product_collection.insert_one(product_data)
        flash("Product added successfully!", "success")
        return redirect(url_for("view_products"))
    return render_template("add_product.html")

# Ensure view_products is using string comparison for IDs if needed
@app.route("/view_products")
@login_required
def view_products():
    if current_user.is_team_member and not current_user.can_view_products():
        flash("You don't have permission to view products.", "warning")
        return redirect(url_for("dashboard"))
    
    owner_id = current_user.get_owner_id()
    
    # Add logging to debug the issue
    logger.info(f"Fetching products for owner_id: {owner_id}")
    
    # Make sure we're querying with the correct type (string vs ObjectId)
    # If owner_id is a string but stored as ObjectId or vice versa, this could cause issues
    products = list(product_collection.find({"owner_id": owner_id}))
    
    logger.info(f"Found {len(products)} products")
    
    low_stock_products = [
        product for product in products if product["stock"] <= product.get("low_stock_threshold", 5)
    ]
    
    return render_template("view_products.html", 
                          products=products, 
                          low_stock_products=low_stock_products,
                          can_edit=current_user.can_edit_products(),
                          can_sell=current_user.can_sell_products())

# Fix edit_product route to use the correct owner_id for consistency
@app.route("/edit_product/<product_id>", methods=["GET", "POST"])
@login_required
def edit_product(product_id):
    owner_id = current_user.get_owner_id()
    product = product_collection.find_one({"_id": ObjectId(product_id), "owner_id": owner_id})
    
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
    try:
        # Get the owner ID for proper product lookup
        owner_id = current_user.get_owner_id()
        
        # Add logging for debugging
        logger.info(f"Processing sell for product ID: {product_id}, owner ID: {owner_id}")
        
        # Use ObjectId for product lookup when the field is an ObjectId in MongoDB
        product = product_collection.find_one({"_id": ObjectId(product_id), "owner_id": owner_id})
        
        if not product:
            logger.warning(f"Product not found for ID: {product_id}, owner ID: {owner_id}")
            flash("Product not found!", "danger")
            return redirect(url_for("view_products"))
        
        # Get quantity from form data
        quantity_sold = int(request.form["quantity"])
        logger.info(f"Selling {quantity_sold} units of '{product['product_name']}'")
        
        if quantity_sold <= 0:
            flash("Invalid quantity!", "danger")
            return redirect(url_for("view_products"))

        if quantity_sold > product["stock"]:
            flash(f"Not enough stock! Only {product['stock']} available.", "danger")
            return redirect(url_for("view_products"))

        # Calculate sale details
        total_price = quantity_sold * product["price"]
        
        # Record the sale
        sale_record = {
            "product_id": str(product_id),  # Store as string for consistency
            "owner_id": owner_id,
            "seller_id": current_user.id,
            "seller_name": current_user.username,
            "product_name": product["product_name"],
            "quantity_sold": quantity_sold,
            "total_price": total_price,
            "date_sold": datetime.utcnow()
        }
        sales_collection.insert_one(sale_record)
        
        # Update product stock
        new_stock = product["stock"] - quantity_sold
        product_collection.update_one(
            {"_id": ObjectId(product_id)},
            {"$set": {"stock": new_stock}}
        )
        
        # Notify based on inventory status
        if new_stock == 0:
            flash(f"Product '{product['product_name']}' is now out of stock!", "warning")
        elif new_stock <= product.get("low_stock_threshold", 5):
            flash(f"Warning! '{product['product_name']}' is low on stock ({new_stock} left).", "warning")
        
        flash(f"Sale of {quantity_sold} {product['product_name']} recorded successfully! Total: ₹{total_price}", "success")
    except ValueError:
        flash("Invalid input. Please enter a valid quantity.", "danger")
    except Exception as e:
        logger.error(f"Error selling product: {str(e)}")
        flash(f"An error occurred: {str(e)}", "danger")
        
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

# Enhanced product sales route with more robust handling of data
@app.route("/product_sales/<product_id>")
@login_required
def product_sales(product_id):
    owner_id = current_user.get_owner_id()
    product = product_collection.find_one({"_id": ObjectId(product_id), "owner_id": owner_id})
    
    if not product:
        flash("Product not found!", "danger")
        return redirect(url_for("view_products"))
    
    # Check plan permissions - only Professional and Enterprise plans get full analytics
    plan_name = current_user.plan
    plan_details = current_user.get_plan_details()
    basic_analytics_only = plan_name == 'starter'
    
    # For starter plan, provide only basic info
    total_sales = 0
    total_quantity = 0
    total_revenue = 0
    chart_dates = []
    chart_quantities = []
    chart_revenues = []
    sales = []
    
    # Always fetch basic stats for all plans
    try:
        # Get all sales for this product
        sales_cursor = sales_collection.find({
            "product_id": str(product_id),
            "owner_id": owner_id
        })
        
        # Calculate basic statistics that are available to all plans
        if sales_cursor:
            sales = list(sales_cursor)
            total_sales = len(sales)
            total_quantity = sum(sale.get("quantity_sold", 0) for sale in sales)
            total_revenue = sum(sale.get("total_price", 0) for sale in sales)
            
        # Advanced analytics only for professional and enterprise plans
        if not basic_analytics_only:
            # Format dates for chart display and process data for advanced charts
            chart_data = {}
            if sales:
                for sale in sales:
                    if "date_sold" in sale:
                        if isinstance(sale["date_sold"], datetime):
                            date_str = sale["date_sold"].strftime("%Y-%m-%d")
                        else:
                            try:
                                date_str = datetime.fromisoformat(str(sale["date_sold"])).strftime("%Y-%m-%d")
                            except (ValueError, TypeError):
                                date_str = "Unknown Date"
                        
                        if date_str not in chart_data:
                            chart_data[date_str] = {"quantity": 0, "revenue": 0}
                        chart_data[date_str]["quantity"] += sale.get("quantity_sold", 0)
                        chart_data[date_str]["revenue"] += sale.get("total_price", 0)
                
                # Sort by date
                chart_dates = sorted(chart_data.keys())
                chart_quantities = [chart_data[date]["quantity"] for date in chart_dates]
                chart_revenues = [chart_data[date]["revenue"] for date in chart_dates]
                
    except Exception as e:
        logger.error(f"Error generating product sales data: {str(e)}")
        flash("An error occurred retrieving sales data.", "danger")
        return redirect(url_for("view_products"))
    
    return render_template("product_sales.html", 
                          product=product,
                          sales=sales, 
                          total_sales=total_sales,
                          total_quantity=total_quantity,
                          total_revenue=total_revenue,
                          chart_dates=chart_dates,
                          chart_quantities=chart_quantities,
                          chart_revenues=chart_revenues,
                          basic_analytics_only=basic_analytics_only,
                          plan_name=plan_name,
                          plan_details=plan_details,
                          pricing=pricing)

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

# Fix the view_sales route to properly handle team members
@app.route("/sales")
@login_required
def view_sales():
    # For team members, check if they have permission to view sales
    if current_user.is_team_member and not current_user.can_view_reports():
        flash("You don't have permission to view sales records.", "warning")
        return redirect(url_for("dashboard"))
        
    owner_id = current_user.get_owner_id()
    sales = list(sales_collection.find({"owner_id": owner_id}).sort("date_sold", -1))
    
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
    # Get owner_id for proper product access
    owner_id = current_user.get_owner_id()
    
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
                # Use the owner_id to find products, not just the current user's id
                product = mongo.db.products.find_one({"_id": ObjectId(item_id), "owner_id": owner_id})
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

                # Record sale with the owner's ID for proper tracking
                sales_collection.insert_one({
                    "product_id": item_id,
                    "owner_id": owner_id,  # Use owner_id instead of current_user.id
                    "seller_id": current_user.id,  # Also track who made the sale
                    "seller_name": current_user.username,
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

        # Add billing info to PDF
        business_info = {
            "name": current_user.business_name,
            "seller": current_user.username,
            "role": current_user.role if current_user.is_team_member else "Owner"
        }
        
        pdf_buffer = generate_pdf_bill(customer_name, items, total_price, business_info)
        return send_file(pdf_buffer, as_attachment=True, download_name="bill.pdf", mimetype="application/pdf")
    
    # Show products from the owner for team members
    products = list(mongo.db.products.find({"owner_id": owner_id}))
    return render_template("billing.html", products=products)

# Add page number function
def add_page_number(canvas, doc):
    canvas.saveState()
    page_num = canvas.getPageNumber()
    canvas.setFont('Helvetica', 9)
    canvas.drawRightString(letter[0] - 72, 30, f"Page {page_num}")
    canvas.restoreState()

# Generate PDF bill function
def generate_pdf_bill(customer_name, items, total_price, business_info):
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
    
    # Add seller information
    content.append(Paragraph(f"<b>Business:</b> {business_info['name']}", styles['Normal']))
    content.append(Paragraph(f"<b>Sale by:</b> {business_info['seller']} ({business_info['role']})", styles['Normal']))
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
    # Only business owners can add team members
    if current_user.is_team_member:
        flash("Only business owners can add team members.", "warning")
        return redirect(url_for("dashboard"))
    
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
        
    # Get owner information to display
    owner_info = None
    if current_user.is_team_member:
        # If team member is adding another team member, show the business owner
        parent = user_collection.find_one({"_id": ObjectId(current_user.parent_user_id)})
        if parent:
            owner_info = {
                "username": parent.get("username", ""),
                "business_name": parent.get("business_name", ""),
                "email": parent.get("email", "")
            }
    else:
        # Business owner is adding team member
        owner_info = {
            "username": current_user.username,
            "business_name": current_user.business_name,
            "email": current_user.email
        }
    
    # Also get existing team members to display
    existing_team_members = list(user_collection.find({"parent_user_id": current_user.get_owner_id()}))
    
    return render_template(
        "add_user.html",
        current_user_count=current_user_count,
        plan_details=plan_details,
        plan_name=plan_name,
        total_products=total_products,
        existing_team_members=existing_team_members,
        owner_info=owner_info
    )

@app.route("/manage_team")
@login_required
def manage_team():
    # Only business owners can manage team
    if current_user.is_team_member:
        flash("Only business owners can manage team members.", "warning")
        return redirect(url_for("dashboard"))
    
    # Get all team members for this business owner
    owner_id = current_user.id  # Use current_user.id directly since only owners can access this route
    team_members = list(user_collection.find({"parent_user_id": owner_id}))
    plan_details = current_user.get_plan_details()
    
    return render_template(
        "manage_team.html",
        team_members=team_members,
        plan_details=plan_details,
        plan_name=current_user.plan,
        owner_info={
            "username": current_user.username,
            "business_name": current_user.business_name
        },
        is_team_member=False  # Will always be false since we're restricting access to owners
    )

@app.route("/delete_team_member/<user_id>", methods=["POST"])
@login_required
def delete_team_member(user_id):
    # Only business owners can delete team members
    if current_user.is_team_member:
        flash("Only business owners can manage team members.", "warning")
        return redirect(url_for("dashboard"))
        
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
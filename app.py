from flask import Flask, render_template, request, redirect, url_for, flash, Response, send_file, session, jsonify
from flask_pymongo import PyMongo
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from bson import ObjectId
from datetime import datetime
from config import Config
from io import StringIO
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image
from reportlab.lib.units import inch
from io import BytesIO
from itsdangerous import URLSafeTimedSerializer
from flask_mail import Mail, Message
from functools import wraps
import logging
import csv

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = 'your_secret_key'

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

mongo = PyMongo(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

user_collection = mongo.db.users
product_collection = mongo.db.products
sales_collection = mongo.db.sales
coupon_collection = mongo.db.coupons  # Collection for managing coupons

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def rate_limit(limit=5):
    calls = {}
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            return f(*args, **kwargs)
        return wrapped
    return decorator

def plan_required(min_plan_level=None, feature=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            plan_levels = ['starter', 'professional', 'enterprise']
            user_plan = current_user.get_effective_plan()
            user_plan_level = plan_levels.index(user_plan)
            required_level = plan_levels.index(min_plan_level) if min_plan_level else 0
            if user_plan_level < required_level:
                flash("Your plan does not allow access to this feature.", "warning")
                return redirect(url_for("dashboard"))
            if feature == 'product_count' and 'add_product' in request.path:
                plan_details = current_user.get_plan_details()
                owner_id = current_user.get_owner_id()
                total_products = product_collection.count_documents({"owner_id": owner_id})
                if total_products >= plan_details['products']:
                    flash("You have reached your product limit for your plan. Please upgrade to add more products.", "warning")
                    return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def role_required(role=None, permission=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_team_member:
                return f(*args, **kwargs)
            if role and current_user.role != role:
                flash(f"This action requires {role} privileges.", "warning")
                return redirect(url_for("dashboard"))
            if permission and permission not in current_user.permissions:
                flash(f"You don't have permission to {permission}.", "warning")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data["_id"])
        self.username = user_data["username"]
        self.is_team_member = "parent_user_id" in user_data
        self.parent_user_id = user_data.get("parent_user_id", None)
        self.role = user_data.get("role", "owner")
        self.permissions = user_data.get("permissions", [])
        self.email = user_data.get("email", "")
        self.business_name = user_data.get("business_name", "")
        self.plan = user_data.get("plan", "starter")
        self._owner = None
    def get_plan_details(self):
        if self.is_team_member and self.parent_user_id:
            owner = self.get_owner()
            if owner:
                return pricing.get(owner.get('plan', 'starter'), pricing['starter'])
        return pricing.get(self.plan, pricing['starter'])
    def get_owner(self):
        if self.is_team_member and not self._owner and self.parent_user_id:
            self._owner = user_collection.find_one({'_id': ObjectId(self.parent_user_id)})
        return self._owner
    def get_effective_plan(self):
        if self.is_team_member and self.parent_user_id:
            owner = self.get_owner()
            if owner:
                return owner.get('plan', 'starter')
        return self.plan
    def get_owner_id(self):
        return self.parent_user_id if self.is_team_member else self.id
    def can_view_products(self):
        return True
    def can_edit_products(self):
        return not self.is_team_member or self.role in ["admin", "manager"] or "add" in self.permissions
    def can_sell_products(self):
        return True
    def can_view_reports(self):
        return not self.is_team_member or "reports" in self.permissions or self.role in ["admin", "manager"]
    def can_manage_team(self):
        return not self.is_team_member or self.role in ["admin", "manager"] or "add" in self.permissions
    def can_access_advanced_features(self):
        effective_plan = self.get_effective_plan()
        return effective_plan in ['professional', 'enterprise']

@login_manager.user_loader
def load_user(user_id):
    user = user_collection.find_one({'_id': ObjectId(user_id)})
    return User(user) if user else None

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

@app.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    else:
        return render_template("home.html", pricing=pricing)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]
        business_name = request.form["business_name"]
        if not username or not email or not password or not business_name:
            flash("Please fill in all required fields", "danger")
            return redirect(url_for("register"))
        if user_collection.find_one({"username": username}):
            flash("Username already exists", "danger")
            return redirect(url_for("register"))
        hashed_password = bcrypt.generate_password_hash(password).decode("utf-8")
        user = {
            "username": username,
            "email": email,
            "password": hashed_password,
            "business_name": business_name,
            "role": "owner",
            "plan": "starter",
            "registration_date": datetime.utcnow()
        }
        user_collection.insert_one(user)
        flash("Registration successful! Please log in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html", pricing=pricing)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = user_collection.find_one({"username": username})
        if user and bcrypt.check_password_hash(user["password"], password):
            user_obj = User(user)
            login_user(user_obj)
            if user_obj.is_team_member:
                owner = user_collection.find_one({"_id": ObjectId(user_obj.parent_user_id)})
                owner_name = owner.get("business_name", "the business") if owner else "the business"
                flash(f"Welcome {username}! You are logged in as a {user_obj.role} for {owner_name}.", "success")
            else:
                flash(f"Welcome {username}!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid username or password!", "danger")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("home"))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    plan_details = current_user.get_plan_details()
    plan_name = current_user.get_effective_plan()
    owner_id = current_user.get_owner_id()
    total_products = product_collection.count_documents({"owner_id": owner_id})
    team_members_count = user_collection.count_documents({"parent_user_id": owner_id})
    total_active_users = 1 + team_members_count
    return render_template(
        "profile.html",
        current_user=current_user,
        pricing=pricing,
        plan_details=plan_details,
        plan_name=plan_name,
        total_products=total_products,
        team_members_count=team_members_count,
        total_active_users=total_active_users
    )

from ai_predictions import predict_restock_time, identify_non_selling_products

@app.route("/dashboard")
@login_required
def dashboard():
    owner_id = current_user.get_owner_id()
    total_products = product_collection.count_documents({"owner_id": owner_id})
    low_stock_products = list(product_collection.find({
        "owner_id": owner_id,
        "$expr": {"$lte": ["$stock", "$low_stock_threshold"]}
    }))
    low_stock_count = len(low_stock_products)
    total_sales = calculate_total_sales(owner_id)
    recent_products = list(product_collection.find({"owner_id": owner_id}).sort("_id", -1).limit(10))
    plan_details = current_user.get_plan_details()
    product_limit = plan_details['products']
    product_usage_percent = (total_products / product_limit) * 100 if product_limit > 0 else 0
    team_info = None
    team_members_count = user_collection.count_documents({"parent_user_id": owner_id})
    total_active_users = 1 + team_members_count
    if not current_user.is_team_member:
        team_info = {
            "count": team_members_count,
            "limit": plan_details['users']
        }
    recent_sales = list(sales_collection.find({"owner_id": owner_id}).sort("date_sold", -1).limit(10))
    
    # Get all products for AI analysis
    all_products = list(product_collection.find({"owner_id": owner_id}))
    
    # Get all sales data for these products
    all_sales = list(sales_collection.find({"owner_id": owner_id}))
    
    # Organize sales data by product_id for faster lookup
    sales_by_product = {}
    for sale in all_sales:
        product_id = sale.get('product_id')
        if product_id:
            if product_id not in sales_by_product:
                sales_by_product[product_id] = []
            sales_by_product[product_id].append(sale)
    
    # AI Predictions for restocking
    restock_predictions = []
    for product in all_products:
        product_id = str(product.get('_id'))
        product_sales = sales_by_product.get(product_id, [])
        if product['stock'] > 0:  # Only predict for products that have stock
            prediction = predict_restock_time(product, product_sales)
            if prediction['prediction_possible']:
                restock_predictions.append({
                    'product': product,
                    'prediction': prediction
                })
    
    # Sort predictions by urgency (days until restock needed)
    restock_predictions.sort(key=lambda x: x['prediction']['days_until_restock'])
    restock_predictions = restock_predictions[:5]  # Only show top 5
    
    # Identify non-selling products
    non_selling_products = identify_non_selling_products(all_products, sales_by_product)
    non_selling_products = non_selling_products[:5]  # Only show top 5
    
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
                        is_team_member=current_user.is_team_member,
                        plan_name=current_user.get_effective_plan(),
                        recent_sales=recent_sales,
                        total_active_users=total_active_users,
                        restock_predictions=restock_predictions,
                        non_selling_products=non_selling_products)

@app.route("/add_product", methods=["GET", "POST"])
@login_required
@plan_required(feature='product_count')
@role_required(permission="add")
def add_product():
    if request.method == "POST":
        if not validate_product_input(request.form):
            flash("Invalid input data!", "danger")
            return redirect(url_for("add_product"))
        owner_id = current_user.get_owner_id()
        product_data = {
            "product_name": request.form["product_name"],
            "description": request.form["description"],
            "price": float(request.form["price"]),
            "stock": int(request.form["stock"]),
            "low_stock_threshold": int(request.form.get("low_stock_threshold", 5)),
            "owner_id": owner_id
        }
        product_collection.insert_one(product_data)
        flash("Product added successfully!", "success")
        return redirect(url_for("view_products"))
    return render_template("add_product.html")

@app.route("/view_products")
@login_required
def view_products():
    if current_user.is_team_member and not current_user.can_view_products():
        flash("You don't have permission to view products.", "warning")
        return redirect(url_for("dashboard"))
    owner_id = current_user.get_owner_id()
    logger.info(f"Fetching products for owner_id: {owner_id}")
    products = list(product_collection.find({"owner_id": owner_id}))
    logger.info(f"Found {len(products)} products")
    low_stock_products = [product for product in products if product["stock"] <= product.get("low_stock_threshold", 5)]
    return render_template("view_products.html", 
                          products=products, 
                          low_stock_products=low_stock_products,
                          can_edit=current_user.can_edit_products(),
                          can_sell=current_user.can_sell_products())

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
            {"_id": ObjectId(product_id), "owner_id": owner_id},
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

@app.route("/sell_product/<product_id>", methods=["POST"])
@login_required
def sell_product(product_id):
    try:
        owner_id = current_user.get_owner_id()
        logger.info(f"Processing sell for product ID: {product_id}, owner ID: {owner_id}")
        product = product_collection.find_one({"_id": ObjectId(product_id), "owner_id": owner_id})
        if not product:
            logger.warning(f"Product not found for ID: {product_id}, owner ID: {owner_id}")
            flash("Product not found!", "danger")
            return redirect(url_for("view_products"))
        quantity_sold = int(request.form["quantity"])
        logger.info(f"Selling {quantity_sold} units of '{product['product_name']}'")
        if quantity_sold <= 0:
            flash("Invalid quantity!", "danger")
            return redirect(url_for("view_products"))
        if quantity_sold > product["stock"]:
            flash(f"Not enough stock! Only {product['stock']} available.", "danger")
            return redirect(url_for("view_products"))
        total_price = quantity_sold * product["price"]
        sale_record = {
            "product_id": str(product_id),
            "owner_id": owner_id,
            "seller_id": current_user.id,
            "seller_name": current_user.username,
            "product_name": product["product_name"],
            "quantity_sold": quantity_sold,
            "total_price": total_price,
            "date_sold": datetime.utcnow()
        }
        sales_collection.insert_one(sale_record)
        new_stock = product["stock"] - quantity_sold
        product_collection.update_one(
            {"_id": ObjectId(product_id), "owner_id": owner_id},
            {"$set": {"stock": new_stock}}
        )
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

@app.route("/export_sales")
@login_required
def export_sales():
    sales = list(sales_collection.find({"owner_id": current_user.id}))
    user_profile = user_collection.find_one({"_id": ObjectId(current_user.id)})
    business_name = user_profile["business_name"] if user_profile and "business_name" in user_profile else "Your Business"
    export_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    plan_name = current_user.get_effective_plan().capitalize()
    def generate_csv():
        output = StringIO()
        csv_writer = csv.writer(output)
        csv_writer.writerow([f"Business Name: {business_name} | Plan: {plan_name}"])
        csv_writer.writerow([f"Exported On: {export_time}"])
        csv_writer.writerow([])
        csv_writer.writerow(["Product Name", "Quantity Sold", "Total Price", "Date Sold"])
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
        csv_writer.writerow([])
        csv_writer.writerow(["Signed By: ", "Shaswat"])
        output.seek(0)
        return output.read()
    response = Response(generate_csv(), content_type="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename=sales_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return response

@app.route("/product_sales/<product_id>")
@login_required
def product_sales(product_id):
    owner_id = current_user.get_owner_id()
    product = product_collection.find_one({"_id": ObjectId(product_id), "owner_id": owner_id})
    if not product:
        flash("Product not found!", "danger")
        return redirect(url_for("view_products"))
    effective_plan = current_user.get_effective_plan()
    plan_details = current_user.get_plan_details()
    basic_analytics_only = effective_plan == 'starter'
    total_sales = 0
    total_quantity = 0
    total_revenue = 0
    chart_dates = []
    chart_quantities = []
    chart_revenues = []
    sales = []
    try:
        sales_cursor = sales_collection.find({
            "product_id": str(product_id),
            "owner_id": owner_id
        })
        if sales_cursor:
            sales = list(sales_cursor)
            total_sales = len(sales)
            total_quantity = sum(sale.get("quantity_sold", 0) for sale in sales)
            total_revenue = sum(sale.get("total_price", 0) for sale in sales)
        if not basic_analytics_only:
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
                chart_dates = sorted(chart_data.keys())
                chart_quantities = [chart_data[date]["quantity"] for date in chart_dates]
                chart_revenues = [chart_data[date]["revenue"] for date in chart_dates]
    except Exception as e:
        logger.error(f"Error generating product sales data: {str(e)}")
        flash("An error occurred retrieving sales data.", "danger")
        return redirect(url_for("view_products"))
    owner_info = None
    if current_user.is_team_member:
        owner = current_user.get_owner()
        if owner:
            owner_info = {
                'business_name': owner.get('business_name', 'Your Business'),
                'plan': owner.get('plan', 'starter')
            }
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
                          plan_name=effective_plan,
                          plan_details=plan_details,
                          pricing=pricing,
                          owner_info=owner_info,
                          is_team_member=current_user.is_team_member)

@app.route("/delete_sale/<sale_id>", methods=["POST"])
@login_required
def delete_sale(sale_id):
    result = sales_collection.delete_one({"_id": ObjectId(sale_id), "owner_id": current_user.id})
    if result.deleted_count == 0:
        flash("Sale not found!", "danger")
    else:
        flash("Sale deleted successfully!", "success")
    return redirect(url_for("view_sales"))

@app.route("/delete_all_sales", methods=["POST"])
@login_required
def delete_all_sales():
    sales_collection.delete_many({"owner_id": current_user.id})
    flash("All sales records have been deleted!", "warning")
    return redirect(url_for("view_sales"))

@app.route("/sales")
@login_required
def view_sales():
    if current_user.is_team_member and not current_user.can_view_reports():
        flash("You don't have permission to view sales records.", "warning")
        return redirect(url_for("dashboard"))
    owner_id = current_user.get_owner_id()
    sales = list(sales_collection.find({"owner_id": owner_id}).sort("date_sold", -1))
    for sale in sales:
        if isinstance(sale["date_sold"], str):
            try:
                sale["date_sold"] = datetime.strptime(sale["date_sold"], "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
    return render_template("view_sales.html", sales=sales)

@app.route("/delete_product/<product_id>")
@login_required
def delete_product(product_id):
    result = product_collection.delete_one({"_id": ObjectId(product_id), "owner_id": current_user.id})
    if result.deleted_count == 0:
        flash("Product not found!", "danger")
    else:
        flash("Product deleted successfully!", "success")
    return redirect(url_for("view_products"))

@app.route("/billing", methods=["GET", "POST"])
@login_required
def billing():
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
                sales_collection.insert_one({
                    "product_id": item_id,
                    "owner_id": owner_id,
                    "seller_id": current_user.id,
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
        # Handle coupon code
        coupon_code = request.form.get("coupon_code")
        discount = 0
        original_total = total_price
        if coupon_code:
            coupon = coupon_collection.find_one({"code": coupon_code, "owner_id": owner_id})
            if coupon:
                if coupon.get("expiration_date") and coupon["expiration_date"] < datetime.utcnow():
                    flash("Coupon code has expired!", "danger")
                    return redirect(url_for("billing"))
                if coupon.get("type") == "percentage":
                    discount = total_price * (coupon.get("value", 0) / 100)
                else:
                    discount = coupon.get("value", 0)
                total_price -= discount
                coupon_collection.update_one({"_id": coupon["_id"]}, {"$inc": {"usage_count": 1}})
                flash(f"Coupon {coupon_code} applied: saved ₹{discount:.2f}", "success")
            else:
                flash("Invalid coupon code!", "danger")
                return redirect(url_for("billing"))
        business_info = {
            "name": current_user.business_name,
            "seller": current_user.username,
            "role": current_user.role if current_user.is_team_member else "Owner"
        }
        pdf_buffer = generate_pdf_bill(customer_name, items, original_total, business_info, coupon_code, discount, total_price)
        return send_file(pdf_buffer, as_attachment=True, download_name="bill.pdf", mimetype="application/pdf")
    products = list(mongo.db.products.find({"owner_id": owner_id}))
    return render_template("billing.html", products=products)

@app.route("/validate_coupon", methods=["POST"])
@login_required
def validate_coupon():
    data = request.get_json()
    coupon_code = data.get("coupon_code")
    owner_id = current_user.get_owner_id()
    coupon = coupon_collection.find_one({"code": coupon_code, "owner_id": owner_id})
    if not coupon:
        return jsonify({"valid": False, "message": "Invalid coupon code."}), 200
    if coupon.get("expiration_date") and coupon["expiration_date"] < datetime.utcnow():
        return jsonify({"valid": False, "message": "Coupon expired."}), 200
    discount_type = coupon.get("type")
    value = coupon.get("value", 0)
    return jsonify({
        "valid": True,
        "type": discount_type,
        "value": value,
        "message": "Coupon valid."
    }), 200

def add_page_number(canvas, doc):
    canvas.saveState()
    page_num = canvas.getPageNumber()
    canvas.setFont('Helvetica', 9)
    canvas.drawRightString(letter[0] - 72, 30, f"Page {page_num}")
    canvas.restoreState()

def generate_pdf_bill(customer_name, items, original_total, business_info, coupon_code=None, discount=0, final_total=0):
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
    content.append(Paragraph(f"<b>Business:</b> {business_info['name']}", styles['Normal']))
    content.append(Paragraph(f"<b>Sale by:</b> {business_info['seller']} ({business_info['role']})", styles['Normal']))
    content.append(Spacer(1, 12))
    content.append(Paragraph(f"<b>Customer:</b> {customer_name}", styles['Normal']))
    content.append(Spacer(1, 12))
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
            Paragraph(f"₹{item['price']:.2f}", styles['TableCell']),
            Paragraph(f"₹{item['total']:.2f}", styles['TableCell'])
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
    content.append(Paragraph(f"<b>Original Total:</b> ₹{original_total:.2f}", styles['InvoiceSubHeader']))
    if discount and coupon_code:
        content.append(Paragraph(f"<b>Coupon ({coupon_code}):</b> -₹{discount:.2f}", styles['Normal']))
    content.append(Paragraph(f"<b>Final Total:</b> ₹{final_total:.2f}", styles['InvoiceSubHeader']))
    content.append(Spacer(1, 24))
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

@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name = request.form.get('name')
        email = request.form.get('email')
        message = request.form.get('message')
        company = request.form.get('company')
        flash('Thanks for contacting us! We will get back to you soon.', 'success')
        return redirect(url_for('contact'))
    return render_template('contact.html')

@app.route("/analytics")
@login_required
@rate_limit(limit=10)
def analytics():
    try:
        total_sales = calculate_total_sales(current_user.id)
        total_products = product_collection.count_documents({"owner_id": current_user.id})
        sales_data = list(sales_collection.find({"owner_id": current_user.id}))
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

@app.route("/advanced-analytics")
@login_required
@plan_required(min_plan_level='professional')
def advanced_analytics():
    return render_template("advanced_analytics.html")

@app.route('/change_plan/<plan_name>', methods=['POST'])
@login_required
def change_plan(plan_name):
    if plan_name not in pricing:
        flash("Invalid plan selected!", "danger")
        return redirect(url_for("profile"))
    try:
        current_plan = current_user.get_effective_plan()
        new_price = pricing[plan_name]['price']
        current_price = pricing[current_plan]['price']
        if new_price > current_price:
            logger.info(f"Processing payment for user {current_user.username}: {current_price} -> {new_price}")
            flash("Payment processed successfully!", "success")
        else:
            flash("Plan downgraded successfully.", "info")
    except Exception as e:
        logger.error(f"Payment error for user {current_user.username}: {e}")
        flash("Payment processing failed. Please try again.", "danger")
        return redirect(url_for("profile"))
    user_collection.update_one(
        {"_id": ObjectId(current_user.id)},
        {"$set": {"plan": plan_name}}
    )
    flash(f"Your plan has been updated to {plan_name.capitalize()}!", "success")
    return redirect(url_for("profile"))

@app.route("/add_team_member", methods=["GET", "POST"])
@login_required
def add_team_member():
    if current_user.is_team_member:
        flash("Only business owners can add team members.", "warning")
        return redirect(url_for("dashboard"))
    current_user_count = user_collection.count_documents({"parent_user_id": current_user.id})
    plan_details = current_user.get_plan_details()
    plan_name = current_user.get_effective_plan()
    total_products = product_collection.count_documents({"owner_id": current_user.id})
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
        if not username or not email or not password:
            flash("Please fill in all required fields", "danger")
            return redirect(url_for("add_team_member"))
        if password != confirm_password:
            flash("Passwords don't match", "danger")
            return redirect(url_for("add_team_member"))
        if user_collection.find_one({"username": username}):
            flash("Username already exists", "danger")
            return redirect(url_for("add_team_member"))
        hashed_password = bcrypt.generate_password_hash(password).decode("utf-8")
        new_user = {
            "username": username,
            "email": email,
            "password": hashed_password,
            "parent_user_id": current_user.id,
            "business_name": current_user.business_name,
            "role": role,
            "permissions": permissions,
            "plan": "team_member",
            "registration_date": datetime.utcnow()
        }
        user_collection.insert_one(new_user)
        flash(f"Team member {username} added successfully!", "success")
        return redirect(url_for("manage_team"))
    owner_info = None
    if current_user.is_team_member:
        parent = user_collection.find_one({"_id": ObjectId(current_user.parent_user_id)})
        if parent:
            owner_info = {
                "username": parent.get("username", ""),
                "business_name": parent.get("business_name", ""),
                "email": parent.get("email", "")
            }
    else:
        owner_info = {
            "username": current_user.username,
            "business_name": current_user.business_name,
            "email": current_user.email
        }
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
    if current_user.is_team_member:
        flash("Only business owners can manage team members.", "warning")
        return redirect(url_for("dashboard"))
    owner_id = current_user.id
    team_members = list(user_collection.find({"parent_user_id": owner_id}))
    plan_details = current_user.get_plan_details()
    return render_template(
        "manage_team.html",
        team_members=team_members,
        plan_details=plan_details,
        plan_name=current_user.get_effective_plan(),
        owner_info={
            "username": current_user.username,
            "business_name": current_user.business_name
        },
        is_team_member=False
    )

@app.route("/delete_team_member/<user_id>", methods=["POST"])
@login_required
def delete_team_member(user_id):
    if current_user.is_team_member:
        flash("Only business owners can manage team members.", "warning")
        return redirect(url_for("dashboard"))
    team_member = user_collection.find_one({
        "_id": ObjectId(user_id),
        "parent_user_id": current_user.id
    })
    if not team_member:
        flash("Team member not found!", "danger")
        return redirect(url_for("manage_team"))
    user_collection.delete_one({"_id": ObjectId(user_id)})
    flash("Team member removed successfully!", "success")
    return redirect(url_for("manage_team"))

@app.route("/edit_team_member/<user_id>", methods=["GET", "POST"])
@login_required
def edit_team_member(user_id):
    if current_user.is_team_member:
        flash("Only business owners can edit team members.", "warning")
        return redirect(url_for("dashboard"))
    member = user_collection.find_one({"_id": ObjectId(user_id), "parent_user_id": current_user.id})
    if not member:
        flash("Team member not found!", "danger")
        return redirect(url_for("manage_team"))
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        role = request.form.get("role", "staff")
        permissions = request.form.getlist("permissions[]")
        # Only update password if provided
        password = request.form.get("password")
        update_fields = {
            "username": username,
            "email": email,
            "role": role,
            "permissions": permissions
        }
        if password:
            hashed_password = bcrypt.generate_password_hash(password).decode("utf-8")
            update_fields["password"] = hashed_password
        user_collection.update_one({"_id": ObjectId(user_id)}, {"$set": update_fields})
        flash("Team member updated successfully!", "success")
        return redirect(url_for("manage_team"))
    plan_details = current_user.get_plan_details()
    plan_name = current_user.get_effective_plan()
    total_products = product_collection.count_documents({"owner_id": current_user.id})
    current_user_count = user_collection.count_documents({"parent_user_id": current_user.id})
    owner_info = {
        "username": current_user.username,
        "business_name": current_user.business_name,
        "email": current_user.email
    }
    return render_template(
        "edit_user.html",
        member=member,
        plan_details=plan_details,
        plan_name=plan_name,
        total_products=total_products,
        current_user_count=current_user_count,
        owner_info=owner_info
    )

@app.route("/manage_coupons")
@login_required
def manage_coupons():
    if current_user.is_team_member:
        flash("Only business owners can manage coupons.", "warning")
        return redirect(url_for("dashboard"))
    owner_id = current_user.get_owner_id()
    coupons = list(coupon_collection.find({"owner_id": owner_id}))
    return render_template("manage_coupons.html", coupons=coupons, now=datetime.utcnow)

@app.route("/manage_coupons/add", methods=["POST"])
@login_required
def add_coupon():
    if current_user.is_team_member:
        flash("Only business owners can manage coupons.", "warning")
        return redirect(url_for("dashboard"))
    owner_id = current_user.get_owner_id()
    code = request.form.get("code")
    ctype = request.form.get("type")
    value = request.form.get("value")
    expiration_date = request.form.get("expiration_date")
    if not code or not ctype or not value:
        flash("Please fill in all coupon fields!", "danger")
        return redirect(url_for("manage_coupons"))
    try:
        value = float(value)
    except ValueError:
        flash("Invalid discount value!", "danger")
        return redirect(url_for("manage_coupons"))
    exp_date = datetime.strptime(expiration_date, "%Y-%m-%d") if expiration_date else None
    coupon = {"code": code, "type": ctype, "value": value, "expiration_date": exp_date, "usage_count": 0, "owner_id": owner_id}
    coupon_collection.insert_one(coupon)
    flash("Coupon added successfully!", "success")
    return redirect(url_for("manage_coupons"))

@app.route("/manage_coupons/delete/<coupon_id>", methods=["POST"])
@login_required
def delete_coupon(coupon_id):
    if current_user.is_team_member:
        flash("Only business owners can manage coupons.", "warning")
        return redirect(url_for("dashboard"))
    result = coupon_collection.delete_one({"_id": ObjectId(coupon_id), "owner_id": current_user.get_owner_id()} )
    if result.deleted_count == 0:
        flash("Coupon not found!", "danger")
    else:
        flash("Coupon deleted successfully!", "success")
    return redirect(url_for("manage_coupons"))

if __name__ == "__main__":
    logger.info("Starting Inventory Manager application")
    app.run(debug=True)
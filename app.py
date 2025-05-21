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

# Update the plan_required decorator to check team members against their owner's plan
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
                
            # Use effective plan - either user's own plan or their owner's plan
            user_plan = current_user.get_effective_plan()
            user_plan_level = plan_levels.get(user_plan, 0)
            required_level = plan_levels.get(min_plan_level, 0)
            
            if user_plan_level < required_level:
                # Different message for team members
                if current_user.is_team_member:
                    owner = current_user.get_owner()
                    owner_name = owner.get('business_name', 'Your business owner') if owner else "Your business owner"
                    flash(f"{owner_name} needs to upgrade to the {min_plan_level.capitalize()} plan for you to access this feature.", "warning")
                else:
                    flash(f"This feature requires the {min_plan_level.capitalize()} plan or higher.", "warning")
                return redirect(url_for("dashboard"))
            
            # Check product count if adding product
            if feature == 'product_count' and 'add_product' in request.path:
                owner_id = current_user.get_owner_id()
                product_count = product_collection.count_documents({"owner_id": owner_id})
                plan_limit = pricing[user_plan]['products']
                
                if product_count >= plan_limit:
                    if current_user.is_team_member:
                        flash(f"Product limit reached for your organization. Ask your administrator to upgrade the plan.", "warning")
                    else:
                        flash(f"Your {user_plan.capitalize()} plan is limited to {plan_limit} products. Please upgrade to add more.", "warning")
                    return redirect(url_for("profile") if not current_user.is_team_member else url_for("dashboard"))
            
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
                
        self.is_team_member = "parent_user_id" in user_data
        self.parent_user_id = user_data.get("parent_user_id", None)
        self.role = user_data.get("role", "owner")
        self.permissions = user_data.get("permissions", [])
        self.email = user_data.get("email", "")inheritance from owner
        er(UserMixin):
        # Store the original user data for access to all fields
        self._data = user_dataa["_id"])
        self.username = user_data["username"]
        # Cache the owner's plan for team members to avoid repeated lookups
        self._owner_plan = Noneet("plan", "starter")  # Default to starter plan if not specified
        self._owner = Noner = "parent_user_id" in user_data
        self.parent_user_id = user_data.get("parent_user_id", None)
    def get_plan_details(self):et("role", "owner")
        # If this is a team member, get the owner's plan details
        if self.is_team_member and self.parent_user_id:
            owner = self.get_owner()
            if owner:riginal user data for access to all fields
                return pricing.get(owner.get('plan', 'starter'), pricing['starter'])
        return pricing.get(self.plan, pricing['starter'])
        # Cache the owner's plan for team members to avoid repeated lookups
    def get_owner(self): = None
        # Cache the owner to avoid repeated database lookups
        if self.is_team_member and not self._owner and self.parent_user_id:
            self._owner = user_collection.find_one({'_id': ObjectId(self.parent_user_id)})
        return self._ownerm member, get the owner's plan details
        if self.is_team_member and self.parent_user_id:
    def get_effective_plan(self):r()
        """Return the actual plan that should be applied (owner's plan for team members)"""
        if self.is_team_member and self.parent_user_id:tarter'), pricing['starter'])
            owner = self.get_owner(), pricing['starter'])
            if owner:
                return owner.get('plan', 'starter')
        return self.planr to avoid repeated database lookups
        if self.is_team_member and not self._owner and self.parent_user_id:
    def get_owner_id(self):ser_collection.find_one({'_id': ObjectId(self.parent_user_id)})
        # Return parent_user_id if team member, or own id if business owner
        return self.parent_user_id if self.is_team_member else self.id
    def get_effective_plan(self):
    def can_view_products(self):n that should be applied (owner's plan for team members)"""
        # All team members should be able to view products
        return True self.get_owner()
            if owner:
    def can_edit_products(self):('plan', 'starter')
        # Admin and manager roles or users with 'add' permission can edit products
        return not self.is_team_member or self.role in ["admin", "manager"] or "add" in self.permissions
        get_owner_id(self):
    def can_sell_products(self):if team member, or own id if business owner
        # All team members should be able to sell productselse self.id
        return True
        can_view_products(self):
    def can_view_reports(self):ld be able to view products
        return not self.is_team_member or "reports" in self.permissions or self.role in ["admin", "manager"]
        
    def can_manage_team(self):):
        # Only business owners can manage team members, not team members themselves
        return not self.is_team_member or self.role in ["admin", "manager"] or "add" in self.permissions
        
    def can_access_advanced_features(self):
        """Check if user's plan allows advanced features (professional or enterprise plans)"""
        effective_plan = self.get_effective_plan()
        return effective_plan in ['professional', 'enterprise']
    def can_view_reports(self):
@login_manager.user_loader_team_member or "reports" in self.permissions or self.role in ["admin", "manager"]
def load_user(user_id):
    user = user_collection.find_one({'_id': ObjectId(user_id)})
    return User(user) if user else Nonege team members, not team members themselves
        return not self.is_team_member
# Helper functions
def calculate_total_sales(user_id):s(self):
    total_sales = 0 user's plan allows advanced features (professional or enterprise plans)"""
    sales = sales_collection.find({"owner_id": user_id})
    for sale in sales:ve_plan in ['professional', 'enterprise']
        total_sales += sale.get("total_price", 0)
    return total_salesader
def load_user(user_id):
def validate_product_input(data):ne({'_id': ObjectId(user_id)})
    if not data.get("product_name") or not data.get("price") or not data.get("stock"):
        return False
    try: functions
        float(data["price"])er_id):
        int(data["stock"])
        return Trueollection.find({"owner_id": user_id})
    except (ValueError, TypeError):
        return False+= sale.get("total_price", 0)
    return total_sales
# Routes
# Home route (redirects to login or dashboard)
@app.route("/").get("product_name") or not data.get("price") or not data.get("stock"):
def home():urn False
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    else:nt(data["stock"])
        return render_template("home.html", pricing=pricing)
    except (ValueError, TypeError):
# Register routealse
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST": or dashboard)
        username = request.form["username"]
        password = request.form["password"]
        business_name = request.form["business_name"]
        email = request.form["email"]board"))
        phone = request.form["phone"]
        plan = request.form.get("plan", "starter")  # Default to starter if not specified

        if user_collection.find_one({"username": username}):
            flash("Username already exists!", "danger")
            return redirect(url_for("register"))
    if request.method == "POST":
        hashed_password = bcrypt.generate_password_hash(password).decode("utf-8")
        new_user = {equest.form["password"]
            "username": username,orm["business_name"]
            "password": hashed_password,
            "business_name": business_name,
            "email": email,.get("plan", "starter")  # Default to starter if not specified
            "phone": phone,
            "plan": plan,n.find_one({"username": username}):
            "registration_date": datetime.utcnow()ger")
        }   return redirect(url_for("register"))
        user_collection.insert_one(new_user)
        flash("Registration successful! Please log in.", "success")ecode("utf-8")
        return redirect(url_for("login"))
    return render_template("register.html", pricing=pricing)
            "password": hashed_password,
# Login routebusiness_name": business_name,
@app.route("/login", methods=["GET", "POST"])
def login():"phone": phone,
    if request.method == "POST":
        username = request.form["username"]tcnow()
        password = request.form["password"]
        user = user_collection.find_one({"username": username})
        if user and bcrypt.check_password_hash(user["password"], password):
            user_obj = User(user)login"))
            login_user(user_obj)ster.html", pricing=pricing)
            
            # Different welcome messages for team members vs owners
            if user_obj.is_team_member:OST"])
                # Get owner info for team member welcome message
                owner = user_collection.find_one({"_id": ObjectId(user_obj.parent_user_id)})
                owner_name = owner.get("business_name", "the business") if owner else "the business"
                flash(f"Welcome {username}! You are logged in as a {user_obj.role} for {owner_name}.", "success")
            else:er_collection.find_one({"username": username})
                flash(f"Welcome {user.get('business_name', username)}!", "success")
            user_obj = User(user)
            return redirect(url_for("dashboard"))
            
        flash("Invalid username or password!", "danger")s vs owners
        return redirect(url_for("login"))
    return render_template("login.html")m member welcome message
                owner = user_collection.find_one({"_id": ObjectId(user_obj.parent_user_id)})
# Logout route  owner_name = owner.get("business_name", "the business") if owner else "the business"
@app.route("/logout")(f"Welcome {username}! You are logged in as a {user_obj.role} for {owner_name}.", "success")
@login_requirede:
def logout():   flash(f"Welcome {user.get('business_name', username)}!", "success")
    logout_user()
    flash("You have been logged out.", "info")"))
    return redirect(url_for("home"))
        flash("Invalid username or password!", "danger")
@app.route('/profile', methods=['GET', 'POST'])
@login_requireder_template("login.html")
def profile():
    if request.method == 'POST':
        # Handle profile updates if needed
        passred
    logout():
    # Get the user's current plan details:
    plan_name = current_user.get_effective_plan()
    plan_details = current_user.get_plan_details()
    
    # Get actual product count=['GET', 'POST'])
    total_products = product_collection.count_documents({"owner_id": current_user.get_owner_id()})
    profile():
    # Get team members countST':
    team_members_count = user_collection.count_documents({"parent_user_id": current_user.get_owner_id()})
        pass
    # Get team members list for display
    team_members = list(user_collection.find({"parent_user_id": current_user.get_owner_id()}))
    plan_name = current_user.get_effective_plan()
    return render_template("profile.html", tails()
                          current_user=current_user, 
                          plan_name=plan_name, 
                          plan_details=plan_details,nts({"owner_id": current_user.get_owner_id()})
                          total_products=total_products,
                          team_members_count=team_members_count,
                          team_members=team_members,ents({"parent_user_id": current_user.get_owner_id()})
                          pricing=pricing)
    # Get team members list for display
# Dashboard route - updated to show the right products for team members_user.get_owner_id()}))
@app.route("/dashboard")
@login_requireder_template("profile.html", 
def dashboard():          current_user=current_user, 
    # Use the owner's ID for product queries (either the team member's parent or the current user)
    owner_id = current_user.get_owner_id()n_details,
                          total_products=total_products,
    total_products = product_collection.count_documents({"owner_id": owner_id})
    low_stock_products = list(product_collection.find({
        "owner_id": owner_id,cing=pricing)
        "$expr": {"$lte": ["$stock", "$low_stock_threshold"]}
    }))oard route - updated to show the right products for team members
    low_stock_count = len(low_stock_products)
    total_sales = calculate_total_sales(owner_id)
    recent_products = list(product_collection.find({"owner_id": owner_id}).sort("_id", -1).limit(10))
    # Use the owner's ID for product queries (either the team member's parent or the current user)
    # Add plan limit informationowner_id()
    plan_details = current_user.get_plan_details()
    product_limit = plan_details['products']t_documents({"owner_id": owner_id})
    product_usage_percent = (total_products / product_limit) * 100 if product_limit > 0 else 0
        "owner_id": owner_id,
    # Get team info if current user is a business ownerold"]}
    team_info = None
    if not current_user.is_team_member:ducts)
        team_members_count = user_collection.count_documents({"parent_user_id": current_user.id})
        team_info = { list(product_collection.find({"owner_id": owner_id}).sort("_id", -1).limit(10))
            "count": team_members_count,
            "limit": plan_details['users']
        }details = current_user.get_plan_details()
    product_limit = plan_details['products']
    return render_template("dashboard.html",  product_limit) * 100 if product_limit > 0 else 0
                        total_products=total_products, 
                        low_stock_count=low_stock_count, 
                        total_sales=total_sales, 
                        low_stock_products=low_stock_products, 
                        recent_products=recent_products, nts({"parent_user_id": current_user.id})
                        username=current_user.username,
                        product_limit=product_limit,
                        product_usage_percent=product_usage_percent,
                        team_info=team_info,
                        is_team_member=current_user.is_team_member)
    return render_template("dashboard.html", 
# Fix add_product route to use the correct owner_idts, 
@app.route("/add_product", methods=["GET", "POST"])ount, 
@login_required         total_sales=total_sales, 
@plan_required(feature='product_count')cts=low_stock_products, 
@role_required(permission="add")roducts=recent_products, 
def add_product():      username=current_user.username,
    if request.method == "POST":limit=product_limit,
        if not validate_product_input(request.form):t_usage_percent,
            flash("Invalid input data!", "danger")
            return redirect(url_for("add_product")).is_team_member)
        
        # Use the owner's ID to ensure products are properly associated
        owner_id = current_user.get_owner_id()ST"])
        equired
        product_data = {product_count')
            "product_name": request.form["product_name"],
            "description": request.form["description"],
            "price": float(request.form["price"]),
            "stock": int(request.form["stock"]),rm):
            "low_stock_threshold": int(request.form.get("low_stock_threshold", 5)),
            "owner_id": owner_id  # Use the owner_id instead of current_user.id
        }
        product_collection.insert_one(product_data) properly associated
        flash("Product added successfully!", "success")
        return redirect(url_for("view_products"))
    return render_template("add_product.html")
            "product_name": request.form["product_name"],
# Ensure view_products is using string comparison for IDs if needed
@app.route("/view_products")equest.form["price"]),
@login_requiredock": int(request.form["stock"]),
def view_products():ck_threshold": int(request.form.get("low_stock_threshold", 5)),
    if current_user.is_team_member and not current_user.can_view_products():.id
        flash("You don't have permission to view products.", "warning")
        return redirect(url_for("dashboard"))_data)
        flash("Product added successfully!", "success")
    owner_id = current_user.get_owner_id()ucts"))
    return render_template("add_product.html")
    # Add logging to debug the issue
    logger.info(f"Fetching products for owner_id: {owner_id}")eeded
    .route("/view_products")
    # Make sure we're querying with the correct type (string vs ObjectId)
    # If owner_id is a string but stored as ObjectId or vice versa, this could cause issues
    products = list(product_collection.find({"owner_id": owner_id}))ducts():
        flash("You don't have permission to view products.", "warning")
    logger.info(f"Found {len(products)} products")
    
    low_stock_products = [r.get_owner_id()
        product for product in products if product["stock"] <= product.get("low_stock_threshold", 5)
    ] Add logging to debug the issue
    logger.info(f"Fetching products for owner_id: {owner_id}")
    return render_template("view_products.html", 
                          products=products, ct type (string vs ObjectId)
                          low_stock_products=low_stock_products,sa, this could cause issues
                          can_edit=current_user.can_edit_products(),
                          can_sell=current_user.can_sell_products())
    logger.info(f"Found {len(products)} products")
# Fix edit_product route to use the correct owner_id for consistency
@app.route("/edit_product/<product_id>", methods=["GET", "POST"])
@login_required for product in products if product["stock"] <= product.get("low_stock_threshold", 5)
def edit_product(product_id):
    owner_id = current_user.get_owner_id()
    product = product_collection.find_one({"_id": ObjectId(product_id), "owner_id": owner_id})
                          products=products, 
    if not product:       low_stock_products=low_stock_products,
        flash("Product not found", "danger")ser.can_edit_products(),
        return redirect(url_for("view_products"))an_sell_products())

    if request.method == "POST":the correct owner_id for consistency
        if not validate_product_input(request.form):ET", "POST"])
            flash("Invalid input data!", "danger")
            return redirect(url_for("edit_product", product_id=product_id))
    owner_id = current_user.get_owner_id()
        product_collection.update_one(one({"_id": ObjectId(product_id), "owner_id": owner_id})
            {"_id": ObjectId(product_id)},
            {"$set": {
                "product_name": request.form["product_name"],
                "description": request.form["description"],
                "price": float(request.form["price"]),
                "stock": int(request.form["stock"]),
                "low_stock_threshold": int(request.form.get("low_stock_threshold", 5))
            }}ash("Invalid input data!", "danger")
        )   return redirect(url_for("edit_product", product_id=product_id))
        flash("Product updated successfully", "success")
        return redirect(url_for("view_products"))
            {"_id": ObjectId(product_id)},
    return render_template("edit_product.html", product=product)
                "product_name": request.form["product_name"],
# Sell product routecription": request.form["description"],
@app.route("/sell_product/<product_id>", methods=["POST"])
@login_required "stock": int(request.form["stock"]),
def sell_product(product_id):reshold": int(request.form.get("low_stock_threshold", 5))
    try:    }}
        # Get the owner ID for proper product lookup
        owner_id = current_user.get_owner_id()"success")
        return redirect(url_for("view_products"))
        # Add logging for debugging
        logger.info(f"Processing sell for product ID: {product_id}, owner ID: {owner_id}")
        
        # Use ObjectId for product lookup when the field is an ObjectId in MongoDB
        product = product_collection.find_one({"_id": ObjectId(product_id), "owner_id": owner_id})
        equired
        if not product:t_id):
            logger.warning(f"Product not found for ID: {product_id}, owner ID: {owner_id}")
            flash("Product not found!", "danger")kup
            return redirect(url_for("view_products"))
        
        # Get quantity from form data
        quantity_sold = int(request.form["quantity"]) {product_id}, owner ID: {owner_id}")
        logger.info(f"Selling {quantity_sold} units of '{product['product_name']}'")
        # Use ObjectId for product lookup when the field is an ObjectId in MongoDB
        if quantity_sold <= 0:ection.find_one({"_id": ObjectId(product_id), "owner_id": owner_id})
            flash("Invalid quantity!", "danger")
            return redirect(url_for("view_products"))
            logger.warning(f"Product not found for ID: {product_id}, owner ID: {owner_id}")
        if quantity_sold > product["stock"]:ger")
            flash(f"Not enough stock! Only {product['stock']} available.", "danger")
            return redirect(url_for("view_products"))
        # Get quantity from form data
        # Calculate sale detailsest.form["quantity"])
        total_price = quantity_sold * product["price"] '{product['product_name']}'")
        
        # Record the sale<= 0:
        sale_record = {lid quantity!", "danger")
            "product_id": str(product_id),  # Store as string for consistency
            "owner_id": owner_id,
            "seller_id": current_user.id,"]:
            "seller_name": current_user.username,ct['stock']} available.", "danger")
            "product_name": product["product_name"],)
            "quantity_sold": quantity_sold,
            "total_price": total_price,
            "date_sold": datetime.utcnow()uct["price"]
        }
        sales_collection.insert_one(sale_record)
        sale_record = {
        # Update product stockproduct_id),  # Store as string for consistency
        new_stock = product["stock"] - quantity_sold
        product_collection.update_one(id,
            {"_id": ObjectId(product_id)},ername,
            {"$set": {"stock": new_stock}}ct_name"],
        )   "quantity_sold": quantity_sold,
            "total_price": total_price,
        # Notify based on inventory status
        if new_stock == 0:
            flash(f"Product '{product['product_name']}' is now out of stock!", "warning")
        elif new_stock <= product.get("low_stock_threshold", 5):
            flash(f"Warning! '{product['product_name']}' is low on stock ({new_stock} left).", "warning")
        new_stock = product["stock"] - quantity_sold
        flash(f"Sale of {quantity_sold} {product['product_name']} recorded successfully! Total: ₹{total_price}", "success")
    except ValueError:jectId(product_id)},
        flash("Invalid input. Please enter a valid quantity.", "danger")
    except Exception as e:
        logger.error(f"Error selling product: {str(e)}")
        flash(f"An error occurred: {str(e)}", "danger")
        if new_stock == 0:
    return redirect(url_for("view_products"))t_name']}' is now out of stock!", "warning")
        elif new_stock <= product.get("low_stock_threshold", 5):
# Export sales routeWarning! '{product['product_name']}' is low on stock ({new_stock} left).", "warning")
@app.route("/export_sales")
@login_required"Sale of {quantity_sold} {product['product_name']} recorded successfully! Total: ₹{total_price}", "success")
def export_sales(): r:
    sales = list(sales_collection.find({"owner_id": current_user.id}))")
    user_profile = user_collection.find_one({"_id": ObjectId(current_user.id)})
    business_name = user_profile["business_name"] if user_profile and "business_name" in user_profile else "Your Business"
    export_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
    # Add plan information to exportoducts"))
    plan_name = current_user.get_effective_plan().capitalize()
# Export sales route
    def generate_csv():es")
        output = StringIO()
        csv_writer = csv.writer(output)
        csv_writer.writerow([f"Business Name: {business_name} | Plan: {plan_name}"])
        csv_writer.writerow([f"Exported On: {export_time}"])(current_user.id)})
        csv_writer.writerow([])e["business_name"] if user_profile and "business_name" in user_profile else "Your Business"
        csv_writer.writerow(["Product Name", "Quantity Sold", "Total Price", "Date Sold"])
        csv_writer.writerow(["Signed By: ", "Shaswat"])
        for sale in sales: to export
            date_sold = sale.get("date_sold", "").capitalize()
            if isinstance(date_sold, datetime):
                date_sold = date_sold.strftime("%Y-%m-%d %H:%M:%S")
            csv_writer.writerow([
                sale.get("product_name", "N/A"),
                sale.get("quantity_sold", 0), {business_name} | Plan: {plan_name}"])
                f"₹{sale.get('total_price', 0.00):.2f}",}"])
                date_soldow([])
            ])iter.writerow(["Product Name", "Quantity Sold", "Total Price", "Date Sold"])
        output.seek(0) erow(["Signed By: ", "Shaswat"])
        return output.read()
            date_sold = sale.get("date_sold", "")
    response = Response(generate_csv(), content_type="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename=sales_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return responseter.writerow([
                sale.get("product_name", "N/A"),
# Enhanced product sales route with more robust handling of data
@app.route("/product_sales/<product_id>")', 0.00):.2f}",
@login_required date_sold
def product_sales(product_id):
    owner_id = current_user.get_owner_id()
    product = product_collection.find_one({"_id": ObjectId(product_id), "owner_id": owner_id})
    
    if not product:onse(generate_csv(), content_type="text/csv")
        flash("Product not found!", "danger") f"attachment; filename=sales_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        return redirect(url_for("view_products"))
    
    # Check effective plan permissions - only Professional and Enterprise plans get full analytics
    effective_plan = current_user.get_effective_plan()
    plan_details = current_user.get_plan_details()
    basic_analytics_only = effective_plan == 'starter'
    owner_id = current_user.get_owner_id()
    # For starter plan, provide only basic info": ObjectId(product_id), "owner_id": owner_id})
    total_sales = 0
    total_quantity = 0
    total_revenue = 0t not found!", "danger")
    chart_dates = []ect(url_for("view_products"))
    chart_quantities = []
    chart_revenues = []sions - only Professional and Enterprise plans get full analytics
    sales = []= current_user.get_effective_plan()
    plan_details = current_user.get_plan_details()
    # Always fetch basic stats for all plansrter'
    try:
        # Get all sales for this productic info
        sales_cursor = sales_collection.find({
            "product_id": str(product_id),
            "owner_id": owner_id
        })dates = []
        t_quantities = []
        # Calculate basic statistics that are available to all plans
        if sales_cursor:
            sales = list(sales_cursor)
            total_sales = len(sales)ll plans
            total_quantity = sum(sale.get("quantity_sold", 0) for sale in sales)
            total_revenue = sum(sale.get("total_price", 0) for sale in sales)
            s_cursor = sales_collection.find({
        # Advanced analytics only for professional and enterprise plans
        if not basic_analytics_only:
            # Format dates for chart display and process data for advanced charts
            chart_data = {}
            if sales:asic statistics that are available to all plans
                for sale in sales:
                    if "date_sold" in sale:
                        if isinstance(sale["date_sold"], datetime):
                            date_str = sale["date_sold"].strftime("%Y-%m-%d")es)
                        else:um(sale.get("total_price", 0) for sale in sales)
                            try:
                                date_str = datetime.fromisoformat(str(sale["date_sold"])).strftime("%Y-%m-%d")
                            except (ValueError, TypeError):
                                date_str = "Unknown Date"data for advanced charts
                         {}
                        if date_str not in chart_data:
                            chart_data[date_str] = {"quantity": 0, "revenue": 0}
                        chart_data[date_str]["quantity"] += sale.get("quantity_sold", 0)
                        chart_data[date_str]["revenue"] += sale.get("total_price", 0)
                            date_str = sale["date_sold"].strftime("%Y-%m-%d")
                # Sort by date
                chart_dates = sorted(chart_data.keys())
                chart_quantities = [chart_data[date]["quantity"] for date in chart_dates].strftime("%Y-%m-%d")
                chart_revenues = [chart_data[date]["revenue"] for date in chart_dates]
                                date_str = "Unknown Date"
    except Exception as e:
        logger.error(f"Error generating product sales data: {str(e)}")
        flash("An error occurred retrieving sales data.", "danger")"revenue": 0}
        return redirect(url_for("view_products"))ntity"] += sale.get("quantity_sold", 0)
                        chart_data[date_str]["revenue"] += sale.get("total_price", 0)
    # If team member, add owner information for display
    owner_info = None
    if current_user.is_team_member:art_data.keys())
        owner = current_user.get_owner()e]["quantity"] for date in chart_dates]
        if owner:nue"] for date in chart_dates]
            owner_info = {
                'business_name': owner.get('business_name', 'Your Business'),
                'plan': owner.get('plan', 'starter'){str(e)}")
            }, "danger")
    
    return render_template("product_sales.html", 
                          product=product,
                          sales=sales, 
                          total_sales=total_sales,                          sales=sales, 
                          total_quantity=total_quantity,       total_sales=total_sales,
                          total_revenue=total_revenue,y,
                          chart_dates=chart_dates,           total_revenue=total_revenue,
                          chart_quantities=chart_quantities, chart_dates=chart_dates,
                          chart_revenues=chart_revenues,
                          basic_analytics_only=basic_analytics_only,evenues=chart_revenues,
                          plan_name=effective_plan,only=basic_analytics_only,
                          plan_details=plan_details,                 plan_name=plan_name,
                          pricing=pricing,
                          owner_info=owner_info,
                          is_team_member=current_user.is_team_member)

# Delete sale routeST"])
@app.route("/delete_sale/<sale_id>", methods=["POST"])
@login_required):
def delete_sale(sale_id):id), "owner_id": current_user.id})
    result = sales_collection.delete_one({"_id": ObjectId(sale_id), "owner_id": current_user.id})
    if result.deleted_count == 0:
        flash("Sale not found!", "danger")    else:
    else:
        flash("Sale deleted successfully!", "success")url_for("view_sales"))
    return redirect(url_for("view_sales"))
s route
# Delete all sales route
@app.route("/delete_all_sales", methods=["POST"])
@login_required
def delete_all_sales(): current_user.id})
    sales_collection.delete_many({"owner_id": current_user.id})h("All sales records have been deleted!", "warning")
    flash("All sales records have been deleted!", "warning")
    return redirect(url_for("view_sales"))
x the view_sales route to properly handle team members
# Fix the view_sales route to properly handle team members
@app.route("/sales")
@login_required
def view_sales():am members, check if they have permission to view sales
    # For team members, check if they have permission to view salesn_view_reports():
    if current_user.is_team_member and not current_user.can_view_reports():        flash("You don't have permission to view sales records.", "warning")
        flash("You don't have permission to view sales records.", "warning")t(url_for("dashboard"))
        return redirect(url_for("dashboard"))
        current_user.get_owner_id()
    owner_id = current_user.get_owner_id()on.find({"owner_id": owner_id}).sort("date_sold", -1))
    sales = list(sales_collection.find({"owner_id": owner_id}).sort("date_sold", -1))
    
    for sale in sales::
        if isinstance(sale["date_sold"], str):   sale["date_sold"] = datetime.strptime(sale["date_sold"], "%Y-%m-%d %H:%M:%S")
            sale["date_sold"] = datetime.strptime(sale["date_sold"], "%Y-%m-%d %H:%M:%S")
             sales=sales)
    return render_template("view_sales.html", sales=sales)
t route
# Delete product route
@app.route("/delete_product/<product_id>")
@login_requiredduct(product_id):
def delete_product(product_id):"_id": ObjectId(product_id), "owner_id": current_user.id})
    result = product_collection.delete_one({"_id": ObjectId(product_id), "owner_id": current_user.id})
    if result.deleted_count == 0:    flash("Product not found!", "danger")
        flash("Product not found!", "danger")
    else:
        flash("Product deleted successfully!", "success")
    return redirect(url_for("view_products"))
# Billing route
# Billing route
@app.route("/billing", methods=["GET", "POST"])
@login_required
def billing():    # Get owner_id for proper product access
    # Get owner_id for proper product accessrent_user.get_owner_id()
    owner_id = current_user.get_owner_id()
    
    if request.method == "POST":_name = request.form.get("customer_name")
        customer_name = request.form.get("customer_name")
        selected_items = request.form.getlist("selected_items")
        quantities = request.form.getlist("quantities")
quantities:
        if not customer_name or not selected_items or not quantities:")
            flash("Please fill in all fields!", "danger")            return redirect(url_for("billing"))
            return redirect(url_for("billing"))

        items = []
        total_price = 0antities):
        for item_id, quantity in zip(selected_items, quantities):            try:
            try: just the current user's id
                # Use the owner_id to find products, not just the current user's ido.db.products.find_one({"_id": ObjectId(item_id), "owner_id": owner_id})
                product = mongo.db.products.find_one({"_id": ObjectId(item_id), "owner_id": owner_id})
                if not product:ound!", "danger")
                    flash(f"Product not found!", "danger")illing"))
                    return redirect(url_for("billing"))
antity = int(quantity)
                quantity = int(quantity)ity > product["stock"]:
                if quantity <= 0 or quantity > product["stock"]:                    flash(f"Invalid quantity for {product['product_name']}!", "danger")
                    flash(f"Invalid quantity for {product['product_name']}!", "danger")
                    return redirect(url_for("billing"))
e"] * quantity
                item_total = product["price"] * quantity
                items.append({
                    "product_name": product["product_name"],
                    "quantity": quantity,
                    "price": product["price"],
                    "total": item_total
                })
                total_price += item_total
Record sale with the owner's ID for proper tracking
                # Record sale with the owner's ID for proper trackingsales_collection.insert_one({
                sales_collection.insert_one({
                    "product_id": item_id,e owner_id instead of current_user.id
                    "owner_id": owner_id,  # Use owner_id instead of current_user.idso track who made the sale
                    "seller_id": current_user.id,  # Also track who made the sale   "seller_name": current_user.username,
                    "seller_name": current_user.username,: product["product_name"],
                    "product_name": product["product_name"],
                    "quantity_sold": quantity,
                    "total_price": item_total,                    "date_sold": datetime.utcnow(),
                    "date_sold": datetime.utcnow(),e": customer_name,
                    "customer_name": customer_name,
                })
                (
                mongo.db.products.update_one(
                    {"_id": ObjectId(item_id)},           {"$inc": {"stock": -int(quantity)}}
                    {"$inc": {"stock": -int(quantity)}}        )
                )
            except Exception as e:
                flash(f"An error occurred: {str(e)}", "danger")            return redirect(url_for("billing"))
                return redirect(url_for("billing"))

        # Add billing info to PDF
        business_info = {            "name": current_user.business_name,
            "name": current_user.business_name,ent_user.username,
            "seller": current_user.username,role if current_user.is_team_member else "Owner"
            "role": current_user.role if current_user.is_team_member else "Owner"
        }
        bill(customer_name, items, total_price, business_info)
        pdf_buffer = generate_pdf_bill(customer_name, items, total_price, business_info)name="bill.pdf", mimetype="application/pdf")
        return send_file(pdf_buffer, as_attachment=True, download_name="bill.pdf", mimetype="application/pdf")
        # Show products from the owner for team members
    # Show products from the owner for team members.products.find({"owner_id": owner_id}))
    products = list(mongo.db.products.find({"owner_id": owner_id}))
    return render_template("billing.html", products=products)

# Add page number functionmber(canvas, doc):
def add_page_number(canvas, doc):
    canvas.saveState()etPageNumber()
    page_num = canvas.getPageNumber()lvetica', 9)
    canvas.setFont('Helvetica', 9)tring(letter[0] - 72, 30, f"Page {page_num}")
    canvas.drawRightString(letter[0] - 72, 30, f"Page {page_num}")()
    canvas.restoreState()

# Generate PDF bill function, total_price, business_info):
def generate_pdf_bill(customer_name, items, total_price, business_info):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,ter,
        pagesize=letter,72,
        rightMargin=72,
        leftMargin=72,,
        topMargin=72,  bottomMargin=72
        bottomMargin=72
    )()
    styles = getSampleStyleSheet()r the invoice
    # Define custom styles for the invoiceraphStyle(
    styles.add(ParagraphStyle(eHeader',
        name='InvoiceHeader',
        fontName='Helvetica-Bold',
        fontSize=20,  alignment=1,
        alignment=1,lor("#333333"),
        textColor=colors.HexColor("#333333"),
        spaceAfter=6
    ))raphStyle(
    styles.add(ParagraphStyle(
        name='InvoiceSubHeader',elvetica',
        fontName='Helvetica',  fontSize=12,
        fontSize=12,
        alignment=1,HexColor("#555555"),
        textColor=colors.HexColor("#555555"),
        spaceAfter=10
    ))
    styles.add(ParagraphStyle(Header',
        name='TableHeader',  fontName='Helvetica-Bold',
        fontName='Helvetica-Bold',
        fontSize=10,rs.whitesmoke,
        textColor=colors.whitesmoke,
        alignment=1
    ))
    styles.add(ParagraphStyle(Cell',
        name='TableCell',  fontName='Helvetica',
        fontName='Helvetica',    fontSize=10,
        fontSize=10,r=colors.black,
        textColor=colors.black,
        alignment=1
    ))dd(ParagraphStyle(
    styles.add(ParagraphStyle(='Footer',
        name='Footer',
        fontName='Helvetica',
        fontSize=10,66"),
        textColor=colors.HexColor("#666666"),
        alignment=1
    ))
    
    content = []# Company Logo and Header
    # Company Logo and Header
    logo = "logo.png"
    if logo:
        try:logo, width=2*inch, height=1*inch)
            company_logo = Image(logo, width=2*inch, height=1*inch)        company_logo.hAlign = 'CENTER'
            company_logo.hAlign = 'CENTER'pend(company_logo)
            content.append(company_logo)
        except Exception as e:t found: %s", e)
            logger.error("Logo not found: %s", e)content.append(Paragraph("Inventory Manager Invoice", styles['InvoiceHeader']))
    content.append(Paragraph("Inventory Manager Invoice", styles['InvoiceHeader']))etime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['InvoiceSubHeader']))
    content.append(Paragraph(f"Invoice Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['InvoiceSubHeader']))
    er information
    # Add seller informationbusiness_info['name']}", styles['Normal']))
    content.append(Paragraph(f"<b>Business:</b> {business_info['name']}", styles['Normal']))ess_info['seller']} ({business_info['role']})", styles['Normal']))
    content.append(Paragraph(f"<b>Sale by:</b> {business_info['seller']} ({business_info['role']})", styles['Normal']))
    content.append(Spacer(1, 12))
     Customer Details
    # Customer Detailsf"<b>Customer:</b> {customer_name}", styles['Normal']))
    content.append(Paragraph(f"<b>Customer:</b> {customer_name}", styles['Normal']))
    content.append(Spacer(1, 12))
    
    # Table Data with alternating row backgrounds
    table_data = []
    header = [
        Paragraph("Item", styles['TableHeader']),aragraph("Quantity", styles['TableHeader']),
        Paragraph("Quantity", styles['TableHeader']),les['TableHeader']),
        Paragraph("Price", styles['TableHeader']),    Paragraph("Total", styles['TableHeader'])
        Paragraph("Total", styles['TableHeader'])
    ]
    table_data.append(header)
    for idx, item in enumerate(items):
        row = [styles['TableCell']),
            Paragraph(item["product_name"], styles['TableCell']),ableCell']),
            Paragraph(str(item["quantity"]), styles['TableCell']),.2f}", styles['TableCell']),
            Paragraph(f"${item['price']:.2f}", styles['TableCell']),, styles['TableCell'])
            Paragraph(f"${item['total']:.2f}", styles['TableCell'])
        ]
        table_data.append(row)
    ata, colWidths=[3 * inch, 1 * inch, 1 * inch, 1 * inch])
    table = Table(table_data, colWidths=[3 * inch, 1 * inch, 1 * inch, 1 * inch])
    table.setStyle(TableStyle([    ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#333333")),
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#333333")),0), (-1,0), colors.whitesmoke),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),), 'Helvetica-Bold'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),    ('FONTSIZE', (0,0), (-1,0), 10),
        ('FONTSIZE', (0,0), (-1,0), 10),-1,0), 12),
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),OUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.lavender])
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.lavender])
    ]))
    content.append(table)
    content.append(Spacer(1, 24))
    
    # Total Price Sectione:</b> ${total_price:.2f}", styles['InvoiceSubHeader']))
    content.append(Paragraph(f"<b>Total Price:</b> ${total_price:.2f}", styles['InvoiceSubHeader']))ntent.append(Spacer(1, 24))
    content.append(Spacer(1, 24))
    
    # Payment Instructions Sectioncontent.append(Paragraph("Payment Instructions:", styles['InvoiceSubHeader']))
    content.append(Paragraph("Payment Instructions:", styles['InvoiceSubHeader']))
    for detail in [l amount to the following bank account:",
        "Please transfer the total amount to the following bank account:",,
        "Bank Name: ABC Bank",r",
        "Account Name: Inventory Manager",
        "Account Number: 1234 5678 9012 3456",
        "SWIFT Code: ABCDEFGH",
        "Thank you for your prompt payment!"
    ]:  content.append(Paragraph(detail, styles['Normal']))
        content.append(Paragraph(detail, styles['Normal']))    content.append(Spacer(1, 6))
        content.append(Spacer(1, 6))
    contact details
    # Footer with contact detailsd(Spacer(1, 36))
    content.append(Spacer(1, 36))    content.append(Paragraph(
    content.append(Paragraph(entory Manager</b><br/>"
        "<b>Inventory Manager</b><br/>">"
        "123 Business Street, City, Country<br/>": +123 456 7890 | Email: info@inventorymanager.com<br/>"
        "Phone: +123 456 7890 | Email: info@inventorymanager.com<br/>"anager.com",
        "Website: www.inventorymanager.com",
        styles['Footer']
    ))
    umber, onLaterPages=add_page_number)
    doc.build(content, onFirstPage=add_page_number, onLaterPages=add_page_number)
    buffer.seek(0)
    return buffer

# Contact routeST"])
@app.route("/contact", methods=["GET", "POST"])def contact():
def contact():POST":
    if request.method == "POST":orm.get('name')
        name = request.form.get('name') request.form.get('email')
        email = request.form.get('email')
        message = request.form.get('message')= request.form.get('company')
        company = request.form.get('company')# Here you would typically save the contact request to a database
        # Here you would typically save the contact request to a database
        # or send an email notification
        flash('Thanks for contacting us! We will get back to you soon.', 'success')
        return redirect(url_for('contact'))html')
    return render_template('contact.html')

# Advanced Analytics route
@app.route("/analytics")
@login_requiredess
@rate_limit(limit=10)  # apply rate limiting to analytics access
def analytics():
    try:ulate_total_sales(current_user.id)
        total_sales = calculate_total_sales(current_user.id)ount_documents({"owner_id": current_user.id})
        total_products = product_collection.count_documents({"owner_id": current_user.id})ner_id": current_user.id}))
        sales_data = list(sales_collection.find({"owner_id": current_user.id}))
        # Compute average sale value        count = len(sales_data)
        count = len(sales_data)
        avg_sale = total_sales/count if count > 0 else 0nt_user.username} accessed analytics.")
        logger.info(f"User {current_user.username} accessed analytics.")render_template("analytics.html", total_sales=total_sales,
        return render_template("analytics.html", total_sales=total_sales,=total_products,
                               total_products=total_products,      avg_sale=avg_sale,
                               avg_sale=avg_sale,
                               sales_count=count)
    except Exception as e:        logger.error(f"Analytics error: {e}")
        logger.error(f"Analytics error: {e}")
        flash("Failed to load analytics.", "danger")
        return redirect(url_for("dashboard"))
ced analytics that requires Professional plan
# Add a new route for advanced analytics that requires Professional plan)
@app.route("/advanced-analytics")
@login_required')
@plan_required(min_plan_level='professional')advanced_analytics():
def advanced_analytics():cs only available to Professional and Enterprise users
    # This would implement more sophisticated analytics only available to Professional and Enterprise usersrn render_template("advanced_analytics.html")
    return render_template("advanced_analytics.html")
essing
# Enhanced change plan route with simulated payment processing['POST'])
@app.route('/change_plan/<plan_name>', methods=['POST'])
@login_required
def change_plan(plan_name):
    if plan_name not in pricing:
        flash("Invalid plan selected!", "danger")
        return redirect(url_for("profile"))
    e payment processing (for demo purposes)
    # Simulate payment processing (for demo purposes)
    try:upgrading to higher tiers, simulate a charge
        # For example, if upgrading to higher tiers, simulate a charge
        current_plan = current_user.get_effective_plan()
        new_price = pricing[plan_name]['price']n]['price']
        current_price = pricing[current_plan]['price']    if new_price > current_price:
        if new_price > current_price:yment success
            # Simulate processing fee and payment successssing payment for user {current_user.username}: {current_price} -> {new_price}")
            logger.info(f"Processing payment for user {current_user.username}: {current_price} -> {new_price}")ion("Payment failed.") in real code
            # If payment fails raise Exception("Payment failed.") in real codesuccessfully!", "success")
            flash("Payment processed successfully!", "success")   else:
        else:
            flash("Plan downgraded successfully.", "info")
    except Exception as e:        logger.error(f"Payment error for user {current_user.username}: {e}")
        logger.error(f"Payment error for user {current_user.username}: {e}")ng failed. Please try again.", "danger")
        flash("Payment processing failed. Please try again.", "danger")
        return redirect(url_for("profile"))
    s plan in the database
    # Update the user's plan in the database
    user_collection.update_one(er.id)},
        {"_id": ObjectId(current_user.id)},
        {"$set": {"plan": plan_name}}
    )flash(f"Your plan has been updated to {plan_name.capitalize()}!", "success")
    flash(f"Your plan has been updated to {plan_name.capitalize()}!", "success")
    return redirect(url_for("profile"))

# Team Member Management routesOST"])
@app.route("/add_team_member", methods=["GET", "POST"])in_required
@login_required
def add_team_member():
    # Only business owners can add team membersif current_user.is_team_member:
    if current_user.is_team_member:can add team members.", "warning")
        flash("Only business owners can add team members.", "warning")
        return redirect(url_for("dashboard"))
    ess owner
    # Get current user count for this business ownercurrent_user_count = user_collection.count_documents({"parent_user_id": current_user.id})
    current_user_count = user_collection.count_documents({"parent_user_id": current_user.id})get_plan_details()
    plan_details = current_user.get_plan_details()()
    plan_name = current_user.get_effective_plan()
    
    # Get total product count for the user_id": current_user.id})
    total_products = product_collection.count_documents({"owner_id": current_user.id})
    
    # Check if user limit is reachedurrent_user_count >= plan_details['users']:
    if current_user_count >= plan_details['users']:ched the maximum number of users for your plan. Please upgrade to add more team members.", "warning")
        flash("You've reached the maximum number of users for your plan. Please upgrade to add more team members.", "warning")
        return redirect(url_for('profile'))
    
    if request.method == "POST":name = request.form.get("username")
        username = request.form.get("username"))
        email = request.form.get("email")
        password = request.form.get("password")ssword")
        confirm_password = request.form.get("confirm_password") = request.form.get("role", "staff")
        role = request.form.get("role", "staff")("permissions[]")
        permissions = request.form.getlist("permissions[]")
        
        # Validate inputs
        if not username or not email or not password:flash("Please fill in all required fields", "danger")
            flash("Please fill in all required fields", "danger")for("add_team_member"))
            return redirect(url_for("add_team_member"))
            != confirm_password:
        if password != confirm_password:t match", "danger")
            flash("Passwords don't match", "danger")(url_for("add_team_member"))
            return redirect(url_for("add_team_member"))
            
        # Check if username already existse}):
        if user_collection.find_one({"username": username}):me already exists", "danger")
            flash("Username already exists", "danger")d_team_member"))
            return redirect(url_for("add_team_member"))
            
        # Create new team memberashed_password = bcrypt.generate_password_hash(password).decode("utf-8")
        hashed_password = bcrypt.generate_password_hash(password).decode("utf-8")new_user = {
        new_user = {
            "username": username,
            "email": email,
            "password": hashed_password,    "parent_user_id": current_user.id,  # Link to the business owner
            "parent_user_id": current_user.id,  # Link to the business ownerser.business_name,
            "business_name": current_user.business_name,ole,
            "role": role,ons,
            "permissions": permissions,
            "plan": "team_member",  # Special designation for team members
            "registration_date": datetime.utcnow()
        }
        
        user_collection.insert_one(new_user)cess")
        flash(f"Team member {username} added successfully!", "success")
        return redirect(url_for("manage_team"))
         owner information to display
    # Get owner information to display
    owner_info = None_team_member:
    if current_user.is_team_member:m member, show the business owner
        # If team member is adding another team member, show the business ownerId(current_user.parent_user_id)})
        parent = user_collection.find_one({"_id": ObjectId(current_user.parent_user_id)})
        if parent:   owner_info = {
            owner_info = {            "username": parent.get("username", ""),
                "username": parent.get("username", ""),siness_name", ""),
                "business_name": parent.get("business_name", ""),
                "email": parent.get("email", "")        }
            }
    else: is adding team member
        # Business owner is adding team member
        owner_info = {er.username,
            "username": current_user.username, current_user.business_name,
            "business_name": current_user.business_name,l
            "email": current_user.email
        }
     Also get existing team members to display
    # Also get existing team members to display    existing_team_members = list(user_collection.find({"parent_user_id": current_user.get_owner_id()}))
    existing_team_members = list(user_collection.find({"parent_user_id": current_user.get_owner_id()}))
    er_template(
    return render_template(html",
        "add_user.html",unt,
        current_user_count=current_user_count,
        plan_details=plan_details,
        plan_name=plan_name,
        total_products=total_products,    existing_team_members=existing_team_members,
        existing_team_members=existing_team_members,
        owner_info=owner_info
    )

@app.route("/manage_team")in_required
@login_required
def manage_team():can manage team
    # Only business owners can manage team:
    if current_user.is_team_member:s can manage team members.", "warning")
        flash("Only business owners can manage team members.", "warning")
        return redirect(url_for("dashboard"))
    wner
    # Get all team members for this business ownerirectly since only owners can access this route
    owner_id = current_user.id  # Use current_user.id directly since only owners can access this routeembers = list(user_collection.find({"parent_user_id": owner_id}))
    team_members = list(user_collection.find({"parent_user_id": owner_id}))
    plan_details = current_user.get_plan_details()
        return render_template(
    return render_template(
        "manage_team.html",mbers=team_members,
        team_members=team_members,s,
        plan_details=plan_details,),
        plan_name=current_user.get_effective_plan(),
        owner_info={
            "username": current_user.username,iness_name
            "business_name": current_user.business_name},
        },ince we're restricting access to owners
        is_team_member=False  # Will always be false since we're restricting access to owners
    )
", methods=["POST"])
@app.route("/delete_team_member/<user_id>", methods=["POST"])_required
@login_requireddelete_team_member(user_id):
def delete_team_member(user_id):ers can delete team members
    # Only business owners can delete team members
    if current_user.is_team_member:team members.", "warning")
        flash("Only business owners can manage team members.", "warning")return redirect(url_for("dashboard"))
        return redirect(url_for("dashboard"))
        
    # Check if the team member belongs to current user
    team_member = user_collection.find_one({
        "_id": ObjectId(user_id),        "parent_user_id": current_user.id
        "parent_user_id": current_user.id
    })
    
    if not team_member:ber not found!", "danger")












    app.run(debug=True)    logger.info("Starting Inventory Manager application")if __name__ == "__main__":# Run the app    return redirect(url_for("manage_team"))    flash("Team member removed successfully!", "success")    user_collection.delete_one({"_id": ObjectId(user_id)})    # Delete the team member                return redirect(url_for("manage_team"))        flash("Team member not found!", "danger")        return redirect(url_for("manage_team"))
        
    # Delete the team member
    user_collection.delete_one({"_id": ObjectId(user_id)})
    flash("Team member removed successfully!", "success")
    return redirect(url_for("manage_team"))

# Run the app
if __name__ == "__main__":
    logger.info("Starting Inventory Manager application")
    app.run(debug=True)
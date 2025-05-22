# AI Predictions Module
from datetime import datetime, timedelta
import numpy as np
from collections import defaultdict

def predict_restock_time(product, sales_data, days_to_predict=30):
    """
    Predict when a product will need to be restocked based on sales history.
    
    Args:
        product (dict): The product document from the database
        sales_data (list): List of sales records for this product
        days_to_predict (int): Number of days to look ahead in prediction
        
    Returns:
        dict: Prediction results including days_until_restock, sales_velocity, etc.
    """
    if not sales_data or len(sales_data) < 2:
        return {
            "prediction_possible": False,
            "message": "Not enough sales data for prediction",
            "sales_velocity": 0,
            "days_until_restock": None,
            "confidence": 0,
            "suggestion": "Check back after recording more sales"
        }
    
    # Sort sales by date
    sorted_sales = sorted(sales_data, key=lambda x: x['date_sold'])
    
    # Calculate the total period over which we have data
    first_sale_date = sorted_sales[0]['date_sold']
    last_sale_date = sorted_sales[-1]['date_sold']
    
    # If all sales are on the same day, we can't calculate a meaningful velocity
    if isinstance(first_sale_date, datetime) and isinstance(last_sale_date, datetime):
        days_elapsed = max(1, (last_sale_date - first_sale_date).days)
    else:
        days_elapsed = 30  # Default to 30 days if dates are not datetime objects
    
    # Calculate quantities sold
    total_quantity_sold = sum(sale['quantity_sold'] for sale in sales_data)
    
    # Calculate sales velocity (units per day)
    sales_velocity = total_quantity_sold / days_elapsed
    
    # If sales velocity is zero or very small, provide a default message
    if sales_velocity < 0.01:
        return {
            "prediction_possible": False,
            "message": "Sales are too infrequent for accurate prediction",
            "sales_velocity": sales_velocity,
            "days_until_restock": 999,  # Very large number to indicate "a long time"
            "confidence": 0,
            "suggestion": "Product selling very slowly"
        }
    
    # Calculate days until we reach the low stock threshold or run out completely
    current_stock = product['stock']
    low_stock_threshold = product.get('low_stock_threshold', 5)
    
    # Days until we hit the low stock threshold
    days_until_low = max(0, (current_stock - low_stock_threshold) / sales_velocity)
    
    # Days until we run out completely
    days_until_empty = current_stock / sales_velocity
    
    # Calculate confidence based on data quality
    # Factors: number of sales records, recency of sales, consistency in sales pattern
    data_points = len(sales_data)
    
    # Calculate variance in daily sales to measure consistency
    daily_sales = defaultdict(int)
    for sale in sorted_sales:
        sale_date = sale['date_sold']
        if isinstance(sale_date, datetime):
            date_key = sale_date.strftime('%Y-%m-%d')
        else:
            date_key = str(sale_date)
        daily_sales[date_key] += sale['quantity_sold']
    
    # Calculate variance if we have enough data
    if len(daily_sales) > 1:
        values = list(daily_sales.values())
        variance = np.var(values) / (np.mean(values) or 1)  # Normalized variance
        consistency_factor = 1 / (1 + variance)  # Higher variance = lower consistency
    else:
        consistency_factor = 0.5  # Default if we don't have enough data
    
    # Factor in recency - more weight to recent sales
    if isinstance(last_sale_date, datetime):
        days_since_last_sale = (datetime.now() - last_sale_date).days
        recency_factor = max(0, 1 - (days_since_last_sale / 30))  # Decay over 30 days
    else:
        recency_factor = 0.5  # Default if dates are not datetime objects
        
    # Combine factors for overall confidence
    data_volume_factor = min(1, data_points / 10)  # Scale up to 1.0 with 10+ data points
    confidence = (data_volume_factor * 0.4 + consistency_factor * 0.4 + recency_factor * 0.2) * 100
    
    # Determine a good time to restock based on lead time estimate (default: 7 days)
    lead_time = 7  # Default assumption for restock delivery time
    ideal_restock_time = max(0, days_until_low - lead_time)
    
    # Generate prediction message
    if days_until_low <= 0:
        message = "Product is already below low stock threshold! Reorder immediately."
        suggestion = "Reorder now - product stock critical"
    elif days_until_low <= lead_time:
        message = f"Product will reach low stock threshold in {days_until_low:.1f} days. Reorder immediately."
        suggestion = f"Reorder now - will reach threshold in {days_until_low:.1f} days"
    else:
        message = f"Product will reach low stock threshold in {days_until_low:.1f} days."
        suggestion = f"Plan to reorder in {ideal_restock_time:.1f} days"
    
    return {
        "prediction_possible": True,
        "message": message,
        "sales_velocity": round(sales_velocity, 2),
        "days_until_restock": round(days_until_low, 1),
        "days_until_empty": round(days_until_empty, 1),
        "confidence": round(confidence),
        "suggestion": suggestion,
        "ideal_restock_date": (datetime.now() + timedelta(days=ideal_restock_time)).strftime('%Y-%m-%d') if ideal_restock_time > 0 else "As soon as possible"
    }


def identify_non_selling_products(products, sales_data, days_threshold=30):
    """
    Identify products that haven't been selling well.
    
    Args:
        products (list): List of all products
        sales_data (dict): Dictionary mapping product_id to its sales records
        days_threshold (int): Number of days to consider for "not selling well"
        
    Returns:
        list: List of products that aren't selling well, with analysis
    """
    non_selling_products = []
    today = datetime.now()
    
    for product in products:
        product_id = str(product.get('_id'))
        
        # Get sales for this product
        product_sales = sales_data.get(product_id, [])
        
        # Skip products with no stock - they can't sell
        if product['stock'] <= 0:
            continue
            
        # Calculate days since last sale
        last_sale_date = None
        if product_sales:
            sorted_sales = sorted(product_sales, key=lambda x: x['date_sold'] if isinstance(x['date_sold'], datetime) else datetime.min)
            last_sale = sorted_sales[-1]
            last_sale_date = last_sale['date_sold']
            
            if isinstance(last_sale_date, datetime):
                days_since_last_sale = (today - last_sale_date).days
            else:
                days_since_last_sale = days_threshold + 1  # Assume older than threshold if date format is unknown
        else:
            # If no sales, use product creation date if available, otherwise assume older than threshold
            days_since_last_sale = days_threshold + 1
        
        # Calculate revenue from this product
        total_revenue = sum(sale.get('total_price', 0) for sale in product_sales)
        
        # Determine if product is not selling well
        not_selling_well = False
        reason = ""
        
        if not product_sales:
            not_selling_well = True
            reason = "No sales recorded for this product"
        elif days_since_last_sale > days_threshold:
            not_selling_well = True
            reason = f"No sales in the last {days_since_last_sale} days"
            
        if not_selling_well:
            # Calculate holding cost estimate (approximation: 25% of product value per year)
            annual_holding_cost_rate = 0.25  # 25% of product value per year
            daily_holding_cost = (product['price'] * annual_holding_cost_rate) / 365
            monthly_holding_cost = daily_holding_cost * 30
            
            # Calculate opportunity cost (what this inventory space could be used for)
            monthly_opportunity_cost = product['price'] * 0.01  # Simplified: 1% of product value per month
            
            # Suggest action based on analysis
            if product['stock'] > product.get('low_stock_threshold', 5) * 3:
                suggestion = "Consider reducing inventory by running a promotion"
            else:
                suggestion = "Monitor for another month before taking action"
                
            non_selling_products.append({
                'product': product,
                'days_since_last_sale': days_since_last_sale if last_sale_date else "Never sold",
                'total_revenue': total_revenue,
                'reason': reason,
                'monthly_holding_cost': round(monthly_holding_cost * product['stock'], 2),
                'suggestion': suggestion
            })
    
    # Sort by days since last sale (descending)
    non_selling_products.sort(key=lambda x: x['days_since_last_sale'] if isinstance(x['days_since_last_sale'], int) else float('inf'), reverse=True)
    
    return non_selling_products

import os
from flask import Flask, request, render_template, redirect, url_for, Response, flash, session
from flask_sqlalchemy import SQLAlchemy
import csv
from io import StringIO
from datetime import datetime

# Initialize Flask app and database
app = Flask(__name__)

# --- Configuration ---
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'a_default_dev_secret_key_longer') # Changed default
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///inventory.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- Models ---
class Stock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    price = db.Column(db.Float, nullable=False)
    # Cascade delete is generally NOT recommended for inventory if orders should persist
    # orders = db.relationship('Order', backref='stock', lazy=True, cascade="all, delete-orphan") # Be careful with cascade!
    orders = db.relationship('Order', backref='stock_item', lazy=True) # Safer default

    def __repr__(self):
        return f'<Stock {self.name}>'

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    stock_id = db.Column(db.Integer, db.ForeignKey('stock.id'), nullable=False)
    quantity_requested = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='Pending', nullable=False)
    # Changed relationship name to avoid conflict if 'stock' is used elsewhere
    # stock = db.relationship('Stock', backref=db.backref('orders', lazy=True))
    # Renamed backref on Stock model, so no need for explicit backref here if lazy='dynamic' or similar isn't needed

    def __repr__(self):
        # Check if stock_item relationship is loaded before accessing name
        stock_name = self.stock_item.name if self.stock_item else "[Deleted Stock]"
        return f'<Order {self.id} for {stock_name}>'

# New Model for Asks
class Ask(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_name = db.Column(db.String(150), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Ask {self.id} for {self.item_name}>'

# --- Database Creation ---
with app.app_context():
    db.create_all() # This will create the 'ask' table if it doesn't exist

# --- Helper ---
@app.context_processor
def inject_now():
    return {'now': datetime.utcnow()}

# --- Routes ---

@app.route('/')
def home():
    return redirect(url_for('inventory'))

# --- Inventory Routes ---

@app.route('/inventory')
def inventory():
    # (Keep existing filter logic)
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)
    min_quantity = request.args.get('min_quantity', type=int)
    max_quantity = request.args.get('max_quantity', type=int)

    query = Stock.query

    if min_price is not None:
        query = query.filter(Stock.price >= min_price)
    if max_price is not None:
        query = query.filter(Stock.price <= max_price)
    if min_quantity is not None:
        query = query.filter(Stock.quantity >= min_quantity)
    if max_quantity is not None:
        query = query.filter(Stock.quantity <= max_quantity)

    stocks = query.order_by(Stock.name).all()
    return render_template('inventory.html',
                           stocks=stocks,
                           title="Inventory",
                           min_price=min_price,
                           max_price=max_price,
                           min_quantity=min_quantity,
                           max_quantity=max_quantity)

@app.route('/add_stock', methods=['GET', 'POST'])
def add_stock():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        quantity_str = request.form.get('quantity')
        price_str = request.form.get('price')

        if not name:
            flash('Stock name is required.', 'error')
            return render_template('add_stock.html', title="Add Stock")

        try:
            quantity = int(quantity_str)
            price = float(price_str)
            if quantity < 0 or price < 0:
                 raise ValueError("Quantity and price cannot be negative.")
        except (TypeError, ValueError) as e:
             flash(f'Invalid quantity or price: {e}. Please enter valid numbers.', 'error')
             return render_template('add_stock.html', title="Add Stock", name=name, quantity=quantity_str, price=price_str)

        existing_stock = Stock.query.filter(Stock.name.ilike(name)).first() # Case-insensitive check
        if existing_stock:
            flash(f'Stock item "{name}" already exists. Use the edit function or choose a different name.', 'error')
            return render_template('add_stock.html', title="Add Stock", name=name, quantity=quantity_str, price=price_str)
        else:
            new_stock = Stock(name=name, quantity=quantity, price=price)
            db.session.add(new_stock)
            db.session.commit()
            flash(f'Stock "{name}" added successfully!', 'success')
            return redirect(url_for('inventory'))

    return render_template('add_stock.html', title="Add Stock")

@app.route('/edit_stock/<int:stock_id>', methods=['GET', 'POST'])
def edit_stock(stock_id):
    stock_item = Stock.query.get_or_404(stock_id)

    if request.method == 'POST':
        new_name = request.form.get('name', '').strip()
        quantity_str = request.form.get('quantity')
        price_str = request.form.get('price')

        if not new_name:
            flash('Stock name cannot be empty.', 'error')
            # Pass current (or attempted invalid) values back to form
            return render_template('edit_stock.html', title=f"Edit {stock_item.name}", stock=stock_item, name=new_name, quantity=quantity_str, price=price_str)

        try:
            quantity = int(quantity_str)
            price = float(price_str)
            if quantity < 0 or price < 0:
                 raise ValueError("Quantity and price cannot be negative.")
        except (TypeError, ValueError) as e:
             flash(f'Invalid quantity or price: {e}. Please enter valid numbers.', 'error')
             return render_template('edit_stock.html', title=f"Edit {stock_item.name}", stock=stock_item, name=new_name, quantity=quantity_str, price=price_str)

        # Check if the new name conflicts with another existing item
        existing_stock = Stock.query.filter(Stock.name.ilike(new_name), Stock.id != stock_id).first()
        if existing_stock:
             flash(f'Another stock item named "{new_name}" already exists. Choose a different name.', 'error')
             return render_template('edit_stock.html', title=f"Edit {stock_item.name}", stock=stock_item, name=new_name, quantity=quantity_str, price=price_str)

        # Update the stock item
        stock_item.name = new_name
        stock_item.quantity = quantity
        stock_item.price = price
        db.session.commit()
        flash(f'Stock item "{stock_item.name}" updated successfully!', 'success')
        return redirect(url_for('inventory'))

    # GET request: Show the edit form pre-filled
    return render_template('edit_stock.html', title=f"Edit {stock_item.name}", stock=stock_item)


@app.route('/delete_stock/<int:stock_id>', methods=['POST'])
def delete_stock(stock_id):
    stock_item = Stock.query.get_or_404(stock_id)

    # --- IMPORTANT CHECK: Prevent deletion if orders exist for this stock ---
    # Querying the relationship directly is efficient
    if stock_item.orders: # Checks if the list of related orders is non-empty
        flash(f'Cannot delete "{stock_item.name}": It has associated orders. Consider setting quantity to 0 instead.', 'error')
        return redirect(url_for('inventory'))
    # Alternative check (if relationship backref isn't set up or you prefer explicit query):
    # existing_orders = Order.query.filter_by(stock_id=stock_id).first()
    # if existing_orders:
    #     flash(f'Cannot delete "{stock_item.name}": It has associated orders. Consider setting quantity to 0 instead.', 'error')
    #    return redirect(url_for('inventory'))

    # If no orders are associated, proceed with deletion
    stock_name = stock_item.name # Get name before deleting
    db.session.delete(stock_item)
    db.session.commit()
    flash(f'Stock item "{stock_name}" deleted successfully.', 'success')
    return redirect(url_for('inventory'))

@app.route('/download_inventory')
def download_inventory():
    # (Keep existing download logic)
    stocks = Stock.query.order_by(Stock.name).all()
    si = StringIO()
    cw = csv.writer(si)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"scent_room_inventory_{timestamp}.csv"
    cw.writerow(['ID', 'Name', 'Quantity', 'Price'])
    for stock in stocks:
        cw.writerow([stock.id, stock.name, stock.quantity, stock.price])
    output = si.getvalue()
    si.close()
    return Response(
        output,
        mimetype='text/csv',
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

# --- Order Routes ---
# (Keep existing order routes: /orders, /add_order, /fulfill_order)

@app.route('/orders')
def orders():
    orders = Order.query.order_by(Order.timestamp.desc()).all()
    return render_template('orders.html', orders=orders, title="View Orders")

@app.route('/add_order', methods=['GET', 'POST'])
def add_order():
    if request.method == 'POST':
        stock_id_str = request.form.get('stock_id')
        quantity_requested_str = request.form.get('quantity_requested')

        if not stock_id_str or not quantity_requested_str:
            flash('Please select a stock item and enter a quantity.', 'error')
            # Pass stocks back to template on error
            stocks = Stock.query.filter(Stock.quantity > 0).order_by(Stock.name).all()
            return render_template('add_order.html', stocks=stocks, title="Add Order")

        try:
            stock_id = int(stock_id_str)
            quantity_requested = int(quantity_requested_str)
            if quantity_requested <= 0:
                raise ValueError("Quantity must be positive.")
        except ValueError as e:
            flash(f'Invalid input: {e}.', 'error')
            stocks = Stock.query.filter(Stock.quantity > 0).order_by(Stock.name).all()
            return render_template('add_order.html', stocks=stocks, title="Add Order")

        stock = Stock.query.get(stock_id)
        if not stock:
             flash('Selected stock item not found.', 'error')
             stocks = Stock.query.filter(Stock.quantity > 0).order_by(Stock.name).all()
             return render_template('add_order.html', stocks=stocks, title="Add Order")

        # Check availability *before* creating pending order (good practice)
        if stock.quantity < quantity_requested:
            flash(f'Error: Not enough stock for "{stock.name}". Available: {stock.quantity}, Requested: {quantity_requested}. Order not placed.', 'error')
            # Don't redirect, let user correct the form
            stocks = Stock.query.filter(Stock.quantity > 0).order_by(Stock.name).all()
            return render_template('add_order.html', stocks=stocks, title="Add Order", selected_stock_id=stock_id, quantity_requested=quantity_requested)
        else:
            new_order = Order(stock_id=stock_id, quantity_requested=quantity_requested, status='Pending')
            db.session.add(new_order)
            db.session.commit()
            flash(f'Order for {quantity_requested} of "{stock.name}" placed successfully. Status: Pending.', 'success')
            return redirect(url_for('orders'))

    # GET request
    stocks = Stock.query.filter(Stock.quantity > 0).order_by(Stock.name).all()
    return render_template('add_order.html', stocks=stocks, title="Add Order")


@app.route('/fulfill_order/<int:order_id>', methods=['POST'])
def fulfill_order(order_id):
    order = Order.query.get_or_404(order_id)

    if order.status != 'Pending':
        flash(f'Order {order.id} is already {order.status}. Cannot fulfill again.', 'warning')
        return redirect(url_for('orders'))

    # Use the relationship to get the stock item
    stock = order.stock_item
    if not stock:
         flash(f'Error: Associated stock item for Order {order.id} not found (might have been deleted). Cannot fulfill.', 'error')
         order.status = 'Failed - Stock Missing' # Update status
         db.session.commit()
         return redirect(url_for('orders'))


    if stock.quantity < order.quantity_requested:
        flash(f'Error: Insufficient stock for "{stock.name}" to fulfill order {order.id}. Available: {stock.quantity}, Required: {order.quantity_requested}.', 'error')
        order.status = 'Failed - Insufficient Stock' # Optional: update status
        db.session.commit()
    else:
        stock.quantity -= order.quantity_requested
        order.status = 'Fulfilled'
        db.session.commit()
        flash(f'Order {order.id} for "{stock.name}" fulfilled successfully! Stock updated.', 'success')

    return redirect(url_for('orders'))


# --- Asks Routes (New) ---

@app.route('/asks')
def asks():
    """Displays the list of requested items (asks)."""
    asks_list = Ask.query.order_by(Ask.timestamp.desc()).all()
    return render_template('asks.html', asks=asks_list, title="Customer Asks")

@app.route('/add_ask', methods=['GET', 'POST'])
def add_ask():
    """Form to add a new ask."""
    if request.method == 'POST':
        item_name = request.form.get('item_name', '').strip()
        notes = request.form.get('notes', '').strip()

        if not item_name:
            flash('The name of the asked item is required.', 'error')
            return render_template('add_ask.html', title="Add Ask", item_name=item_name, notes=notes)

        new_ask = Ask(item_name=item_name, notes=notes if notes else None)
        db.session.add(new_ask)
        db.session.commit()
        flash(f'Ask for "{item_name}" added successfully.', 'success')
        return redirect(url_for('asks'))

    return render_template('add_ask.html', title="Add Ask")

@app.route('/delete_ask/<int:ask_id>', methods=['POST'])
def delete_ask(ask_id):
    """Deletes an ask."""
    ask_item = Ask.query.get_or_404(ask_id)
    item_name = ask_item.item_name # Get name before deleting
    db.session.delete(ask_item)
    db.session.commit()
    flash(f'Ask for "{item_name}" removed.', 'success')
    return redirect(url_for('asks'))


# --- Run the App ---
if __name__ == '__main__':
    app.run(debug=True)

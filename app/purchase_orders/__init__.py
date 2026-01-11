from flask import Blueprint

bp = Blueprint('po', __name__)

from app.purchase_orders import routes

from flask import Blueprint

bp = Blueprint('ar', __name__)

from app.accounts_receivable import routes, forms

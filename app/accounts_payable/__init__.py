from flask import Blueprint

bp = Blueprint('ap', __name__)

from app.accounts_payable import routes

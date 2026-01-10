from flask import Blueprint

bp = Blueprint('office', __name__)

from app.office import routes

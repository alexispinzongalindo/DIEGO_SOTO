from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SubmitField, SelectField
from wtforms.fields import DateField, DecimalField
from wtforms.validators import DataRequired, Optional, Length, Email, NumberRange


class CustomerForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=100)])
    address = StringField('Address', validators=[Optional(), Length(max=200)])
    phone = StringField('Phone', validators=[Optional(), Length(max=20)])
    email = StringField('Email', validators=[Optional(), Email(), Length(max=120)])
    tax_id = StringField('Tax ID', validators=[Optional(), Length(max=30)])
    credit_limit = DecimalField('Credit Limit', validators=[Optional(), NumberRange(min=0)], places=2)
    submit = SubmitField('Save Customer')


class InvoiceForm(FlaskForm):
    number = StringField('Invoice #', validators=[DataRequired(), Length(max=20)])
    date = DateField('Invoice Date', validators=[DataRequired()])
    due_date = DateField('Due Date', validators=[Optional()])
    customer_id = SelectField('Customer', coerce=int, validators=[DataRequired()])
    subtotal = DecimalField('Subtotal', validators=[Optional(), NumberRange(min=0)], places=2)
    tax = DecimalField('Tax', validators=[Optional(), NumberRange(min=0)], places=2)
    total = DecimalField('Total', validators=[Optional(), NumberRange(min=0)], places=2)
    terms = StringField('Terms', validators=[Optional(), Length(max=50)])
    notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Create Invoice')


class PaymentForm(FlaskForm):
    date = DateField('Payment Date', validators=[DataRequired()])
    customer_id = SelectField('Customer', coerce=int, validators=[DataRequired()])
    invoice_id = SelectField('Invoice (optional)', coerce=int, validators=[Optional()])
    amount = DecimalField('Amount', validators=[DataRequired(), NumberRange(min=0.01)], places=2)
    payment_method = StringField('Payment Method', validators=[Optional(), Length(max=50)])
    reference = StringField('Reference', validators=[Optional(), Length(max=50)])
    notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Record Payment')

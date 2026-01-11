from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SubmitField, SelectField, FormField, FieldList
from wtforms.form import Form
from wtforms.fields import DateField, DecimalField
from wtforms.validators import DataRequired, Optional, Length, Email, NumberRange


class VendorForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=100)])
    address = StringField('Address', validators=[Optional(), Length(max=200)])
    phone = StringField('Phone', validators=[Optional(), Length(max=20)])
    email = StringField('Email', validators=[Optional(), Email(), Length(max=120)])
    tax_id = StringField('Tax ID', validators=[Optional(), Length(max=30)])
    account_number = StringField('Account #', validators=[Optional(), Length(max=30)])
    submit = SubmitField('Save Vendor')


class BillItemForm(Form):
    product_id = SelectField('Item', coerce=int, validators=[Optional()])
    description = StringField('Description', validators=[Optional(), Length(max=200)])
    quantity = DecimalField('Qty', validators=[Optional(), NumberRange(min=0.01)], places=2)
    unit_price = DecimalField('Unit Price', validators=[Optional(), NumberRange(min=0)], places=2)


class BillForm(FlaskForm):
    number = StringField('Bill #', validators=[DataRequired(), Length(max=20)])
    date = DateField('Bill Date', validators=[DataRequired()])
    due_date = DateField('Due Date', validators=[Optional()])
    vendor_id = SelectField('Vendor', coerce=int, validators=[DataRequired()])

    tax = DecimalField('Tax', validators=[Optional(), NumberRange(min=0)], places=2)
    terms = StringField('Terms', validators=[Optional(), Length(max=50)])
    notes = TextAreaField('Notes', validators=[Optional()])

    items = FieldList(FormField(BillItemForm), min_entries=10, max_entries=30)
    submit = SubmitField('Create Bill')


class VendorPaymentForm(FlaskForm):
    date = DateField('Payment Date', validators=[DataRequired()])
    vendor_id = SelectField('Vendor', coerce=int, validators=[DataRequired()])
    bill_id = SelectField('Bill (optional)', coerce=int, validators=[Optional()])
    amount = DecimalField('Amount', validators=[DataRequired(), NumberRange(min=0.01)], places=2)
    payment_method = StringField('Payment Method', validators=[Optional(), Length(max=50)])
    reference = StringField('Reference', validators=[Optional(), Length(max=50)])
    notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Record Payment')


class DeleteForm(FlaskForm):
    submit = SubmitField('Delete')

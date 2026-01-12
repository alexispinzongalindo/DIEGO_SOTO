from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SubmitField, SelectField, FormField, FieldList
from wtforms.form import Form
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


class InvoiceItemForm(Form):
    description = StringField('Description', validators=[Optional(), Length(max=200)])
    quantity = DecimalField('Qty', validators=[Optional(), NumberRange(min=0.01)], places=2)
    unit_price = DecimalField('Unit Price', validators=[Optional(), NumberRange(min=0)], places=2)


class InvoiceForm(FlaskForm):
    number = StringField('Invoice #', validators=[DataRequired(), Length(max=20)])
    date = DateField('Invoice Date', validators=[DataRequired()])
    due_date = DateField('Due Date', validators=[Optional()])
    customer_id = SelectField('Customer', coerce=int, validators=[DataRequired()])

    tax = DecimalField('Tax', validators=[Optional(), NumberRange(min=0)], places=2)
    terms = StringField('Terms', validators=[Optional(), Length(max=50)])
    notes = TextAreaField('Notes', validators=[Optional()])

    items = FieldList(FormField(InvoiceItemForm), min_entries=10, max_entries=30)
    submit = SubmitField('Create Invoice')


class QuoteItemForm(Form):
    description = StringField('Description', validators=[Optional(), Length(max=200)])
    quantity = DecimalField('Qty', validators=[Optional(), NumberRange(min=0.01)], places=2)
    unit_price = DecimalField('Unit Price', validators=[Optional(), NumberRange(min=0)], places=2)


class QuoteForm(FlaskForm):
    date = DateField('Quote Date', validators=[DataRequired()])
    due_date = DateField('Due Date', validators=[Optional()])
    valid_until = DateField('Valid Until', validators=[Optional()])
    customer_id = SelectField('Customer', coerce=int, validators=[DataRequired()])
    status = SelectField(
        'Status',
        choices=[
            ('draft', 'Draft'),
            ('sent', 'Sent'),
            ('accepted', 'Accepted'),
            ('rejected', 'Rejected'),
            ('invoiced', 'Invoiced'),
        ],
        validators=[DataRequired()],
    )

    tax = DecimalField('Tax', validators=[Optional(), NumberRange(min=0)], places=2)
    terms = StringField('Terms', validators=[Optional(), Length(max=50)])
    notes = TextAreaField('Notes', validators=[Optional()])

    items = FieldList(FormField(QuoteItemForm), min_entries=10, max_entries=30)
    submit = SubmitField('Create Quote')


class ItemForm(FlaskForm):
    code = StringField('Code', validators=[Optional(), Length(max=20)])
    description = StringField('Description', validators=[DataRequired(), Length(max=200)])
    price = DecimalField('Default Price', validators=[Optional(), NumberRange(min=0)], places=2)
    submit = SubmitField('Save Item')


class EmailInvoiceForm(FlaskForm):
    to_email = StringField('To', validators=[DataRequired(), Email(), Length(max=120)])
    message = TextAreaField('Message', validators=[Optional()])
    submit = SubmitField('Send Invoice')


class PaymentForm(FlaskForm):
    date = DateField('Payment Date', validators=[DataRequired()])
    customer_id = SelectField('Customer', coerce=int, validators=[DataRequired()])
    invoice_id = SelectField('Invoice (optional)', coerce=int, validators=[Optional()])
    amount = DecimalField('Amount', validators=[DataRequired(), NumberRange(min=0.01)], places=2)
    payment_method = StringField('Payment Method', validators=[Optional(), Length(max=50)])
    reference = StringField('Reference', validators=[Optional(), Length(max=50)])
    notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Record Payment')


class DeleteForm(FlaskForm):
    submit = SubmitField('Delete')

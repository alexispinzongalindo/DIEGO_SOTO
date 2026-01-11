from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SubmitField, SelectField
from wtforms.fields import DateField, DecimalField
from wtforms.validators import DataRequired, Optional, Length, NumberRange
from wtforms import Form
from wtforms.fields import FieldList, FormField


class PurchaseOrderItemForm(Form):
    description = StringField('Description', validators=[Optional(), Length(max=200)])
    quantity = DecimalField('Qty', validators=[Optional(), NumberRange(min=0.01)], places=2)
    unit_price = DecimalField('Unit Price', validators=[Optional(), NumberRange(min=0)], places=2)


class PurchaseOrderForm(FlaskForm):
    po_type = SelectField(
        'Type',
        choices=[('vendor', 'Vendor'), ('customer', 'Customer')],
        validators=[DataRequired()],
    )
    date = DateField('PO Date', validators=[DataRequired()])
    vendor_id = SelectField('Vendor', coerce=int, validators=[Optional()])
    customer_id = SelectField('Customer', coerce=int, validators=[Optional()])
    status = SelectField(
        'Status',
        choices=[('draft', 'Draft'), ('sent', 'Sent'), ('closed', 'Closed')],
        validators=[DataRequired()],
    )
    tax = DecimalField('Tax', validators=[Optional(), NumberRange(min=0)], places=2)
    terms = StringField('Terms', validators=[Optional(), Length(max=50)])
    notes = TextAreaField('Notes', validators=[Optional()])

    items = FieldList(FormField(PurchaseOrderItemForm), min_entries=10, max_entries=30)
    submit = SubmitField('Save Purchase Order')


class DeleteForm(FlaskForm):
    submit = SubmitField('Delete')

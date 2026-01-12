from datetime import date

from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required

from app import db
from app.models import Customer, Vendor, PurchaseOrder, PurchaseOrderItem
from app.purchase_orders import bp
from app.purchase_orders.forms import PurchaseOrderForm, DeleteForm


def _digits_only(value: str) -> str:
    raw = (value or '').strip()
    digits = ''.join([c for c in raw if c.isdigit()])
    return digits


def _next_po_number() -> str:
    last = PurchaseOrder.query.order_by(PurchaseOrder.id.desc()).first()
    if not last or not last.number:
        return '0001'
    try:
        digits = _digits_only(last.number)
        n = int(digits)
        return f"{n + 1:04d}"
    except Exception:
        return f"{(last.id + 1):04d}"


@bp.route('/purchase-orders')
@login_required
def purchase_orders():
    po_list = PurchaseOrder.query.order_by(PurchaseOrder.date.desc()).all()
    delete_form = DeleteForm()
    return render_template('po/purchase_orders.html', title='Purchase Orders', purchase_orders=po_list, delete_form=delete_form)


@bp.route('/purchase-order/<int:id>')
@login_required
def view_purchase_order(id):
    po = PurchaseOrder.query.get_or_404(id)
    items = po.items.order_by(PurchaseOrderItem.id.asc()).all()
    delete_form = DeleteForm()
    return render_template('po/view_purchase_order.html', title=f'Purchase Order {po.number}', purchase_order=po, items=items, delete_form=delete_form)


@bp.route('/purchase-order/create', methods=['GET', 'POST'])
@login_required
def create_purchase_order():
    customers = Customer.query.order_by(Customer.name.asc()).all()
    vendors = Vendor.query.order_by(Vendor.name.asc()).all()

    form = PurchaseOrderForm()
    form.customer_id.choices = [(0, '-- Select --')] + [(c.id, c.name) for c in customers]
    form.vendor_id.choices = [(0, '-- Select --')] + [(v.id, v.name) for v in vendors]

    if request.method == 'GET':
        form.date.data = date.today()
        form.status.data = 'draft'
        form.po_type.data = 'vendor'

    if form.validate_on_submit():
        item_rows = []
        subtotal = 0.0
        for item_form in form.items:
            description = (item_form.form.description.data or '').strip()
            qty = item_form.form.quantity.data
            unit_price = item_form.form.unit_price.data

            is_blank = (not description) and (qty is None) and (unit_price is None)
            if is_blank:
                continue

            if not description:
                flash('Each PO item must include a description.', 'danger')
                return render_template('po/create_purchase_order.html', title='Create Purchase Order', form=form)

            if qty is None:
                flash('Each PO item must include a quantity.', 'danger')
                return render_template('po/create_purchase_order.html', title='Create Purchase Order', form=form)

            if unit_price is None:
                flash('Each PO item must include a unit price.', 'danger')
                return render_template('po/create_purchase_order.html', title='Create Purchase Order', form=form)

            amount = float(qty) * float(unit_price)
            subtotal += amount
            item_rows.append({'description': description, 'quantity': qty, 'unit_price': unit_price, 'amount': amount})

        if not item_rows:
            flash('Add at least one PO item.', 'danger')
            return render_template('po/create_purchase_order.html', title='Create Purchase Order', form=form)

        tax = float(form.tax.data or 0)
        total = subtotal + tax

        po_type = form.po_type.data
        vendor_id = form.vendor_id.data or 0
        customer_id = form.customer_id.data or 0
        if po_type == 'vendor':
            if vendor_id == 0:
                flash('Select a vendor for a vendor PO.', 'danger')
                return render_template('po/create_purchase_order.html', title='Create Purchase Order', form=form)
            customer_id = None
        else:
            if customer_id == 0:
                flash('Select a customer for a customer PO.', 'danger')
                return render_template('po/create_purchase_order.html', title='Create Purchase Order', form=form)
            vendor_id = None

        po = PurchaseOrder(
            number=_next_po_number(),
            po_type=po_type,
            date=form.date.data,
            vendor_id=vendor_id,
            customer_id=customer_id,
            subtotal=subtotal,
            tax=tax,
            total=total,
            status=form.status.data,
            terms=form.terms.data,
            notes=form.notes.data,
        )
        db.session.add(po)

        for row in item_rows:
            db.session.add(
                PurchaseOrderItem(
                    purchase_order=po,
                    description=row['description'],
                    quantity=row['quantity'],
                    unit_price=row['unit_price'],
                    amount=row['amount'],
                )
            )

        db.session.commit()
        flash('Purchase order created.', 'success')
        return redirect(url_for('po.view_purchase_order', id=po.id))

    return render_template('po/create_purchase_order.html', title='Create Purchase Order', form=form)


@bp.route('/purchase-order/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_purchase_order(id):
    po = PurchaseOrder.query.get_or_404(id)

    customers = Customer.query.order_by(Customer.name.asc()).all()
    vendors = Vendor.query.order_by(Vendor.name.asc()).all()

    form = PurchaseOrderForm(obj=po)
    form.customer_id.choices = [(0, '-- Select --')] + [(c.id, c.name) for c in customers]
    form.vendor_id.choices = [(0, '-- Select --')] + [(v.id, v.name) for v in vendors]

    if request.method == 'GET':
        form.po_type.data = po.po_type
        form.customer_id.data = po.customer_id or 0
        form.vendor_id.data = po.vendor_id or 0
        existing_items = po.items.order_by(PurchaseOrderItem.id.asc()).all()
        for idx, item in enumerate(existing_items[: len(form.items)]):
            form.items[idx].form.description.data = item.description
            form.items[idx].form.quantity.data = item.quantity
            form.items[idx].form.unit_price.data = item.unit_price

    if form.validate_on_submit():
        item_rows = []
        subtotal = 0.0
        for item_form in form.items:
            description = (item_form.form.description.data or '').strip()
            qty = item_form.form.quantity.data
            unit_price = item_form.form.unit_price.data

            is_blank = (not description) and (qty is None) and (unit_price is None)
            if is_blank:
                continue

            if not description or qty is None or unit_price is None:
                flash('Each PO item must include description, quantity, and unit price.', 'danger')
                return render_template('po/edit_purchase_order.html', title=f'Edit Purchase Order {po.number}', form=form, purchase_order=po)

            amount = float(qty) * float(unit_price)
            subtotal += amount
            item_rows.append({'description': description, 'quantity': qty, 'unit_price': unit_price, 'amount': amount})

        if not item_rows:
            flash('Add at least one PO item.', 'danger')
            return render_template('po/edit_purchase_order.html', title=f'Edit Purchase Order {po.number}', form=form, purchase_order=po)

        tax = float(form.tax.data or 0)
        total = subtotal + tax

        po_type = form.po_type.data
        vendor_id = form.vendor_id.data or 0
        customer_id = form.customer_id.data or 0
        if po_type == 'vendor':
            if vendor_id == 0:
                flash('Select a vendor for a vendor PO.', 'danger')
                return render_template('po/edit_purchase_order.html', title=f'Edit Purchase Order {po.number}', form=form, purchase_order=po)
            customer_id = None
        else:
            if customer_id == 0:
                flash('Select a customer for a customer PO.', 'danger')
                return render_template('po/edit_purchase_order.html', title=f'Edit Purchase Order {po.number}', form=form, purchase_order=po)
            vendor_id = None

        po.po_type = po_type
        po.date = form.date.data
        po.vendor_id = vendor_id
        po.customer_id = customer_id
        po.subtotal = subtotal
        po.tax = tax
        po.total = total
        po.status = form.status.data
        po.terms = form.terms.data
        po.notes = form.notes.data

        existing_items = po.items.all()
        for item in existing_items:
            db.session.delete(item)
        db.session.flush()

        for row in item_rows:
            db.session.add(
                PurchaseOrderItem(
                    purchase_order=po,
                    description=row['description'],
                    quantity=row['quantity'],
                    unit_price=row['unit_price'],
                    amount=row['amount'],
                )
            )

        db.session.commit()
        flash('Purchase order updated.', 'success')
        return redirect(url_for('po.view_purchase_order', id=po.id))

    return render_template('po/edit_purchase_order.html', title=f'Edit Purchase Order {po.number}', form=form, purchase_order=po)


@bp.route('/purchase-order/<int:id>/delete', methods=['POST'])
@login_required
def delete_purchase_order(id):
    po = PurchaseOrder.query.get_or_404(id)
    form = DeleteForm()
    if not form.validate_on_submit():
        flash('Unable to delete purchase order.', 'danger')
        return redirect(url_for('po.view_purchase_order', id=po.id))

    items = po.items.all()
    for item in items:
        db.session.delete(item)
    db.session.delete(po)
    db.session.commit()
    flash('Purchase order deleted.', 'success')
    return redirect(url_for('po.purchase_orders'))

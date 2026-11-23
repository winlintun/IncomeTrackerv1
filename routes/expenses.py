import math
from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError
from models import Expense, ExpenseBudget, db
from validators import (
    MAX_DESCRIPTION_LEN,
    VALID_EXPENSE_TYPES,
    _clean_str,
    _clean_tags,
    _require_body,
    _valid_amount,
    _valid_date,
    _valid_expense_type,
    _valid_month,
    utcnow,
)

expenses_bp = Blueprint('expenses', __name__)


@expenses_bp.route('/api/expenses', methods=['GET', 'POST'])
@login_required
def manage_expenses():
    if request.method == 'POST':
        data, error = _require_body()
        if error:
            return error

        expense_date = _valid_date(data.get('date'))
        if not expense_date:
            return jsonify({'error': 'date must be YYYY-MM-DD'}), 400

        amount = _valid_amount(data.get('amount', 0))
        if amount is None:
            return jsonify({'error': 'Invalid amount'}), 400

        description = _clean_str(data.get('description'), MAX_DESCRIPTION_LEN)
        if description is None:
            return jsonify({'error': f'description must be at most {MAX_DESCRIPTION_LEN} characters'}), 400
        tags_str = _clean_tags(data.get('tags', []))
        expense_type = _valid_expense_type(data.get('expense_type', 'daily'))
        if not expense_type:
            return jsonify({'error': 'Invalid expense_type'}), 400

        expense = Expense(
            user_id=current_user.id,
            date=expense_date,
            amount=amount,
            description=description,
            tags=tags_str,
            expense_type=expense_type
        )
        db.session.add(expense)
        db.session.commit()
        return jsonify({
            'id': expense.id,
            'date': expense.date,
            'amount': expense.amount,
            'description': expense.description,
            'tags': expense.tags.split(',') if expense.tags else [],
            'expense_type': expense.expense_type,
            'created_at': expense.created_at.isoformat()
        }), 201

    expenses = Expense.query.filter_by(user_id=current_user.id).order_by(Expense.date.desc()).all()
    return jsonify([{
        'id': e.id,
        'date': e.date,
        'amount': e.amount,
        'description': e.description,
        'tags': e.tags.split(',') if e.tags else [],
        'expense_type': e.expense_type,
        'created_at': e.created_at.isoformat()
    } for e in expenses])


@expenses_bp.route('/api/expenses/<int:expense_id>', methods=['PUT', 'DELETE'])
@login_required
def manage_expense_item(expense_id):
    expense = Expense.query.filter_by(id=expense_id, user_id=current_user.id).first_or_404()

    if request.method == 'PUT':
        data, error = _require_body()
        if error:
            return error
        if 'amount' in data:
            amount = _valid_amount(data['amount'])
            if amount is None:
                return jsonify({'error': 'Invalid amount'}), 400
            expense.amount = amount
        if 'description' in data:
            description = _clean_str(data['description'], MAX_DESCRIPTION_LEN)
            if description is None:
                return jsonify({'error': f'description must be at most {MAX_DESCRIPTION_LEN} characters'}), 400
            expense.description = description
        if 'date' in data:
            expense_date = _valid_date(data['date'])
            if not expense_date:
                return jsonify({'error': 'date must be YYYY-MM-DD'}), 400
            expense.date = expense_date
        if 'tags' in data:
            expense.tags = _clean_tags(data['tags'])
        if 'expense_type' in data:
            expense_type = _valid_expense_type(data['expense_type'])
            if not expense_type:
                return jsonify({'error': 'Invalid expense_type'}), 400
            expense.expense_type = expense_type
        db.session.commit()
        return jsonify({
            'id': expense.id,
            'date': expense.date,
            'amount': expense.amount,
            'description': expense.description,
            'tags': expense.tags.split(',') if expense.tags else [],
            'expense_type': expense.expense_type
        })

    db.session.delete(expense)
    db.session.commit()
    return jsonify({'message': 'Expense deleted'})


def _serialize_budget(budget):
    return {
        'id': budget.id,
        'month': budget.month,
        'expense_type': budget.expense_type,
        'limit_amount': budget.limit_amount
    }


def _budget_status(spent, limit):
    if limit <= 0:
        return 'over' if spent > 0 else 'ok'
    if spent > limit:
        return 'over'
    if spent >= limit * 0.8:
        return 'warning'
    return 'ok'


@expenses_bp.route('/api/expenses/budgets', methods=['GET', 'POST'])
@login_required
def manage_expense_budgets():
    if request.method == 'POST':
        data, error = _require_body()
        if error:
            return error

        month = _valid_month(data.get('month'))
        if not month:
            return jsonify({'error': 'month must be YYYY-MM'}), 400

        expense_type = _valid_expense_type(data.get('expense_type'))
        if not expense_type:
            return jsonify({'error': 'Invalid expense_type'}), 400

        limit_amount = _valid_amount(data.get('limit_amount'))
        if limit_amount is None:
            return jsonify({'error': 'Invalid limit_amount'}), 400

        budget = ExpenseBudget.query.filter_by(
            user_id=current_user.id, month=month, expense_type=expense_type
        ).first()
        if budget:
            budget.limit_amount = limit_amount
        else:
            budget = ExpenseBudget(
                user_id=current_user.id,
                month=month,
                expense_type=expense_type,
                limit_amount=limit_amount
            )
            db.session.add(budget)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            budget = ExpenseBudget.query.filter_by(
                user_id=current_user.id, month=month, expense_type=expense_type
            ).first()
            if not budget:
                return jsonify({'error': 'Could not save budget'}), 400
            budget.limit_amount = limit_amount
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                return jsonify({'error': 'Could not save budget'}), 400
        return jsonify(_serialize_budget(budget))

    query = ExpenseBudget.query.filter_by(user_id=current_user.id)
    month_arg = request.args.get('month') or None
    if month_arg is not None:
        month = _valid_month(month_arg)
        if not month:
            return jsonify({'error': 'month must be YYYY-MM'}), 400
        query = query.filter_by(month=month)
    budgets = query.order_by(ExpenseBudget.month.desc(), ExpenseBudget.expense_type).all()
    return jsonify([_serialize_budget(b) for b in budgets])


@expenses_bp.route('/api/expenses/budgets/<int:budget_id>', methods=['DELETE'])
@login_required
def delete_expense_budget(budget_id):
    budget = ExpenseBudget.query.filter_by(id=budget_id, user_id=current_user.id).first_or_404()
    db.session.delete(budget)
    db.session.commit()
    return jsonify({'message': 'Budget deleted'})


@expenses_bp.route('/api/expenses/stats')
@login_required
def expense_stats():
    current_month = _valid_month(request.args.get('month') or utcnow().strftime('%Y-%m'))
    if not current_month:
        return jsonify({'error': 'month must be YYYY-MM'}), 400

    expenses = Expense.query.filter(
        Expense.user_id == current_user.id,
        Expense.date.startswith(current_month)
    ).all()

    monthly_total = sum(e.amount for e in expenses)

    by_type = {}
    for e in expenses:
        by_type[e.expense_type] = by_type.get(e.expense_type, 0) + e.amount

    all_tags = {}
    for e in expenses:
        for tag in (e.tags.split(',') if e.tags else []):
            tag = tag.strip()
            if tag:
                all_tags[tag] = all_tags.get(tag, 0) + e.amount

    budgets = {}
    budget_rows = ExpenseBudget.query.filter_by(
        user_id=current_user.id, month=current_month
    ).all()
    budget_by_type = {b.expense_type: b for b in budget_rows}
    for expense_type in VALID_EXPENSE_TYPES:
        spent = by_type.get(expense_type, 0)
        budget = budget_by_type.get(expense_type)
        if budget is None:
            budgets[expense_type] = {
                'id': None,
                'limit_amount': None,
                'spent': spent,
                'remaining': None,
                'percent': None,
                'status': 'unset'
            }
        else:
            limit = budget.limit_amount
            percent = (spent / limit * 100) if limit > 0 else None
            if percent is not None and not math.isfinite(percent):
                percent = None
            budgets[expense_type] = {
                'id': budget.id,
                'limit_amount': limit,
                'spent': spent,
                'remaining': limit - spent,
                'percent': percent,
                'status': _budget_status(spent, limit)
            }

    return jsonify({
        'month': current_month,
        'monthly_total': monthly_total,
        'by_type': by_type,
        'by_tag': all_tags,
        'budgets': budgets
    })

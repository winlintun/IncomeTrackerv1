from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError
from models import Target, db
from validators import _as_float, _require_body, _valid_amount, _valid_month

targets_bp = Blueprint('targets', __name__)


@targets_bp.route('/api/targets', methods=['GET', 'POST'])
@login_required
def manage_targets():
    if request.method == 'POST':
        data, error = _require_body()
        if error:
            return error

        month = _valid_month(data.get('month'))
        if not month:
            return jsonify({'error': 'month must be YYYY-MM'}), 400

        amount = _valid_amount(data.get('amount'))
        if amount is None:
            return jsonify({'error': 'Invalid amount'}), 400

        work_days = data.get('work_days_per_week')
        if work_days is not None:
            work_days = _valid_amount(work_days)
            if work_days is None or work_days > 7:
                return jsonify({'error': 'work_days_per_week must be between 0 and 7'}), 400

        target = Target.query.filter_by(user_id=current_user.id, month=month).first()
        if target:
            target.amount = amount
            if work_days is not None:
                target.work_days_per_week = work_days
        else:
            target = Target(
                user_id=current_user.id,
                month=month,
                amount=amount,
                work_days_per_week=work_days
            )
            db.session.add(target)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            target = Target.query.filter_by(user_id=current_user.id, month=month).first()
            if not target:
                return jsonify({'error': 'Could not save target'}), 400
            target.amount = amount
            if work_days is not None:
                target.work_days_per_week = work_days
            db.session.commit()
        return jsonify({
            'id': target.id,
            'month': target.month,
            'amount': _as_float(target.amount),
            'work_days_per_week': target.work_days_per_week
        })

    targets = Target.query.filter_by(user_id=current_user.id).order_by(Target.month.desc()).all()
    return jsonify([{
        'id': t.id,
        'month': t.month,
        'amount': _as_float(t.amount),
        'work_days_per_week': t.work_days_per_week
    } for t in targets])


@targets_bp.route('/api/targets/<int:target_id>', methods=['DELETE'])
@login_required
def delete_target(target_id):
    target = Target.query.filter_by(id=target_id, user_id=current_user.id).first()
    if not target:
        return jsonify({'error': 'Target not found'}), 404
    db.session.delete(target)
    db.session.commit()
    return jsonify({'message': 'Target deleted'})

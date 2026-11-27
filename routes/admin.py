from datetime import timedelta
from flask import Blueprint, jsonify, request
from flask_login import current_user
from sqlalchemy.orm import joinedload
from models import IncomeRecord, Job, Note, PasswordResetToken, User, db
from validators import VALID_ROLES, _as_float, _require_body, admin_required, utcnow

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/api/admin/users')
@admin_required
def admin_users():
    users = User.query.all()
    return jsonify([{
        'id': u.id,
        'username': u.username,
        'role': u.role
    } for u in users])


@admin_bp.route('/api/admin/users/<int:user_id>', methods=['PUT', 'DELETE'])
@admin_required
def admin_manage_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    if request.method == 'PUT':
        data, error = _require_body()
        if error:
            return error
        if 'role' in data:
            new_role = data['role']
            if not isinstance(new_role, str) or new_role not in VALID_ROLES:
                return jsonify({'error': 'role must be "admin" or "user"'}), 400
            if user.id == current_user.id and new_role != 'admin':
                return jsonify({'error': 'Cannot demote your own account'}), 400
            if new_role == 'admin' and user.role != 'admin':
                if User.query.filter_by(role='admin').count() >= 1:
                    return jsonify({'error': 'Only one admin user is allowed'}), 400
            if new_role != 'admin' and user.role == 'admin':
                if User.query.filter_by(role='admin').count() <= 1:
                    return jsonify({'error': 'Cannot remove the last admin'}), 400
            user.role = new_role
        db.session.commit()
        return jsonify({'id': user.id, 'username': user.username, 'role': user.role})

    if user.role == 'admin' and User.query.filter_by(role='admin').count() <= 1:
        return jsonify({'error': 'Cannot delete the last admin'}), 400

    if user.id == current_user.id:
        return jsonify({'error': 'Cannot delete your own account'}), 400

    PasswordResetToken.query.filter_by(user_id=user_id).delete()
    Note.query.filter_by(user_id=user_id).delete()
    db.session.delete(user)
    db.session.commit()
    return jsonify({'message': 'User deleted'})


@admin_bp.route('/api/admin/stats')
@admin_required
def admin_stats():
    total_users = User.query.count()
    total_jobs = Job.query.count()
    total_records = IncomeRecord.query.count()
    total_income = _as_float(db.session.query(db.func.sum(IncomeRecord.amount)).scalar() or 0)

    recent_records = (
        IncomeRecord.query
        .options(joinedload(IncomeRecord.user))
        .order_by(IncomeRecord.created_at.desc())
        .limit(10)
        .all()
    )

    today = utcnow().date()
    date_window = [(today - timedelta(days=offset)).strftime('%Y-%m-%d') for offset in range(29, -1, -1)]
    start_date, end_date = date_window[0], date_window[-1]
    trend_rows = (
        db.session.query(IncomeRecord.date, db.func.sum(IncomeRecord.amount))
        .filter(IncomeRecord.date >= start_date, IncomeRecord.date <= end_date)
        .group_by(IncomeRecord.date)
        .all()
    )
    totals_by_date = {row_date: _as_float(row_total) for row_date, row_total in trend_rows}
    daily_trend = [{'date': day_str, 'total': totals_by_date.get(day_str, 0.0)} for day_str in date_window]

    return jsonify({
        'total_users': total_users,
        'total_jobs': total_jobs,
        'total_records': total_records,
        'total_income': total_income,
        'daily_trend': daily_trend,
        'recent_activity': [{
            'id': r.id,
            'amount': _as_float(r.amount),
            'date': r.date,
            'job_name': r.job_name,
            'username': r.user.username if r.user else 'Unknown'
        } for r in recent_records]
    })

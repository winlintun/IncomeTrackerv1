from flask import Blueprint, jsonify, request
from flask_login import current_user
from models import IncomeRecord, Job, Note, PasswordResetToken, User, db
from validators import VALID_ROLES, _require_body, admin_required

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
    total_income = db.session.query(db.func.sum(IncomeRecord.amount)).scalar() or 0

    recent_records = IncomeRecord.query.order_by(IncomeRecord.created_at.desc()).limit(10).all()

    return jsonify({
        'total_users': total_users,
        'total_jobs': total_jobs,
        'total_records': total_records,
        'total_income': total_income,
        'recent_activity': [{
            'id': r.id,
            'amount': r.amount,
            'date': r.date,
            'job_name': r.job_name,
            'username': r.user.username if r.user else 'Unknown'
        } for r in recent_records]
    })

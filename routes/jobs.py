from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from models import IncomeRecord, Job, db
from validators import MAX_JOB_NAME_LEN, _clean_color, _clean_str, _require_body, _valid_amount

jobs_bp = Blueprint('jobs', __name__)


@jobs_bp.route('/api/jobs', methods=['GET', 'POST'])
@login_required
def manage_jobs():
    if request.method == 'POST':
        data, error = _require_body()
        if error:
            return error

        name = _clean_str(data.get('name'), MAX_JOB_NAME_LEN)
        if name is None:
            return jsonify({'error': f'name must be at most {MAX_JOB_NAME_LEN} characters'}), 400
        if not name:
            return jsonify({'error': 'Job name is required'}), 400

        hourly_rate = _valid_amount(data.get('hourly_rate', 0) or 0)
        hours_per_day = _valid_amount(data.get('hours_per_day', 0) or 0)
        if hourly_rate is None or hours_per_day is None:
            return jsonify({'error': 'Invalid numeric values for rate or hours'}), 400

        new_job = Job(
            name=name,
            hourly_rate=hourly_rate,
            hours_per_day=hours_per_day,
            color=_clean_color(data.get('color', '#18181b')),
            user_id=current_user.id
        )
        db.session.add(new_job)
        db.session.commit()
        return jsonify({
            'id': new_job.id,
            'name': new_job.name,
            'hourly_rate': new_job.hourly_rate,
            'hours_per_day': new_job.hours_per_day,
            'color': new_job.color
        }), 201

    jobs = Job.query.filter_by(user_id=current_user.id).all()
    return jsonify([{
        'id': j.id,
        'name': j.name,
        'hourly_rate': j.hourly_rate,
        'hours_per_day': j.hours_per_day,
        'color': j.color
    } for j in jobs])


@jobs_bp.route('/api/jobs/<int:job_id>', methods=['PUT', 'DELETE'])
@login_required
def manage_job_item(job_id):
    job = Job.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()

    if request.method == 'PUT':
        data, error = _require_body()
        if error:
            return error

        if 'name' in data:
            name = _clean_str(data.get('name'), MAX_JOB_NAME_LEN)
            if name is None:
                return jsonify({'error': f'name must be at most {MAX_JOB_NAME_LEN} characters'}), 400
            if not name:
                return jsonify({'error': 'Job name is required'}), 400
            job.name = name
            IncomeRecord.query.filter_by(job_id=job.id, user_id=current_user.id).update(
                {'job_name': name}, synchronize_session=False
            )
        if 'hourly_rate' in data:
            hourly_rate = _valid_amount(data['hourly_rate'] or 0)
            if hourly_rate is None:
                return jsonify({'error': 'Invalid numeric values for rate or hours'}), 400
            job.hourly_rate = hourly_rate
        if 'hours_per_day' in data:
            hours_per_day = _valid_amount(data['hours_per_day'] or 0)
            if hours_per_day is None:
                return jsonify({'error': 'Invalid numeric values for rate or hours'}), 400
            job.hours_per_day = hours_per_day
        if 'color' in data:
            job.color = _clean_color(data['color'])
        db.session.commit()
        return jsonify({
            'id': job.id,
            'name': job.name,
            'hourly_rate': job.hourly_rate,
            'hours_per_day': job.hours_per_day,
            'color': job.color
        })

    record_count = IncomeRecord.query.filter_by(job_id=job.id, user_id=current_user.id).count()
    if record_count:
        return jsonify({
            'error': f'This job still has {record_count} income record(s). Delete them first or keep the job.',
            'income_records': record_count
        }), 409

    db.session.delete(job)
    db.session.commit()
    return jsonify({'message': 'Job deleted'})

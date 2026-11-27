from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from models import IncomeRecord, Job, db
from validators import (
    _as_float,
    _parse_pagination,
    _require_body,
    _resolve_amount,
    _valid_date,
    _valid_month,
)

income_bp = Blueprint('income', __name__)


@income_bp.route('/api/income', methods=['GET', 'POST'])
@login_required
def manage_income():
    if request.method == 'POST':
        data, error = _require_body()
        if error:
            return error

        try:
            job_id = int(data.get('job_id'))
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid job_id'}), 400

        job = Job.query.filter_by(id=job_id, user_id=current_user.id).first()
        if not job:
            return jsonify({'error': 'Job not found'}), 400

        record_date = _valid_date(data.get('date'))
        if not record_date:
            return jsonify({'error': 'date must be YYYY-MM-DD'}), 400

        amount, amount_error = _resolve_amount(data.get('amount'), job, 'amount' in data)
        if amount_error:
            return jsonify({'error': amount_error}), 400

        new_record = IncomeRecord(
            job_id=job.id,
            user_id=current_user.id,
            date=record_date,
            amount=amount,
            job_name=job.name
        )
        db.session.add(new_record)
        db.session.commit()
        return jsonify({
            'id': new_record.id,
            'job_id': new_record.job_id,
            'date': new_record.date,
            'amount': _as_float(new_record.amount),
            'job_name': new_record.job_name
        }), 201

    query = IncomeRecord.query.filter_by(user_id=current_user.id)
    month_arg = request.args.get('month')
    if month_arg is not None and month_arg != '':
        month = _valid_month(month_arg)
        if not month:
            return jsonify({'error': 'month must be YYYY-MM'}), 400
        query = query.filter(IncomeRecord.date.startswith(month))

    limit, offset, page_error = _parse_pagination()
    if page_error:
        return page_error

    total = None
    if limit is not None or offset is not None:
        total = query.count()

    query = query.order_by(IncomeRecord.date.desc(), IncomeRecord.id.desc())
    if offset is not None:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)

    records = query.all()
    resp = jsonify([{
        'id': r.id,
        'job_id': r.job_id,
        'date': r.date,
        'amount': _as_float(r.amount),
        'job_name': r.job_name
    } for r in records])
    if total is not None:
        resp.headers['X-Total-Count'] = str(total)
    return resp


@income_bp.route('/api/income/<int:record_id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
def manage_income_item(record_id):
    record = IncomeRecord.query.filter_by(id=record_id, user_id=current_user.id).first()
    if not record:
        return jsonify({'error': 'Record not found'}), 404

    if request.method == 'DELETE':
        db.session.delete(record)
        db.session.commit()
        return jsonify({'message': 'Record deleted'})

    if request.method == 'GET':
        return jsonify({
            'id': record.id,
            'job_id': record.job_id,
            'job_name': record.job_name,
            'date': record.date,
            'amount': _as_float(record.amount)
        })

    data, error = _require_body()
    if error:
        return error

    try:
        new_job_id = int(data.get('job_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid job_id'}), 400

    job = Job.query.filter_by(id=new_job_id, user_id=current_user.id).first()
    if not job:
        return jsonify({'error': 'Job not found'}), 400

    new_date = _valid_date(data.get('date'))
    if not new_date:
        return jsonify({'error': 'date must be YYYY-MM-DD'}), 400

    if 'amount' in data:
        new_amount, amount_error = _resolve_amount(data.get('amount'), job, True)
        if amount_error:
            return jsonify({'error': amount_error}), 400
        record.amount = new_amount

    record.job_id = job.id
    record.date = new_date
    record.job_name = job.name
    db.session.commit()
    return jsonify({
        'id': record.id,
        'job_id': record.job_id,
        'job_name': record.job_name,
        'date': record.date,
        'amount': _as_float(record.amount)
    })

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required
from models import Note, db
from validators import (
    MAX_NOTE_TITLE_LEN,
    _clean_str,
    _month_bounds,
    _parse_pagination,
    _require_body,
    _valid_month,
    utcnow,
)

notes_bp = Blueprint('notes', __name__)


@notes_bp.route('/notes')
@login_required
def notes_page():
    return render_template('note.html')


@notes_bp.route('/api/notes', methods=['GET', 'POST'])
@login_required
def manage_notes():
    if request.method == 'POST':
        data, error = _require_body()
        if error:
            return error

        title = _clean_str(data.get('title'), MAX_NOTE_TITLE_LEN)
        if title is None:
            return jsonify({'error': f'title must be at most {MAX_NOTE_TITLE_LEN} characters'}), 400
        title = title or 'Untitled'
        content = data.get('content', '')
        if not isinstance(content, str):
            content = ''
        pinned = bool(data.get('pinned', False))

        note = Note(
            user_id=current_user.id,
            title=title,
            content=content,
            pinned=pinned
        )
        db.session.add(note)
        db.session.commit()
        return jsonify({
            'id': note.id,
            'title': note.title,
            'content': note.content,
            'pinned': note.pinned,
            'created_at': note.created_at.isoformat(),
            'updated_at': note.updated_at.isoformat()
        }), 201

    query = Note.query.filter_by(user_id=current_user.id)
    month_arg = request.args.get('month')
    if month_arg is not None and month_arg != '':
        month = _valid_month(month_arg)
        if not month:
            return jsonify({'error': 'month must be YYYY-MM'}), 400
        start_dt, end_dt = _month_bounds(month)
        query = query.filter(Note.updated_at >= start_dt, Note.updated_at < end_dt)

    limit, offset, page_error = _parse_pagination()
    if page_error:
        return page_error

    total = None
    if limit is not None or offset is not None:
        total = query.count()

    query = query.order_by(Note.pinned.desc(), Note.updated_at.desc(), Note.id.desc())
    if offset is not None:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)

    notes = query.all()
    resp = jsonify([{
        'id': n.id,
        'title': n.title,
        'content': n.content,
        'pinned': n.pinned,
        'created_at': n.created_at.isoformat(),
        'updated_at': n.updated_at.isoformat()
    } for n in notes])
    if total is not None:
        resp.headers['X-Total-Count'] = str(total)
    return resp


@notes_bp.route('/api/notes/<int:note_id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
def manage_note_item(note_id):
    note = Note.query.filter_by(id=note_id, user_id=current_user.id).first_or_404()

    if request.method == 'GET':
        return jsonify({
            'id': note.id,
            'title': note.title,
            'content': note.content,
            'pinned': note.pinned,
            'created_at': note.created_at.isoformat(),
            'updated_at': note.updated_at.isoformat()
        })

    if request.method == 'PUT':
        data, error = _require_body()
        if error:
            return error
        if 'title' in data:
            title = _clean_str(data.get('title'), MAX_NOTE_TITLE_LEN)
            if title is None:
                return jsonify({'error': f'title must be at most {MAX_NOTE_TITLE_LEN} characters'}), 400
            if not title:
                return jsonify({'error': 'Title is required'}), 400
            note.title = title
        if 'content' in data:
            content = data['content']
            if not isinstance(content, str):
                return jsonify({'error': 'Content must be a string'}), 400
            note.content = content
        if 'pinned' in data:
            note.pinned = bool(data['pinned'])
        note.updated_at = utcnow()
        db.session.commit()
        return jsonify({
            'id': note.id,
            'title': note.title,
            'content': note.content,
            'pinned': note.pinned,
            'created_at': note.created_at.isoformat(),
            'updated_at': note.updated_at.isoformat()
        })

    db.session.delete(note)
    db.session.commit()
    return jsonify({'message': 'Note deleted'})

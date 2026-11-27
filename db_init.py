import time
from sqlalchemy import inspect as sa_inspect, text
from models import MAX_USERNAME_LEN, Setting, db, normalize_username


def _migrate_user_normalized_postgres():
    result = db.session.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'user' AND column_name = 'username_normalized'
    """))
    if result.fetchone() is None:
        db.session.execute(text('ALTER TABLE "user" ADD COLUMN username_normalized VARCHAR(80)'))
        db.session.commit()
        print("Added username_normalized column.")
    _backfill_normalized_usernames()


def _migrate_user_normalized_sqlite():
    result = db.session.execute(text("PRAGMA table_info(user)"))
    columns = [row[1] for row in result]
    if 'username_normalized' not in columns:
        db.session.execute(text('ALTER TABLE "user" ADD COLUMN username_normalized VARCHAR(80)'))
        db.session.commit()
        print("Added username_normalized column.")
    _backfill_normalized_usernames()


def _backfill_normalized_usernames():
    try:
        db.session.execute(text('DROP INDEX IF EXISTS ix_user_username_normalized'))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f'Could not drop username_normalized index before backfill: {e}')
    rows = db.session.execute(text('SELECT id, username FROM "user"')).fetchall()
    for user_id, username in rows:
        db.session.execute(
            text('UPDATE "user" SET username_normalized = :n WHERE id = :i'),
            {'n': normalize_username(username), 'i': user_id}
        )
    db.session.commit()
    _drop_duplicate_normalized_users()


def _duplicate_username(username, user_id):
    suffix = f'-dup{user_id}'
    attempt = 0
    while True:
        base = username[:max(1, MAX_USERNAME_LEN - len(suffix))]
        candidate = base + suffix
        clash = db.session.execute(
            text('SELECT id FROM "user" WHERE username_normalized = :n AND id != :i'),
            {'n': normalize_username(candidate), 'i': user_id}
        ).first()
        if not clash:
            return candidate
        attempt += 1
        suffix = f'-dup{user_id}-{attempt}'


def _drop_duplicate_normalized_users():
    duplicates = db.session.execute(text("""
        SELECT username_normalized FROM "user"
        WHERE username_normalized IS NOT NULL
        GROUP BY username_normalized HAVING COUNT(*) > 1
    """)).fetchall()
    for (normalized,) in duplicates:
        rows = db.session.execute(
            text('SELECT id, username, role FROM "user" WHERE username_normalized = :n ORDER BY id'),
            {'n': normalized}
        ).fetchall()
        if len(rows) < 2:
            continue
        keep = next((r for r in rows if r.role == 'admin'), rows[0])
        for row in rows:
            user_id, username = row.id, row.username
            if user_id == keep.id:
                continue
            new_username = _duplicate_username(username, user_id)
            db.session.execute(
                text('UPDATE "user" SET username = :u, username_normalized = :n WHERE id = :i'),
                {'u': new_username, 'n': normalize_username(new_username), 'i': user_id}
            )
            print(f'Renamed duplicate account {username!r} to {new_username!r}.')
        db.session.commit()
    try:
        db.session.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS ix_user_username_normalized
            ON "user" (username_normalized)
        """))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f'Could not create unique index on username_normalized: {e}')


def _migrate_target_unique_constraint():
    try:
        inspector = sa_inspect(db.engine)
        if 'target' not in inspector.get_table_names():
            return
        columns = {col['name'] for col in inspector.get_columns('target')}
    except Exception as e:
        print(f'Could not inspect target schema: {e}')
        return
    if not {'user_id', 'month'}.issubset(columns):
        return
    try:
        db.session.execute(text("""
            DELETE FROM target WHERE id NOT IN (
                SELECT MIN(id) FROM target GROUP BY user_id, month
            )
        """))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f'Could not deduplicate target rows: {e}')
    try:
        db.session.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_target_user_month
            ON target (user_id, month)
        """))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f'Could not create target unique index: {e}')


def _migrate_expense_budget_unique_constraint():
    try:
        inspector = sa_inspect(db.engine)
        if 'expense_budget' not in inspector.get_table_names():
            return
        columns = {col['name'] for col in inspector.get_columns('expense_budget')}
    except Exception as e:
        print(f'Could not inspect expense_budget schema: {e}')
        return
    if not {'user_id', 'month', 'expense_type'}.issubset(columns):
        return
    try:
        db.session.execute(text("""
            DELETE FROM expense_budget WHERE id NOT IN (
                SELECT MIN(id) FROM expense_budget GROUP BY user_id, month, expense_type
            )
        """))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f'Could not deduplicate expense_budget rows: {e}')
    try:
        db.session.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_expense_budget_user_month_type
            ON expense_budget (user_id, month, expense_type)
        """))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f'Could not create expense_budget unique index: {e}')


def _migrate_monetary_columns_postgres():
    targets = [
        ('job', 'hourly_rate'),
        ('income_record', 'amount'),
        ('target', 'amount'),
        ('expense', 'amount'),
        ('expense_budget', 'limit_amount'),
    ]
    for table_name, col_name in targets:
        try:
            row = db.session.execute(text("""
                SELECT data_type FROM information_schema.columns
                WHERE table_schema = current_schema() AND table_name = :t AND column_name = :c
            """), {'t': table_name, 'c': col_name}).fetchone()
            if row and row[0] in ('double precision', 'real'):
                db.session.execute(text(
                    f'ALTER TABLE "{table_name}" ALTER COLUMN "{col_name}" '
                    f'TYPE NUMERIC(12, 2) USING ROUND("{col_name}"::numeric, 2)'
                ))
                db.session.commit()
                print(f'Migrated {table_name}.{col_name} to NUMERIC(12, 2).')
        except Exception as e:
            db.session.rollback()
            print(f'Could not migrate {table_name}.{col_name} to NUMERIC(12, 2): {e}')


def _seed_bootstrap_flag():
    existing_users = db.session.execute(text('SELECT COUNT(*) FROM "user"')).scalar() or 0
    marker = Setting.query.filter_by(key='admin_bootstrap_done').first()
    if marker is None and existing_users:
        db.session.add(Setting(key='admin_bootstrap_done', value='1'))
        db.session.commit()
        print('Seeded admin_bootstrap_done marker for an existing database.')


def init_db_with_retry(app, retries=5, delay=3):
    required_tables = {
        'user', 'job', 'income_record', 'target',
        'note', 'expense', 'expense_budget', 'password_reset_token', 'setting'
    }
    for attempt in range(retries):
        try:
            with app.app_context():
                db.create_all()
                db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
                if 'postgresql' in db_uri:
                    result = db.session.execute(text("""
                        SELECT table_name FROM information_schema.tables
                        WHERE table_schema = 'public'
                    """))
                    tables = [row[0] for row in result]
                    missing = required_tables - set(tables)
                    if missing:
                        raise RuntimeError(f"Database initialization failed. Missing tables: {missing}")
                    result = db.session.execute(text("""
                        SELECT column_name FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = 'target' AND column_name = 'work_days_per_week'
                    """))
                    if result.fetchone() is None:
                        db.session.execute(text("ALTER TABLE target ADD COLUMN work_days_per_week FLOAT"))
                        db.session.commit()
                        print("Added work_days_per_week column.")
                    _migrate_user_normalized_postgres()
                    _migrate_target_unique_constraint()
                    _migrate_expense_budget_unique_constraint()
                    _migrate_monetary_columns_postgres()
                    _seed_bootstrap_flag()
                elif 'sqlite' in db_uri:
                    result = db.session.execute(text("PRAGMA table_list"))
                    tables = [row[1] for row in result]
                    missing = required_tables - set(tables)
                    if missing:
                        raise RuntimeError(f"Database initialization failed. Missing tables: {missing}")
                    result = db.session.execute(text("PRAGMA table_info(target)"))
                    columns = [row[1] for row in result]
                    if 'work_days_per_week' not in columns:
                        db.session.execute(text("ALTER TABLE target ADD COLUMN work_days_per_week FLOAT"))
                        db.session.commit()
                        print("Added work_days_per_week column.")
                    _migrate_user_normalized_sqlite()
                    _migrate_target_unique_constraint()
                    _migrate_expense_budget_unique_constraint()
                    _seed_bootstrap_flag()
                db.session.execute(text('SELECT 1'))
                print("Database initialized successfully.")
                return
        except Exception as e:
            print(f"DB not ready (attempt {attempt + 1}/{retries}): {e}")
            time.sleep(delay)
    raise RuntimeError("Could not connect to the database after retries.")

import os
import re
import secrets
import sqlite3
from pathlib import Path
from functools import wraps

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 display_name TEXT NOT NULL, password_hash TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')));
CREATE TABLE IF NOT EXISTS posts (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 body TEXT NOT NULL CHECK(length(body) BETWEEN 1 AND 280),
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')));
CREATE TABLE IF NOT EXISTS likes (
 user_id INTEGER NOT NULL REFERENCES users(id), post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
 PRIMARY KEY(user_id, post_id));
CREATE TABLE IF NOT EXISTS follows (
 follower_id INTEGER NOT NULL REFERENCES users(id), followed_id INTEGER NOT NULL REFERENCES users(id),
 PRIMARY KEY(follower_id, followed_id), CHECK(follower_id != followed_id));
CREATE INDEX IF NOT EXISTS posts_author ON posts(user_id, id DESC);
CREATE INDEX IF NOT EXISTS likes_post ON likes(post_id);
CREATE INDEX IF NOT EXISTS follows_target ON follows(followed_id);
'''


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        DATABASE=os.environ.get('SNS_DATABASE', str(Path(app.instance_path) / 'sns.sqlite3')),
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('SNS_SECURE_COOKIE') == '1',
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    if config:
        app.config.update(config)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    if not app.config.get('SECRET_KEY'):
        key = os.environ.get('SNS_SECRET_KEY')
        if not key:
            key_path = Path(app.instance_path) / 'session.key'
            try:
                with key_path.open('x') as f:
                    os.chmod(key_path, 0o600)
                    f.write(secrets.token_hex(32))
            except FileExistsError:
                pass
            key = key_path.read_text().strip()
        app.config['SECRET_KEY'] = key

    def db():
        if 'db' not in g:
            g.db = sqlite3.connect(app.config['DATABASE'], timeout=10)
            g.db.row_factory = sqlite3.Row
            g.db.execute('PRAGMA foreign_keys = ON')
        return g.db

    @app.teardown_appcontext
    def close_db(_error):
        connection = g.pop('db', None)
        if connection is not None:
            connection.close()

    with app.app_context():
        db().executescript(SCHEMA)
        db().commit()

    @app.before_request
    def load_user_and_check_csrf():
        g.user = db().execute('SELECT * FROM users WHERE id=?', (session.get('user_id'),)).fetchone()
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_hex(32)
        if request.method == 'POST':
            token = request.form.get('csrf_token', '')
            if not secrets.compare_digest(token, session['csrf_token']):
                abort(400, 'ページを再読み込みして、もう一度お試しください。')

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not g.user:
                flash('この操作にはログインが必要です。', 'error')
                return redirect(url_for('login'))
            return view(*args, **kwargs)
        return wrapped

    def timeline(where='', params=()):
        viewer = g.user['id'] if g.user else -1
        return db().execute('''
            SELECT p.*, u.username, u.display_name,
              (SELECT count(*) FROM likes WHERE post_id=p.id) AS like_count,
              EXISTS(SELECT 1 FROM likes WHERE post_id=p.id AND user_id=?) AS liked
            FROM posts p JOIN users u ON u.id=p.user_id
            ''' + where + ' ORDER BY p.id DESC LIMIT 50', (viewer, *params)).fetchall()

    def sidebar():
        viewer = g.user['id'] if g.user else -1
        return db().execute('''SELECT u.id, u.username, u.display_name,
            EXISTS(SELECT 1 FROM follows WHERE follower_id=? AND followed_id=u.id) AS followed
            FROM users u WHERE u.id != ? ORDER BY u.id DESC LIMIT 4''', (viewer, viewer)).fetchall()

    def back():
        # Only route to local, known destinations; do not trust a submitted URL.
        username = request.form.get('profile')
        if username and re.fullmatch(r'[A-Za-z0-9_]{3,24}', username):
            return redirect(url_for('profile', username=username))
        return redirect(url_for('home', feed='following' if request.form.get('feed') == 'following' else 'all'))

    @app.get('/')
    def home():
        feed = 'following' if request.args.get('feed') == 'following' and g.user else 'all'
        where, params = '', ()
        if feed == 'following':
            where = 'WHERE p.user_id=? OR p.user_id IN (SELECT followed_id FROM follows WHERE follower_id=?)'
            params = (g.user['id'], g.user['id'])
        return render_template('home.html', posts=timeline(where, params), feed=feed, people=sidebar(), profile_user=None)

    @app.route('/signup', methods=['GET', 'POST'])
    def signup():
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            display_name = request.form.get('display_name', '').strip()
            password = request.form.get('password', '')
            if not re.fullmatch(r'[A-Za-z0-9_]{3,24}', username):
                flash('ユーザー名は半角英数字・_で3〜24文字にしてください。', 'error')
            elif not 1 <= len(display_name) <= 40:
                flash('表示名は1〜40文字にしてください。', 'error')
            elif not 8 <= len(password) <= 128:
                flash('パスワードは8〜128文字にしてください。', 'error')
            else:
                try:
                    cursor = db().execute('INSERT INTO users(username,display_name,password_hash) VALUES(?,?,?)',
                                          (username, display_name, generate_password_hash(password)))
                    db().commit()
                except sqlite3.IntegrityError:
                    flash('このユーザー名はすでに使われています。', 'error')
                else:
                    session.clear()
                    session['user_id'] = cursor.lastrowid
                    flash('ようこそ！最初のひとことを投稿してみましょう。', 'success')
                    return redirect(url_for('home'))
        return render_template('auth.html', signup=True)

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            user = db().execute('SELECT * FROM users WHERE username=?', (request.form.get('username', '').strip(),)).fetchone()
            password = request.form.get('password', '')
            if user and len(password) <= 128 and check_password_hash(user['password_hash'], password):
                session.clear()
                session['user_id'] = user['id']
                return redirect(url_for('home'))
            flash('ユーザー名またはパスワードが違います。', 'error')
        return render_template('auth.html', signup=False)

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect(url_for('home'))

    @app.post('/posts')
    @login_required
    def post():
        body = request.form.get('body', '').strip()
        if not 1 <= len(body) <= 280:
            flash('投稿は1〜280文字で入力してください。', 'error')
        else:
            db().execute('INSERT INTO posts(user_id,body) VALUES(?,?)', (g.user['id'], body))
            db().commit()
            flash('投稿しました。', 'success')
        return back()

    @app.post('/posts/<int:post_id>/like')
    @login_required
    def like(post_id):
        if not db().execute('SELECT id FROM posts WHERE id=?', (post_id,)).fetchone():
            abort(404)
        pair = (g.user['id'], post_id)
        if db().execute('SELECT 1 FROM likes WHERE user_id=? AND post_id=?', pair).fetchone():
            db().execute('DELETE FROM likes WHERE user_id=? AND post_id=?', pair)
        else:
            db().execute('INSERT INTO likes(user_id,post_id) VALUES(?,?)', pair)
        db().commit()
        return back()

    @app.post('/users/<int:user_id>/follow')
    @login_required
    def follow(user_id):
        if user_id == g.user['id']:
            abort(400)
        if not db().execute('SELECT id FROM users WHERE id=?', (user_id,)).fetchone():
            abort(404)
        pair = (g.user['id'], user_id)
        if db().execute('SELECT 1 FROM follows WHERE follower_id=? AND followed_id=?', pair).fetchone():
            db().execute('DELETE FROM follows WHERE follower_id=? AND followed_id=?', pair)
        else:
            db().execute('INSERT INTO follows(follower_id,followed_id) VALUES(?,?)', pair)
        db().commit()
        return back()

    @app.post('/posts/<int:post_id>/delete')
    @login_required
    def delete_post(post_id):
        existing = db().execute('SELECT user_id FROM posts WHERE id=?', (post_id,)).fetchone()
        if not existing:
            abort(404)
        if existing['user_id'] != g.user['id']:
            abort(403)
        db().execute('DELETE FROM posts WHERE id=?', (post_id,))
        db().commit()
        return back()

    @app.get('/@<username>')
    def profile(username):
        user = db().execute('''SELECT u.*,
            (SELECT count(*) FROM posts WHERE user_id=u.id) AS post_count,
            (SELECT count(*) FROM follows WHERE followed_id=u.id) AS follower_count,
            (SELECT count(*) FROM follows WHERE follower_id=u.id) AS following_count,
            EXISTS(SELECT 1 FROM follows WHERE follower_id=? AND followed_id=u.id) AS followed
            FROM users u WHERE username=?''', (g.user['id'] if g.user else -1, username)).fetchone()
        if not user:
            abort(404)
        return render_template('home.html', posts=timeline('WHERE p.user_id=?', (user['id'],)),
                               feed='all', profile_user=user, people=sidebar())

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def error(exc):
        messages = {400: '入力内容を確認するか、ページを再読み込みしてください。',
                    403: 'この操作は許可されていません。', 404: 'ページや投稿が見つかりません。',
                    413: '送信されたデータが大きすぎます。'}
        return render_template('error.html', code=exc.code, message=messages[exc.code]), exc.code

    return app


if __name__ == '__main__':
    create_app().run(host='0.0.0.0', port=int(os.environ.get('PORT', '5000')), debug=False)

import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import create_app


class SNSTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.database = str(Path(self.tmp.name) / 'test.sqlite3')
        self.config = {'TESTING': True, 'SECRET_KEY': 'test-only-key', 'DATABASE': self.database}
        self.app = create_app(self.config)
        self.alice, self.bob, self.guest = (self.app.test_client() for _ in range(3))

    def tearDown(self):
        self.tmp.cleanup()

    def submit(self, client, path, data=None):
        page = client.get('/signup').get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
        return client.post(path, data={'csrf_token': token, **(data or {})}, follow_redirects=True)

    def register(self, client, name):
        return self.submit(client, '/signup', {'username': name, 'display_name': name.title(), 'password': 'testpass123'})

    def count(self, table):
        with sqlite3.connect(self.database) as db:
            return db.execute('SELECT count(*) FROM ' + table).fetchone()[0]

    def test_account_password_login_and_logout(self):
        self.assertIn('ようこそ', self.register(self.alice, 'alice').get_data(as_text=True))
        self.assertEqual(self.count('users'), 1)
        with sqlite3.connect(self.database) as db:
            saved = db.execute('SELECT password_hash FROM users').fetchone()[0]
            self.assertNotEqual(saved, 'testpass123')
        self.submit(self.alice, '/logout')
        invalid = self.submit(self.alice, '/login', {'username': 'alice', 'password': 'wrong'})
        self.assertIn('パスワードが違います', invalid.get_data(as_text=True))
        valid = self.submit(self.alice, '/login', {'username': 'ALICE', 'password': 'testpass123'})
        self.assertIn('マイプロフィール', valid.get_data(as_text=True))
        duplicate = self.register(self.bob, 'ALICE')
        self.assertIn('すでに使われています', duplicate.get_data(as_text=True))
        self.assertEqual(self.count('users'), 1)

    def test_posts_following_likes_profiles_and_delete(self):
        self.register(self.alice, 'alice')
        self.register(self.bob, 'bob')
        self.submit(self.alice, '/posts', {'body': 'Aliceの投稿'})
        self.submit(self.bob, '/posts', {'body': 'Bobの投稿'})
        public = self.guest.get('/').get_data(as_text=True)
        self.assertIn('Aliceの投稿', public)
        self.assertIn('Bobの投稿', public)
        before = self.alice.get('/?feed=following').get_data(as_text=True)
        self.assertIn('Aliceの投稿', before)
        self.assertNotIn('Bobの投稿', before)
        self.submit(self.alice, '/users/2/follow')
        self.assertEqual(self.count('follows'), 1)
        self.assertIn('Bobの投稿', self.alice.get('/?feed=following').get_data(as_text=True))
        self.assertIn('フォロー中 ✓', self.alice.get('/@bob').get_data(as_text=True))
        self.submit(self.alice, '/posts/2/like')
        self.assertEqual(self.count('likes'), 1)
        self.assertIn('aria-pressed="true"', self.alice.get('/').get_data(as_text=True))
        self.submit(self.alice, '/posts/2/like')
        self.assertEqual(self.count('likes'), 0)
        self.submit(self.alice, '/users/2/follow')
        self.assertEqual(self.count('follows'), 0)
        self.assertNotIn('Bobの投稿', self.alice.get('/?feed=following').get_data(as_text=True))
        self.assertEqual(self.submit(self.bob, '/posts/1/delete').status_code, 403)
        self.assertEqual(self.count('posts'), 2)
        self.submit(self.bob, '/posts/1/like')
        self.submit(self.alice, '/posts/1/delete')
        self.assertEqual(self.count('posts'), 1)
        self.assertEqual(self.count('likes'), 0)

    def test_csrf_and_unauthenticated_mutations(self):
        self.assertEqual(self.alice.post('/signup', data={'username': 'alice'}).status_code, 400)
        self.submit(self.guest, '/posts', {'body': 'unauthorized'})
        self.assertEqual(self.count('posts'), 0)
        self.register(self.alice, 'alice')
        self.assertEqual(self.alice.post('/posts', data={'csrf_token': 'wrong', 'body': 'x'}).status_code, 400)
        self.assertEqual(self.submit(self.alice, '/users/1/follow').status_code, 400)
        self.assertEqual(self.submit(self.alice, '/users/999/follow').status_code, 404)
        self.assertEqual(self.submit(self.alice, '/posts/999/like').status_code, 404)
        self.assertEqual(self.alice.get('/@missing').status_code, 404)

    def test_validation_and_xss(self):
        for name, display, password in [('x', 'X', 'testpass123'), ('good', '', 'testpass123'), ('good', 'Good', 'short')]:
            self.submit(self.alice, '/signup', {'username': name, 'display_name': display, 'password': password})
        self.assertEqual(self.count('users'), 0)
        self.register(self.alice, 'alice')
        for body in ['', '   ', 'あ' * 281]:
            self.submit(self.alice, '/posts', {'body': body})
        self.assertEqual(self.count('posts'), 0)
        self.submit(self.alice, '/posts', {'body': 'あ' * 280})
        self.assertEqual(self.count('posts'), 1)
        response = self.submit(self.alice, '/posts', {'body': '<script>alert(1)</script>'}).get_data(as_text=True)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', response)
        self.assertNotIn('<script>alert(1)</script>', response)

    def test_data_persists_across_restart(self):
        self.register(self.alice, 'alice')
        self.submit(self.alice, '/posts', {'body': '再起動後も残る投稿'})
        new_app = create_app(self.config)
        client = new_app.test_client()
        self.assertIn('再起動後も残る投稿', client.get('/').get_data(as_text=True))
        response = self.submit(client, '/login', {'username': 'alice', 'password': 'testpass123'})
        self.assertIn('マイプロフィール', response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()

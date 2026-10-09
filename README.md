# komorebi — ひとことから、つながろう。

Flask + SQLite で動く日本語の短文SNSです。登録済みのアカウントと投稿はSQLiteに保存されます。デモ投稿や固定ユーザーはありません。

## 機能

- アカウント登録、ログイン、ログアウト（ユーザー名・表示名・パスワード）
- 280文字までの投稿、自分の投稿の削除
- 全体／フォロー中のタイムライン（最新50件、自分の投稿も表示）
- いいね・いいね解除、フォロー・フォロー解除
- プロフィール、投稿数・フォロー数・フォロワー数
- スマートフォン対応、日本語UI

## 開発環境

Python 3.9と3.12で依存関係の導入とテストを確認しています。外部API、Node.js、DBサーバーは不要です。

```sh
cd /workspace/OriginalSNS
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python app.py
```

既存の`.venv`は再作成せず再利用できます。

Macで親フォルダ`SNS開発`に`.venv`を作成済みの場合は、次の手順で取得・起動できます。

```sh
cd "/Users/hw24a111/Desktop/SNS開発/OriginalSNS"
git pull --ff-only
../.venv/bin/python -m pip install -r requirements.txt
../.venv/bin/python app.py
```

`click==8.5.0`に関するエラーが出た古いチェックアウトは、`git pull --ff-only`でPython 3.9対応の依存関係に更新してください。インストールに失敗した場合は、そのエラーを解消してから起動してください。

開発サーバーはポート5000で起動します（`PORT`で変更可能）。停止はCtrl+Cです。ヘルス確認は`curl -fsS http://127.0.0.1:5000/`で行えます。画面からアカウントを作成して投稿してください。

## データと設定

初回起動で`instance/sns.sqlite3`を作成します。`instance/session.key`にはセッション署名用のランダムなキーを生成し、再起動時に再利用します。どちらもGit管理対象外です。テストは一時DBを使い、開発データを変更しません。

| 環境変数 | 用途 |
| --- | --- |
| `PORT` | 開発サーバーのポート（既定: 5000） |
| `SNS_DATABASE` | SQLiteファイルのパス（親ディレクトリは事前に作成） |
| `SNS_SECRET_KEY` | セッション署名キー。未設定ならローカルファイルを自動生成 |
| `SNS_SECURE_COOKIE` | HTTPSで運用する場合は`1`に設定 |

パスワードはscryptでハッシュ化し、状態変更はCSRFトークン付きPOSTに限定しています。HTMLエスケープ、SQLパラメータ、投稿削除の所有者確認も実装しています。

## 公開・運用について

この構成は開発用MVPです。公開はまだ行っていません。インターネット向けの運用では開発サーバーを使わず、WSGIサーバーとHTTPS、永続ディスク上のDB、適切なセッションキー管理を用意してください。SQLiteのバックアップはPythonのSQLite backup APIなどで整合性を保って取得します。多数の書き込みが必要になったらPostgreSQL等への移行を検討してください。

公開前にログイン・投稿のレート制限、不正利用対策、通報・管理機能、パスワードリセット、利用規約・プライバシーポリシー、監視・復旧手順の追加が必要です。このMVPにはメール認証、画像、返信、通知、アカウント削除、タイムラインのページ送りはありません。

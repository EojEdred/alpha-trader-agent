#!/usr/bin/env python3
"""
Schwab OAuth server with explicit URL printing.

Usage:
    python scripts/schwab_auth_server.py

Then open the printed URL in your browser, log in, click Done.
The server will catch the redirect and save the token.
"""

import os
import sys
import json
import time
import warnings
import webbrowser
import urllib.parse
import multiprocessing

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from authlib.integrations.httpx_client import OAuth2Client
from schwab.auth import TOKEN_ENDPOINT


def make_token_writer(token_path: str):
    def update_token(t, *args, **kwargs):
        wrapped = {"creation_timestamp": int(time.time()), "token": t}
        with open(token_path, 'w') as f:
            json.dump(wrapped, f, indent=2)
        print(f"\n💾 Token written to {token_path}")
    return update_token


def run_server(queue, port, path):
    """Flask server to catch OAuth redirect."""
    import flask
    import logging

    app = flask.Flask(__name__)
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)

    @app.route(path)
    def handle_token():
        queue.put(flask.request.url)
        return '<h1>Schwab auth received!</h1><p>You can close this tab.</p>'

    @app.route('/status')
    def status():
        return 'running'

    app.run(host='127.0.0.1', port=port, ssl_context='adhoc')


def wait_for_server(port, timeout=30):
    import urllib3
    import httpx
    start = time.time()
    while time.time() - start < timeout:
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore', category=urllib3.exceptions.InsecureRequestWarning)
                resp = httpx.get(f'https://127.0.0.1:{port}/status', verify=False)
                if resp.status_code == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.1)
    return False


def main():
    app_key = os.getenv("SCHWAB_APP_KEY")
    app_secret = os.getenv("SCHWAB_APP_SECRET")
    callback_url = os.getenv("SCHWAB_REDIRECT_URI", "https://127.0.0.1:8182")
    token_path = os.getenv("SCHWAB_TOKEN_PATH", "schwab_token.json")

    if not (app_key and app_secret):
        print("Error: SCHWAB_APP_KEY and SCHWAB_APP_SECRET must be set in .env")
        sys.exit(1)

    parsed = urllib.parse.urlparse(callback_url)
    port = parsed.port or 443
    path = parsed.path if parsed.path else '/'

    # Build auth URL
    oauth = OAuth2Client(app_key, redirect_uri=callback_url)
    auth_url, state = oauth.create_authorization_url(
        'https://api.schwabapi.com/v1/oauth/authorize'
    )

    print("=" * 70)
    print("Schwab OAuth server is starting...")
    print("=" * 70)

    # Start server in separate process
    queue = multiprocessing.Queue()
    server = multiprocessing.Process(target=run_server, args=(queue, port, path))
    server.start()

    try:
        if not wait_for_server(port):
            print("❌ Server failed to start")
            sys.exit(1)

        print(f"\n✅ Server listening on https://127.0.0.1:{port}")
        print("\n👉 Open this URL in your browser:")
        print(f"\n{auth_url}\n")
        print("Log in to Schwab, complete 2FA, and click 'Done'.")
        print("The server will catch the redirect automatically.\n")
        print("Waiting for callback... (timeout: 5 minutes)")

        # Wait for callback
        try:
            received_url = queue.get(timeout=300)
        except Exception:
            print("\n❌ Timed out waiting for callback")
            sys.exit(1)

        print(f"\n✅ Got callback: {received_url[:80]}...")

        # Exchange code for token
        token_write_func = make_token_writer(token_path)
        token = oauth.fetch_token(
            TOKEN_ENDPOINT,
            authorization_response=received_url,
            client_id=app_key,
            auth=(app_key, app_secret),
            state=state,
        )
        token_write_func(token)

        # Create client and verify
        from schwab.client import Client
        from schwab.auth import TokenMetadata

        load = lambda: json.load(open(token_path, 'rb'))
        update = token_write_func

        from schwab.auth import client_from_token_file
        client = client_from_token_file(token_path, app_key, app_secret)

        print("\n✅ Schwab authentication successful!")
        resp = client.get_account_numbers()
        if resp.status_code == 200:
            accounts = resp.json()
            print(f"Connected accounts: {[a.get('accountNumber') for a in accounts]}")
        else:
            print(f"Account check: HTTP {resp.status_code}")

    finally:
        server.terminate()
        server.join(timeout=5)


if __name__ == "__main__":
    main()

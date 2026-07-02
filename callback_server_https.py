import os
import sys
import json
import threading
import time
import ssl
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

import schwab.auth
from authlib.integrations.requests_client import OAuth2Session

APP_KEY = os.getenv('SCHWAB_APP_KEY')
APP_SECRET = os.getenv('SCHWAB_APP_SECRET')
REDIRECT_URI = os.getenv('SCHWAB_REDIRECT_URI')
TOKEN_PATH = os.getenv('SCHWAB_TOKEN_PATH', 'schwab_token.json')
CERT_DIR = Path(__file__).parent / 'certs'

if not all([APP_KEY, APP_SECRET, REDIRECT_URI]):
    print("Missing credentials in .env")
    sys.exit(1)

TOKEN_ENDPOINT = 'https://api.schwabapi.com/v1/oauth/token'
AUTH_ENDPOINT = 'https://api.schwabapi.com/v1/oauth/authorize'

session = OAuth2Session(APP_KEY, APP_SECRET, redirect_uri=REDIRECT_URI)
authorization_url, state = session.create_authorization_url(AUTH_ENDPOINT, response_type='code')

print("\n" + "="*70, flush=True)
print("STEP 1: Update your Schwab app callback URL to:", flush=True)
print(f"  {REDIRECT_URI}", flush=True)
print("="*70, flush=True)
print("\nSTEP 2: Click this authorization URL:", flush=True)
print(f"  {authorization_url}", flush=True)
print("="*70 + "\n", flush=True)

received_url = [None]

class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        received_url[0] = self.path
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b'<h1>Authorization received!</h1><p>You can close this window.</p>')
        print(f"\nReceived callback: {self.path[:120]}...", flush=True)
    
    def log_message(self, format, *args):
        pass

server = HTTPServer(('127.0.0.1', 8182), CallbackHandler)

# Wrap with SSL
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(CERT_DIR / 'localhost.crt', CERT_DIR / 'localhost.key')
server.socket = context.wrap_socket(server.socket, server_side=True)

def run_server():
    server.serve_forever()

thread = threading.Thread(target=run_server, daemon=True)
thread.start()

try:
    timeout = 600
    start = time.time()
    while received_url[0] is None and time.time() - start < timeout:
        time.sleep(0.1)
    
    if received_url[0] is None:
        print("\n❌ Timed out waiting for callback", flush=True)
        sys.exit(1)
    
    full_url = f'{REDIRECT_URI}{received_url[0]}'
    print(f"Full callback URL: {full_url[:120]}...", flush=True)
    
    print("\nExchanging authorization code for token...", flush=True)
    token = session.fetch_token(
        TOKEN_ENDPOINT,
        authorization_response=full_url,
        client_id=APP_KEY,
        auth=(APP_KEY, APP_SECRET),
        state=state,
    )
    
    print("\n=== RAW TOKEN RESPONSE ===", flush=True)
    print(json.dumps(token, indent=2, default=str), flush=True)
    print("==========================\n", flush=True)
    
    with open(TOKEN_PATH, 'w') as f:
        json.dump({
            'creation_timestamp': int(time.time()),
            'token': token,
        }, f, indent=2)
    print(f"✅ Token saved to {TOKEN_PATH}", flush=True)
    
    # Test it immediately
    import requests
    headers = {'Authorization': f'Bearer {token["access_token"]}', 'accept': 'application/json'}
    resp = requests.get('https://api.schwabapi.com/trader/v1/accounts/accountNumbers', headers=headers)
    print(f"\nAccount API test status: {resp.status_code}", flush=True)
    print(resp.json(), flush=True)
    
    print("\n🎉 Schwab authentication flow completed.", flush=True)
    server.shutdown()
except Exception as e:
    print(f"\n❌ Authentication failed: {e}", flush=True)
    import traceback
    traceback.print_exc()
    server.shutdown()
    sys.exit(1)

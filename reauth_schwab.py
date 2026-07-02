import os
import sys
import json
import ssl
import threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

from schwab.auth import client_from_received_url, AuthContext, get_auth_context

APP_KEY = os.getenv('SCHWAB_APP_KEY')
APP_SECRET = os.getenv('SCHWAB_APP_SECRET')
REDIRECT_URI = os.getenv('SCHWAB_REDIRECT_URI')
TOKEN_PATH = os.getenv('SCHWAB_TOKEN_PATH', 'schwab_token.json')
CERT_PATH = Path.home() / '.alphatrader' / 'certs' / 'localhost_cert.pem'
KEY_PATH = Path.home() / '.alphatrader' / 'certs' / 'localhost_key.pem'

if not all([APP_KEY, APP_SECRET, REDIRECT_URI]):
    print("Missing credentials in .env")
    sys.exit(1)

# Generate auth context and URL
auth_context = get_auth_context(APP_KEY, REDIRECT_URI)

print("\n=== CLICK THIS URL ===")
print(auth_context.authorization_url)
print("======================\n")
print("After clicking Allow, the browser should redirect automatically.")
print("This server will capture the callback and save the token.\n")

received_url = [None]

class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        received_url[0] = self.path
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b'<h1>Authorization received!</h1><p>You can close this window.</p>')
        print(f"\nReceived callback: {self.path[:80]}...")
    
    def log_message(self, format, *args):
        pass  # Suppress request logs

# Start HTTPS server
server = HTTPServer(('127.0.0.1', 8182), CallbackHandler)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(CERT_PATH, KEY_PATH)
server.socket = context.wrap_socket(server.socket, server_side=True)

def run_server():
    server.serve_forever()

thread = threading.Thread(target=run_server, daemon=True)
thread.start()

# Wait for callback
try:
    import time
    timeout = 300
    start = time.time()
    while received_url[0] is None and time.time() - start < timeout:
        time.sleep(0.1)
    
    if received_url[0] is None:
        print("\n❌ Timed out waiting for callback")
        sys.exit(1)
    
    # Reconstruct full URL
    full_url = f'https://127.0.0.1:8182{received_url[0]}'
    
    def token_write_func(token):
        with open(TOKEN_PATH, 'w') as f:
            json.dump(token, f, indent=2)
        print(f'Token saved to {TOKEN_PATH}')
    
    client = client_from_received_url(
        APP_KEY, APP_SECRET, auth_context, full_url, token_write_func,
        enforce_enums=False,
    )
    print("\n✅ Schwab authentication successful!")
    server.shutdown()
except Exception as e:
    print(f"\n❌ Authentication failed: {e}")
    import traceback
    traceback.print_exc()
    server.shutdown()
    sys.exit(1)

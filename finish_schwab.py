import os
import sys
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
if env_path.exists():
    load_dotenv(dotenv_path=env_path)

from schwab.auth import client_from_received_url, AuthContext

APP_KEY = os.getenv('SCHWAB_APP_KEY')
APP_SECRET = os.getenv('SCHWAB_APP_SECRET')
REDIRECT_URI = os.getenv('SCHWAB_REDIRECT_URI')
TOKEN_PATH = os.getenv('SCHWAB_TOKEN_PATH', 'schwab_token.json')

if len(sys.argv) < 2:
    print("Usage: python3 finish_schwab.py '<callback_url>'")
    sys.exit(1)

received_url = sys.argv[1]
parsed = urlparse(received_url)
params = parse_qs(parsed.query)
state = params.get('state', [None])[0]
code = params.get('code', [None])[0]

print(f'Code: {code[:30]}...' if code else 'No code')
print(f'State: {state}')

def token_write_func(token):
    with open(TOKEN_PATH, 'w') as f:
        json.dump(token, f, indent=2)
    print(f'Token written to {TOKEN_PATH}')

# Build authorization URL with matching state
auth_url = (
    f'https://api.schwabapi.com/v1/oauth/authorize?'
    f'response_type=code&client_id={APP_KEY}&redirect_uri='
    f'{REDIRECT_URI.replace(":", "%3A").replace("/", "%2F")}&state={state}'
)

# Create AuthContext manually with matching state
auth_context = AuthContext(
    callback_url=REDIRECT_URI,
    authorization_url=auth_url,
    state=state,
)

try:
    client = client_from_received_url(
        APP_KEY,
        APP_SECRET,
        auth_context,
        received_url,
        token_write_func,
        enforce_enums=False,
    )
    print('✅ Schwab authentication successful!')
except Exception as e:
    print(f'❌ Authentication failed: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)

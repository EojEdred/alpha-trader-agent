#!/usr/bin/env python3
"""
Schwab OAuth token exchange helper.

Usage:
    # Get the auth URL (run this first)
    python scripts/schwab_auth.py --url

    # After logging in and getting the redirect URL, complete the flow:
    python scripts/schwab_auth.py "https://127.0.0.1:8182/?code=ABC&session=XYZ"
"""

import json
import os
import sys
import argparse
from urllib.parse import urlparse, parse_qs

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from schwab.auth import get_auth_context, client_from_received_url


def make_token_writer(token_path: str):
    """Create a token write function compatible with schwab-py."""
    def update_token(t, *args, **kwargs):
        with open(token_path, 'w') as f:
            json.dump(t, f, indent=2)
    return update_token


def show_auth_url():
    """Print the Schwab OAuth authorization URL."""
    app_key = os.getenv("SCHWAB_APP_KEY")
    redirect_uri = os.getenv("SCHWAB_REDIRECT_URI", "https://127.0.0.1:8182")

    if not app_key:
        print("Error: SCHWAB_APP_KEY not set in .env")
        sys.exit(1)

    ctx = get_auth_context(app_key, redirect_uri)
    print(ctx.authorization_url)


def complete_flow(redirect_url: str):
    """Exchange the redirect URL for an access token and save it."""
    app_key = os.getenv("SCHWAB_APP_KEY")
    app_secret = os.getenv("SCHWAB_APP_SECRET")
    redirect_uri = os.getenv("SCHWAB_REDIRECT_URI", "https://127.0.0.1:8182")
    token_path = os.getenv("SCHWAB_TOKEN_PATH", "schwab_token.json")

    if not (app_key and app_secret):
        print("Error: SCHWAB_APP_KEY and SCHWAB_APP_SECRET must be set in .env")
        sys.exit(1)

    print(f"Completing OAuth flow...")
    print(f"Callback URL: {redirect_uri}")
    print(f"Token path:   {token_path}")

    try:
        # Extract the state from the received redirect URL to avoid CSRF mismatch
        parsed = urlparse(redirect_url)
        state = parse_qs(parsed.query).get("state", [None])[0]
        if not state:
            print("⚠️ Warning: no state found in redirect URL; generating fresh auth context")

        ctx = get_auth_context(app_key, redirect_uri, state=state)
        client = client_from_received_url(
            api_key=app_key,
            app_secret=app_secret,
            auth_context=ctx,
            received_url=redirect_url,
            token_write_func=make_token_writer(token_path),
            asyncio=False,
            enforce_enums=True,
        )
        print("✅ Schwab authentication successful!")

        # Quick verification
        resp = client.get_account_numbers()
        if resp.status_code == 200:
            accounts = resp.json()
            print(f"Connected accounts: {[a.get('accountNumber') for a in accounts]}")
        else:
            print(f"⚠️ Token saved but account check returned HTTP {resp.status_code}: {resp.text}")

    except Exception as e:
        print(f"❌ Authentication failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Schwab OAuth helper")
    parser.add_argument("redirect_url", nargs="?", help="Full redirect URL after Schwab login")
    parser.add_argument("--url", action="store_true", help="Print the authorization URL")
    args = parser.parse_args()

    if args.url:
        show_auth_url()
    elif args.redirect_url:
        complete_flow(args.redirect_url)
    else:
        parser.print_help()
        print("\nTo start, run: python scripts/schwab_auth.py --url")
        print("Then after login, run: python scripts/schwab_auth.py '<redirect URL>'")


if __name__ == "__main__":
    main()

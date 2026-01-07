"""
Token acquisition module for Schwab API.
Handles the initial OAuth flow to obtain tokens.
"""
import base64
import requests
import webbrowser
from loguru import logger
from typing import Tuple, Optional, Dict
from constants.parameters import SCHWAB_APP_KEY, SCHWAB_APP_SECRET
from schwab.tokens.storage import save_tokens


def construct_auth_url() -> Tuple[str, str, str]:
    """
    Construct the initial OAuth authorization URL.
    
    Returns:
        Tuple of (app_key, app_secret, auth_url)
    """
    app_key = SCHWAB_APP_KEY
    app_secret = SCHWAB_APP_SECRET
    
    auth_url = f"https://api.schwabapi.com/v1/oauth/authorize?client_id={app_key}&redirect_uri=https://127.0.0.1"
    
    logger.info("Click to authenticate:")
    logger.info(auth_url)
    
    return app_key, app_secret, auth_url


def parse_callback_url(returned_url: str) -> str:
    """
    Parse the authorization code from the callback URL.
    
    Args:
        returned_url: The full callback URL returned after authorization
    
    Returns:
        The authorization code
    """
    # Extract code from URL (format: ...code=XXX@...)
    if 'code=' in returned_url:
        code_start = returned_url.index('code=') + 5
        if '%40' in returned_url:
            code_end = returned_url.index('%40')
        else:
            # If no %40, code might extend to end or next parameter
            if '&' in returned_url[code_start:]:
                code_end = returned_url.index('&', code_start)
            else:
                code_end = len(returned_url)
        return f"{returned_url[code_start:code_end]}@"
    else:
        raise ValueError("No authorization code found in callback URL")


def construct_token_request_headers_and_payload(
    returned_url: str, 
    app_key: str, 
    app_secret: str
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Construct headers and payload for token exchange request.
    
    Args:
        returned_url: The callback URL from OAuth flow
        app_key: Schwab app key
        app_secret: Schwab app secret
    
    Returns:
        Tuple of (headers, payload) dictionaries
    """
    response_code = parse_callback_url(returned_url)
    
    credentials = f"{app_key}:{app_secret}"
    base64_credentials = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    
    headers = {
        "Authorization": f"Basic {base64_credentials}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    
    payload = {
        "grant_type": "authorization_code",
        "code": response_code,
        "redirect_uri": "https://127.0.0.1",
    }
    
    return headers, payload


def retrieve_tokens(headers: Dict[str, str], payload: Dict[str, str]) -> Dict:
    """
    Exchange authorization code for access and refresh tokens.
    
    Args:
        headers: HTTP headers for the token request
        payload: Request payload with authorization code
    
    Returns:
        Dictionary containing tokens and metadata
    """
    response = requests.post(
        url="https://api.schwabapi.com/v1/oauth/token",
        headers=headers,
        data=payload,
    )
    
    if response.status_code != 200:
        logger.error(f"Token acquisition failed: {response.status_code} - {response.text}")
        response.raise_for_status()
    
    return response.json()


def acquire_tokens() -> Optional[Dict]:
    """
    Complete OAuth flow to acquire initial tokens.
    Opens browser for user authorization.
    
    Returns:
        Dictionary containing tokens if successful, None otherwise
    """
    logger.info("Starting token acquisition process...")
    
    app_key, app_secret, auth_url = construct_auth_url()
    
    # Open browser for user authorization
    webbrowser.open(auth_url)
    
    logger.info("Please complete authorization in the browser.")
    logger.info("After authorization, paste the returned URL here:")
    returned_url = input().strip()
    
    if not returned_url:
        logger.error("No URL provided")
        return None
    
    try:
        # Construct request
        headers, payload = construct_token_request_headers_and_payload(
            returned_url, app_key, app_secret
        )
        
        # Exchange code for tokens
        token_dict = retrieve_tokens(headers, payload)
        
        logger.debug(f"Token acquisition response: {token_dict}")
        
        # Save tokens to secure storage
        if save_tokens(token_dict):
            logger.info("Tokens acquired and saved successfully")
            return token_dict
        else:
            logger.error("Failed to save tokens")
            return None
            
    except Exception as e:
        logger.error(f"Error during token acquisition: {e}")
        return None


if __name__ == "__main__":
    """Run token acquisition as standalone script."""
    result = acquire_tokens()
    if result:
        print("✓ Token acquisition completed successfully!")
    else:
        print("✗ Token acquisition failed")


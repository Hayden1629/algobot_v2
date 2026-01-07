"""
Token refresh module for Schwab API.
Handles refreshing access tokens using refresh tokens.
"""
import base64
import requests
from loguru import logger
from typing import Optional, Dict
from constants.parameters import SCHWAB_APP_KEY, SCHWAB_APP_SECRET
from schwab.tokens.storage import get_refresh_token, save_tokens


def refresh_tokens() -> Optional[Dict]:
    """
    Refresh access token using the stored refresh token.
    
    Returns:
        Dictionary containing new tokens if successful, None otherwise
    """
    logger.info("Refreshing access token...")
    
    # Get refresh token from storage
    refresh_token_value = get_refresh_token()
    if not refresh_token_value:
        logger.error("No refresh token found in storage. Please run token acquisition first.")
        return None
    
    # Construct request
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token_value,
    }
    
    credentials = f"{SCHWAB_APP_KEY}:{SCHWAB_APP_SECRET}"
    base64_credentials = base64.b64encode(credentials.encode()).decode()
    
    headers = {
        "Authorization": f'Basic {base64_credentials}',
        "Content-Type": "application/x-www-form-urlencoded",
    }
    
    # Make refresh request
    try:
        response = requests.post(
            url="https://api.schwabapi.com/v1/oauth/token",
            headers=headers,
            data=payload,
        )
        
        if response.status_code == 200:
            token_dict = response.json()
            
            # Save new tokens
            if save_tokens(token_dict):
                logger.info("Tokens refreshed and saved successfully")
                return token_dict
            else:
                logger.error("Failed to save refreshed tokens")
                return None
        else:
            logger.error(f"Token refresh failed: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Error refreshing tokens: {e}")
        return None


if __name__ == "__main__":
    """Run token refresh as standalone script."""
    result = refresh_tokens()
    if result:
        print("✓ Token refresh completed successfully!")
    else:
        print("✗ Token refresh failed")


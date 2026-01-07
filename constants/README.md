# Configuration Setup

## Setting up parameters.py

1. Copy the template file:
   ```bash
   cp constants/parameters.py.template constants/parameters.py
   ```

2. Edit `constants/parameters.py` and fill in your actual values:
   - `GODEL_USERNAME`: Your Godel Terminal email
   - `GODEL_PASSWORD`: Your Godel Terminal password
   - `SCHWAB_APP_KEY`: Your Schwab API app key
   - `SCHWAB_APP_SECRET`: Your Schwab API app secret

3. The `parameters.py` file is gitignored and will not be committed to the repository.

## Security Note

Never commit `parameters.py` or `schwab_tokens.json` to version control. These files contain sensitive credentials.


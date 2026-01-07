# Algobot v2

A modular, maintainable trading algorithm system that interfaces with Godel Terminal and Schwab API.

## Overview

Algobot v2 is a complete redesign of the original godel_api, built with maintainability and organization as core principles. The system is structured into clear, modular components that are easy to understand and maintain.

## Features

- **Modular Architecture**: Clear separation of concerns with dedicated packages
- **Token Management**: Automated Schwab API token acquisition, storage, and refresh
- **Database**: Local SQLite database for trade and PRT data storage
- **Godel Terminal Integration**: Framework for executing Godel Terminal commands
- **Maintainable Code**: Well-organized, documented, and following best practices

## Quick Start

### 1. Set Up Virtual Environment

```bash
cd algobot_v2
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Initialize System

```bash
python scripts/startup.py
```

This will:
- Initialize the database (if needed)
- Acquire tokens (if needed)
- Connect to Godel Terminal
- Prepare the system for use

## Project Structure

```
algobot_v2/
├── constants/      # Global parameters and configuration
├── tokens/         # Token management (acquisition, storage, refresh)
├── database/       # Database initialization and schema
├── core/           # Core framework (Godel Terminal controller)
├── commands/       # Godel Terminal command implementations
└── scripts/        # Utility and startup scripts
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed architecture documentation.

## Configuration

All configuration values are in `constants/parameters.py`. Key settings include:

- Godel Terminal credentials
- Schwab API credentials
- Token refresh intervals
- Database settings
- Trading parameters (stop loss, take profit, etc.)

## Usage

### Token Management

**Acquire tokens (first time)**:
```python
from tokens.acquisition import acquire_tokens
acquire_tokens()
```

**Get access token (in your code)**:
```python
from tokens.manager import get_token_manager
token_manager = get_token_manager()
access_token = token_manager.get_access_token()
```

### Database

**Initialize database**:
```python
from database.init import init_database
init_database()
```

**Get database connection**:
```python
from database.init import get_connection
conn = get_connection()
```

### Godel Terminal

**Use the controller**:
```python
from core.controller import GodelTerminalController
from constants.parameters import GODEL_USERNAME, GODEL_PASSWORD

controller = GodelTerminalController()
controller.connect()
controller.login(GODEL_USERNAME, GODEL_PASSWORD)
controller.load_layout("dev")
controller.open_terminal()

# Execute commands (once commands are implemented)
# result, cmd = controller.execute_command("DES", "AAPL", "EQ")
```

## Architecture Rules

This project follows strict architecture rules defined in [RULES.md](RULES.md):

1. **Organization**: Related components grouped in folders
2. **Modularity**: Separate files for different tasks
3. **Documentation**: Architecture markdown maintained after changes
4. **Constants**: All parameters in dedicated constants file

## Development

### Adding New Commands

1. Create a new command class in `commands/`
2. Inherit from `core.controller.BaseCommand`
3. Implement `get_command_string()` and `extract_data()`
4. Register with controller: `controller.register_command("COMMAND", CommandClass)`

### Adding New Features

1. Follow the modular structure
2. Update `ARCHITECTURE.md` after changes
3. Keep constants in `constants/parameters.py`
4. Maintain separation of concerns

## Requirements

- Python 3.8+
- Chrome browser (for Selenium)
- ChromeDriver (managed by webdriver-manager)

## License

[Your License Here]


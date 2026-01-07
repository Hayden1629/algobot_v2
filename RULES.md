# Architecture Rules for Algobot v2

These rules must be followed when designing and implementing the algobot_v2 architecture.

## 1. Organization Principle

**Everything must be organized. Keep related components in similar folders.**

- All related functionality should be grouped in dedicated directories
- Use clear, descriptive folder names that indicate their purpose
- Avoid flat directory structures with many files at the root level
- Group by feature/domain rather than by technical layer when possible

### Folder Structure:
```
algobot_v2/
├── tokens/          # All token-related functionality
├── database/        # Database initialization and management
├── core/            # Core framework (Godel terminal controller, base classes)
├── commands/        # Godel terminal commands (DES, PRT, etc.)
├── constants/       # Global constants and parameters
└── scripts/         # Utility and startup scripts
```

## 2. Modularity Principle

**Everything must be modules. Separate files for different tasks.**

- Each file should have a single, well-defined responsibility
- Related functionality should be split into separate modules, not combined
- Example: Token management should be split into:
  - `tokens/acquisition.py` - Initial token acquisition
  - `tokens/storage.py` - Token storage logic
  - `tokens/refresh.py` - Token refresh logic
  - `tokens/manager.py` - Token manager (orchestrates the above)

- Avoid monolithic files that handle multiple unrelated concerns
- Each module should be independently testable and maintainable

## 3. Architecture Documentation

**An architecture markdown file will be kept and maintained after every change.**

- `ARCHITECTURE.md` must exist and be kept up-to-date
- After every significant change, update the architecture documentation
- The architecture file must document:
  - Overall system structure
  - Folder organization and purpose
  - Class hierarchies and inheritance relationships
  - Control flow and how components interact
  - Module dependencies
  - Key design decisions

## 4. Constants Management

**Global constants (parameters and hyperparameters) will be kept in their own file.**

- All constants, parameters, and hyperparameters must be in `constants/parameters.py`
- No magic numbers or hardcoded values in business logic
- Constants should be clearly named and documented
- Examples:
  - Stop loss percentages
  - Take profit percentages
  - API endpoints
  - Timeouts and intervals
  - Database configuration (if not sensitive)

## 5. Additional Guidelines

### Code Quality
- Use type hints where appropriate
- Include docstrings for classes and functions
- Follow PEP 8 style guidelines
- Use meaningful variable and function names

### Error Handling
- Implement proper error handling and logging
- Use appropriate exception types
- Log errors with sufficient context

### Dependencies
- Keep `requirements.txt` up-to-date
- Pin dependency versions for reproducibility
- Document why each dependency is needed

### Testing
- Write tests for critical functionality
- Keep tests organized in a `tests/` directory
- Tests should be independent and repeatable

### Security
- Never commit sensitive credentials to version control
- Use environment variables or secure storage for secrets
- Follow principle of least privilege

## 6. Migration from godel_api

Use the old `godel_api` folder for guidance on how to create functionalities.
When porting functionality from the old `godel_api`:
- Only take what is needed
- Refactor to fit the new modular structure
- Don't copy spaghetti code - rewrite if necessary
- Maintain backward compatibility only where explicitly required

## 7. Maintenance

- Code should be maintainable and readable
- Complex logic should be broken down into smaller functions
- Avoid deep nesting and long functions
- Use design patterns where appropriate, but don't over-engineer

## 8. Trading-Specific Rules

- Always use limit orders whenever possible. Avoid using market orders unless limit orders have been repeatedly tried and failed (e.g., due to low liquidity), and log such instances.
- Implement mandatory risk controls: Enforce position sizing limits, daily loss limits, ensure all positions have stop losses or OCO stop loss/profit taking orders at all times unless they are about to be closed.
- Ensure all trades are logged with full audit trails, including decision rationale, entry/exit prices, and outcomes.
- Control loops should be aware of market hours and especially closing time. Under no circumstances should positions be open within 5 minutes of market close. 


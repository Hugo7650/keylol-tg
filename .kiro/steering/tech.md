# Technology Stack

## Language & Runtime
- Python 3.12+ (specified in pyproject.toml)
- Async/await pattern for concurrent operations

## Key Dependencies
- **pyrofork**: Telegram client library (fork of Pyrogram)
- **httpx**: HTTP client for forum scraping and async transport
- **lxml**: XML/HTML parsing for forum content
- **schedule**: Task scheduling
- **python-dotenv**: Environment variable management
- **tgcrypto**: Telegram encryption support

## Build System
- **uv**: Modern Python package manager (uv.lock present)
- **pyproject.toml**: Project configuration and dependencies

## Common Commands
```bash
# Install dependencies
pip install -e .

# Run the application
python main.py

# Setup configuration
cp .env.example .env
# Edit .env with your configuration
```

## Architecture Pattern
- Clean Architecture with domain-driven design principles
- Layered structure: domain, application, infrastructure, presentation
- Dependency injection and service-oriented design
- Async/await for I/O operations
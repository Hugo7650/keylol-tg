# Project Structure

## Root Level
- `main.py`: Application entry point and orchestration
- `config.py`: Configuration management with environment variables
- `pyproject.toml`: Project metadata and dependencies
- `.env`: Environment configuration (not in repo)
- `data/`: Runtime data storage (sessions, logs, cache)

## Clean Architecture Layers

### Domain Layer (`domain/`)
- `entities/`: Core business entities
- `value_objects/`: Immutable value types
- `repositories/`: Abstract repository interfaces
- `services/`: Domain business logic
- `exceptions/`: Domain-specific exceptions

### Application Layer (`application/`)
- `handlers/`: Application request handlers
- `services/`: Application orchestration services

### Infrastructure Layer (`infrastructure/`)
- `configuration/`: Configuration implementations
- `repositories/`: Concrete repository implementations
- `services/`: External service integrations
- `error_handling/`: Error handling utilities

### Presentation Layer (`presentation/`)
- User interface and API endpoints (currently empty)

## Legacy Structure (Being Refactored)
- `clients/`: External service clients (forum, telegram)
- `services/`: Business logic services
- `models/`: Data models and entities

## Conventions
- Use async/await for I/O operations
- Follow dependency injection patterns
- Keep domain layer pure (no external dependencies)
- Store runtime data in `data/` directory
- Use dataclasses for configuration and models
- Implement proper error handling with custom exceptions
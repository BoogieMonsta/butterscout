# Contributing to Butterscout

Thank you for your interest in contributing to Butterscout! We welcome contributions from the community to help make this the best open-source search and extraction API for LLM agents.

## Code of Conduct

Please be respectful and considerate of others. We want to maintain a welcoming and inclusive environment.

## How to Contribute

### Reporting Bugs

If you find a bug, please open an issue on GitHub using the [Bug Report template](.github/ISSUE_TEMPLATE/bug_report.md). Include as much detail as possible:
- Steps to reproduce
- Expected behavior
- Actual behavior
- Logs or error messages
- Your environment (OS, Docker version, etc.)

### Suggesting Enhancements

We love ideas! Open an issue to discuss your feature request before writing code. This ensures your work aligns with the project's roadmap.

### Pull Requests

1.  **Fork the repository** and create a new branch for your feature or fix.
2.  **Write code** that is clean, readable, and follows the project's style.
3.  **Add tests**! We aim for high test coverage (>80%).
4.  **Run tests** locally to ensure everything passes:
    ```bash
    pytest
    ```
5.  **Submit a Pull Request** (PR) to the `main` branch.
6.  Describe your changes in detail and link to any relevant issues.

## Development Setup

1.  **Clone the repo**:
    ```bash
    git clone https://github.com/BoogieMonsta/butterscout.git
    cd butterscout
    ```

2.  **Set up environment**:
    ```bash
    python -m venv .venv
    source .venv/bin/activate
    pip install -e ".[dev]"
    ```

3.  **Run dependencies** (Redis, SearXNG):
    ```bash
    docker compose up -d redis searxng
    ```

4.  **Run the app**:
    ```bash
    uvicorn butterscout.main:app --reload
    ```

## Style Guide

- We use `ruff` for linting and formatting.
- We use `mypy` for static type checking.
- Please run the following before submitting:
    ```bash
    ruff check .
    ruff format .
    mypy .
    ```

## License

By contributing, you agree that your contributions will be licensed under the [AGPLv3 License](LICENSE).

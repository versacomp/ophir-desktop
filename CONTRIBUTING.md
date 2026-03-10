# Contributing to ophir-desktop

Thank you for your interest in contributing. Contributions of all kinds are welcome — bug reports, new strategies, RL environment improvements, UI polish, and documentation.

## Getting Started

1. Fork the repository and clone your fork locally.
2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in your tastytrade sandbox credentials.
4. Run the app: `python src/main.py`

## Workflow

- **Branch** from `main` for every change (`git checkout -b feature/my-thing`).
- **Keep PRs focused** — one logical change per pull request.
- **Write clear commit messages** that explain *why*, not just *what*.
- Open a **draft PR** early if you want feedback before your work is finished.

## Coding Conventions

- Python 3.11+, PEP 8 style, 100-character line limit.
- Qt signals/slots for cross-thread communication — do not call UI methods directly from worker threads.
- All new strategy code belongs under `src/strategies/` or `src/sandbox/`.
- New environment variables must be documented in `.env.example`.

## Strategy Contributions

ophir-desktop is designed to be strategy-agnostic. If you have a rules-based or ML strategy to contribute:

- Implement it as a standalone Python class with a clear `on_candle(candle)` interface.
- Include a brief docstring describing the signal logic, intended instruments, and any known limitations.
- Back-test results or simulation logs are appreciated but not required.

## Reporting Bugs

Open a GitHub issue with:
- OS and Python version
- Steps to reproduce
- Expected vs. actual behaviour
- Any relevant log output from the terminal panel

## Security Issues

Do **not** open public issues for security vulnerabilities. Follow the process in [SECURITY.md](SECURITY.md).

## Code of Conduct

By participating in this project you agree to abide by the [Code of Conduct](CODE_OF_CONDUCT.md).

"""Allow ``python -m friday`` → same as the ``friday`` console script."""

from friday.cli import main

if __name__ == "__main__":
    main()

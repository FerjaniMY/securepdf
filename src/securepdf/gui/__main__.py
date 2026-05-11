"""Allow `python -m securepdf.gui` to launch the app."""

import sys

from securepdf.gui.app import main

if __name__ == "__main__":
    sys.exit(main())

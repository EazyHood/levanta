"""Never open a console over the user's screen.

A console process started from a parent that has no console of its own gets a fresh,
visible one, which is the opposite of what hiding the parent would suggest.  Jhona was pulled
out of a game by such windows on 2026-09-06, so every child process the bench starts carries
this flag.  On anything but Windows it is a no-op.
"""

import subprocess

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

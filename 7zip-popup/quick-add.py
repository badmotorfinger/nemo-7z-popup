#!/usr/bin/env python3
"""GTK 'Add to NAME.7z' quick action for the Nemo 7-Zip menu."""

import os
import sys

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402,F401

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import compress  # noqa: E402


def main():
    if len(sys.argv) < 2:
        compress.show_error("No files were passed to the action.")
        sys.exit(1)

    files = sys.argv[1:]
    working_dir = os.path.dirname(os.path.abspath(files[0]))

    if len(files) == 1:
        only = files[0]
        base = os.path.basename(only)
        if os.path.isdir(only):
            archive_name = base + ".7z"
        else:
            stem = os.path.splitext(base)[0] or base
            archive_name = stem + ".7z"
    else:
        archive_name = os.path.basename(working_dir) + ".7z"

    archive_path = os.path.join(working_dir, archive_name)

    if not compress.confirm_overwrite(archive_path):
        return

    basenames = [os.path.basename(f) for f in files]
    extra_args = ["-t7z", "-mx=5", "-m0=LZMA2"]

    compress.run_compression(
        archive_path=archive_path,
        working_dir=working_dir,
        basenames=basenames,
        extra_args=extra_args,
        title="Creating " + archive_name,
    )


if __name__ == "__main__":
    main()

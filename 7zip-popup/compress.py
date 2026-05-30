"""Shared compression helper used by add-to-archive.py and quick-add.py.

Public API:
  run_compression(archive_path, working_dir, basenames, extra_args, title, parent=None) -> bool
  confirm_overwrite(archive_path, parent=None) -> bool
  show_error(message_markup, parent=None)
"""

import datetime
import os
import re
import shlex
import shutil

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Gio, Pango  # noqa: E402

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
PERCENT_RE = re.compile(r"^\s*(\d+)%(.*)$")
FILE_IN_REST_RE = re.compile(r"[-+=U]\s+(.+?)\s*$")
COMPRESSING_RE = re.compile(r"^Compressing\s+(.+?)\s*$")

DEBUG_LOG_NAME = "7zip-popup-debug.log"


def _mask_args(args):
    # The 7z password switch is -p<password> (no other 7z switch starts with -p).
    out = []
    for a in args:
        if a.startswith("-p") and len(a) > 2:
            out.append("-p***")
        else:
            out.append(a)
    return out


_SPLIT_SUFFIX_RE = re.compile(r"^\d{3,}(?:\.tmp)?$")


def _archive_companions(archive_path):
    """Return all files associated with this archive: the archive itself, its
    split-volume parts (.001, .002, ..., including 4+ digit ones for huge
    archives), and any .tmp files 7z may have written alongside."""
    paths = []
    if os.path.exists(archive_path):
        paths.append(archive_path)
    tmp = archive_path + ".tmp"
    if os.path.exists(tmp):
        paths.append(tmp)
    parent = os.path.dirname(archive_path) or "."
    base = os.path.basename(archive_path)
    prefix = base + "."
    try:
        entries = os.listdir(parent)
    except OSError:
        entries = []
    for entry in entries:
        if entry.startswith(prefix) and _SPLIT_SUFFIX_RE.match(entry[len(prefix):]):
            paths.append(os.path.join(parent, entry))
    return paths


def _remove_archive_files(archive_path):
    """Delete the archive plus any split-volume / temp companion files.
    Returns the list of files that were actually deleted."""
    removed = []
    for p in _archive_companions(archive_path):
        try:
            os.remove(p)
            removed.append(p)
        except OSError:
            pass
    return removed


def _open_debug_log(working_dir):
    candidates = [
        os.path.join(working_dir, DEBUG_LOG_NAME),
        os.path.join(GLib.get_user_cache_dir(), DEBUG_LOG_NAME),
        os.path.join("/tmp", DEBUG_LOG_NAME),
    ]
    for path in candidates:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            fh = open(path, "a", encoding="utf-8", errors="replace")
            return fh, path
        except OSError:
            continue
    return None, None


def _count_files(working_dir, basenames):
    total = 0
    for name in basenames:
        path = os.path.join(working_dir, name)
        if os.path.isdir(path):
            for _, _, files in os.walk(path):
                total += len(files)
        elif os.path.exists(path):
            total += 1
    return max(total, 1)


def show_error(message_markup, parent=None):
    dlg = Gtk.MessageDialog(
        transient_for=parent,
        modal=True,
        message_type=Gtk.MessageType.ERROR,
        buttons=Gtk.ButtonsType.CLOSE,
        text="7-Zip",
    )
    dlg.set_icon_name("package-x-generic")
    dlg.format_secondary_markup(message_markup)
    dlg.set_default_size(680, 200)
    dlg.run()
    dlg.destroy()


def confirm_overwrite(archive_path, parent=None):
    """Ask the user whether to replace an existing archive. If yes, also
    delete it (and any split-volume companions) so 7z starts fresh instead
    of trying to open a possibly-corrupt file as an existing archive."""
    # Check companions too: a split archive leaves foo.7z.001/.002... with no
    # bare foo.7z, and re-running -v over existing volumes fails (E_NOTIMPL).
    if not _archive_companions(archive_path):
        return True
    dlg = Gtk.MessageDialog(
        transient_for=parent,
        modal=True,
        message_type=Gtk.MessageType.QUESTION,
        buttons=Gtk.ButtonsType.NONE,
        text="Archive already exists",
    )
    dlg.set_icon_name("package-x-generic")
    dlg.format_secondary_markup(
        "<b>{}</b> already exists.\n\nReplace it?".format(
            GLib.markup_escape_text(os.path.basename(archive_path))
        )
    )
    dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Replace", Gtk.ResponseType.OK)
    rc = dlg.run()
    dlg.destroy()
    if rc != Gtk.ResponseType.OK:
        return False
    _remove_archive_files(archive_path)
    return True


class _ProgressDialog(Gtk.Dialog):
    def __init__(self, title, archive_path, parent=None):
        super().__init__(title=title, transient_for=parent, modal=True)
        self.set_icon_name("package-x-generic")
        self.set_default_size(640, -1)
        self.set_resizable(False)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)

        box = self.get_content_area()
        box.set_spacing(10)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(16)
        box.set_margin_end(16)

        header = Gtk.Label(xalign=0)
        header.set_markup(
            "Compressing into:\n<tt>{}</tt>".format(GLib.markup_escape_text(archive_path))
        )
        header.set_line_wrap(True)
        header.set_selectable(False)
        box.add(header)

        self.status = Gtk.Label(xalign=0)
        self.status.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.status.set_max_width_chars(70)
        box.add(self.status)

        self.bar = Gtk.ProgressBar()
        self.bar.set_show_text(True)
        box.add(self.bar)

        self.show_all()


class _Runner:
    """One-shot 7z runner driving a _ProgressDialog through GLib async I/O."""

    def __init__(self, archive_path, working_dir, basenames, extra_args, title, parent):
        self.archive_path = archive_path
        self.working_dir = working_dir
        self.basenames = basenames
        # 7z block-buffers stdout when writing to a pipe instead of a TTY,
        # so all the \r-separated progress lines accumulate and only flush
        # when the process exits. stdbuf -o0 disables that buffering so the
        # progress dialog actually updates in real time.
        prefix = ["stdbuf", "-o0"] if shutil.which("stdbuf") else []
        self.cmd = (
            prefix
            + ["7z", "a"] + list(extra_args)
            + ["-y", "-bsp1", "-bso1", "-bse2", "--", archive_path]
            + list(basenames)
        )
        self.dialog = _ProgressDialog(title, archive_path, parent)
        self.parent = parent

        self.total_files = _count_files(working_dir, basenames)
        self.file_count = 0
        self.saw_pct = False
        self.last_pct = -1
        self.last_file = None

        self.stdout_buf = ""
        self.stderr_buf = bytearray()

        self.cancelled = False
        self.exit_status = None
        self.proc = None
        self._tick_id = None

        self.log_fh, self.log_path = _open_debug_log(working_dir)

    def _log(self, text):
        if self.log_fh is None:
            return
        try:
            self.log_fh.write(text)
            self.log_fh.flush()
        except OSError:
            pass

    def _log_header(self):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        masked = " ".join(shlex.quote(a) for a in _mask_args(self.cmd))
        sep = "=" * 70
        header = (
            "\n{sep}\n"
            "[{ts}] 7-Zip popup\n"
            "Working dir : {cwd}\n"
            "Archive     : {arc}\n"
            "Basenames   : {bn}\n"
            "Total files : {n}\n"
            "Command     : {cmd}\n"
            "{sep}\n"
        ).format(
            sep=sep, ts=ts,
            cwd=self.working_dir,
            arc=self.archive_path,
            bn=", ".join(self.basenames),
            n=self.total_files,
            cmd=masked,
        )
        self._log(header)

    def start(self):
        self.dialog.connect("response", self._on_response)
        self.dialog.connect("delete-event", lambda *a: self._on_response(None, Gtk.ResponseType.CANCEL))

        self.dialog.status.set_text(
            "Preparing {} ({} file(s))...".format(
                os.path.basename(self.archive_path), self.total_files
            )
        )
        self.bar_set(0, "0%")

        self._log_header()

        launcher = Gio.SubprocessLauncher.new(
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
        )
        launcher.set_cwd(self.working_dir)
        try:
            self.proc = launcher.spawnv(self.cmd)
        except GLib.Error as exc:
            self._log("\n--- spawn failed ---\n{}\n".format(exc))
            self._close_log()
            self.dialog.destroy()
            show_error(
                "Failed to launch <tt>7z</tt>:\n\n<tt>{}</tt>".format(
                    GLib.markup_escape_text(str(exc))
                ),
                self.parent,
            )
            return False

        self.proc.get_stdout_pipe().read_bytes_async(
            8192, GLib.PRIORITY_DEFAULT, None, self._on_stdout
        )
        self.proc.get_stderr_pipe().read_bytes_async(
            8192, GLib.PRIORITY_DEFAULT, None, self._on_stderr
        )
        self.proc.wait_async(None, self._on_proc_done)

        # Periodic re-apply of the last known fraction. Timer callbacks fire
        # in GLib's idle phase where paints reliably process, so even if the
        # I/O-phase pump can't get paints through, this drives them.
        self._tick_id = GLib.timeout_add(100, self._tick)

        self.dialog.run()
        if self._tick_id is not None:
            try:
                GLib.source_remove(self._tick_id)
            except (GLib.Error, ValueError):
                pass
            self._tick_id = None
        self.dialog.destroy()

        self._log("\n--- exit ---\nstatus  : {}\ncancelled: {}\n".format(
            self.exit_status, self.cancelled
        ))

        if self.cancelled or (self.exit_status not in (0, None)):
            removed = _remove_archive_files(self.archive_path)
            if removed:
                self._log("removed partial files:\n  " + "\n  ".join(removed) + "\n")
            else:
                self._log("no partial files to remove\n")

        self._close_log()

        if self.cancelled:
            return False
        if self.exit_status == 0:
            return True

        err = bytes(self.stderr_buf).decode("utf-8", errors="replace").strip()
        log_hint = ""
        if self.log_path:
            log_hint = "\n\nDebug log:\n<tt>{}</tt>".format(
                GLib.markup_escape_text(self.log_path)
            )
        show_error(
            "<b>7z exited with status {}</b>\n\n<tt>{}</tt>{}".format(
                self.exit_status if self.exit_status is not None else "?",
                GLib.markup_escape_text(err) or "(no error output)",
                log_hint,
            ),
            self.parent,
        )
        return False

    def _close_log(self):
        if self.log_fh is not None:
            try:
                self.log_fh.close()
            except OSError:
                pass
            self.log_fh = None

    def bar_set(self, fraction, text):
        clamped = max(0.0, min(1.0, fraction))
        self.bar.set_fraction(clamped)
        self.bar.set_text(text)
        self.bar.queue_draw()
        self._log("[bar_set] fraction={:.3f} text={!r} (queried back: {:.3f})\n".format(
            clamped, text, self.bar.get_fraction()
        ))

    def _tick(self):
        """Periodic refresh. Re-applies the last known fraction every 100 ms so
        the fill paints visibly even if the I/O-phase event pump isn't getting
        paint events through for some reason."""
        if self.last_pct >= 0:
            self.bar.set_fraction(self.last_pct / 100.0)
            self.bar.queue_draw()
        return True  # keep timer running

    @property
    def bar(self):
        return self.dialog.bar

    def _on_response(self, _dlg, response):
        if response in (Gtk.ResponseType.CANCEL, Gtk.ResponseType.DELETE_EVENT):
            self.cancelled = True
            if self.proc is not None:
                try:
                    self.proc.force_exit()
                except GLib.Error:
                    pass

    def _process_line(self, line):
        raw = line
        line = ANSI_RE.sub("", line).rstrip()
        if not line:
            return

        m = PERCENT_RE.match(line)
        if m:
            pct = int(m.group(1))
            rest = m.group(2)
            self.saw_pct = True
            self._log("[line] pct={} raw={!r}\n".format(pct, raw))
            if pct != self.last_pct:
                self.last_pct = pct
                self.bar_set(pct / 100.0, "{}%".format(pct))
            fm = FILE_IN_REST_RE.search(rest)
            if fm:
                name = fm.group(1).strip()
                if name and name != self.last_file:
                    self.last_file = name
                    self.dialog.status.set_text("Adding: {}".format(name))
            return

        cm = COMPRESSING_RE.match(line)
        if cm:
            name = cm.group(1).strip()
            if name != self.last_file:
                self.last_file = name
                self.file_count += 1
                if not self.saw_pct:
                    pct = min(100, int(self.file_count * 100 / self.total_files))
                    self.bar_set(pct / 100.0, "{}%".format(pct))
                self.dialog.status.set_text("Adding: {}".format(name))

    def _on_stdout(self, source, result):
        try:
            data = source.read_bytes_finish(result)
        except GLib.Error:
            return
        if data is None or data.get_size() == 0:
            for chunk in re.split(r"[\r\n]", self.stdout_buf):
                self._process_line(chunk)
            self.stdout_buf = ""
            return
        chunk_bytes = data.get_data()
        chunk_str = chunk_bytes.decode("utf-8", errors="replace")
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._log("\n[chunk {} {}B] raw={!r}\n".format(ts, len(chunk_bytes), chunk_str))
        self.stdout_buf += chunk_str
        # 7z 23.x uses \x08 (backspace) sequences to overwrite progress lines in
        # place — NOT \r as older builds did. Splitting on \b too is what makes
        # progress events visible to the parser.
        parts = re.split(r"[\r\n\x08]+", self.stdout_buf)
        self.stdout_buf = parts[-1]
        self._log("[split parts={} kept={!r}]\n".format(len(parts), self.stdout_buf))
        for chunk in parts[:-1]:
            self._process_line(chunk)
        # Trailing partial buffer is now safe to process: FILE_IN_REST_RE stops
        # at the next "\s\d+%", and last_pct/last_file de-dup repeats.
        if self.stdout_buf:
            self._process_line(self.stdout_buf)
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        source.read_bytes_async(8192, GLib.PRIORITY_DEFAULT, None, self._on_stdout)

    def _on_stderr(self, source, result):
        try:
            data = source.read_bytes_finish(result)
        except GLib.Error:
            return
        if data is None or data.get_size() == 0:
            return
        chunk = data.get_data()
        self.stderr_buf.extend(chunk)
        self._log("[stderr] " + chunk.decode("utf-8", errors="replace"))
        source.read_bytes_async(8192, GLib.PRIORITY_DEFAULT, None, self._on_stderr)

    def _on_proc_done(self, proc, result):
        try:
            proc.wait_finish(result)
        except GLib.Error:
            self.exit_status = -1
        else:
            if proc.get_if_exited():
                self.exit_status = proc.get_exit_status()
            else:
                self.exit_status = -1

        self.bar_set(1.0, "100%")
        self.dialog.status.set_text("Done")

        def close_dialog():
            self.dialog.response(Gtk.ResponseType.OK)
            return False

        GLib.timeout_add(150, close_dialog)


def run_compression(archive_path, working_dir, basenames, extra_args, title, parent=None):
    if shutil.which("7z") is None:
        show_error(
            "The <b>7z</b> command was not found.\n\n"
            "Install it with:\n\n<tt>sudo apt install p7zip-full</tt>",
            parent,
        )
        return False
    runner = _Runner(archive_path, working_dir, basenames, extra_args, title, parent)
    return runner.start()

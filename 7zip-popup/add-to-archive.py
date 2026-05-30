#!/usr/bin/env python3
"""GTK 'Add to Archive' dialog for the Nemo 7-Zip menu."""

import os
import sys

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import compress  # noqa: E402

METHODS_BY_FORMAT = {
    "7z":  ["LZMA2", "LZMA", "PPMd", "BZip2", "Deflate", "Copy"],
    "zip": ["Deflate", "Deflate64", "BZip2", "LZMA", "PPMd"],
    "tar": ["GNU", "POSIX", "USTAR"],
}
LEVELS       = ["Store", "Fastest", "Fast", "Normal", "Maximum", "Ultra"]
DICT_SIZES   = ["64 KB", "1 MB", "4 MB", "16 MB", "64 MB", "256 MB", "1 GB", "1536 MB"]
WORD_SIZES   = ["8", "12", "16", "24", "32", "48", "64", "96", "128", "192", "273"]
SOLID_SIZES  = ["Non-solid", "1 MB", "2 MB", "4 MB", "8 MB", "16 MB", "32 MB",
                "64 MB", "128 MB", "256 MB", "512 MB", "1 GB", "2 GB", "4 GB",
                "8 GB", "16 GB", "32 GB", "64 GB", "Solid"]
MEM_LEVELS   = ["10%", "20%", "30%", "40%", "50%", "60%", "70%", "80%", "90%", "100%"]
SPLIT_PRESETS = ["", "10M", "100M", "650M - CD", "700M - CD",
                 "4480M - DVD", "8128M - DVD DL", "23040M - BD"]
UPDATE_MODES = ["Add and replace files", "Update and add files",
                "Freshen existing files", "Synchronize files"]
PATH_MODES   = ["Relative pathnames", "Full pathnames", "Absolute pathnames"]

LEVEL_TO_MX = {"Store": "0", "Fastest": "1", "Fast": "3",
               "Normal": "5", "Maximum": "7", "Ultra": "9"}

INVALID_CSS = b"""
entry.invalid { border-color: #d33; box-shadow: inset 0 0 0 1px #d33; }
"""


def total_mem_gb():
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024 // 1024
    except OSError:
        pass
    return 0


def to_7z_size(s):
    return s.lower().replace(" ", "").rstrip("b")


def fix_extension(path, fmt):
    base, ext = os.path.splitext(path)
    if ext.lower() != "." + fmt:
        return base + "." + fmt
    return path


def default_archive_name(files):
    first = files[0]
    if len(files) == 1:
        base = os.path.basename(first)
        if os.path.isdir(first):
            return base
        stem = os.path.splitext(base)[0]
        return stem or base
    return os.path.basename(os.path.dirname(first))


class AddToArchiveDialog(Gtk.Dialog):
    def __init__(self, files):
        super().__init__(title="Add to Archive", modal=True)
        self.set_icon_name("package-x-generic")
        self.set_default_size(760, -1)
        self.set_resizable(False)

        self.files = files
        self.working_dir = os.path.dirname(os.path.abspath(files[0]))
        self.basenames = [os.path.basename(f) for f in files]
        default_name = default_archive_name(files)
        self._default_archive = os.path.join(self.working_dir, default_name + ".7z")

        self.add_button("Help", Gtk.ResponseType.HELP)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.ok_button = self.add_button("OK", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        self._install_css()
        self._build_ui()
        self._connect_signals()
        self._apply_format_rules()

    def _install_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(INVALID_CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _build_ui(self):
        outer = self.get_content_area()
        outer.set_spacing(10)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        outer.set_margin_start(14)
        outer.set_margin_end(14)

        archive_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        archive_row.pack_start(Gtk.Label(label="Archive:", xalign=0), False, False, 0)
        self.archive_entry = Gtk.Entry(hexpand=True)
        self.archive_entry.set_text(self._default_archive)
        archive_row.pack_start(self.archive_entry, True, True, 0)
        browse = Gtk.Button(label="...")
        browse.connect("clicked", self._on_browse)
        archive_row.pack_start(browse, False, False, 0)
        outer.add(archive_row)

        columns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        outer.add(columns)

        left = Gtk.Grid(row_spacing=6, column_spacing=10)
        right = Gtk.Grid(row_spacing=6, column_spacing=10)
        columns.pack_start(left, True, True, 0)
        columns.pack_start(right, True, True, 0)

        # --- Left column ---
        r = 0
        self.format_combo = self._combo_row(left, r, "Archive format:", ["7z", "zip", "tar"], "7z");          r += 1
        self.level_combo  = self._combo_row(left, r, "Compression level:", LEVELS, "Normal");                  r += 1
        self.method_combo = self._combo_row(left, r, "Compression method:", METHODS_BY_FORMAT["7z"], "LZMA2"); r += 1
        self.dict_combo   = self._combo_row(left, r, "Dictionary size:", DICT_SIZES, "16 MB");                 r += 1
        self.word_combo   = self._combo_row(left, r, "Word size:", WORD_SIZES, "32");                          r += 1
        self.solid_combo  = self._combo_row(left, r, "Solid Block size:", SOLID_SIZES, "4 GB");                r += 1

        left.attach(Gtk.Label(label="CPU threads:", xalign=0), 0, r, 1, 1)
        cpu = os.cpu_count() or 1
        adj = Gtk.Adjustment(value=cpu, lower=1, upper=cpu, step_increment=1)
        self.threads_spin = Gtk.SpinButton(adjustment=adj, numeric=True)
        left.attach(self.threads_spin, 1, r, 1, 1); r += 1

        mem_label = "Memory for Compressing\n({} GB total):".format(total_mem_gb())
        self.mem_combo = self._combo_row(left, r, mem_label, MEM_LEVELS, "80%"); r += 1

        left.attach(Gtk.Label(label="Memory for Decompressing:", xalign=0), 0, r, 1, 1)
        self.mem_decomp_label = Gtk.Label(label="—", xalign=0)
        left.attach(self.mem_decomp_label, 1, r, 1, 1); r += 1

        left.attach(Gtk.Label(label="Split to volumes:", xalign=0), 0, r, 1, 1)
        self.split_combo = Gtk.ComboBoxText.new_with_entry()
        for s in SPLIT_PRESETS:
            self.split_combo.append_text(s)
        self.split_combo.set_active(0)
        self.split_combo.set_hexpand(True)
        left.attach(self.split_combo, 1, r, 1, 1); r += 1

        left.attach(Gtk.Label(label="Parameters:", xalign=0), 0, r, 1, 1)
        self.params_entry = Gtk.Entry(hexpand=True)
        left.attach(self.params_entry, 1, r, 1, 1); r += 1

        # --- Right column ---
        r = 0
        self.update_combo = self._combo_row(right, r, "Update mode:", UPDATE_MODES); r += 1
        self.path_combo   = self._combo_row(right, r, "Path mode:", PATH_MODES);     r += 1

        opts_frame = Gtk.Frame(label="Options")
        opts_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        opts_box.set_margin_top(6); opts_box.set_margin_bottom(8)
        opts_box.set_margin_start(10); opts_box.set_margin_end(10)
        self.shared_check  = Gtk.CheckButton(label="Compress shared files")
        self.delete_check  = Gtk.CheckButton(label="Delete files after compression")
        for w in (self.shared_check, self.delete_check):
            opts_box.add(w)
        opts_frame.add(opts_box)
        right.attach(opts_frame, 0, r, 2, 1); r += 1

        enc_frame = Gtk.Frame(label="Encryption")
        enc_grid = Gtk.Grid(row_spacing=4, column_spacing=8)
        enc_grid.set_margin_top(6); enc_grid.set_margin_bottom(8)
        enc_grid.set_margin_start(10); enc_grid.set_margin_end(10)
        enc_frame.add(enc_grid)
        right.attach(enc_frame, 0, r, 2, 1); r += 1

        er = 0
        enc_grid.attach(Gtk.Label(label="Enter password:", xalign=0), 0, er, 1, 1)
        self.password_entry = Gtk.Entry(visibility=False, hexpand=True)
        enc_grid.attach(self.password_entry, 1, er, 1, 1); er += 1
        enc_grid.attach(Gtk.Label(label="Reenter password:", xalign=0), 0, er, 1, 1)
        self.repassword_entry = Gtk.Entry(visibility=False, hexpand=True)
        enc_grid.attach(self.repassword_entry, 1, er, 1, 1); er += 1
        self.show_password_check = Gtk.CheckButton(label="Show password")
        enc_grid.attach(self.show_password_check, 1, er, 1, 1); er += 1
        self.encrypt_names_check = Gtk.CheckButton(label="Encrypt file names")
        enc_grid.attach(self.encrypt_names_check, 1, er, 1, 1)

        self.show_all()

    def _combo_row(self, grid, row, label, items, default=None):
        grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
        combo = Gtk.ComboBoxText()
        for it in items:
            combo.append_text(it)
        if default and default in items:
            combo.set_active(items.index(default))
        else:
            combo.set_active(0)
        combo.set_hexpand(True)
        grid.attach(combo, 1, row, 1, 1)
        return combo

    def _connect_signals(self):
        self.format_combo.connect("changed", self._on_format_changed)
        self.show_password_check.connect("toggled", self._on_show_password_toggled)
        self.password_entry.connect("changed", self._on_password_changed)
        self.repassword_entry.connect("changed", self._on_password_changed)
        self.connect("response", self._on_response)

    def _on_browse(self, _btn):
        dlg = Gtk.FileChooserDialog(
            title="Choose archive path",
            transient_for=self,
            action=Gtk.FileChooserAction.SAVE,
        )
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Select", Gtk.ResponseType.OK)
        current = self.archive_entry.get_text()
        if current:
            folder = os.path.dirname(current) or self.working_dir
            dlg.set_current_folder(folder)
            dlg.set_current_name(os.path.basename(current))
        if dlg.run() == Gtk.ResponseType.OK:
            self.archive_entry.set_text(dlg.get_filename())
        dlg.destroy()

    def _on_format_changed(self, combo):
        fmt = combo.get_active_text()
        current = self.archive_entry.get_text().strip()
        if current:
            self.archive_entry.set_text(fix_extension(current, fmt))
        self._refill_combo(self.method_combo, METHODS_BY_FORMAT[fmt])
        self._apply_format_rules()

    @staticmethod
    def _refill_combo(combo, items):
        combo.remove_all()
        for it in items:
            combo.append_text(it)
        combo.set_active(0 if items else -1)

    def _apply_format_rules(self):
        fmt = self.format_combo.get_active_text()
        is_7z  = fmt == "7z"
        is_tar = fmt == "tar"
        not_tar = not is_tar

        self.level_combo.set_sensitive(not_tar)
        self.method_combo.set_sensitive(not_tar)
        self.dict_combo.set_sensitive(is_7z)
        self.word_combo.set_sensitive(is_7z)
        self.solid_combo.set_sensitive(is_7z)
        self.threads_spin.set_sensitive(not_tar)
        self.mem_combo.set_sensitive(not_tar)
        self.password_entry.set_sensitive(not_tar)
        self.repassword_entry.set_sensitive(not_tar)
        self.show_password_check.set_sensitive(not_tar)
        self.encrypt_names_check.set_sensitive(is_7z)

        if is_tar:
            self.level_combo.set_active(LEVELS.index("Store"))
            self.password_entry.set_text("")
            self.repassword_entry.set_text("")

    def _on_show_password_toggled(self, check):
        visible = check.get_active()
        self.password_entry.set_visibility(visible)
        self.repassword_entry.set_visibility(visible)

    def _on_password_changed(self, _entry):
        pw1 = self.password_entry.get_text()
        pw2 = self.repassword_entry.get_text()
        mismatch = bool(pw1) and pw1 != pw2
        for entry in (self.password_entry, self.repassword_entry):
            ctx = entry.get_style_context()
            if mismatch:
                ctx.add_class("invalid")
            else:
                ctx.remove_class("invalid")
        self.ok_button.set_sensitive(not mismatch)

    def _on_response(self, _dlg, response):
        if response == Gtk.ResponseType.HELP:
            self._show_help()
            self.stop_emission_by_name("response")

    def _show_help(self):
        dlg = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.CLOSE,
            text="Add to Archive",
        )
        dlg.format_secondary_markup(
            "Fields that are greyed out don't apply to the selected archive format.\n\n"
            "<b>7z</b>  full feature set\n"
            "<b>zip</b>  no solid blocks, no filename encryption\n"
            "<b>tar</b>  pure container — no compression or encryption options"
        )
        dlg.run()
        dlg.destroy()

    def collect(self):
        return {
            "archive":        self.archive_entry.get_text().strip(),
            "format":         self.format_combo.get_active_text(),
            "level":          self.level_combo.get_active_text(),
            "method":         self.method_combo.get_active_text(),
            "dict":           self.dict_combo.get_active_text(),
            "word":           self.word_combo.get_active_text(),
            "solid":          self.solid_combo.get_active_text(),
            "threads":        self.threads_spin.get_value_as_int(),
            "mem":            self.mem_combo.get_active_text(),
            "split":          self.split_combo.get_active_text() or "",
            "params":         self.params_entry.get_text().strip(),
            "update":         self.update_combo.get_active_text(),
            "path_mode":      self.path_combo.get_active_text(),
            "shared":         self.shared_check.get_active(),
            "delete":         self.delete_check.get_active(),
            "password":       self.password_entry.get_text(),
            "repassword":     self.repassword_entry.get_text(),
            "encrypt_names":  self.encrypt_names_check.get_active(),
        }


def build_7z_args(v):
    args = []
    fmt = v["format"]
    args.append("-t" + fmt)

    method = v["method"]
    if fmt != "tar":
        if v["level"] in LEVEL_TO_MX:
            args.append("-mx=" + LEVEL_TO_MX[v["level"]])
        if method:
            args.append("-m0=" + method)

    if fmt == "7z":
        # -md (dictionary) and -mfb (word/fast-bytes) are only accepted by the
        # LZMA family. PPMd/BZip2/Deflate/Copy reject one or both with
        # E_INVALIDARG (and Copy would also be re-promoted to LZMA2). The
        # dialog's dict/word values are LZMA-oriented anyway, so only pass them
        # for LZMA2/LZMA and let the other codecs use their own defaults.
        lzma_family = method in ("LZMA2", "LZMA")
        if v["dict"] and lzma_family:
            args.append("-md=" + to_7z_size(v["dict"]))
        if v["word"] and lzma_family:
            args.append("-mfb=" + v["word"])
        s = v["solid"]
        if s == "Non-solid":
            args.append("-ms=off")
        elif s == "Solid":
            args.append("-ms=on")
        elif s:
            args.append("-ms=" + to_7z_size(s))

    if fmt != "tar":
        args.append("-mmt={}".format(v["threads"]))
        if v["mem"].endswith("%"):
            args.append("-mmemuse=p" + v["mem"][:-1])

    # Update-mode switches verified against 7z 23.01 (6-state model p,q,r,x,y,z;
    # the help shows no 'w' state). p1=keep archive-only, p3=anti-item delete
    # (synchronize); q0; r2=add new disk files, r0=add nothing (freshen);
    # x1=keep archive when disk copy is older; y2=take newer disk copy;
    # z1=keep same-time entries. Round-trip verified: no data loss, no stale
    # content, no stray 0-byte entries.
    update_flag = {
        "Update and add files":   "-up1q0r2x1y2z1",
        "Freshen existing files": "-up1q0r0x1y2z1",
        "Synchronize files":      "-up3q0r2x1y2z1",
    }.get(v["update"])
    if update_flag:
        args.append(update_flag)

    # Path mode only has an effect when the file arguments are absolute (see
    # main(), which passes absolute paths for these two modes). -spf stores the
    # full path with leading slash; -spf2 strips the root.
    if v["path_mode"] == "Absolute pathnames":
        args.append("-spf")
    elif v["path_mode"] == "Full pathnames":
        args.append("-spf2")

    if v["shared"]:
        args.append("-ssw")
    if v["delete"]:
        args.append("-sdel")

    if fmt != "tar" and v["password"]:
        args.append("-p" + v["password"])
        # 7z always uses AES-256; zip defaults to ZipCrypto. No -mem flag.
        if fmt == "7z" and v["encrypt_names"]:
            args.append("-mhe=on")

    if v["split"]:
        size = v["split"].split(" ", 1)[0].lower()
        if size:
            args.append("-v" + size)

    if v["params"]:
        args.extend(v["params"].split())

    return args


def main():
    if len(sys.argv) < 2:
        compress.show_error("No files were passed to the action.")
        sys.exit(1)
    files = sys.argv[1:]

    dialog = AddToArchiveDialog(files)
    while True:
        response = dialog.run()
        if response != Gtk.ResponseType.OK:
            dialog.destroy()
            return

        v = dialog.collect()
        if v["password"] and v["password"] != v["repassword"]:
            err = Gtk.MessageDialog(
                transient_for=dialog, modal=True,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.CLOSE,
                text="Passwords don't match",
            )
            err.run(); err.destroy()
            continue
        break

    archive = fix_extension(v["archive"] or dialog._default_archive, v["format"])
    if not compress.confirm_overwrite(archive, parent=dialog):
        dialog.destroy()
        return

    extra_args = build_7z_args(v)
    # For Full/Absolute path modes 7z must receive absolute file arguments,
    # otherwise -spf/-spf2 have nothing to qualify and silently store relative
    # paths. For Relative mode we pass bare basenames (resolved against cwd).
    if v["path_mode"] in ("Full pathnames", "Absolute pathnames"):
        file_args = [os.path.abspath(f) for f in dialog.files]
    else:
        file_args = dialog.basenames
    dialog.hide()
    while Gtk.events_pending():
        Gtk.main_iteration()

    compress.run_compression(
        archive_path=archive,
        working_dir=dialog.working_dir,
        basenames=file_args,
        extra_args=extra_args,
        title="Creating " + os.path.basename(archive),
        parent=None,
    )
    dialog.destroy()


if __name__ == "__main__":
    main()

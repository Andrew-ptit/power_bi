"""Native folder choice contract without opening a UI during automation."""
import base64
import json
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest
from pbip_assistant.errors import InputError


class FolderPickerTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("powershell.exe"), "Windows PowerShell is required")
    def test_actual_dialog_command_parses_without_opening_a_dialog(self):
        calls = []
        def capture(command, **options):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, '{"path":null}', "")
        self.picker()(run=capture)
        encoded = calls[0][calls[0].index("-EncodedCommand") + 1]
        probe = (
            "$source=[Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('"
            + encoded + "'));$tokens=$null;$errors=$null;"
            "[Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$errors)|Out-Null;"
            "@($errors)|ForEach-Object{$_.ErrorId+': '+$_.Message};"
            "if(@($errors).Count){exit 1}"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand",
             base64.b64encode(probe.encode("utf-16-le")).decode("ascii")],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def picker(self):
        try:
            from pbip_assistant.excel.folder_picker import pick_folder
            return pick_folder
        except ImportError:
            self.fail("Native folder picker is unavailable")

    def test_cancel_is_explicit_and_does_not_use_a_placeholder_path(self):
        result = self.picker()(run=lambda *a, **kw: subprocess.CompletedProcess(a, 0, '{"path":null}', ""))
        self.assertEqual(result, {"cancelled": True, "path": None, "name": None})

    def test_selected_folder_is_validated_and_console_is_hidden(self):
        with tempfile.TemporaryDirectory() as temporary:
            calls = []
            def run(command, **options):
                calls.append((command, options))
                return subprocess.CompletedProcess(command, 0, json.dumps({"path": temporary}), "")
            result = self.picker()(run=run)
            self.assertEqual(Path(result["path"]), Path(temporary).resolve())
            self.assertFalse(result["cancelled"])
            self.assertIn("-STA", calls[0][0])
            self.assertEqual(calls[0][1]["timeout"], 120)
            self.assertNotIn("shell", calls[0][1])

    def test_failure_timeout_or_invalid_path_is_not_returned_as_a_choice(self):
        picker = self.picker()
        for output in ('{"path":"relative"}', '{"path":"C:/does-not-exist/pick"}', 'not json'):
            with self.subTest(output=output), self.assertRaises(InputError):
                picker(run=lambda *a, **kw: subprocess.CompletedProcess(a, 0, output, ""))
        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired("picker", 120)
        with self.assertRaises(InputError):
            picker(run=timeout)

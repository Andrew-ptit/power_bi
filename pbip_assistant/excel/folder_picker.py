"""Local Windows folder dialog, opened only by an authenticated user action."""
import base64
import json
import os
from pathlib import Path
import subprocess
from threading import Lock

from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_ingest import _guard

_LOCK = Lock()
_SCRIPT = r"""$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$excel = $null
$picker = $null
try {
  # Use Excel's own modal dialog so the chooser belongs to the visible host,
  # rather than an unowned window in the hidden PowerShell helper process.
  $excel = [Runtime.InteropServices.Marshal]::GetActiveObject('Excel.Application')
  $picker = $excel.FileDialog(4)
  $picker.Title = 'Chon thu muc chua file CSV hoac Excel'
  $picker.AllowMultiSelect = $false
  $chosen = $null
  if ($picker.Show() -eq -1) { $chosen = $picker.SelectedItems.Item(1) }
  @{ path = $chosen } | ConvertTo-Json -Compress
} finally {
  # Release only this helper's proxies; never Quit or save the user's Excel.
  foreach ($proxy in @($picker, $excel)) {
    if ($null -ne $proxy -and [Runtime.InteropServices.Marshal]::IsComObject($proxy)) {
      [void][Runtime.InteropServices.Marshal]::ReleaseComObject($proxy)
    }
  }
}
"""


def pick_folder(*, run=None):
    if run is None and os.name != "nt":
        raise InputError("DP_PICKER_UNAVAILABLE", "folder", "Hộp thoại chọn thư mục cần Excel trên Windows.")
    if not _LOCK.acquire(blocking=False):
        raise InputError("DP_PICKER_BUSY", "folder", "Hộp thoại chọn thư mục đang mở.")
    try:
        encoded = base64.b64encode(_SCRIPT.encode("utf-16-le")).decode("ascii")
        result = (run or subprocess.run)(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-EncodedCommand", encoded],
            capture_output=True, text=True, encoding="utf-8-sig", timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            raise ValueError("Dialog failed")
        value = json.loads(result.stdout)
        if not isinstance(value, dict) or set(value) != {"path"}:
            raise ValueError("Invalid selection")
        selected = value["path"]
        if selected is None:
            return {"cancelled": True, "path": None, "name": None}
        if not isinstance(selected, str) or not Path(selected).is_absolute():
            raise ValueError("Invalid folder")
        path = _guard(Path(selected), folder=True)
        return {"cancelled": False, "path": str(path), "name": path.name or str(path.anchor)}
    except subprocess.TimeoutExpired as exc:
        raise InputError("DP_PICKER_TIMEOUT", "folder", "Chưa chọn thư mục. Bấm Chọn thư mục để mở lại.") from exc
    except (OSError, ValueError, InputError) as exc:
        raise InputError("DP_PICKER_UNAVAILABLE", "folder", "Không mở được thư mục đã chọn. Hãy chọn lại thư mục đang tồn tại.") from exc
    finally:
        _LOCK.release()

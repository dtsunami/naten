import os
import time
import tempfile
import shutil
import difflib
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

# Try to use the python-patch library if available for robust apply behavior
try:
    import patch as python_patch  # type: ignore
except Exception:
    python_patch = None


def _is_within_root(target_path: str, root: str) -> bool:
    root = os.path.abspath(root)
    target = os.path.abspath(target_path)
    try:
        return os.path.commonpath([root]) == os.path.commonpath([root, target])
    except ValueError:
        return False


def _read_text_file_preserve_newlines(path: str) -> Tuple[str, str]:
    b = Path(path).read_bytes()
    if b.find(b'\x00') != -1:
        raise ValueError("binary file (contains NUL bytes)")
    newline_style = '\r\n' if b.find(b'\r\n') != -1 else '\n'
    try:
        text = b.decode('utf-8')
    except Exception:
        text = b.decode('latin1')
    return text, newline_style


def produce_patch(path: str, new_contents: str) -> str:
    """
    Produce a unified diff between current file contents and new_contents.
    Uses splitlines(keepends=True) so line-endings are preserved in diff hunks.
    Returns a unified diff string suitable for apply_patch().
    """
    path = os.fspath(path)
    try:
        old_text, _ = _read_text_file_preserve_newlines(path)
    except FileNotFoundError:
        old_text = ""
    except ValueError:
        # binary -> raise to caller
        raise

    # Use splitlines without keeping end-of-line markers so difflib produces
    # canonical unified diffs without embedded newlines in hunk lines.
    old_lines = old_text.splitlines(keepends=False)
    new_lines = new_contents.splitlines(keepends=False)

    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm='\n'
        )
    )
    return "\n".join(diff_lines) + ("\n" if diff_lines else "")


def _atomic_write(path: str, data: bytes):
    dirpath = os.path.dirname(path) or "."
    os.makedirs(dirpath, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dirpath)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass


def apply_patch(
    patch_text: str,
    *,
    dry_run: bool = True,
    backup: bool = True,
    workspace_root: Optional[str] = None,
    fuzzy: bool = False
) -> Dict[str, Any]:
    workspace_root = os.path.abspath(workspace_root or os.getcwd())
    results = []

    if python_patch is not None:
        # Attempt to use python-patch, but fall back to manual parser if it cannot parse/apply
        try:
            # python-patch expects a bytes-like input in some versions; ensure we pass bytes
            try:
                p = python_patch.fromstring(patch_text if isinstance(patch_text, (bytes, bytearray)) else patch_text.encode('utf-8'))
            except TypeError:
                # Fallback: try passing the original text
                p = python_patch.fromstring(patch_text)

            if not p:
                # let fallback handle parsing
                raise RuntimeError('python-patch failed to parse')

            # python-patch may return a boolean False or a PatchSet object. If boolean, wrap accordingly
            items = p.items if hasattr(p, 'items') else getattr(p, 'patches', [])
            if not items and isinstance(p, bool):
                # Failed parse
                raise RuntimeError('python-patch failed to parse')

            for item in items:
                target = item.source or item.target
                if target is None:
                    results.append({"file": None, "status": "error", "message": "could not determine target path"})
                    continue
                target_norm = target
                if target_norm.startswith("a/") or target_norm.startswith("b/"):
                    target_norm = target_norm[2:]
                abs_target = os.path.abspath(target_norm)
                if not _is_within_root(abs_target, workspace_root):
                    results.append({"file": abs_target, "status": "error", "message": "path outside workspace"})
                    continue
                exists = os.path.exists(abs_target)
                if dry_run:
                    results.append({"file": abs_target, "status": "appliable" if exists or getattr(item, 'is_new_file', False) else "created"})
                else:
                    if os.path.exists(abs_target) and backup:
                        ts = int(time.time())
                        bak = f"{abs_target}.bak.{ts}"
                        shutil.copy2(abs_target, bak)
                    try:
                        ok = p.apply(patch_root=workspace_root, strip=0, fuzz=1 if fuzzy else 0)
                        if not ok:
                            results.append({"file": abs_target, "status": "conflict", "message": "python-patch failed to apply hunks"})
                        else:
                            results.append({"file": abs_target, "status": "applied", "message": "applied by python-patch"})
                    except Exception as e:
                        results.append({"file": abs_target, "status": "error", "message": str(e)})
            return {"results": results}
        except Exception:
            # If python-patch cannot parse or apply this patch, fall back to manual parser below.
            pass

    # Fallback parser
    lines = patch_text.splitlines()
    i = 0
    files = []
    while i < len(lines):
        line = lines[i]
        if line.startswith('--- '):
            fromfile = line[4:].strip()
            i += 1
            # Skip blank lines that sometimes appear between --- and +++ headers
            while i < len(lines) and lines[i].strip() == '':
                i += 1
            if i >= len(lines):
                break
            tofile_line = lines[i]
            if not tofile_line.startswith('+++ '):
                # If header isn't immediately found, continue scanning from this position
                # (robustness for diffs that include extra metadata lines)
                i += 1
                continue
            tofile = tofile_line[4:].strip()
            for pref in ('a/', 'b/'):
                if fromfile.startswith(pref):
                    fromfile = fromfile[len(pref):]
                if tofile.startswith(pref):
                    tofile = tofile[len(pref):]
            current = {"fromfile": fromfile, "tofile": tofile, "hunks": []}
            i += 1
            # Skip blank lines between header and first hunk
            while i < len(lines) and lines[i].strip() == '':
                i += 1
            while i < len(lines) and lines[i].startswith('@@'):
                hunk_header = lines[i]
                i += 1
                hunk_lines = []
                while i < len(lines) and not lines[i].startswith('@@') and not lines[i].startswith('--- '):
                    hunk_lines.append(lines[i])
                    i += 1
                current['hunks'].append({"header": hunk_header, "lines": hunk_lines})
            files.append(current)
        else:
            i += 1

    for file_entry in files:
        tofile = file_entry['tofile']
        abs_target = os.path.abspath(tofile)
        if not _is_within_root(abs_target, workspace_root):
            results.append({"file": abs_target, "status": "error", "message": "path outside workspace"})
            continue

        file_result = {"file": abs_target, "status": None, "hunks": []}
        exists = os.path.exists(abs_target)
        if not exists:
            if dry_run:
                file_result['status'] = "created"
                file_result['message'] = "file would be created"
            else:
                pass
        try:
            old_text, newline = _read_text_file_preserve_newlines(abs_target) if exists else ("", "\n")
        except ValueError:
            file_result['status'] = "error"
            file_result['message'] = "binary file"
            results.append(file_result)
            continue
        old_lines = old_text.splitlines(keepends=True)
        new_lines = list(old_lines)
        hunk_index = 0
        overall_conflict = False
        for hunk in file_entry['hunks']:
            header = hunk['header']
            try:
                parts = header.split()
                minus = parts[1]
                plus = parts[2]
                def parse_range(r):
                    r = r.lstrip('+-')
                    if ',' in r:
                        start, cnt = r.split(',', 1)
                        return int(start), int(cnt)
                    else:
                        return int(r), 1
                from_start, from_count = parse_range(minus)
                to_start, to_count = parse_range(plus)
            except Exception:
                file_result['hunks'].append({"hunk_index": hunk_index, "status": "conflict", "message": "invalid hunk header"})
                overall_conflict = True
                hunk_index += 1
                continue

            old_pos = from_start - 1
            idx_cursor = old_pos
            expected_ok = True
            consumed_old = 0
            for l in hunk['lines']:
                if l.startswith(' '):
                    expected_line = l[1:]
                    if idx_cursor >= len(new_lines):
                        expected_ok = False
                        file_result['hunks'].append({"hunk_index": hunk_index, "status": "conflict", "message": f"context line beyond EOF: expected {expected_line!r}"})
                        break
                    if new_lines[idx_cursor].rstrip('\r\n') != expected_line.rstrip('\r\n'):
                        expected_ok = False
                        file_result['hunks'].append({"hunk_index": hunk_index, "status": "conflict", "message": f"context mismatch at line {idx_cursor+1}: expected {expected_line!r}, got {new_lines[idx_cursor]!r}"})
                        break
                    idx_cursor += 1
                    consumed_old += 1
                elif l.startswith('-'):
                    expected_line = l[1:]
                    if idx_cursor >= len(new_lines):
                        expected_ok = False
                        file_result['hunks'].append({"hunk_index": hunk_index, "status": "conflict", "message": "removal beyond EOF"})
                        break
                    if new_lines[idx_cursor].rstrip('\r\n') != expected_line.rstrip('\r\n'):
                        expected_ok = False
                        file_result['hunks'].append({"hunk_index": hunk_index, "status": "conflict", "message": f"removal mismatch at line {idx_cursor+1}: expected {expected_line!r}, got {new_lines[idx_cursor]!r}"})
                        break
                    idx_cursor += 1
                    consumed_old += 1
                elif l.startswith('+'):
                    pass
                else:
                    pass

            if not expected_ok:
                overall_conflict = True
                hunk_index += 1
                continue

            if dry_run:
                file_result['hunks'].append({"hunk_index": hunk_index, "status": "appliable", "message": "hunk matches current file"})
            else:
                apply_idx = from_start - 1
                out_block = []
                scan_idx = apply_idx
                for l in hunk['lines']:
                    if l.startswith(' '):
                        out_block.append(new_lines[scan_idx])
                        scan_idx += 1
                    elif l.startswith('-'):
                        scan_idx += 1
                    elif l.startswith('+'):
                        out_block.append(l[1:] if l[1:] else "\n")
                    else:
                        pass
                end_idx = apply_idx + consumed_old
                new_lines[apply_idx:end_idx] = out_block
                file_result['hunks'].append({"hunk_index": hunk_index, "status": "applied", "message": "hunk applied"})
            hunk_index += 1

        if overall_conflict:
            file_result['status'] = "conflict"
        else:
            file_result['status'] = "appliable" if dry_run else "applied"

        if not dry_run and not overall_conflict:
            new_text = "".join(new_lines)
            try:
                encoded = new_text.encode("utf-8")
            except Exception:
                encoded = new_text.encode("latin1", errors="replace")
            if exists and backup:
                ts = int(time.time())
                bak = f"{abs_target}.bak.{ts}"
                shutil.copy2(abs_target, bak)
            try:
                _atomic_write(abs_target, encoded)
                file_result['message'] = "written"
            except Exception as e:
                file_result['status'] = "error"
                file_result['message'] = f"write failed: {e}"

        results.append(file_result)

    return {"results": results}
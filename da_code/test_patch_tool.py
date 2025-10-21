import os
import json
import tempfile
import shutil
from . import agno_tools as agno


def test_produce_and_apply_patch(temp_dir):
    tool = agno.FileTool()
    fpath = os.path.join(temp_dir, 'p.txt')
    # create original file
    tool.create_file(fpath, 'line1\nline2\n')
    # produce patch replacing line2
    new_content = 'line1\nLINE2_CHANGED\n'
    diff = tool.produce_patch(fpath, new_content)
    assert diff.strip() != ''
    # dry run apply
    res = json.loads(tool.apply_patch(diff, dry_run=True))
    assert res['results'][0]['status'] == 'dry_run_ok'
    # real apply
    res2 = json.loads(tool.apply_patch(diff, dry_run=False, backup=True))
    assert res2['results'][0]['status'] == 'applied'
    # verify file contents
    with open(fpath, 'r', encoding='utf-8') as f:
        s = f.read()
    assert 'LINE2_CHANGED' in s


def test_apply_patch_conflict(temp_dir):
    tool = agno.FileTool()
    fpath = os.path.join(temp_dir, 'q.txt')
    tool.create_file(fpath, 'a\nb\nc\n')
    # create a patch that expects different context
    patch = '--- a/q.txt\n+++ b/q.txt\n@@ -1,3 +1,3 @@\n-a\n-b\n-c\n+X\n+Y\n+Z\n'
    res = json.loads(tool.apply_patch(patch, dry_run=True))
    # Since content doesn't match context, expect conflict
    assert res['results'][0]['status'] == 'conflict' or res['results'][0]['status'] == 'error'
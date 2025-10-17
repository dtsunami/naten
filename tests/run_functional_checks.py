import os
import sys
import json
import tempfile
import shutil
import subprocess
from pathlib import Path

sys.path.insert(0, os.path.abspath('.'))

from da_code import agno_tools as agno

results = []

temp_dir = tempfile.mkdtemp()

try:
    # Utilities
    try:
        gw = agno.get_workspace_root()
        results.append({"name": "get_workspace_root", "ok": True, "output": gw})
    except Exception as e:
        results.append({"name": "get_workspace_root", "ok": False, "error": str(e)})

    try:
        os.environ['DA_CODE_WORKSPACE_ROOT'] = temp_dir
        sp = agno.safe_path('file.txt')
        results.append({"name": "safe_path", "ok": True, "input": "file.txt", "output": sp})
    except Exception as e:
        results.append({"name": "safe_path", "ok": False, "input": "file.txt", "error": str(e)})

    try:
        fe = agno.get_file_emoji('test.py')
        results.append({"name": "get_file_emoji", "ok": True, "input": "test.py", "output": fe})
    except Exception as e:
        results.append({"name": "get_file_emoji", "ok": False, "input": "test.py", "error": str(e)})

    # TodoTool
    try:
        ttool = agno.TodoTool(working_directory=temp_dir)
        c = ttool.create_todo('My Task')
        r = ttool.read_todo()
        e = ttool.check_exists()
        results.append({"name": "TodoTool", "ok": True, "create": c, "read": r, "check": e})
    except Exception as e:
        results.append({"name": "TodoTool", "ok": False, "error": str(e)})

    # CommandTool
    try:
        ctool = agno.CommandTool()
        out = ctool.execute_command('echo hello')
        results.append({"name": "CommandTool", "ok": True, "input": "echo hello", "output": out})
    except Exception as e:
        results.append({"name": "CommandTool", "ok": False, "error": str(e)})

    # WebSearchTool - monkeypatch httpx.Client
    try:
        class DummyResponse:
            status_code = 200
            def json(self):
                return {'AbstractText': 'Summary', 'AbstractURL': 'url'}
        class DummyClient:
            def __enter__(self): return self
            def __exit__(self,a,b,c): pass
            def get(self, url): return DummyResponse()
        agno.httpx.Client = lambda **k: DummyClient()
        wtool = agno.WebSearchTool()
        wout = wtool.search('query')
        results.append({"name": "WebSearchTool", "ok": True, "input": "query", "output": wout})
    except Exception as e:
        results.append({"name": "WebSearchTool", "ok": False, "error": str(e)})

    # FileTool
    try:
        ftool = agno.FileTool()
        fpath = os.path.join(temp_dir, 'a.txt')
        cf = ftool.create_file(fpath, 'data')
        listing = ftool.list_directory(temp_dir)
        ftool.write_file(os.path.join(temp_dir, 'b.txt'), 'hello')
        rf = ftool.read_file(os.path.join(temp_dir, 'b.txt'))
        ftool.write_file(os.path.join(temp_dir, 'c.txt'), 'abc abc')
        rep = ftool.replace_text(os.path.join(temp_dir, 'c.txt'), 'abc', 'xyz')
        results.append({"name": "FileTool", "ok": True, "create": cf, "list": listing, "read": rf, "replace": rep})
    except Exception as e:
        results.append({"name": "FileTool", "ok": False, "error": str(e)})

    # TimeTool
    try:
        ttool = agno.TimeTool()
        iso = ttool.current_time('iso')
        human = ttool.current_time('human')
        results.append({"name": "TimeTool", "ok": True, "iso": iso, "human": human})
    except Exception as e:
        results.append({"name": "TimeTool", "ok": False, "error": str(e)})

    # PythonTool
    try:
        ptool = agno.PythonTool()
        okp = ptool.execute_code("print('hi')")
        errp = ptool.execute_code("raise ValueError('x')")
        results.append({"name": "PythonTool", "ok": True, "success": okp, "error_case": errp})
    except Exception as e:
        results.append({"name": "PythonTool", "ok": False, "error": str(e)})

    # GitTool - monkeypatch subprocess.run
    try:
        import subprocess as sp
        orig_run = sp.run
        sp.run = lambda *a, **k: subprocess.CompletedProcess(a[0], 0, stdout='dirty', stderr='')
        gtool = agno.GitTool()
        gstatus = gtool.status()
        sp.run = orig_run
        results.append({"name": "GitTool", "ok": True, "status": gstatus})
    except Exception as e:
        results.append({"name": "GitTool", "ok": False, "error": str(e)})

    # HttpTool - monkeypatch httpx.Client
    try:
        class DummyResponse2:
            status_code = 200
            reason_phrase = 'OK'
            headers = {'content-type': 'text/plain'}
            content = b'data'
            text = 'hello'
            def json(self):
                return {'k':'v'}
        class DummyClient2:
            def __enter__(self): return self
            def __exit__(self,a,b,c): pass
            def get(self, url, headers=None): return DummyResponse2()
            def head(self, url, headers=None): return DummyResponse2()
        agno.httpx.Client = lambda **k: DummyClient2()
        htool = agno.HttpTool()
        hout = htool.fetch('http://test')
        results.append({"name": "HttpTool", "ok": True, "input": "http://test", "output": hout})
    except Exception as e:
        results.append({"name": "HttpTool", "ok": False, "error": str(e)})

except Exception as overall:
    results.append({"name": "overall_failure", "ok": False, "error": str(overall)})
finally:
    # cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)

print(json.dumps(results, indent=2))
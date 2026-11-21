"""Startup task XML preserves account and install paths containing XML characters."""
import ast
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

import system_tools


class StartupXmlTests(unittest.TestCase):
    def test_task_round_trips_paths_and_user_without_xml_injection(self):
        source = Path(__file__).resolve().parents[1] / 'app.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_ensure_logon_task')
        target = r'C:\Users\Ryan & Co\Echo.exe'
        errors = []
        captured = []
        def run(cmd, **kwargs):
            if '/query' in cmd:
                return SimpleNamespace(returncode=1, stdout='', stderr='')
            captured.append(ET.parse(cmd[cmd.index('/xml') + 1]).getroot())
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        scope = dict(os=os, sys=SimpleNamespace(frozen=True), system_tools=system_tools,
                     TASK_NAME='Echo test', _STARTUP_ARG='--startup',
                     _startup_target=lambda: target, _log_startup_error=errors.append)
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), 'exec'), scope)
        with mock.patch.object(subprocess, 'run', side_effect=run), \
             mock.patch.object(subprocess, 'CREATE_NO_WINDOW', 0, create=True), \
             mock.patch.dict(os.environ, USERNAME='Ryan & Co', USERDOMAIN='Office <Test>'):
            scope['_ensure_logon_task']()
        self.assertEqual([], errors)
        self.assertEqual(1, len(captured))
        ns = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}
        root = captured[0]
        self.assertEqual(target, root.find('.//t:Command', ns).text)
        self.assertEqual('Office <Test>\\Ryan & Co', root.find('.//t:UserId', ns).text)
        self.assertEqual('--startup', root.find('.//t:Arguments', ns).text)

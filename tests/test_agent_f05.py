"""F-05  Agentic mode toggle + step-scoped Brandy + English voice states"""
import subprocess
import json
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).parent.parent
AGENT_JS = REPO_ROOT / "app" / "static" / "agent.js"

class TestAgentJS:
    def test_agent_js_syntax(self):
        result = subprocess.run(["node", "--check", str(AGENT_JS)], capture_output=True, text=True)
        assert result.returncode == 0

    def test_module_loads(self):
        code = "const a = require('./app/static/agent.js'); console.log(JSON.stringify({ok: typeof a.buildStepSummary === 'function'}));"
        result = subprocess.run(["node", "-e", code], cwd=str(REPO_ROOT), capture_output=True, text=True)
        assert result.returncode == 0
        assert json.loads(result.stdout.strip())["ok"]

    def test_step_order(self):
        code = "const a = require('./app/static/agent.js'); console.log(JSON.stringify(a.STEP_ORDER));"
        result = subprocess.run(["node", "-e", code], cwd=str(REPO_ROOT), capture_output=True, text=True)
        assert json.loads(result.stdout.strip()) == ['brain', 'catalog', 'script', 'audiovisual', 'editing']

    def test_global_tool_names(self):
        code = "const a = require('./app/static/agent.js'); console.log(JSON.stringify(a.GLOBAL_TOOL_NAMES));"
        result = subprocess.run(["node", "-e", code], cwd=str(REPO_ROOT), capture_output=True, text=True)
        assert json.loads(result.stdout.strip()) == ['get_status', 'get_balance', 'go_to_step']

    def test_tools_for_step_returns_array(self):
        code = "const a = require('./app/static/agent.js'); console.log(JSON.stringify(Array.isArray(a.toolsForStep('brain'))));"
        result = subprocess.run(["node", "-e", code], cwd=str(REPO_ROOT), capture_output=True, text=True)
        assert result.stdout.strip() == "true"

    def test_send_session_update_mock_ws(self):
        code = "const a = require('./app/static/agent.js'); var sent=[]; var ws={readyState:1,send:function(d){sent.push(JSON.parse(d));}}; a.sendSessionUpdate(false,'brain',{},ws); console.log(sent.length);"
        result = subprocess.run(["node", "-e", code], cwd=str(REPO_ROOT), capture_output=True, text=True)
        assert result.stdout.strip().endswith("1")

    def test_propose_action_returns_not_available(self):
        code = "const a = require('./app/static/agent.js'); console.log(JSON.stringify(a.handleProposeAction('test',{})));"
        result = subprocess.run(["node", "-e", code], cwd=str(REPO_ROOT), capture_output=True, text=True)
        data = json.loads(result.stdout.strip())
        assert data["status"] == "not_available"

    def test_confirm_action_returns_not_available(self):
        code = "const a = require('./app/static/agent.js'); console.log(JSON.stringify(a.handleConfirmAction('token')));"
        result = subprocess.run(["node", "-e", code], cwd=str(REPO_ROOT), capture_output=True, text=True)
        data = json.loads(result.stdout.strip())
        assert data["status"] == "not_available"

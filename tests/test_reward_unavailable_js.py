from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from cinegate.web.rewards import _reward_page_html


def test_pending_page_unavailable_retry_does_not_replay_ad_or_duplicate_claim() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to execute the Mini App JavaScript regression")
    page = _reward_page_html(
        session_id=uuid4(), quality="720p", block_id="test", reward_status="pending",
    )
    script = re.search(r"<script>\s*(.*?)\s*</script>", page, re.DOTALL)
    assert script is not None
    result = subprocess.run(
        [node, str(Path(__file__).with_name("reward_unavailable_retry.cjs"))],
        input=script.group(1), text=True, capture_output=True, check=False, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr

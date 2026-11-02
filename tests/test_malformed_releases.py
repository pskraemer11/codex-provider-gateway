import io
import json
from unittest import mock

import pytest

from opencode_go_proxy import updates


@pytest.mark.parametrize("payload", [None, 42, "bad", ["bad"]])
def test_invalid_release_shapes_degrade_to_error(payload):
    with mock.patch(
        "urllib.request.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())
    ):
        result = updates.check_for_updates(force=True)
    assert result.error is not None
    assert not result.available


@pytest.mark.parametrize("tag", ["v①.0.0", "v" + "9" * 5000 + ".0.0"])
def test_invalid_numeric_tags_do_not_crash_version_checks(tag):
    body = json.dumps({"tag_name": tag}).encode()
    with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(body)):
        result = updates.check_for_updates(force=True)
    assert not result.available
    assert result.error is not None


@pytest.mark.parametrize("tag", ["①.0.0", "9" * 5000 + ".0.0"])
def test_invalid_cached_numeric_tags_degrade_to_error(tag):
    result = updates._info_from_cache(updates.__version__, {"latest": tag})
    assert not result.available
    assert result.error is not None

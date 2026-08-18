"""
_get_bytes: binary reads from SData (attachment file streams).

Needed by the CRM-report ingestion path discovered 2026-07-26 — every Crystal
report anyone runs is archived as an SLX attachment and its bytes come from
`attachments('<key>')/file`, which is NOT JSON. `_get` would blow up on
resp.json(), so the client needs a binary sibling that still fails loud on
HTTP errors and on an SData error envelope returned in place of a file.
"""
import pytest

from src.slx.client import SLXClient, SLXError


class _Resp:
    def __init__(self, content, status=200, ctype="application/vnd.ms-excel"):
        self.content = content
        self.status_code = status
        self.headers = {"content-type": ctype}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


class _Session:
    def __init__(self, resp):
        self._resp = resp
        self.urls = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        return self._resp


def _client(resp):
    c = SLXClient.__new__(SLXClient)          # no network/auth in unit tests
    c.base_url = "https://x/sdata/slx/dynamic/-/"
    c.session = _Session(resp)
    return c


def test_get_bytes_returns_raw_content():
    blob = b"\xd0\xcf\x11\xe0binary-xls"
    c = _client(_Resp(blob))
    assert c._get_bytes("attachments('e1')/file") == blob
    # no format=json on a binary stream — it would corrupt some SData handlers
    assert c.session.urls == ["https://x/sdata/slx/dynamic/-/attachments('e1')/file"]


def test_get_bytes_raises_on_http_error():
    c = _client(_Resp(b"", status=404))
    with pytest.raises(Exception):
        c._get_bytes("attachments('missing')/file")


def test_get_bytes_raises_when_sdata_returns_an_error_envelope():
    # SLX answers some failures with a JSON diagnosis and HTTP 200
    envelope = b'[{"severity": "Error", "message": "File not found"}]'
    c = _client(_Resp(envelope, ctype="application/json"))
    with pytest.raises(SLXError, match="File not found"):
        c._get_bytes("attachments('gone')/file")

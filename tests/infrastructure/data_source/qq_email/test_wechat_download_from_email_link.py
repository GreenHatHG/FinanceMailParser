from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

from financemailparser.infrastructure.data_source.qq_email.parser import QQEmailParser
from financemailparser.infrastructure.data_source.qq_email import parser as parser_mod


class _ResponseStub:
    def __init__(
        self, *, status_code: int, headers: dict[str, str], body: bytes, url: str
    ):
        self.status_code = status_code
        self.headers = headers
        self._body = body
        self.url = url

    def iter_content(self, chunk_size: int = 8192):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]

    def close(self) -> None:  # pragma: no cover
        return


def _make_email_with_html(html: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = "微信支付账单"
    msg.set_content("plain")
    msg.add_alternative(html, subtype="html")
    return msg


def test_extract_wechat_download_links_uses_img_alt_and_title() -> None:
    parser = QQEmailParser("dummy@qq.com", "dummy-auth-code")
    html = """
    <html><body>
      <a href="https://tenpay.wechatpay.cn/userroll/userbilldownload/downloadfilefromemail?encrypted_file_data=ABCD">
        <img alt="点击下载" />
      </a>
      <a href="https://example.com/help" title="帮助中心">帮助</a>
    </body></html>
    """
    email_data = {"raw_message": _make_email_with_html(html)}
    links = parser.extract_wechat_download_links(email_data)
    assert links
    assert links[0].startswith("https://tenpay.wechatpay.cn/")


def test_download_wechat_bill_candidates_requires_zip_magic(
    tmp_path: Path, monkeypatch
) -> None:
    parser = QQEmailParser("dummy@qq.com", "dummy-auth-code")
    save_dir = tmp_path / "wechat"

    bad_url = "https://tenpay.wechatpay.cn/not-a-zip"
    good_url = "https://tenpay.wechatpay.cn/zip"

    def fake_get(url: str, *, timeout: int, stream: bool):
        assert timeout > 0
        assert stream is True
        if url == bad_url:
            return _ResponseStub(
                status_code=200,
                headers={"content-type": "text/html"},
                body=b"<html>not zip</html>",
                url=url,
            )
        if url == good_url:
            return _ResponseStub(
                status_code=200,
                headers={
                    "content-type": "application/zip",
                    "content-disposition": 'attachment; filename="wechat.zip"',
                },
                body=b"PK\x03\x04" + b"dummy-zip-content",
                url=url,
            )
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(parser_mod.requests, "get", fake_get)

    saved = parser.download_wechat_bill_candidates([bad_url, good_url], save_dir)
    assert saved is not None
    out = Path(saved)
    assert out.exists()
    assert out.read_bytes().startswith(b"PK\x03\x04")

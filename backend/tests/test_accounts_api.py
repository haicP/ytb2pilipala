import httpx

from backend.app.accounts import _qr_sessions
from backend.app.models import AccountBinding


class FakeBilibiliClient:
    def __init__(self):
        self.poll_code = 86101
        self.poll_message = "未扫码"
        self.cookies = {"SESSDATA": "secret-session", "bili_jct": "secret-jct", "DedeUserID": "10086"}

    def get(self, url, params=None, cookies=None):
        request = httpx.Request("GET", url)
        if url.endswith("/qrcode/generate"):
            return httpx.Response(
                200,
                request=request,
                json={
                    "code": 0,
                    "data": {
                        "url": "https://passport.bilibili.com/h5-app/passport/login/scan?demo=1",
                        "qrcode_key": "qr-key-demo",
                    },
                },
            )
        if url.endswith("/qrcode/poll"):
            response = httpx.Response(
                200,
                request=request,
                json={"code": 0, "data": {"code": self.poll_code, "message": self.poll_message}},
            )
            if self.poll_code == 0:
                response.cookies.update(self.cookies)
            return response
        if url.endswith("/x/web-interface/nav"):
            assert cookies == self.cookies
            return httpx.Response(
                200,
                request=request,
                json={
                    "code": 0,
                    "data": {
                        "isLogin": True,
                        "mid": 10086,
                        "uname": "Bili Demo",
                        "face": "https://i0.hdslb.com/demo.jpg",
                    },
                },
            )
        raise AssertionError(f"Unexpected URL: {url}")


def test_bilibili_qrcode_create_returns_session_and_data_url(client, monkeypatch):
    fake_client = FakeBilibiliClient()
    monkeypatch.setattr("backend.app.accounts.httpx.Client", lambda **kwargs: fake_client)

    response = client.post("/api/accounts/bilibili/qrcode")

    assert response.status_code == 200
    payload = response.json()
    assert payload["login_session_id"]
    assert payload["qrcode_data_url"].startswith("data:image/png;base64,")
    assert payload["expires_at"]
    assert payload["login_session_id"] in _qr_sessions


def test_bilibili_qrcode_poll_maps_scan_states(client, monkeypatch):
    fake_client = FakeBilibiliClient()
    monkeypatch.setattr("backend.app.accounts.httpx.Client", lambda **kwargs: fake_client)
    session_id = client.post("/api/accounts/bilibili/qrcode").json()["login_session_id"]

    pending_response = client.post(f"/api/accounts/bilibili/qrcode/{session_id}/poll")
    assert pending_response.status_code == 200
    assert pending_response.json()["status"] == "pending_scan"

    fake_client.poll_code = 86090
    fake_client.poll_message = "二维码已扫码未确认"
    scanned_response = client.post(f"/api/accounts/bilibili/qrcode/{session_id}/poll")
    assert scanned_response.status_code == 200
    assert scanned_response.json()["status"] == "scanned"

    fake_client.poll_code = 86038
    fake_client.poll_message = "二维码已失效"
    expired_response = client.post(f"/api/accounts/bilibili/qrcode/{session_id}/poll")
    assert expired_response.status_code == 200
    assert expired_response.json()["status"] == "expired"


def test_bilibili_qrcode_poll_success_binds_account_without_cookie_in_response(
    client, db_session, monkeypatch
):
    fake_client = FakeBilibiliClient()
    monkeypatch.setattr("backend.app.accounts.httpx.Client", lambda **kwargs: fake_client)
    session_id = client.post("/api/accounts/bilibili/qrcode").json()["login_session_id"]
    fake_client.poll_code = 0
    fake_client.poll_message = "扫码登录成功"

    response = client.post(f"/api/accounts/bilibili/qrcode/{session_id}/poll")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "confirmed"
    assert payload["account"]["platform"] == "bilibili"
    assert payload["account"]["platform_user_id"] == "10086"
    assert payload["account"]["nickname"] == "Bili Demo"
    assert "secret-session" not in response.text
    assert "secret-jct" not in response.text

    account = db_session.query(AccountBinding).one()
    assert "secret-session" in account.cookies_json
    assert account.status == "active"


def test_list_and_unbind_accounts(client, db_session):
    account = AccountBinding(
        platform="bilibili",
        platform_user_id="10086",
        nickname="Bili Demo",
        avatar_url="",
        status="active",
        is_primary=1,
        cookie_summary="已保存 3 项关键 Cookie：SESSDATA, bili_jct, DedeUserID",
        cookies_json='{"SESSDATA":"secret-session"}',
    )
    db_session.add(account)
    db_session.commit()

    list_response = client.get("/api/accounts")
    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["nickname"] == "Bili Demo"
    assert "secret-session" not in list_response.text

    unbind_response = client.post(f"/api/accounts/{account.id}/unbind")
    assert unbind_response.status_code == 200
    assert unbind_response.json()["status"] == "unbound"
    assert unbind_response.json()["cookie_summary"] == ""

    db_session.refresh(account)
    assert account.cookies_json == "{}"

import base64
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import AccountBinding, utc_now


BILIBILI_QRCODE_GENERATE_URL = (
    "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
)
BILIBILI_QRCODE_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
BILIBILI_NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
BILIBILI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}
FALLBACK_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/"
    "l0e6kgAAAABJRU5ErkJggg=="
)


@dataclass
class QrLoginSession:
    qrcode_key: str
    expires_at: datetime


_qr_sessions: dict[str, QrLoginSession] = {}


def _json_response_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("B 站接口返回了无法解析的响应") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("B 站接口返回格式异常")
    return payload


def _qrcode_data_url(url: str) -> str:
    try:
        import qrcode
    except ModuleNotFoundError:
        return f"data:image/png;base64,{FALLBACK_PNG_BASE64}"
    image = qrcode.make(url)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _cookie_summary(cookies: dict[str, str]) -> str:
    important_names = ["SESSDATA", "bili_jct", "DedeUserID"]
    present = [name for name in important_names if cookies.get(name)]
    if present:
        return f"已保存 {len(present)} 项关键 Cookie：{', '.join(present)}"
    return f"已保存 {len(cookies)} 项 Cookie"


class AccountRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_accounts(self) -> list[AccountBinding]:
        statement = select(AccountBinding).order_by(AccountBinding.updated_at.desc())
        return list(self.session.execute(statement).scalars())

    def get_account(self, account_id: int) -> AccountBinding | None:
        return self.session.get(AccountBinding, account_id)

    def unbind_account(self, account: AccountBinding) -> AccountBinding:
        account.status = "unbound"
        account.is_primary = 0
        account.cookies_json = "{}"
        account.cookie_summary = ""
        account.updated_at = utc_now()
        self.session.commit()
        loaded = self.get_account(account.id)
        if loaded is None:
            raise ValueError(f"Account {account.id} not found")
        return loaded

    def upsert_bilibili_account(
        self,
        *,
        platform_user_id: str,
        nickname: str,
        avatar_url: str,
        cookies: dict[str, str],
    ) -> AccountBinding:
        now = utc_now()
        statement = (
            select(AccountBinding)
            .where(AccountBinding.platform == "bilibili")
            .where(AccountBinding.platform_user_id == platform_user_id)
        )
        account = self.session.execute(statement).scalar_one_or_none()
        if account is None:
            account = AccountBinding(
                platform="bilibili",
                platform_user_id=platform_user_id,
                created_at=now,
            )
            self.session.add(account)

        account.nickname = nickname
        account.avatar_url = avatar_url
        account.status = "active"
        account.is_primary = 1
        account.cookie_summary = _cookie_summary(cookies)
        account.cookies_json = json.dumps(cookies, ensure_ascii=False, sort_keys=True)
        account.last_login_at = now
        account.error_summary = ""
        account.updated_at = now
        self.session.commit()
        loaded = self.get_account(account.id)
        if loaded is None:
            raise ValueError(f"Account {account.id} not found")
        return loaded


class BilibiliLoginService:
    def __init__(self, repo: AccountRepository, client: httpx.Client | None = None):
        self.repo = repo
        self.client = client or httpx.Client(timeout=10.0, headers=BILIBILI_HEADERS)

    def create_qrcode(self) -> tuple[str, str, datetime]:
        response = self.client.get(BILIBILI_QRCODE_GENERATE_URL)
        response.raise_for_status()
        payload = _json_response_payload(response)
        if payload.get("code") != 0:
            raise RuntimeError(str(payload.get("message") or "B 站二维码生成失败"))

        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("B 站二维码生成响应缺少 data")
        url = str(data.get("url") or "")
        qrcode_key = str(data.get("qrcode_key") or "")
        if not url or not qrcode_key:
            raise RuntimeError("B 站二维码生成响应缺少二维码参数")

        login_session_id = secrets.token_urlsafe(24)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=180)
        _qr_sessions[login_session_id] = QrLoginSession(qrcode_key=qrcode_key, expires_at=expires_at)
        return login_session_id, _qrcode_data_url(url), expires_at

    def poll_qrcode(self, login_session_id: str) -> tuple[str, str, AccountBinding | None]:
        session = _qr_sessions.get(login_session_id)
        if session is None:
            return "expired", "二维码会话不存在或已过期", None
        if session.expires_at <= datetime.now(timezone.utc):
            _qr_sessions.pop(login_session_id, None)
            return "expired", "二维码已过期，请重新生成", None

        response = self.client.get(BILIBILI_QRCODE_POLL_URL, params={"qrcode_key": session.qrcode_key})
        response.raise_for_status()
        payload = _json_response_payload(response)
        if payload.get("code") != 0:
            return "failed", str(payload.get("message") or "B 站扫码状态查询失败"), None

        data = payload.get("data")
        if not isinstance(data, dict):
            return "failed", "B 站扫码状态响应缺少 data", None

        code = int(data.get("code", -1))
        message = str(data.get("message") or "")
        if code == 86101:
            return "pending_scan", "等待使用哔哩哔哩客户端扫码", None
        if code == 86090:
            return "scanned", "已扫码，请在手机上确认登录", None
        if code == 86038:
            _qr_sessions.pop(login_session_id, None)
            return "expired", "二维码已过期，请重新生成", None
        if code != 0:
            return "failed", message or "B 站扫码登录失败", None

        cookies = {cookie.name: cookie.value for cookie in response.cookies.jar}
        nav_response = self.client.get(BILIBILI_NAV_URL, cookies=cookies)
        nav_response.raise_for_status()
        nav_payload = _json_response_payload(nav_response)
        nav_data = nav_payload.get("data") if nav_payload.get("code") == 0 else None
        if not isinstance(nav_data, dict) or not nav_data.get("isLogin"):
            return "failed", str(nav_payload.get("message") or "B 站账号信息校验失败"), None

        platform_user_id = str(nav_data.get("mid") or "")
        nickname = str(nav_data.get("uname") or "B 站账号")
        avatar_url = str(nav_data.get("face") or "")
        if not platform_user_id:
            return "failed", "B 站账号信息缺少用户 ID", None

        _qr_sessions.pop(login_session_id, None)
        account = self.repo.upsert_bilibili_account(
            platform_user_id=platform_user_id,
            nickname=nickname,
            avatar_url=avatar_url,
            cookies=cookies,
        )
        return "confirmed", "B 站账号绑定成功", account

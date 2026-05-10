from dataclasses import dataclass
from pathlib import Path

NETSCAPE_COOKIE_HEADER = "# Netscape HTTP Cookie File"


@dataclass(frozen=True)
class CookiesFileValidation:
    exists: bool
    valid: bool
    cookie_count: int = 0
    reason: str = ""


def validate_youtube_cookies_file(path: Path | str) -> CookiesFileValidation:
    cookies_path = Path(path)
    if not cookies_path.is_file():
        return CookiesFileValidation(exists=False, valid=False, reason="文件不存在")

    try:
        lines = cookies_path.read_text(encoding="utf-8-sig").splitlines()
    except UnicodeDecodeError:
        return CookiesFileValidation(
            exists=True,
            valid=False,
            reason="文件不是有效的 UTF-8 文本",
        )
    except OSError:
        return CookiesFileValidation(
            exists=True,
            valid=False,
            reason="文件无法读取",
        )

    if not lines:
        return CookiesFileValidation(exists=True, valid=False, reason="文件为空")

    if not lines[0].startswith(NETSCAPE_COOKIE_HEADER):
        return CookiesFileValidation(
            exists=True,
            valid=False,
            reason="缺少 Netscape HTTP Cookie File 文件头",
        )

    cookie_count = 0
    for line_number, raw_line in enumerate(lines[1:], start=2):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#") and not line.startswith("#HttpOnly_"):
            continue

        fields = line.split("\t")
        if len(fields) != 7:
            return CookiesFileValidation(
                exists=True,
                valid=False,
                reason=f"第 {line_number} 行不是 7 列 Netscape cookie 记录",
            )

        domain = fields[0]
        include_subdomains = fields[1]
        cookie_path_field = fields[2]
        secure = fields[3]
        expires = fields[4]
        name = fields[5]
        if not domain or not cookie_path_field or not name:
            return CookiesFileValidation(
                exists=True,
                valid=False,
                reason=f"第 {line_number} 行缺少必要字段",
            )
        if include_subdomains.upper() not in {"TRUE", "FALSE"}:
            return CookiesFileValidation(
                exists=True,
                valid=False,
                reason=f"第 {line_number} 行 include_subdomains 字段无效",
            )
        if secure.upper() not in {"TRUE", "FALSE"}:
            return CookiesFileValidation(
                exists=True,
                valid=False,
                reason=f"第 {line_number} 行 secure 字段无效",
            )
        try:
            int(expires)
        except ValueError:
            return CookiesFileValidation(
                exists=True,
                valid=False,
                reason=f"第 {line_number} 行 expires 字段不是整数",
            )

        cookie_count += 1

    if cookie_count == 0:
        return CookiesFileValidation(
            exists=True,
            valid=False,
            reason="文件没有有效 cookie 记录",
        )

    return CookiesFileValidation(exists=True, valid=True, cookie_count=cookie_count)


def is_valid_youtube_cookies_file(path: Path | str) -> bool:
    return validate_youtube_cookies_file(path).valid


def format_invalid_youtube_cookies_message(
    path: Path | str,
    validation: CookiesFileValidation,
) -> str:
    reason = validation.reason or "格式无效"
    return (
        f"YouTube cookies 文件不可用：{Path(path)}，{reason}。"
        "请使用 Netscape HTTP Cookie File 格式重新导出 cookies.txt，"
        "或删除该无效文件后再重试公开视频下载。"
    )

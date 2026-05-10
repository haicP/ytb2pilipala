from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.accounts import AccountRepository, BilibiliLoginService
from backend.app.database import get_db_session
from backend.app.schemas import (
    AccountBindingListResponse,
    AccountBindingResponse,
    BilibiliQrCodePollResponse,
    BilibiliQrCodeResponse,
)


router = APIRouter(prefix="/accounts", tags=["accounts"])


def _get_account_or_404(repo: AccountRepository, account_id: int):
    account = repo.get_account(account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account binding not found")
    return account


@router.get("", response_model=AccountBindingListResponse)
def list_accounts(db: Session = Depends(get_db_session)) -> AccountBindingListResponse:
    repo = AccountRepository(db)
    return AccountBindingListResponse(
        items=[AccountBindingResponse.from_model(account) for account in repo.list_accounts()]
    )


@router.post("/bilibili/qrcode", response_model=BilibiliQrCodeResponse)
def create_bilibili_qrcode(db: Session = Depends(get_db_session)) -> BilibiliQrCodeResponse:
    try:
        login_session_id, qrcode_data_url, expires_at = BilibiliLoginService(
            AccountRepository(db)
        ).create_qrcode()
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return BilibiliQrCodeResponse(
        login_session_id=login_session_id,
        qrcode_data_url=qrcode_data_url,
        expires_at=expires_at,
    )


@router.post(
    "/bilibili/qrcode/{login_session_id}/poll",
    response_model=BilibiliQrCodePollResponse,
)
def poll_bilibili_qrcode(
    login_session_id: str,
    db: Session = Depends(get_db_session),
) -> BilibiliQrCodePollResponse:
    try:
        status_value, message, account = BilibiliLoginService(AccountRepository(db)).poll_qrcode(
            login_session_id
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return BilibiliQrCodePollResponse(
        status=status_value,
        message=message,
        account=AccountBindingResponse.from_model(account) if account is not None else None,
    )


@router.post("/{account_id}/unbind", response_model=AccountBindingResponse)
def unbind_account(account_id: int, db: Session = Depends(get_db_session)) -> AccountBindingResponse:
    repo = AccountRepository(db)
    account = _get_account_or_404(repo, account_id)
    return AccountBindingResponse.from_model(repo.unbind_account(account))

import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Clapperboard,
  Link2,
  LoaderCircle,
  Music2,
  QrCode,
  RefreshCw,
  ShieldCheck,
  Smartphone,
  Tv,
  Unlink,
  Youtube,
  Zap,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { apiClient } from "../api/client";
import type { AccountBinding, BilibiliQrCodePollResponse, BilibiliQrCodeResponse } from "../api/types";
import { Card } from "../components/Card";

const POLL_INTERVAL_MS = 2500;

const platformCards: Array<{
  key: string;
  name: string;
  badge: string;
  description: string;
  Icon: LucideIcon;
  enabled: boolean;
}> = [
  {
    key: "bilibili",
    name: "B站",
    badge: "热门",
    description: "绑定B站账号，自动发布视频到B站",
    Icon: Tv,
    enabled: true,
  },
  {
    key: "youtube",
    name: "YouTube",
    badge: "",
    description: "绑定YouTube账号，同步管理国际平台",
    Icon: Youtube,
    enabled: false,
  },
  {
    key: "douyin",
    name: "抖音",
    badge: "开发中",
    description: "绑定抖音账号，自动发布短视频到抖音",
    Icon: Music2,
    enabled: false,
  },
  {
    key: "xigua",
    name: "西瓜视频",
    badge: "开发中",
    description: "绑定西瓜视频账号，拓展视频分发渠道",
    Icon: Clapperboard,
    enabled: false,
  },
  {
    key: "kuaishou",
    name: "快手",
    badge: "开发中",
    description: "绑定快手账号，覆盖更多用户群体",
    Icon: Zap,
    enabled: false,
  },
];

function formatDate(value: string | null) {
  if (!value) {
    return "-";
  }
  return new Date(value).toLocaleString();
}

function pollStatusLabel(status: BilibiliQrCodePollResponse["status"] | "") {
  if (status === "pending_scan") {
    return "等待扫码";
  }
  if (status === "scanned") {
    return "等待确认";
  }
  if (status === "confirmed") {
    return "绑定成功";
  }
  if (status === "expired") {
    return "二维码过期";
  }
  if (status === "failed") {
    return "绑定失败";
  }
  return "准备扫码";
}

export function AccountsPage() {
  const [accounts, setAccounts] = useState<AccountBinding[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState("");
  const [error, setError] = useState("");
  const [qrSession, setQrSession] = useState<BilibiliQrCodeResponse | null>(null);
  const [qrStatus, setQrStatus] = useState<BilibiliQrCodePollResponse["status"] | "">("");
  const [qrMessage, setQrMessage] = useState("");
  const [nowMs, setNowMs] = useState(() => Date.now());

  const activeAccounts = useMemo(
    () => accounts.filter((account) => account.status === "active"),
    [accounts]
  );

  async function loadAccounts() {
    setLoading(true);
    try {
      const data = await apiClient.accounts();
      setAccounts(data.items);
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "账号数据加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadAccounts();
  }, []);

  useEffect(() => {
    if (!qrSession || ["confirmed", "expired", "failed"].includes(qrStatus)) {
      return undefined;
    }

    const timerId = window.setInterval(() => {
      void (async () => {
        try {
          const result = await apiClient.pollBilibiliQrCode(qrSession.login_session_id);
          setQrStatus(result.status);
          setQrMessage(result.message);
          if (result.status === "confirmed") {
            await loadAccounts();
          }
        } catch (caught) {
          setQrStatus("failed");
          setQrMessage(caught instanceof Error ? caught.message : "扫码状态查询失败");
        }
      })();
    }, POLL_INTERVAL_MS);

    return () => window.clearInterval(timerId);
  }, [qrSession, qrStatus]);

  useEffect(() => {
    if (!qrSession || ["confirmed", "expired", "failed"].includes(qrStatus)) {
      return undefined;
    }

    const timerId = window.setInterval(() => {
      setNowMs(Date.now());
    }, 1000);

    return () => window.clearInterval(timerId);
  }, [qrSession, qrStatus]);

  async function startBilibiliBinding() {
    setActionLoading("qrcode");
    try {
      const qrcode = await apiClient.createBilibiliQrCode();
      setQrSession(qrcode);
      setQrStatus("pending_scan");
      setQrMessage("请使用哔哩哔哩客户端扫码登录");
      setNowMs(Date.now());
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "B 站二维码生成失败");
    } finally {
      setActionLoading("");
    }
  }

  async function unbindAccount(accountId: number) {
    setActionLoading(`unbind-${accountId}`);
    try {
      await apiClient.unbindAccount(accountId);
      await loadAccounts();
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "账号解绑失败");
    } finally {
      setActionLoading("");
    }
  }

  const secondsLeft = qrSession
    ? Math.max(0, Math.ceil((new Date(qrSession.expires_at).getTime() - nowMs) / 1000))
    : 0;

  return (
    <div className="page accounts-page">
      <Card>
        <div className="accounts-head">
          <div>
            <span className="eyebrow">Account Bindings</span>
            <h1>账号绑定管理</h1>
            <p>绑定多个平台账号；B站支持多账号接入，并可切换主账号用于上传。</p>
          </div>
          <button className="button secondary" type="button" onClick={() => void loadAccounts()} disabled={loading}>
            <RefreshCw size={16} aria-hidden="true" />
            <span>刷新</span>
          </button>
        </div>
      </Card>

      {error ? <div className="alert">账号操作暂不可用：{error}</div> : null}

      <section className="accounts-section" aria-labelledby="bound-accounts-heading">
        <div className="accounts-section-title">
          <ShieldCheck size={18} aria-hidden="true" />
          <h2 id="bound-accounts-heading">已绑定账号</h2>
        </div>

        {loading ? <p className="empty-state">加载账号绑定...</p> : null}
        {!loading && activeAccounts.length === 0 ? (
          <div className="accounts-empty">
            <Link2 size={48} aria-hidden="true" />
            <strong>暂无绑定账号</strong>
            <span>请在下方选择平台进行绑定</span>
          </div>
        ) : null}

        {activeAccounts.length ? (
          <div className="bound-account-list">
            {activeAccounts.map((account) => (
              <article className="bound-account-card" key={account.id}>
                <div className="bound-account-avatar">
                  {account.avatar_url ? <img src={account.avatar_url} alt="" /> : <Tv size={24} aria-hidden="true" />}
                </div>
                <div className="bound-account-main">
                  <div className="bound-account-title">
                    <strong>{account.nickname || "B 站账号"}</strong>
                    <span>{account.is_primary ? "主账号" : "备用账号"}</span>
                  </div>
                  <p>UID：{account.platform_user_id}</p>
                  <small>{account.cookie_summary || "登录凭据已保存"}</small>
                </div>
                <div className="bound-account-meta">
                  <span>最近登录：{formatDate(account.last_login_at)}</span>
                  <button
                    className="icon-text-button danger"
                    type="button"
                    disabled={Boolean(actionLoading)}
                    onClick={() => void unbindAccount(account.id)}
                  >
                    <Unlink size={14} aria-hidden="true" />
                    <span>{actionLoading === `unbind-${account.id}` ? "解绑中" : "解绑"}</span>
                  </button>
                </div>
              </article>
            ))}
          </div>
        ) : null}
      </section>

      {qrSession ? (
        <Card className="bilibili-qr-panel">
          <div className="qr-panel-copy">
            <span className="eyebrow">Bilibili QR Login</span>
            <h2>B站扫码登录</h2>
            <p>请使用哔哩哔哩客户端扫描二维码，并在手机端确认登录。</p>
            <div className={`qr-status qr-status-${qrStatus || "idle"}`}>
              {qrStatus === "confirmed" ? (
                <CheckCircle2 size={16} aria-hidden="true" />
              ) : qrStatus === "failed" || qrStatus === "expired" ? (
                <AlertTriangle size={16} aria-hidden="true" />
              ) : (
                <LoaderCircle size={16} aria-hidden="true" />
              )}
              <strong>{pollStatusLabel(qrStatus)}</strong>
              <span>{qrMessage}</span>
            </div>
            <div className="qr-panel-actions">
              <button
                className="button secondary"
                type="button"
                onClick={() => void startBilibiliBinding()}
                disabled={Boolean(actionLoading)}
              >
                <RefreshCw size={16} aria-hidden="true" />
                <span>刷新二维码</span>
              </button>
            </div>
          </div>
          <div className="qr-code-box">
            <img src={qrSession.qrcode_data_url} alt="B站扫码登录二维码" />
            <span>
              <Clock3 size={14} aria-hidden="true" />
              {secondsLeft > 0 ? `${secondsLeft} 秒后过期` : "二维码已过期"}
            </span>
          </div>
        </Card>
      ) : null}

      <section className="accounts-section" aria-labelledby="platforms-heading">
        <div className="accounts-section-title">
          <Link2 size={18} aria-hidden="true" />
          <h2 id="platforms-heading">添加新平台</h2>
        </div>

        <div className="platform-card-grid">
          {platformCards.map((platform) => (
            <article className={`platform-card${platform.enabled ? "" : " disabled"}`} key={platform.key}>
              <div className={`platform-icon platform-${platform.key}`}>
                <platform.Icon size={26} aria-hidden="true" />
              </div>
              <div className="platform-title">
                <h3>{platform.name}</h3>
                {platform.badge ? <span>{platform.badge}</span> : null}
              </div>
              <p>{platform.description}</p>
              <button
                className={`button ${platform.enabled ? "" : "secondary"}`}
                type="button"
                disabled={!platform.enabled || Boolean(actionLoading)}
                onClick={() => {
                  if (platform.key === "bilibili") {
                    void startBilibiliBinding();
                  }
                }}
              >
                {platform.enabled ? (
                  <>
                    <QrCode size={16} aria-hidden="true" />
                    <span>{actionLoading === "qrcode" ? "生成中..." : "立即绑定"}</span>
                  </>
                ) : (
                  <>
                    <Clock3 size={16} aria-hidden="true" />
                    <span>敬请期待</span>
                  </>
                )}
              </button>
            </article>
          ))}
        </div>
      </section>

      <div className="accounts-guide-grid">
        <Card className="accounts-guide-card blue">
          <div className="accounts-guide-title">
            <Smartphone size={17} aria-hidden="true" />
            <h2>快速指南</h2>
          </div>
          <ol>
            <li>选择您想要分发视频的目标平台，点击“立即绑定”</li>
            <li>B站扫码绑定，请使用哔哩哔哩客户端完成确认</li>
            <li>绑定成功后，即可在视频列表页选择一键发布</li>
          </ol>
        </Card>
        <Card className="accounts-guide-card amber">
          <div className="accounts-guide-title">
            <AlertTriangle size={17} aria-hidden="true" />
            <h2>注意事项</h2>
          </div>
          <ul>
            <li>B站二维码有效期约为3分钟，请尽快完成扫码</li>
            <li>Cookie 有效期受平台策略影响，失效后需重新绑定</li>
            <li>解绑账号不会删除您的历史数据，可随时重新绑定</li>
          </ul>
        </Card>
      </div>
    </div>
  );
}

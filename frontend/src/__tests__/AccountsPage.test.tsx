import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { AccountsPage } from "../pages/AccountsPage";

const apiMock = vi.hoisted(() => ({
  accounts: vi.fn(),
  createBilibiliQrCode: vi.fn(),
  pollBilibiliQrCode: vi.fn(),
  unbindAccount: vi.fn(),
}));

vi.mock("../api/client", () => ({
  apiClient: apiMock,
}));

const accountFixture = {
  id: 7,
  platform: "bilibili",
  platform_user_id: "10086",
  nickname: "Bili Demo",
  avatar_url: "https://i0.hdslb.com/demo.jpg",
  status: "active",
  is_primary: true,
  cookie_summary: "已保存 3 项关键 Cookie：SESSDATA, bili_jct, DedeUserID",
  last_login_at: "2026-05-05T08:00:00Z",
  error_summary: "",
  created_at: "2026-05-05T07:00:00Z",
  updated_at: "2026-05-05T08:00:00Z",
};

beforeEach(() => {
  apiMock.accounts.mockResolvedValue({ items: [] });
  apiMock.createBilibiliQrCode.mockResolvedValue({
    login_session_id: "session-demo",
    qrcode_data_url: "data:image/png;base64,AAAA",
    expires_at: new Date(Date.now() + 180_000).toISOString(),
  });
  apiMock.pollBilibiliQrCode.mockResolvedValue({
    status: "pending_scan",
    message: "等待使用哔哩哔哩客户端扫码",
    account: null,
  });
  apiMock.unbindAccount.mockResolvedValue({ ...accountFixture, status: "unbound", cookie_summary: "" });
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("AccountsPage", () => {
  test("renders account empty state and disabled non-bilibili platforms", async () => {
    render(<AccountsPage />);

    expect(await screen.findByRole("heading", { name: "账号绑定管理" })).toBeInTheDocument();
    expect(screen.getByText("暂无绑定账号")).toBeInTheDocument();
    expect(screen.getByText("请在下方选择平台进行绑定")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "立即绑定" })).toBeEnabled();
    expect(screen.getAllByRole("button", { name: "敬请期待" })).toHaveLength(4);
    expect(screen.getAllByRole("button", { name: "敬请期待" })[0]).toBeDisabled();
  });

  test("starts bilibili QR login and polls until confirmed", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    apiMock.pollBilibiliQrCode.mockResolvedValueOnce({
      status: "scanned",
      message: "已扫码，请在手机上确认登录",
      account: null,
    });
    apiMock.pollBilibiliQrCode.mockResolvedValueOnce({
      status: "confirmed",
      message: "B 站账号绑定成功",
      account: accountFixture,
    });
    apiMock.accounts.mockResolvedValueOnce({ items: [] }).mockResolvedValueOnce({ items: [accountFixture] });

    render(<AccountsPage />);

    fireEvent.click(await screen.findByRole("button", { name: "立即绑定" }));

    expect(await screen.findByRole("heading", { name: "B站扫码登录" })).toBeInTheDocument();
    expect(screen.getByAltText("B站扫码登录二维码")).toHaveAttribute("src", "data:image/png;base64,AAAA");

    await vi.advanceTimersByTimeAsync(2500);
    expect(await screen.findByText("等待确认")).toBeInTheDocument();

    await vi.advanceTimersByTimeAsync(2500);
    await waitFor(() => expect(apiMock.accounts).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Bili Demo")).toBeInTheDocument();
    expect(screen.getByText("UID：10086")).toBeInTheDocument();
  });

  test("renders bound account and unbinds it", async () => {
    apiMock.accounts.mockResolvedValueOnce({ items: [accountFixture] }).mockResolvedValueOnce({ items: [] });

    render(<AccountsPage />);

    expect(await screen.findByText("Bili Demo")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "解绑" }));

    await waitFor(() => expect(apiMock.unbindAccount).toHaveBeenCalledWith(7));
    await waitFor(() => expect(screen.getByText("暂无绑定账号")).toBeInTheDocument());
  });
});

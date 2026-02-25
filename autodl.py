import time
import re
import logging
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)


class AutoDLManager:
    def __init__(self, config):
        self.phone = config["credentials"]["phone"]
        self.password = config["credentials"]["password"]
        self.headless = config["settings"].get("headless", False)
        self.browser_type = config["settings"].get("browser", "chrome")
        self.base_url = config["settings"]["base_url"]
        self.login_url = config["settings"]["login_url"]
        self.boot_timeout = config["settings"]["boot_timeout_seconds"]
        self.poll_interval = config["settings"]["poll_interval_seconds"]

    def run(self):
        with sync_playwright() as p:
            if self.browser_type == "chrome":
                browser = p.chromium.launch(
                    headless=self.headless, channel="chrome"
                )
            else:
                browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context()
            page = context.new_page()

            self._login(page)
            self._navigate_to_console(page)

            servers = self._get_server_info(page)
            logger.info(f"共找到 {len(servers)} 台服务器")

            # 检查是否有无卡模式运行中的服务器
            self._handle_running_nocard(page, servers)

            for i, server in enumerate(servers):
                if server["remain_days"] >= 14:
                    logger.info(
                        f"--- [{i + 1}] {server['name']} 剩余 {server['remain_days']} 天，跳过 ---"
                    )
                    continue
                try:
                    self._process_server(page, i, server)
                except Exception as e:
                    logger.error(f"服务器 {server['name']} 处理失败: {e}，继续下一台...")

            logger.info("全部服务器处理完毕")
            browser.close()

    def _login(self, page):
        logger.info("正在登录...")
        page.goto(self.login_url)
        page.wait_for_load_state("networkidle")

        page.fill("input[name='phone']", self.phone)
        page.fill("input[name='password']", self.password)
        page.click("button.el-button--primary:has-text('登录')")

        # 等待跳转到控制台，留足时间给验证码
        page.wait_for_url("**/console/**", timeout=60000)
        logger.info("登录成功")

    def _navigate_to_console(self, page):
        page.goto(self.base_url)
        page.wait_for_selector(".el-table__row", timeout=15000)
        logger.info("已进入控制台实例列表")

    def _get_server_info(self, page):
        """获取所有服务器的名称、状态和剩余天数"""
        rows = page.query_selector_all(".el-table__row")
        servers = []
        for row in rows:
            name_el = row.query_selector("[data-v-7af0f7ca] span")
            name = name_el.inner_text().strip() if name_el else "未知"
            status_el = row.query_selector(".status span")
            status = status_el.inner_text().strip() if status_el else "未知"
            # 获取剩余天数
            date_el = row.query_selector(".date span")
            date_text = date_el.inner_text().strip() if date_el else ""
            remain_days = self._parse_remain_days(date_text)
            servers.append({"name": name, "status": status, "remain_days": remain_days})
            logger.info(f"  发现服务器: {name} - 状态: {status} - 剩余: {remain_days}天")
        return servers

    def _parse_remain_days(self, text):
        """从 '13天04小时35分后释放' 或 '关机15天后释放' 中提取天数"""
        m = re.search(r"(\d+)天", text)
        return int(m.group(1)) if m else 0

    def _handle_running_nocard(self, page, servers):
        """检查是否有无卡模式运行中的服务器，如果有先关掉"""
        for i, server in enumerate(servers):
            if server["status"] == "运行中":
                logger.info(f"{server['name']} 正在运行中，先关机...")
                self._shutdown_server(page, i, server["name"])
                server["status"] = "已关机"
                # 刷新后重新获取剩余天数
                self._click_refresh(page)
                rows = page.query_selector_all(".el-table__row")
                date_el = rows[i].query_selector(".date span")
                date_text = date_el.inner_text().strip() if date_el else ""
                server["remain_days"] = self._parse_remain_days(date_text)
                logger.info(f"{server['name']} 已关机，剩余 {server['remain_days']} 天")

    def _process_server(self, page, index, server):
        name = server["name"]
        logger.info(f"--- [{index + 1}] 开始处理服务器: {name} ---")

        # 刷新页面确保状态最新
        self._navigate_to_console(page)
        rows = page.query_selector_all(".el-table__row")
        row = rows[index]

        # 检查当前状态
        status = self._get_row_status(row)
        if status == "运行中":
            logger.info(f"{name} 已经在运行中，先关机再无卡开机")
            self._shutdown_server(page, index, name)
            self._navigate_to_console(page)
            rows = page.query_selector_all(".el-table__row")
            row = rows[index]

        # 点击"更多"按钮
        more_btn = row.query_selector(".el-dropdown .el-dropdown-selfdefine")
        more_btn.hover()
        time.sleep(1)

        # 点击当前可见的"无卡模式开机"
        self._click_visible_menu_item(page, "无卡模式开机")
        time.sleep(0.5)

        # 处理确认弹窗
        self._confirm_dialog(page)

        logger.info(f"{name} 无卡开机指令已发送，等待启动...")
        self._wait_for_status(page, index, "运行中")
        logger.info(f"{name} 已启动，开始关机...")

        self._shutdown_server(page, index, name)
        logger.info(f"{name} 处理完成")

    def _get_row_status(self, row):
        """获取某一行的状态文本"""
        status_el = row.query_selector(".status span")
        return status_el.inner_text().strip() if status_el else "未知"

    def _confirm_dialog(self, page):
        """处理确认弹窗（el-message-box），点击确定"""
        try:
            dialog = page.wait_for_selector(
                ".el-message-box", timeout=5000
            )
            confirm_btn = dialog.query_selector(
                "button.el-button--primary"
            )
            if confirm_btn:
                confirm_btn.click()
                time.sleep(1)
        except PlaywrightTimeout:
            pass  # 没有弹窗

    def _click_visible_menu_item(self, page, text):
        """在所有匹配的菜单项中，点击当前可见的那个"""
        items = page.query_selector_all(f"text={text}")
        for item in items:
            if item.is_visible():
                item.click()
                return
        raise Exception(f"未找到可见的菜单项: {text}")

    def _click_refresh(self, page):
        """点击页面上的刷新按钮"""
        page.click("button.refresh-btn")
        page.wait_for_selector(".el-table__row", timeout=15000)

    def _wait_for_status(self, page, index, target):
        """轮询点击刷新按钮，等待服务器达到目标状态"""
        deadline = time.time() + self.boot_timeout
        while time.time() < deadline:
            time.sleep(5)
            self._click_refresh(page)
            rows = page.query_selector_all(".el-table__row")
            status = self._get_row_status(rows[index])
            logger.info(f"  当前状态: {status}")
            if target in status:
                return
        raise TimeoutError(
            f"等待状态 '{target}' 超时 ({self.boot_timeout}s)"
        )

    def _shutdown_server(self, page, index, name):
        """关机操作"""
        self._click_refresh(page)
        rows = page.query_selector_all(".el-table__row")
        row = rows[index]

        # 关机按钮在"更多"左边
        shutdown_btn = row.query_selector(
            "button.thirteenSize:has-text('关机')"
        )
        if shutdown_btn:
            shutdown_btn.click()
            time.sleep(0.5)
            self._confirm_dialog(page)
        else:
            # 关机可能在更多菜单里
            more_btn = row.query_selector(
                ".el-dropdown .el-dropdown-selfdefine"
            )
            more_btn.hover()
            time.sleep(1)
            self._click_visible_menu_item(page, "关机")
            time.sleep(0.5)
            self._confirm_dialog(page)

        logger.info(f"{name} 关机指令已发送，等待关机...")
        self._wait_for_status(page, index, "已关机")
        logger.info(f"{name} 已关机")

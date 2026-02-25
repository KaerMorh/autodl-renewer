# autodl-renewer

AutoDL 服务器自动续期工具。通过无卡模式开关机，自动为即将到期的实例续期，防止被平台释放。

## 工作原理

1. 使用 Playwright 自动登录 AutoDL 控制台
2. 遍历所有服务器实例，检查剩余天数
3. 对剩余天数 < 14 天的实例，执行「无卡模式开机 → 关机」操作完成续期
4. 已在运行中的实例会先关机再处理

## 安装

```bash
pip install -r requirements.txt
playwright install chromium
```

## 配置

复制配置模板并填入你的账号信息：

```bash
cp config.yaml.example config.yaml
```

```yaml
credentials:
  phone: "your_phone_number"
  password: "your_password"

settings:
  headless: false          # true 为无头模式
  browser: "chrome"        # "chrome" 用系统 Chrome，"chromium" 用 Playwright 自带
  boot_timeout_seconds: 120
  poll_interval_seconds: 10
  base_url: "https://www.autodl.com/console/instance/list"
  login_url: "https://www.autodl.com/login"
```

## 使用

```bash
python main.py
```

> 首次登录可能需要手动完成验证码，建议先用 `headless: false` 运行。

## 注意事项

- `config.yaml` 包含敏感信息，已在 `.gitignore` 中排除
- 建议配合定时任务（如 cron / 任务计划程序）定期执行

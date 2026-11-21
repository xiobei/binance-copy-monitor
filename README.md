# 币安带单员交易记录监控

一个小脚本,盯**一个**带单员的公开"最新紀錄"(开仓/平仓),有新操作就推送到你的手机。

- **只读**:不登录、不下单、不碰你的币安账户,只读取页面上公开的文字。
- 推送渠道:Telegram 机器人(优先)或 ntfy.sh。

## 隐私:哪些东西不会、也绝不能上传

本仓库**不包含**任何个人信息。下面这些文件只存在你自己的电脑上,已被 `.gitignore` 排除:

| 文件 | 内容 |
|---|---|
| `telegram.json` | Telegram 机器人令牌 |
| `config.local.bat` | 带单员链接 |
| `heartbeat_url.txt` / `ntfy_topic.txt` | 心跳链接 / 推送频道名 |

在 GitHub Actions 里,令牌和带单员链接都放在仓库 **Secrets**,不写进任何文件。

## 本机使用(Windows)

1. 安装 Python 3.9+(勾选 *Add Python to PATH*)。
2. 复制 `config.example.bat` 为 `config.local.bat`,填入带单员链接。
3. 在 Telegram 找 `@BotFather` 创建机器人,拿到令牌;给机器人发一条消息。把 `telegram.example.json` 复制为 `telegram.json`,填入令牌(`chat_id` 留 `null`,脚本会自动找)。
4. 双击 `start_monitor.bat`。第一次会自动安装依赖。启动后手机会收到"交易监控已启动"。

### 自动重启 / 开机自启 / 心跳

- **自动重启**:`loop_monitor.bat` 在脚本崩溃后 15 秒自动重启,并给手机发通知。
- **开机自启**:把 `start_monitor.bat` 的快捷方式(目标加参数 `auto`)放进 `shell:startup` 文件夹。
- **心跳告警**:到 healthchecks.io 免费注册,建一个检查(周期 5 分钟、宽限 5 分钟),把 ping 链接写进 `heartbeat_url.txt`。脚本每分钟报一次平安,停了它会通知你。
- 运行期间电脑不会自动休眠;请自己关掉"更新后自动重启"。

## GitHub Actions(可选的备份)

1. 仓库 **Settings → Secrets and variables → Actions** 添加:`TRADER_URL`、`TG_TOKEN`、`TG_CHAT_ID`,可选 `HEARTBEAT_URL`。
2. **Actions** 页手动运行一次 `monitor-trades` 验证。
3. 成功后,在 `.github/workflows/monitor.yml` 里取消 `schedule` 两行的注释,才会开始定时运行。

限制:GitHub 服务器多在美国,币安可能拒绝访问(运行会失败);定时任务有延迟,最快约 5-10 分钟一次;公开仓库 60 天无活动会被自动停用。
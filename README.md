# 黄金宏观监测中心｜自动更新版

这是一个**可部署的静态网站 + GitHub Actions 定时采集器**。页面不需要持续开着电脑，但必须先部署到 GitHub 才能让服务器端定时执行采集。网页和源代码可公开访问；**它与 ChatGPT 任务通知是两个独立系统**，暂不自动同步 ChatGPT 任务的通知正文。

## 已实现的功能

- 保留原版的黄金、美元、美债、原油、VIX、GDX、GDXU第三方行情图、经济日历、新闻与手动观察板。
- **自动指标模块**：从 FRED 下载美国实际利率 DFII10、2Y/10Y美债 DGS2/DGS10、**美元广义贸易加权指数 DTWEXBGS（不是DXY）**、WTI原油 DCOILWTICO、VIXCLS、10年盈亏平衡通胀率 T10YIE、Fed目标利率上限 DFEDTARU、初请 ICSA、失业率 UNRATE、非农就业总量 PAYEMS、CPIAUCSL、核心PCE PCEPILFE。
- 同步抓取美联储货币政策RSS、讲话RSS、BLS非农和CPI新闻发布RSS、Google News宏观线索RSS。RSS可中断、不保证收齐所有信息。
- 公开且可审计的**规则初判**：利多、利空、混合、中性、待确认，按条件说明原因。不会捏造分析师预期，油价大涨/战争/高通胀不机械判利多。
- 保存**最新指标 + 最近最多350条已去重历史事件**，网页筛选利多/利空/混合/待确认，附来源链接和日本时间显示。
- **每小时第17分钟（UTC）请求调度一次**，不保证准点；官方数据本身可能按日/周/月更新，故页面不会变成实时数据终端。
- 无API密钥；Python只使用标准库，代码与数据均可检查。

## 部署至 GitHub Pages：建议电脑完成

1. 登录 [GitHub](https://github.com) 并新建一个**公开仓库**，例如 `gold-macro-radar`，不用预创建 README（避免历史冲突）。GitHub Pages在Free计划下支持公开仓库。
2. 将本 ZIP 解压到电脑，确保 `index.html`、`.github`、`assets`、`data`、`scripts` 等目录均在同一层。使用 GitHub Desktop 或 Git 提交所有文件（**包含隐藏的 `.github/workflows/refresh.yml`**）。命令行示例：

   ```bash
   cd gold_monitor_auto
   git init -b main
   git add .
   git commit -m "Initial gold macro radar"
   git remote add origin https://github.com/你的用户名/gold-macro-radar.git
   git push -u origin main
   ```

   需要先安装Git，且完成GitHub登录授权。也可以直接通过GitHub网页上传文件，但注意隐藏的 `.github` 工作流目录不能漏传。
3. 仓库 `Settings → Pages → Build and deployment → Source` 选择 **GitHub Actions**。不要选择 Deploy from a branch（本项目用同一工作流主动部署Page）。
4. 打开仓库 `Actions → 黄金宏观数据更新与网页发布 → Run workflow` 手动运行第一次。
5. 等工作流成功后，在 `Settings → Pages` 获取站点地址，通常形如 `https://你的用户名.github.io/gold-macro-radar/`。把地址加入手机收藏夹。
6. 后续 `refresh.yml` 会尝试每小时更新；可在仓库 Actions 查看最近运行结果。若来源不通，会显示错误并保留先前快照，避免伪造或覆盖为空白。

> 注意：GitHub Actions的计划任务可延迟、跳过；公开仓库若60天无活动，计划任务也可能被自动停用。任务运行成功后，最好验证下页面显示的更新时间。公开Pages不能放个人账号、API token或机密资料。

## 数据与逻辑边界

**自动方向 ≠ “公布数据超/低于预期”。** 免费FRED数据仅提供公布的历史序列；本项目大多比较最近若干观测值的变化，尤其需要注意：

- 美债与TIPS：收益率下降通常利多黄金，但这只是传导关系；危机时也可能出现反例。
- 广义贸易加权美元指数不是DXY，日线TradingView组件另有DXY。
- “非农总量本月增量”不是非农意外值；缺一致预期时自动标**待确认**。
- CPI/核心PCE同比由**季调指数**换算，可能与媒体广泛引用的未季调CPI同比不同。FRED可能晚于官方新闻稿刷新。
- 原油、战争、VIX和通胀上行往往影响方向相互矛盾，规则标为**多空交织**。
- RSS**只解析标题和发布时间**，并不核对全文；标题判读置信度低。Google News等接口有可能失效或改变格式。
- 交易所行情、CME FedWatch、一致预期、CFTC COT、ETF净流和央行购金保持**原网页快捷入口或独立ChatGPT预警**，本公开版不宣称这些已接入自动实时评分。
- GitHub Pages网站的更新时间由Actions控制；点击“重新读取”只重新加载已经发布的数据，**不会在网页里即时运行采集器**。

## 本地预览与测试

```bash
python -m http.server 8000
# 在浏览器打开 http://localhost:8000/
python -m unittest discover -s tests -v
# 手动拉取真实数据需要网络
python scripts/update.py
```

本地通过 `file://` 直接打开 HTML 时，浏览器通常禁止 `fetch` 邻近的 JSON，建议使用上面的 HTTP 预览。**初始data文件明确显示未启动，不包含伪造的“当前行情”。**

## 主要来源

- FRED：https://fred.stlouisfed.org/　（CSV下载：https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10）
- 美联储RSS：https://www.federalreserve.gov/feeds/feeds.htm
- BLS RSS：https://www.bls.gov/feed/
- GitHub Pages部署：https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site
- Actions事件：https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

**不是投资建议。** 不承诺新闻实时性、全部覆盖、方向预测准确率或可用的交易信号。
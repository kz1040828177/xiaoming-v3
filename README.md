# 小明选股 V3.0｜手机优先可运行原型

## 5分钟启动（只需手机浏览器）
1. 在 GitHub 新建 **Private** 仓库，例如 `xiaoming-v3`。
2. 将本 ZIP 解压后，保持目录结构上传至仓库根目录（包括隐藏目录 `.github/workflows`）。手机上传隐藏目录不方便时，可使用 GitHub 网页编辑器逐个创建文件。
3. 打开仓库 **Actions**，启用工作流，选 **Xiaoming A-share screener → Run workflow**。
4. 等待执行结束，进入该次运行的 **Artifacts → xiaoming-latest** 下载报告，解压后打开 `latest.md` 或 `latest.json`。
5. 将 `latest.json` 上传至 ChatGPT 的“小明选股”对话，要求“基于本次快照复核市场、板块、个股并给出最终0–6只”。

默认北京时间工作日15:35自动运行一次（GitHub定时可能延迟；A股休市日也可能执行）。可手动触发。GitHub Actions 免费额度、私有仓库限制以 GitHub 当时政策为准。

## 本地电脑备用
Python 3.11+：`pip install -r requirements.txt` 然后 `python screener.py`，报告在 `output/`。

## 重要边界
- 本原型仅覆盖**全市场行情快照**，再对成交额前80只进行历史K线分析，**并非完整的全市场逐股技术扫描**。
- 盘中日线可能未收盘，结果只能作预筛；正式买入必须复核当日分钟数据和板块强度。
- `score` 是启发式技术评分，不是经过回测验证的收益概率。
- 接口可能变化、限流、失败；`latest.json` 保留错误和覆盖数量，不能把失败当成“0只机会”。
- 无自动下单、无真实交易权限；不保证实时性或稳定性。
- 后续升级：历史K线本地缓存、全市场增量扫描、行业强度、双源报价校验、回测与失败告警。

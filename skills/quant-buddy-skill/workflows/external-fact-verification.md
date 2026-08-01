# 外部时效性事实核验

> 本 workflow 只核验易变化的外部事实，例如上市、退市、更名、换代码、换交易所和并购状态。它不能替代 Quant Buddy 的行情、财务、公式、Grant 或验证收据。

## 触发门禁（命中任一项必须执行）

1. 用户询问“最新”“目前”“现在”“是否已经”等易变化事实。
2. 结论涉及近期上市、退市、暂停交易、更名、换代码、换交易所或并购。
3. 用户陈述、模型记忆、本地资产库或 Quant Buddy 接口响应互相冲突。
4. 本地资产库已命中目标资产，但任一平台资产接口返回 `ASSET_NOT_FOUND`；该情况标记为 `asset_catalog_conflict`。
5. 结论依赖模型知识截止时间之后发生的事实。

触发后不得仅凭模型记忆下结论。`ASSET_NOT_FOUND` ≠ `公司未上市`；它只说明当前接口没有识别目标资产，不得推导为公司未上市、不存在或用户陈述错误。

## 执行顺序

1. 保留本地资产库命中的标准名称、ticker 和市场，不得替换为相似资产。
2. 先完成当前任务要求的 Quant Buddy 独立数据接口调用；外部搜索不得替代可用的平台数据通道。
3. 若当前 Agent 具有 **Agent 宿主 Web Search**，优先使用宿主搜索。
4. 宿主搜索不可用时，调用本地 `webSearch` / Bocha：

```json
{
  "query": "SpaceX SPCX NASDAQ listing date",
  "count": 8,
  "freshness_months": 12
}
```

5. Agent 宿主搜索与本地 `webSearch` 均不可用或无可靠结果时，标记为 `unverified`，不得退回模型旧知识作确定性断言。

## 来源优先级

按以下顺序寻找并交叉检查，首个可靠层级足以形成结论时停止：

1. 交易所、SEC 或其他监管机构。
2. 公司官网、公司 IR、正式公告。
3. 权威财经数据源。
4. 主流财经媒体。

只有低质量来源、搜索摘要无法支持结论或可靠来源互相冲突时，使用 `conflicted`，不得确定性宣布上市状态。

## 状态合同

内部判断必须分别保留以下状态，不得合并：

```yaml
external_fact_status: verified | unverified | conflicted
quant_buddy_data_status: available | unavailable | blocked
```

- `external_fact_status=verified`：权威来源足以确认上市状态、ticker、交易所、上市日期或其他目标事实。
- `external_fact_status=unverified`：搜索能力不可用，或没有找到足以支持结论的来源。
- `external_fact_status=conflicted`：可靠来源之间存在尚未消除的冲突。
- `quant_buddy_data_status=available`：任务要求的平台行情、财务或计算通道返回有效目标资产数据。
- `quant_buddy_data_status=unavailable`：平台完成调用但未识别资产、返回空数据或缺少任务要求的数据。
- `quant_buddy_data_status=blocked`：鉴权、配额、协议、网络、超时或服务异常阻止了平台调用。

外部事实已核验但平台无数据时，使用以下语义：

> 公开权威来源确认该公司已经上市，但 Quant Buddy 当前接口尚未识别、覆盖或同步该资产。

## 证据边界

外部搜索结果只允许确认：

- 公司是否上市、退市或暂停交易。
- ticker、交易所、上市日期。
- 更名、换代码、换交易所、并购等公司事件。

外部搜索结果不得：

- 冒充 Quant Buddy 行情、财务或公式结果。
- 生成或替代 Grant、公式包、验证收据。
- 将网页中的行情数字描述成 Quant Buddy 实时数据。
- 因外部事实核验成功而跳过仍可独立尝试的平台数据通道。

## 失败处理

- 外部事实无法核验：明确说明“当前无法可靠核验该外部事实”，不作确定性断言。
- 平台数据不可用：明确说明“Quant Buddy 当前未返回可靠数据”，不推导公司不存在或未上市。
- 平台系统级阻塞：报告 `blocked`，不得用网页搜索结果掩盖系统错误。
- 无论外部核验是否成功，都继续遵守对应 leaf workflow 的数据完整性、重试止损和 evidence-only 规则。

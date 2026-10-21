# Real_Time_Quote_List

> Category: 行情数据 | Folder: `Market_Quotes` | Index: `SKILL_EN.md`

<!-- generated_at: 2026-05-08T17:36:14.630-1778232974639 -->


### 描述

查询个股实时行情数据，支持指定多个股票代码，返回最新价、涨跌幅、成交量、成交额、换手率、振幅等。适用于实时监控个股行情。

### 请求参数

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|:---|:---|:---|:---|:---|
| `interfaceId` | `str` | 是 | "G1" | 接口ID |
| `stockCodes` | `str` | 否 | - | 支持查询单只股票和多只股票(单次查询不超过20个)，如果是多只，以逗号隔开；示例：000001,<br>600519 |

### 返回参数

ResultData.data 为 List，元素为实时行情列表

| 名称 | 类型 | 是否必返回 | 说明 |
|:---|:---|:---|:---|
| `stockCode` | `str` | 否 | 股票代码 |
| `stockName` | `str` | 否 | 股票名称 |
| `newprice` | `float` | 否 | 股票价格 |
| `maxPrice` | `float` | 否 | 最高价 |
| `minPrice` | `float` | 否 | 最低价 |
| `openPrice` | `float` | 否 | 开盘价 |
| `yesterdayClosePrice` | `float` | 否 | 昨收价 |
| `chg` | `float` | 否 | 涨跌幅 |
| `chgMoney` | `float` | 否 | 涨跌额 |
| `volume` | `int` | 否 | 成交量 |
| `tradeMoney` | `float` | 否 | 成交额 |

### 调用示例

```python
from equal_data import EqualDataApi  
api = EqualDataApi('your API_KEY') 
# 调用接口
data = api.query_equal_data(
    interfaceId="G1",
    stockCodes=None,  # str  # 默认: 
)
```



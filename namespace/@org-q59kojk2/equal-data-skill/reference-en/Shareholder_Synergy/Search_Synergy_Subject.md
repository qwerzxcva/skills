# Search_Synergy_Subject

> Category: 股东协同 | Folder: `Shareholder_Synergy` | Index: `SKILL_EN.md`

<!-- generated_at: 2026-05-08T17:36:14.630-1778232974639 -->


### 描述

 搜索协同主体（机构名称），支持精确搜索和模糊搜索，返回匹配的机构列表，用作最新协同数据接口的前置查询。适用于不确定完整机构名称时的模糊检索

### 请求参数

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|:---|:---|:---|:---|:---|
| `interfaceId` | `str` | 是 | "M4" | 接口ID |
| `keyWord` | `str` | 是 | - | 搜索字符串 |

### 返回参数

协同主体列表

| 名称 | 类型 | 是否必返回 | 说明 |
|:---|:---|:---|:---|

### 调用示例

```python
from equal_data import EqualDataApi  
api = EqualDataApi('your API_KEY') 
# 调用接口
data = api.query_equal_data(
    interfaceId="M4",
    keyWord=None,  # str  # 默认: 
)
```



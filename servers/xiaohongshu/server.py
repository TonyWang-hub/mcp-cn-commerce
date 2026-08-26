"""Xiaohongshu (小红书) 电商开放平台 MCP server — 只读商家数据工具集。

契约要点（逐项官方出处见 ``docs/api-contracts/xiaohongshu.md``）：

* **单一网关**：所有业务接口都打到
  ``https://ark.xiaohongshu.com/ark/open_api/v3/common_controller``，**只有 POST**。
  官方 API 文档里那个 ``"path": "/ark/order.getOrderList"`` 字段是文档系统的内部注册
  路径，**不是调用地址**。
* **系统参数与业务参数全部扁平放在 POST body（JSON）**，
  ``Content-Type: application/json;charset=utf-8``。没有 query string。
* **系统参数**：``appId`` / ``method`` / ``version``（``"2.0"``）/ ``timestamp`` /
  ``sign`` 必填，``accessToken``（小驼峰）调用商家业务接口必带；全部为 string 类型。
  ``timestamp`` 是 **UNIX 秒**（10 位字符串）。
* **签名**：待签串 = ``{method}?appId={appId}&timestamp={timestamp}&version={version}``
  再直接拼 ``appSecret``，MD5 取 **32 位小写 hex**。**只有那 4 个系统参数参与**，
  业务参数与 ``accessToken`` 都不参与（官方两处明文）。
* **判错**：网关信封 ``{"error_code": 0, "error_msg": ..., "data": {...},
  "success": true}``，``error_code == 0 且 success == true`` 才是成功，业务数据在
  ``data``（需解包一层）。错误码为负整数。
* **网关版本混排**：``afterSale.listAfterSaleInfos`` / ``afterSale.getAfterSaleInfo``
  / ``inventory.getSkuStockV2`` / ``finance.*`` 注册在 gatewayId=165 /
  gatewayVersionId=2804，其官方响应 schema 自带一层 ``{code, msg, success, data}``；
  ``order.*`` / ``product.*`` / ``bill.*`` 在 103/1661，响应即业务体。因此**不能用一套
  信封解析无脑套** —— 见 ``_unwrap_envelope``。

⚠️ 单位陷阱：``order.getOrderList`` 的业务入参 ``startTime``/``endTime`` 是**秒**，
而所有出参时间字段（``createdTime``/``paidTime``/``updateTime`` 等）是**毫秒**；
``afterSale.*`` 与 ``finance.*`` 的入参时间是**毫秒**。逐接口以 docstring 为准。

Auth via env vars: XHS_CLIENT_ID (appId), XHS_CLIENT_SECRET (appSecret),
XHS_ACCESS_TOKEN (accessToken).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

from shared.cn_commerce_base import (
    CommerceAPIError,
    CommerceMCPBase,
    ConfigValidationError,
    SignMethod,
    register_common_tools,
)

# ── 契约常量（wire 断言直接引用这些，避免测试里重抄字面量） ────────────────────

#: 唯一网关地址。官方《系统参数说明》注2 明文，只支持 POST。
GATEWAY_URL = "https://ark.xiaohongshu.com/ark/open_api/v3/common_controller"

#: 官方《系统参数说明》：采用 oauth2 授权后均填 "2.0"。
API_VERSION = "2.0"

#: 官方《系统参数说明》注1：数据传输采用 JSON，headers 统一设置该 content-type。
CONTENT_TYPE = "application/json;charset=utf-8"

#: 参与签名的字段集合。官方《签名算法》："目前参与加密的均为系统参数和 appSecret。
#: 系统参数有：appId,timestamp,version,method"。accessToken 与业务参数都不参与。
SIGNED_PARAMS = frozenset({"method", "appId", "timestamp", "version"})

#: 系统参数字段名（含不参与签名的 sign / accessToken），用于业务参数撞名检查。
SYSTEM_PARAMS = frozenset(SIGNED_PARAMS | {"sign", "accessToken"})

# 网关版本族。同一个 URL、同一套系统参数，但入参/信封形态不同。
GATEWAY_103_1661 = "103/1661"
GATEWAY_165_2804 = "165/2804"

#: method → 网关版本族。取自官方文档清单接口
#: ``api/doc/second/listNew?apiNavigationId=<id>`` 里每条记录自带的
#: ``gatewayId``/``gatewayVersionId``，不是推断。
METHOD_GATEWAY: dict[str, str] = {
    # 订单域
    "order.getOrderList": GATEWAY_103_1661,
    "order.getOrderDetail": GATEWAY_103_1661,
    "order.getOrderTracking": GATEWAY_103_1661,
    # 商品域
    "product.searchItemList": GATEWAY_103_1661,
    "product.getItemInfo": GATEWAY_103_1661,
    # 账单域（注意：bill.* 在 103/1661，只有 finance.* 在 165/2804）
    "bill.downloadStatement": GATEWAY_103_1661,
    # 售后域（新版售后接口整体迁到 165/2804）
    "afterSale.listAfterSaleInfos": GATEWAY_165_2804,
    "afterSale.getAfterSaleInfo": GATEWAY_165_2804,
    # 库存域（V2 在 165/2804，旧版 inventory.getSkuStock 在 103/1661）
    "inventory.getSkuStockV2": GATEWAY_165_2804,
    # 财务域
    "finance.pageQueryTransaction": GATEWAY_165_2804,
    "finance.querySellerAccountRecords": GATEWAY_165_2804,
    "finance.pageQueryExpense": GATEWAY_165_2804,
}


# ── Xiaohongshu client ────────────────────────────────────────────────────────


class XiaohongshuMCP(CommerceMCPBase):
    """小红书网关客户端。

    完全不走 ``CommerceMCPBase._request`` / ``._sign``：那套统一实现假设
    ``access_token`` 入签、``timestamp`` 为毫秒、签名 ``secret+sorted_kv+secret``
    转大写、按 ``error_response`` 判错 —— 四项对小红书全部不成立。
    """

    BASE_URL = GATEWAY_URL
    sign_method = SignMethod.MD5

    # ── 签名 ────────────────────────────────────────────────────────────────

    def _sign_source(self, api_method: str, timestamp: str) -> str:
        """构造待签串（不含 appSecret 之外的任何分隔符）。

        官方《签名算法》示例正文把串写成 ``method?appId=xxx& timestamp=...``，
        ``&`` 后带一个空格，同页已注明「拼接字段空格为格式，实际中不存在」，
        官方 Java/Python/Go 代码示例里也没有空格 —— 真实串无空格。

        三个 ``k=v`` 段按官方示例代码 ``params.sort()`` 的自然序排列，恰好是
        ``appId`` < ``timestamp`` < ``version``；``method`` 在 ``?`` 之前，
        本身不是 ``k=v`` 形式、不参与排序。
        """
        return f"{api_method}?appId={self.app_key}&timestamp={timestamp}&version={API_VERSION}"

    def _sign_request(self, api_method: str, timestamp: str) -> str:
        """MD5(待签串 + appSecret) → 32 位小写 hex（官方示例代码为 ``hexdigest()``）。"""
        raw = self._sign_source(api_method, timestamp) + self.app_secret
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    # ── 信封 ────────────────────────────────────────────────────────────────

    @staticmethod
    def _check_envelope(payload: Any, *, api_method: str, layer: str) -> Any:
        """校验一层信封并返回其 ``data``。

        成功判据是 ``error_code == 0 且 success == true``（165/2804 族的内层用
        ``code`` 承载同一语义）。**任何认不出来的信封都 fail-closed 抛错**，
        而不是把信封原样当业务数据返回给模型 —— 后者正是重写前的缺陷：旧实现只查
        淘宝/拼多多的 ``error_response``，小红书的失败一律检测不到。
        """
        if not isinstance(payload, dict):
            raise CommerceAPIError(
                code=-1,
                msg=f"{api_method}: {layer} 信封不是 JSON object（得到 {type(payload).__name__}）",
            )
        code = payload.get("error_code", payload.get("code"))
        if code == 0 and payload.get("success") is True:
            return payload.get("data")
        msg = payload.get("error_msg") or payload.get("msg")
        if not msg:
            msg = f"无法识别的{layer}信封，字段为 {sorted(payload)}"
        raise CommerceAPIError(
            code=code if isinstance(code, int) else -1,
            msg=f"{api_method}: {msg}",
        )

    @classmethod
    def _unwrap_envelope(cls, payload: Any, *, api_method: str, gateway: str) -> Any:
        """解包网关信封，返回业务数据。

        103/1661 族：外层网关信封一层即到业务体。
        165/2804 族：官方响应 schema 自身就是 ``{code, msg, success, data}``，
        即业务体外还有一层 —— 但官方未明文说明这层是网关叠加还是接口自带，
        所以这里按「存在则再解一层」处理，两种读法都能走通（契约文档已标为待真机回归）。
        """
        data = cls._check_envelope(payload, api_method=api_method, layer="网关")
        if gateway == GATEWAY_165_2804 and isinstance(data, dict) and {"code", "success"} <= set(data):
            data = cls._check_envelope(data, api_method=api_method, layer="内层")
        return data

    # ── 调用 ────────────────────────────────────────────────────────────────

    async def _call(self, api_method: str, biz_params: dict | None = None) -> Any:
        """调用一个官方 method，返回已解包的业务数据。

        Args:
            api_method: 官方 method 名，如 ``order.getOrderList``。必须在
                ``METHOD_GATEWAY`` 里登记，未登记的直接拒绝 —— 防止再次出现
                「打到不存在的接口上」这类缺陷。
            biz_params: 业务参数，值为 ``None`` 的键会被丢弃。不做统一 str 化：
                官方业务参数表里 ``pageNo``/``timeType``/``startTime`` 等是
                integer/number，系统参数才是 string。
        """
        gateway = METHOD_GATEWAY.get(api_method)
        if gateway is None:
            raise ValueError(
                f"未登记的 method {api_method!r}；请先在 METHOD_GATEWAY 里按官方文档清单"
                "登记它的 gatewayId/gatewayVersionId"
            )

        biz = {k: v for k, v in (biz_params or {}).items() if v is not None}
        collisions = SYSTEM_PARAMS & set(biz)
        if collisions:
            raise ValueError(f"业务参数与系统参数撞名: {sorted(collisions)}")

        # 系统参数：全部 string；timestamp 为 UNIX 秒（10 位）。
        system: dict[str, str] = {
            "appId": self.app_key,
            "method": api_method,
            "timestamp": str(int(time.time())),
            "version": API_VERSION,
        }
        # 签名与发送共用同一份取值，避免「签一份、发另一份」。
        system["sign"] = self._sign_request(system["method"], system["timestamp"])
        if self.access_token:
            # 官方两处明文：accessToken 不参与 sign 签名运算。
            system["accessToken"] = self.access_token

        body: dict[str, Any] = {**system, **biz}

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(GATEWAY_URL, json=body, headers={"Content-Type": CONTENT_TYPE})

        return self._unwrap_envelope(resp.json(), api_method=api_method, gateway=gateway)


# ── 参数辅助 ─────────────────────────────────────────────────────────────────


def _optional_int(raw: str, field: str) -> int | None:
    """把「空串表示不传」的可选整数参数转成 int 或 None。

    这些字段的官方枚举里 0 本身是有效值（如 ``settleBizType`` 0=结算入账），
    所以不能用 0 当「不传」的哨兵值。
    """
    if raw == "":
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{field} 必须是整数或空串，得到 {raw!r}") from exc


def _int_list(raw: str, field: str) -> list[int] | None:
    """把逗号分隔的整数列表转成 list[int]（空串→None，即不传该过滤条件）。"""
    if raw.strip() == "":
        return None
    try:
        return [int(part) for part in raw.split(",") if part.strip() != ""]
    except ValueError as exc:
        raise ValueError(f"{field} 必须是逗号分隔的整数，得到 {raw!r}") from exc


def _str_list(raw: str, field: str) -> list[str] | None:
    """把逗号分隔的字符串列表转成 list[str]（空串→None）。"""
    if raw.strip() == "":
        return None
    return [part.strip() for part in raw.split(",") if part.strip() != ""]


def _compact(biz_params: dict[str, Any]) -> dict[str, Any]:
    """丢掉值为 ``None`` 的可选业务参数（``None`` = 该条件不传）。"""
    return {k: v for k, v in biz_params.items() if v is not None}


def _dump(result: Any) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2)


# ── Instantiate client from env ────────────────────────────────────────────


def _create_xiaohongshu_client() -> XiaohongshuMCP:
    """Create xiaohongshu client with configuration validation."""
    try:
        return XiaohongshuMCP.from_env("XHS", ["CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN"])
    except ConfigValidationError:
        # Fallback to direct instantiation for backward compatibility
        return XiaohongshuMCP(
            app_key=os.environ.get("XHS_CLIENT_ID", ""),
            app_secret=os.environ.get("XHS_CLIENT_SECRET", ""),
            access_token=os.environ.get("XHS_ACCESS_TOKEN", ""),
        )


xhs = _create_xiaohongshu_client()


# ── MCP server ─────────────────────────────────────────────────────────────────

mcp = MCPServer("mcp-cn-xiaohongshu")


# ═══════════════════════════════════════════════════════════════════════════════
# 订单 (Orders) — order.* / 103·1661
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_order_list(
    start_time: int,
    end_time: int,
    time_type: int = 1,
    order_type: int = 0,
    order_status: int = 0,
    page_no: int = 1,
    page_size: int = 50,
) -> str:
    """查询订单列表（官方 method ``order.getOrderList``）。

    平台侧硬约束，调用前必须知道：

    * ``time_type=1``（创建时间）时 ``end_time - start_time`` **≤ 24 小时**；
      ``time_type=2``（更新时间）时 **≤ 30 分钟**。
    * ``time_type=2`` 官方要求**从 ``maxPageNo`` 倒着往第一页翻**（响应里返回
      ``maxPageNo``）。顺序翻页会因为翻页期间订单更新时间变化而**漏单**，增量同步
      必须倒序。
    * ``page_no`` ≤ 100、``page_size`` ≤ 100 ⇒ 单个时间窗最多取到 10000 单；
      窗口内订单更多时只能缩小时间窗，不能靠翻页。

    Args:
        start_time: 时间范围起点，**UNIX 秒**（10 位）。
        end_time: 时间范围终点，**UNIX 秒**。
        time_type: 时间类型，1 创建时间（窗口 ≤24h），2 更新时间（窗口 ≤30min）。
        order_type: 订单类型，0 全部 / 1 现货 / 2 定金预售 / 3 全款预售(废弃)
            / 4 全款预售(新) / 5 换货补发。
        order_status: 订单状态，0 全部 / 1 已下单待付款 / 2 已支付处理中 / 3 清关中
            / 4 待发货 / 5 部分发货 / 6 待收货 / 7 已完成 / 8 已关闭 / 9 已取消
            / 10 换货申请中。
        page_no: 页码，默认 1，上限 100。
        page_size: 每页条数，默认 50，上限 100。

    Returns:
        JSON 字符串。⚠️ 出参里的 ``createdTime``/``paidTime``/``updateTime`` 等
        时间字段是**毫秒**，与入参的秒不同单位。金额字段单位为**分**。
        收件人姓名/手机/地址不在此接口返回，需另调 ``order.getOrderReceiverInfo``
        （仅待发货状态返回）。
    """
    if time_type == 1 and end_time - start_time > 24 * 3600:
        raise ValueError("time_type=1（创建时间）的时间窗上限为 24 小时（官方约束）")
    if time_type == 2 and end_time - start_time > 30 * 60:
        raise ValueError("time_type=2（更新时间）的时间窗上限为 30 分钟（官方约束）")
    if page_no > 100 or page_size > 100:
        raise ValueError("page_no 与 page_size 的官方上限均为 100")

    biz_params: dict[str, Any] = {
        "startTime": start_time,
        "endTime": end_time,
        "timeType": time_type,
        "orderType": order_type,
        "orderStatus": order_status,
        "pageNo": page_no,
        "pageSize": page_size,
    }
    return _dump(await xhs._call("order.getOrderList", biz_params))


@mcp.tool()
async def get_order_detail(order_id: str) -> str:
    """查询单个订单详情（官方 method ``order.getOrderDetail``）。

    Args:
        order_id: 订单号（官方字段名 ``orderId``，形如 ``P141***1412``）。

    Returns:
        JSON 字符串。时间字段单位**毫秒**、金额字段单位**分**、净重单位 g。
        ``receiverName``/``receiverPhone``/``receiverAddress`` 官方标注「暂不返回」，
        收件人明文需走 ``order.getOrderReceiverInfo``（仅待发货状态返回）；
        只读分析请直接用本接口已明文返回的 ``receiverProvinceName`` /
        ``receiverCityName`` / ``receiverDistrictName``。
    """
    return _dump(await xhs._call("order.getOrderDetail", {"orderId": order_id}))


# ═══════════════════════════════════════════════════════════════════════════════
# 物流 (Logistics) — order.getOrderTracking / 103·1661
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_logistics_tracking(order_id: str) -> str:
    """查询订单物流轨迹（官方 method ``order.getOrderTracking``）。

    Args:
        order_id: 订单号（官方字段名 ``orderId``）。

    Returns:
        JSON 字符串，``orderTrackInfos[]`` 含快递公司编码/名称、快递单号，以及
        ``records[]`` 轨迹节点（``eventAt`` 为 ``yyyy-MM-dd HH:mm:ss`` 字符串，
        不是时间戳；``nodeId`` 5 交易系统 / 6 履约系统 / 8 仓库系统 / 35 快递公司）。
    """
    return _dump(await xhs._call("order.getOrderTracking", {"orderId": order_id}))


# ═══════════════════════════════════════════════════════════════════════════════
# 商品 (Products) — product.* / 103·1661
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_product_list(
    page_no: int = 1,
    page_size: int = 50,
    keyword: str = "",
    last_id: str = "",
) -> str:
    """查询商品（ITEM）列表（官方 method ``product.searchItemList``）。

    粒度选择：本工具用 **ITEM 粒度**的 ``product.searchItemList``，而不是 SKU 粒度的
    ``product.getDetailSkuList``。理由：(1) 与 ``get_product_detail``
    （``product.getItemInfo``，入参 ``itemId``）的 ID 空间一致，列表→详情可直接串联；
    SKU 列表返回的是 skuId，喂不进 ``getItemInfo``；(2) SKU 级库存已由
    ``get_inventory``（``inventory.getSkuStockV2``）覆盖，不必在商品列表里重复。
    若确实需要按库存/条码/更新时间筛 SKU，官方对应接口是
    ``product.getDetailSkuList``（本 server 暂未暴露）。

    Args:
        page_no: 页码（官方必填 ``pageNo``）。
        page_size: 每页条数（官方必填 ``pageSize``）。
        keyword: 商品名称关键词，写入官方 ``searchParam.keyword``；空串表示不筛。
        last_id: 查询起始 itemId（官方 ``searchParam.lastId``，全店 item 按时间倒序）；
            空串表示从头查。

    Returns:
        JSON 字符串。官方 ``searchParam`` 还支持 ``topCategoryIds`` /
        ``lvl2~4CategoryIds`` / ``buyable`` / ``keywords``（小红书编码/条形码/商品ID/
        SPUID/货号）/ ``logisticsPlanIds`` / ``createTimeFrom`` / ``createTimeTo``，
        本工具只暴露了关键词与游标两项。
    """
    search_param: dict[str, Any] = {}
    if keyword:
        search_param["keyword"] = keyword
    if last_id:
        search_param["lastId"] = last_id

    biz_params: dict[str, Any] = {
        "pageNo": page_no,
        "pageSize": page_size,
        # searchParam 官方必填；无筛选条件时传空 object。
        "searchParam": search_param,
    }
    return _dump(await xhs._call("product.searchItemList", biz_params))


@mcp.tool()
async def get_product_detail(item_id: str, page_no: int = 1, page_size: int = 50) -> str:
    """查询单个商品（ITEM）详情及其 SKU 列表（官方 method ``product.getItemInfo``）。

    Args:
        item_id: 商品 ITEM id（官方必填字段 ``itemId``）。
        page_no: SKU 列表页码。
        page_size: SKU 列表每页条数。

    Returns:
        JSON 字符串，含 ``itemInfo``、``skuInfos[]``、``total``（sku 数量）。

    Note:
        官方参数表把 ``pageSize`` 的说明写成「当前页码」、``pageNo`` 的说明写成
        「页码大小」，两条描述互换，明显是文档笔误。本实现按字段名的通行语义传参
        （``pageNo``=页码、``pageSize``=页大小），该判断已记入契约文档待真机回归。
    """
    biz_params: dict[str, Any] = {
        "itemId": item_id,
        "pageNo": page_no,
        "pageSize": page_size,
    }
    return _dump(await xhs._call("product.getItemInfo", biz_params))


# ═══════════════════════════════════════════════════════════════════════════════
# 售后 (After-Sale) — afterSale.* / 165·2804
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_refund_list(
    page_no: int = 1,
    page_size: int = 50,
    order_id: str = "",
    start_time: int = 0,
    end_time: int = 0,
    time_type: int = 0,
    return_types: str = "",
    statuses: str = "",
) -> str:
    """查询售后列表（官方 method ``afterSale.listAfterSaleInfos``，新版售后接口）。

    小红书**没有独立的"退款"域**：退款是售后单的一种类型。若只要「仅退款」，
    传 ``return_types="4,5"``（4 已发货仅退款、5 未发货仅退款）；不传则返回全部
    售后类型（含退货/换货/保价）。

    官方约束：

    * ``order_id`` 与 ``time_type`` **至少传一个**。
    * ``time_type=1``（创建时间）窗口 ≤ 24 小时；``time_type=2``（更新时间）窗口
      ≤ 30 分钟。
    * ``page_size`` ∈ (0, 100]，且 ``page_no * page_size`` ≤ 50000。

    Args:
        page_no: 页数，从 1 开始（官方必填）。
        page_size: 页大小，>0 且 ≤100（官方必填）。
        order_id: 包裹号（官方字段 ``orderId``）；空串表示不按包裹号查。
        start_time: 时间起点，**毫秒**（含）。选了时间类型后必传。
        end_time: 时间终点，**毫秒**（含）。选了时间类型后必传。
        time_type: 时间类型，1 创建时间 / 2 更新时间；0 表示不按时间查。
        return_types: 售后类型列表，逗号分隔。1 退货 / 2 换货 / 4 已发货仅退款
            / 5 未发货仅退款 / 6 保价。空串表示不筛。
        statuses: 售后状态列表，逗号分隔。1 待审核 / 2 待用户寄回 / 3 待商家收货
            / 4 已完成 / 5 已取消 / 6 已关闭 / 9 商家审核拒绝 / 9001 商家收货拒绝
            / 12 换货待商家发货 / 13 换货待用户确认收货 / 14 平台介入中。空串表示不筛。

    Returns:
        JSON 字符串，``afterSaleBasicInfos[]``；``applyTime``/``updatedAt`` 单位**毫秒**。
    """
    if not order_id and time_type == 0:
        raise ValueError("order_id 与 time_type 至少传一个（官方约束）")
    if time_type != 0 and not (start_time and end_time):
        raise ValueError("选择时间类型后 start_time / end_time 必传（官方约束）")
    if time_type == 1 and end_time - start_time > 24 * 3600 * 1000:
        raise ValueError("time_type=1 的时间窗上限为 24 小时（毫秒入参，官方约束）")
    if time_type == 2 and end_time - start_time > 30 * 60 * 1000:
        raise ValueError("time_type=2 的时间窗上限为 30 分钟（毫秒入参，官方约束）")
    if not 0 < page_size <= 100:
        raise ValueError("page_size 必须 >0 且 ≤100（官方约束）")
    if page_no * page_size > 50000:
        raise ValueError("page_no * page_size 不得超过 50000（官方约束）")

    biz_params: dict[str, Any] = {
        "pageNo": page_no,
        "pageSize": page_size,
        "orderId": order_id or None,
        "startTime": start_time or None,
        "endTime": end_time or None,
        "timeType": time_type or None,
        "returnTypes": _int_list(return_types, "return_types"),
        "statuses": _int_list(statuses, "statuses"),
    }
    return _dump(await xhs._call("afterSale.listAfterSaleInfos", _compact(biz_params)))


@mcp.tool()
async def get_refund_detail(returns_id: str, need_negotiate_record: int = 0) -> str:
    """查询售后单详情（官方 method ``afterSale.getAfterSaleInfo``，新版）。

    Args:
        returns_id: 售后单号（官方字段 ``returnsId``）。
        need_negotiate_record: 是否返回协商记录，0 否 / 1 是。官方字段
            ``needNegotiateRecord`` 是 boolean，这里按本仓 MCP 工具入参只用 str/int
            的约定收 0/1，发送前转回 boolean。

    Returns:
        JSON 字符串，``afterSaleInfo``（含 ``returnAddress`` 省/市/区县/街道等）。

    Note:
        该接口官方入参还有一个可选 object ``requestHeader{requestFrom:number}``，
        文档里 ``requestFrom`` 的描述为空（字面是 ``//``），语义不明，因此本实现
        **不发送**该字段。这是 165/2804 族与 103/1661 族的入参形态差异之一。
    """
    biz_params: dict[str, Any] = {
        "returnsId": returns_id,
        "needNegotiateRecord": bool(need_negotiate_record),
    }
    return _dump(await xhs._call("afterSale.getAfterSaleInfo", biz_params))


# ═══════════════════════════════════════════════════════════════════════════════
# 库存 (Inventory) — inventory.getSkuStockV2 / 165·2804
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_inventory(sku_id: str, inventory_type: str = "") -> str:
    """查询单个 SKU 的库存（官方 method ``inventory.getSkuStockV2``，支持多仓）。

    官方 V2 接口按 ``skuId`` 单查，**没有**"整店库存列表"形态；要批量看库存，
    官方路径是 ``product.getDetailSkuList``（带 ``stockGte``/``stockLte`` 过滤，
    本 server 暂未暴露）后逐个查询。

    Args:
        sku_id: 规格 ID（官方必填字段 ``skuId``）。
        inventory_type: 库存类型（官方字段 ``inventoryType``）。官方仅写「库存类型」
            未给枚举值，因此默认空串=**不发送**该字段，不替官方猜默认值。

    Returns:
        JSON 字符串，含 ``skuStockInfo``（``available`` 可售 / ``total`` 总库存 /
        ``occupiedQuantity`` 占用 等）与 ``apiVersion``。响应体内层还有一个
        ``response{code,msg,success}`` 业务状态节点，本实现按业务数据原样返回，
        不当作信封解析（该层非官方明文的判错层）。
    """
    biz_params: dict[str, Any] = {
        "skuId": sku_id,
        "inventoryType": _optional_int(inventory_type, "inventory_type"),
    }
    return _dump(await xhs._call("inventory.getSkuStockV2", _compact(biz_params)))


# ═══════════════════════════════════════════════════════════════════════════════
# 财务 (Finance / Bill)
#
# 原来的单个 get_bill_list 是虚构的：官方账单不是一个列表，而是四个语义不同的接口。
# 按语义拆成四个工具，不做"主用途二选一"，避免把结算明细、动账流水、服务费三类
# 混成一个含义不明的 bill_type 过滤器。
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_settlement_transactions(
    start_time: int,
    end_time: int,
    page_num: int = 1,
    page_size: int = 50,
    settle_biz_type: str = "",
    settle_status: str = "",
    account_type: str = "",
    load_goods_info: int = 0,
) -> str:
    """分页查询订单货款结算明细（官方 method ``finance.pageQueryTransaction``）。

    官方约束：``end_time - start_time`` ≤ 24*60*60*1000，即**单次最多查一天**。

    Args:
        start_time: 开始时间，**毫秒**（含）。结算状态为「已结算」时指结算时间，
            为「未结算」时指订单完成时间。
        end_time: 结束时间，**毫秒**（不含），与 start_time 差值 ≤ 一天。
        page_num: 页码（官方字段 ``pageNum``，注意不是 ``pageNo``）。
        page_size: 分页大小；官方提示过大会超时，建议小分页多次调用。
        settle_biz_type: 交易类型（官方 ``settleBizType``）：0 结算入账 / 1 退款。
            空串表示不筛（0 是有效值，不能当哨兵）。
        settle_status: 结算状态（官方 ``commonSettleStatus``）：0 未结算 / 1 已结算。
            空串表示不筛。
        account_type: 结算账户（官方 ``erqingType``）：0 店铺余额 / 1 支付宝 / 2 微信。
            空串表示不筛。
        load_goods_info: 是否查询商品信息，0 否 / 1 是（官方 ``shouldLoadGoodsInfo``
            是 boolean，按本仓工具入参只用 str/int 的约定收 0/1，发送前转回 boolean）。

    Returns:
        JSON 字符串，``transactions[]`` + ``total``/``totalPage``/``pageNum``/``pageSize``。
    """
    if end_time - start_time > 24 * 3600 * 1000:
        raise ValueError("单次查询区间不得超过一天（24*60*60*1000 毫秒，官方约束）")

    biz_params: dict[str, Any] = {
        "startTime": start_time,
        "endTime": end_time,
        "pageNum": page_num,
        "pageSize": page_size,
        "settleBizType": _optional_int(settle_biz_type, "settle_biz_type"),
        "commonSettleStatus": _optional_int(settle_status, "settle_status"),
        "erqingType": _optional_int(account_type, "account_type"),
        "shouldLoadGoodsInfo": bool(load_goods_info),
    }
    return _dump(await xhs._call("finance.pageQueryTransaction", _compact(biz_params)))


@mcp.tool()
async def get_account_records(
    start_time: int,
    end_time: int,
    page_num: int = 1,
    page_size: int = 50,
    business_no: str = "",
    debit_type: str = "",
    trade_types: str = "",
    fund_type: str = "",
) -> str:
    """分页查询账户动账流水（官方 method ``finance.querySellerAccountRecords``）。

    Args:
        start_time: 开始时间，**毫秒**（如按日查询传当日 00:00:00 的时间戳）。
        end_time: 结束时间，**毫秒**（如按日查询传当日 23:59:59 的时间戳）。
        page_num: 当前分页（官方 ``pageNum``）。
        page_size: 分页大小；官方提示过大会超时。
        business_no: 业务单号（官方 ``businessNo``）；空串表示不筛。
        debit_type: 资金流向（官方 ``debitType``）：``IN`` 收入 / ``OUT`` 支出。
        trade_types: 交易类型列表，逗号分隔（官方 ``tradeTypes``）：``RECHARGE`` 充值
            / ``STATEMENT_IN`` 结算入账 / ``STATEMENT_REFUND`` 退款 / ``PAY_SUCCESS``
            提现 / ``BOUNCE`` 提现退回 / ``SELLER_FINE`` 扣款 / ``REFUND`` 扣款退回
            / ``LOGISTIC_OUT`` 物流费用结算 / ``MANUAL_ADJUST_STATEMENT`` 人工调账结算。
        fund_type: 账户类型（官方 ``fundType``）：0 店铺余额 / 1 微信 / 2 支付宝。
            空串表示不筛。

    Returns:
        JSON 字符串。
    """
    biz_params: dict[str, Any] = {
        "startTime": start_time,
        "endTime": end_time,
        "pageNum": page_num,
        "pageSize": page_size,
        "businessNo": business_no or None,
        "debitType": debit_type or None,
        "tradeTypes": _str_list(trade_types, "trade_types"),
        "fundType": _optional_int(fund_type, "fund_type"),
    }
    return _dump(await xhs._call("finance.querySellerAccountRecords", _compact(biz_params)))


@mcp.tool()
async def get_expense_settlements(
    start_time: int,
    end_time: int,
    page_num: int = 1,
    page_size: int = 50,
    base_biz_type: str = "",
    settle_status: str = "",
) -> str:
    """分页查询其他服务款结算明细（官方 method ``finance.pageQueryExpense``）。

    官方约束：``end_time - start_time`` ≤ 24*60*60*1000，即**单次最多查一天**。

    Args:
        start_time: 开始时间，**毫秒**（含）。
        end_time: 结束时间，**毫秒**（不含）。
        page_num: 页码（官方 ``pageNum``）。
        page_size: 分页大小；官方提示过大会超时。
        base_biz_type: 交易类型（官方 ``baseBizType``）：0 薯券 / 1 在线寄件快递费
            / 2 极速退款赔付 / 3 发货延误赔付 / 4 运费宝 / 5 分期免息平台补贴
            / 6 仲裁结算 / 7 小额打款 / 8 运费报销赔付。空串表示不筛。
        settle_status: 结算状态（官方 ``settleStatus``）：0 未结算 / 1 已结算。
            空串表示不筛。

    Returns:
        JSON 字符串。
    """
    if end_time - start_time > 24 * 3600 * 1000:
        raise ValueError("单次查询区间不得超过一天（24*60*60*1000 毫秒，官方约束）")

    biz_params: dict[str, Any] = {
        "startTime": start_time,
        "endTime": end_time,
        "pageNum": page_num,
        "pageSize": page_size,
        "baseBizType": _optional_int(base_biz_type, "base_biz_type"),
        "settleStatus": _optional_int(settle_status, "settle_status"),
    }
    return _dump(await xhs._call("finance.pageQueryExpense", _compact(biz_params)))


@mcp.tool()
async def get_monthly_statement_url(month: str) -> str:
    """查询月度结算单下载地址（官方 method ``bill.downloadStatement``）。

    Args:
        month: 结算月份，``yyyy-MM`` 格式（官方必填字段 ``month``）。

    Returns:
        JSON 字符串，含 ``downloadUrl``（官方标注**2 小时有效期**）。

    Note:
        该 method 属 ``bill.*``，注册在 gatewayId=103/gatewayVersionId=1661，
        与同为账单语义的 ``finance.*``（165/2804）**不在同一个网关版本**。
    """
    return _dump(await xhs._call("bill.downloadStatement", {"month": month}))


# ── Cross-platform operational tools (get_metrics/get_traces/get_alerts/export_data) ──
register_common_tools(mcp, xhs)


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════


def main() -> None:
    """Entry point for 'mcp-cn-xiaohongshu' console script."""
    mcp.run()


if __name__ == "__main__":
    main()

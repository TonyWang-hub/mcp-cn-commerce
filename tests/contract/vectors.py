"""Official signature vectors published by the platforms themselves.

Each entry is a worked example lifted verbatim from official documentation, so a
passing assertion means our signing agrees with the platform's own arithmetic.

Provenance matters more than convenience here: a vector whose exact input string
could not be recovered from the official source is recorded as ``pending`` rather
than reconstructed, because a guessed input that happens to hash correctly would
silently bless a wrong implementation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SignatureVector:
    """One official worked example for a platform's signing algorithm."""

    platform: str
    secret: str
    #: Exact concatenated string the platform's doc feeds to the digest,
    #: *excluding* any secret wrapping the algorithm itself applies.
    payload: str
    expected: str
    algorithm: str
    source: str
    #: True when the official expected value has been reproduced locally.
    verified: bool = True
    notes: str = ""


#: Vectors reproduced locally, byte for byte.
VERIFIED: tuple[SignatureVector, ...] = (
    SignatureVector(
        platform="pinduoduo",
        secret="testSecret",
        payload=(
            "access_tokenasd78172s8ds9a921j9qqwda12312w1w21211"
            "client_id1"
            "data_typeXML"
            "order_status1"
            "page1"
            "page_size10"
            "timestamp1480411125"
            "typepdd.order.number.list.get"
        ),
        expected="E4DE3ED21002510DED352819E7AE6775",
        algorithm="upper(md5(secret + payload + secret))",
        source="https://open.pinduoduo.com/application/document/browse?idStr=8EC06C399636041E",
        notes="公共参数与业务参数全部参与，拼接处无任何字符，结果转大写。",
    ),
    SignatureVector(
        platform="jd",
        secret="yourappSecret",
        payload=(
            '360buy_param_json{"end_date":null,"optional_fields":null,'
            '"order_state":"WAIT_SELLER_STOCK_OUT","page":"1","page_size":"200",'
            '"start_date":null}'
            "access_tokenyourtoken"
            "app_keyyourappkey"
            "methodjingdong.pop.order.search"
            "timestamp2021-05-07 09:20:39.683+0800"
            "v2.0"
        ),
        expected="D70825340F4084360B9362B60DFD7930",
        algorithm="upper(md5(secret + payload + secret))",
        source="https://open.jd.com/v2/#/doc/dev-guide?listId=2643",
        notes=(
            "该向量同时坐实六件事：secret 首尾各包一次、360buy_param_json 参与且因 '3' "
            "开头排最前、access_token 参与、format 与 sign_method 不参与、timestamp 用"
            "原文字符串、结果大写。京东虽不在本 mission 范围内，此向量仍作为共享签名"
            "逻辑（md5 + secret 包裹）的回归护栏保留。"
        ),
    ),
)

#: Vectors whose official expected value is known but whose exact input string
#: could not be recovered. Deliberately not reconstructed.
PENDING: tuple[SignatureVector, ...] = (
    SignatureVector(
        platform="taobao",
        secret="helloworld",
        payload="",
        expected="66987CB115214E59E6EC978214934FB8",
        algorithm="unknown — see notes",
        source="https://open.taobao.com/docV3.htm?docId=101617&docType=1",
        verified=False,
        notes=(
            "官方算例的期望值已知，但完整入参串未取到。用文档正文中出现的参数串 "
            "'bar2foo1foo_bar3foobar4' 配 secret='helloworld' 试过 5 种公式"
            "（md5 包裹 / md5 前缀 / md5 后缀 / hmac-md5 裸串 / hmac-md5 包裹）"
            "均不匹配，故该算例对应的参数集与我们假设的不同。"
            "不重构输入串——猜出来的输入若碰巧对上，会把错误实现盖章为正确。"
            "取回方式：官方文档为公开可读，需带 _tb_token_ cookie 访问 "
            "/handler/document/getDocument.json?docId=101617&docType=1。"
        ),
    ),
)


def all_vectors() -> tuple[SignatureVector, ...]:
    return VERIFIED + PENDING

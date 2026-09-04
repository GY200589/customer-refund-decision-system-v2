"""知识库检索（RAG 的 R，定稿 §4.7）。

MVP 检索：词典命中打分（标题 ×3 + 正文 ×1）+ 字符二元组重叠兜底，
Postgres 本地查询，无外部依赖；后续可平滑升级 embedding（复用 DashScope
的 qwen3.7-text-embedding，密钥已就位），检索接口签名不变。

铁律：检索不到依据就返回空列表，上层必须明确说"暂时没有查到"，禁止编造。
"""
import re

from sqlalchemy.orm import Session

from ..models import KnowledgeDocument

# 参与打分的业务词典（与 intent 词典同源，另含数字规则类短语）
_TERM_VOCAB = [
    "无理由", "退货", "退款", "凭证", "吊牌", "到账", "原路", "人工审核",
    "尺码", "码数", "腰围", "身高", "体重", "斤",
    "物流", "发货", "快递", "签收", "运输",
    "丹宁", "卫衣", "衬衫", "夹克", "羽绒服", "牛仔裤", "休闲裤", "西裤",
    "工装裤", "运动裤", "短裤", "分类", "上装", "下装",
    "识别失败", "照片", "转人工", "风险", "24小时", "退款流程", "进度",
    "运费", "拒绝", "取消订单", "优惠券", "差价", "发票", "投诉", "密码", "起球", "缩水", "掉色", "异味",
    "商品搜索", "商品推荐", "订单号", "订单详情", "退款详情", "店名", "支付", "扣款", "联系", "客服", "支付方式", "客服电话", "模拟支付",
]


def _query_terms(text: str) -> list[str]:
    """从查询中抽取打分词：业务词典命中 + 数字规则（如 7天/48小时/2尺5）。"""
    terms = [t for t in _TERM_VOCAB if t in text]
    for m in re.findall(r"\d+\s*天|\d+\s*小时|\d+\s*码|\d+\s*斤|2\s*尺\d", text):
        terms.append(m.replace(" ", ""))
    return terms


def _bigrams(text: str) -> set[str]:
    cleaned = re.sub(r"[，。、；：？！\s\n]", "", text)
    return {cleaned[i:i + 2] for i in range(len(cleaned) - 1)} if len(cleaned) > 1 else {cleaned}


def retrieve_knowledge(db: Session, query: str, top_k: int = 3) -> list[dict]:
    """返回命中知识条目 [{doc_key,title,version,category,content,score}]，无命中返回 []。"""
    docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.enabled.is_(True)).all()
    if not docs:
        return []

    terms = _query_terms(query)
    query_bigrams = _bigrams(query)
    scored: list[tuple[float, KnowledgeDocument]] = []
    for doc in docs:
        score = 0.0
        for term in terms:
            if term in doc.title:
                score += 3.0
            if term in doc.content:
                score += 1.0
        # “多久/规则/政策/能否退”属于政策询问，避免被标题含“退款流程”的条目压过。
        if doc.doc_key == "refund_policy" and any(cue in query for cue in ("多久", "规则", "政策", "能不能退", "可以退", "退货退款")):
            score += 4.0
        if doc.doc_key == "service_basics" and any(cue in query for cue in ("店名", "什么店", "你们是谁", "支付", "扣款", "客服电话", "怎么联系")):
            score += 5.0
        if doc.doc_key == "order_query_guide" and any(cue in query for cue in ("订单号", "订单详情", "退款详情", "退款案件")):
            score += 5.0
        if doc.doc_key == "product_search_guide" and any(cue in query for cue in ("找衣服", "找裤子", "商品搜索", "推荐", "颜色", "面料", "版型")):
            score += 3.0
        if score == 0.0 and query_bigrams:
            # 兜底只接受明显重叠，单个“什么/怎么”等通用二元组不能构成依据。
            overlap = len(query_bigrams & _bigrams(doc.title + doc.content))
            ratio = overlap / max(len(query_bigrams), 1)
            if overlap >= 3 and ratio >= 0.30:
                score = ratio
        if score > 0:
            scored.append((score, doc))

    scored.sort(key=lambda pair: (-pair[0], pair[1].id))
    return [
        {
            "doc_key": doc.doc_key,
            "title": doc.title,
            "version": doc.version,
            "category": doc.category,
            "content": doc.content,
            "score": round(score, 2),
        }
        for score, doc in scored[:top_k]
    ]


def format_citations(hits: list[dict]) -> list[str]:
    """回答引用格式：《标题》(版本)，如《售后规则》(v1)。"""
    return [f"《{h['title']}》({h['version']})" for h in hits]

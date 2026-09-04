"""知识检索（RAG）单元测试（定稿 §4.7）。"""
from app.db import SessionLocal
from app.models import KnowledgeDocument
from app.services.rag import format_citations, retrieve_knowledge


def test_retrieval_refund_policy(db_setup):
    with SessionLocal() as db:
        hits = retrieve_knowledge(db, "多久可以退货退款")
        assert hits, "退款政策类查询应有命中"
        assert hits[0]["doc_key"] == "refund_policy"
        assert hits[0]["version"]


def test_retrieval_size_bottom(db_setup):
    with SessionLocal() as db:
        hits = retrieve_knowledge(db, "腰围2尺5穿多大码")
        keys = [h["doc_key"] for h in hits]
        assert "size_guide_bottom" in keys


def test_retrieval_no_hit_returns_empty(db_setup):
    with SessionLocal() as db:
        hits = retrieve_knowledge(db, "量子波动速读法是什么")
        assert hits == [], "无依据查询必须返回空（禁止编造）"


def test_citations_format(db_setup):
    with SessionLocal() as db:
        hits = retrieve_knowledge(db, "退货政策是什么")
        cites = format_citations(hits)
        assert all(c.startswith("《") and "》(" in c for c in cites)


def test_disabled_doc_excluded(db_setup):
    with SessionLocal() as db:
        doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.doc_key == "logistics_guide").first()
        doc.enabled = False
        db.commit()
        hits = retrieve_knowledge(db, "什么时候发货几天能到")
        assert "logistics_guide" not in [h["doc_key"] for h in hits]
        doc.enabled = True
        db.commit()


def test_retrieval_product_order_and_store_guides(db_setup):
    with SessionLocal() as db:
        scenarios = {
            "商品搜索怎么按颜色和面料推荐": "product_search_guide",
            "输入订单号怎么查订单详情": "order_query_guide",
            "MISTER 男装的支付会真实扣款吗": "service_basics",
        }
        for query, expected in scenarios.items():
            keys = [hit["doc_key"] for hit in retrieve_knowledge(db, query)]
            assert expected in keys, (query, keys)

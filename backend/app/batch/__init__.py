"""batch 模块：批量审批

提供以下能力：
1. exporter: 导出挂起订单为 Excel
2. parser: 沙箱隔离解析审批后的 Excel
3. executor: 批量 resume_workflow + 三层防重 + 汇总
"""
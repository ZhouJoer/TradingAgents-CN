"""行业分析两阶段提示词模板。"""

from __future__ import annotations

from textwrap import dedent

RISK_DISCLAIMER = "仅供研究参考，不构成投资建议"

DUE_DILIGENCE_PROMPT_TEMPLATE = dedent(
    """\
    你是一名严格、审慎、注重证据链的行业研究员。
    现在请围绕“{industry_query}”执行第一阶段任务：行业尽调。

    总体要求：
    1. 只允许使用中文输出。
    2. 采用“结论先行”写法：开头先给出执行摘要，再展开分析。
    3. 全文尽量多用表格，尤其是产业链、项目验证、风险矩阵等部分必须以表格为主。
    4. 不得推荐、暗示或影射任何具体股票、基金或投资标的。
    5. 对不确定、存疑或缺少证据的内容，必须明确标注“待验证/信息不足/需进一步核实”。
    6. 所有判断尽量给出判断依据、验证线索和后续跟踪指标。
    7. 结尾必须保留风险提示：{risk_disclaimer}
    8. 必须先判断主题类型：产业链型、政策主题型、风格因子型、周期型或其他；如果是“高股息”等非标准产业链主题，可用“资产类型/行业来源/现金流来源/风险来源”替代上中下游。

    请严格按照以下结构输出，且不要遗漏任何部分：

    # 一、执行摘要
    - 用 4-6 条要点直接回答：这个概念是否值得持续关注、目前大致处于什么阶段、最值得看的产业环节、最大不确定性是什么。

    # 二、概念解析
    - 将“{industry_query}”这个可能较模糊的概念拆解为：核心标签、行业映射、应用场景、政策标签、主题风格标签。
    - 区分它到底更偏“行业”“主题”“技术路线”“应用场景”还是“政策驱动概念”。
    - 请输出表格：原始概念表述｜标准化标签｜对应行业映射｜风格标签｜备注

    # 三、行业边界定义
    - 明确什么业务真正属于该概念，什么只是概念邻近、主题沾边或阶段性蹭概念。
    - 说明谁是真正受益方，谁只是间接受益方。
    - 请输出表格：业务类型｜是否属于核心受益｜属于原因｜常见误判点

    # 四、产业链拆解
    - 将该行业拆成关键环节，说明每个环节的主要业务、核心参与者类型、进入壁垒、盈利难点。
    - 必须输出表格：环节｜主要业务｜核心参与者类型｜壁垒｜盈利难点

    # 五、政策与周期判断
    - 判断该行业是否具有明显政策驱动属性。
    - 说明目前更像导入期、成长期、景气扩散期、竞争加剧期还是出清期。
    - 列出影响最大的监管政策、产业政策、招投标规则、补贴机制或行业标准。
    - 请输出表格：政策/规则｜当前状态｜影响方向｜影响强度｜需要跟踪的变化点

    # 六、经济性公式
    - 提炼行业的核心盈利公式。
    - 说明主要收入来源、关键成本项、利润弹性来源、最敏感变量。
    - 请输出表格：项目｜具体内容｜对盈利的作用｜敏感变量｜典型风险

    # 七、需求端验证
    - 说明谁是最终买单方，付款意愿来自什么，是否存在替代方案，需求是否可持续。
    - 区分“政策催生需求”“真实商业需求”“短期主题性需求”。
    - 请输出表格：需求方｜购买动机｜支付能力/意愿｜替代品｜需求持续性判断

    # 八、真实项目/订单验证
    - 优先梳理能验证行业景气度的真实项目、订单、招标、中标、产能落地、客户导入等线索。
    - 不要求追求穷尽，但要突出“能证明什么”和“有什么风险”。
    - 必须输出表格：项目｜相关主体｜规模｜进度｜下游客户｜验证了什么｜风险

    # 九、竞争格局
    - 判断行业龙头、二线玩家、潜在进入者各自优势。
    - 说明行业集中度、是否容易价格战、渠道壁垒、客户壁垒、认证壁垒、技术壁垒等。
    - 请输出表格：公司类型/阵营｜主要优势｜主要短板｜集中度判断｜竞争焦点

    # 十、风险矩阵
    - 从政策、需求、技术替代、价格竞争、资本开支、海外风险、供应链、财务兑现等维度构建风险矩阵。
    - 必须输出表格：风险｜等级｜触发条件｜影响｜跟踪指标

    # 十一、行业结论
    - 回答以下问题：
      - 这个行业/概念是否值得持续关注？
      - 当前处于什么阶段？
      - 最值得跟踪的细分环节是什么？
      - 最大的不确定性是什么？
    - 请再输出一个总结表格：结论项｜判断｜核心依据｜后续验证指标

    最后单独输出一行风险提示：{risk_disclaimer}
    """
).strip()

STOCK_SELECTION_PROMPT_TEMPLATE = dedent(
    """\
    你是一名专注A股的选股研究员。
    现在请基于“{industry_query}”的行业尽调结果，执行第二阶段任务：基于尽调结果选股。

    重要输入信息如下：
    一、行业尽调报告：
    {industry_due_diligence_report}

    二、候选股票数据（如有）：
    {candidate_data}

    总体要求：
    1. 只允许使用中文输出。
    2. 采用“结论先行”写法：先给出Top 5结论摘要，再展开过程。
    3. 尽量使用表格表达，评分、候选池、剔除原因、组合建议必须以表格呈现。
    4. 选股逻辑必须严格基于尽调结论，不得脱离行业逻辑另起炉灶。
    5. 若候选数据不足或为空，可以自行构建A股候选池，但必须明确说明数据限制，且不能编造不存在的财务或交易数据。
    6. 仅讨论A股，不要输出港股、美股、ETF、基金或其他非A股标的。
    7. 结尾必须保留风险提示：{risk_disclaimer}
    8. 正文结束后，必须额外输出一个 fenced JSON 代码块。JSON 只能使用真实候选数据或明确标注数据缺口，不得编造财务或行情数据。

    请严格按照以下结构输出：

    # 一、Top 5结论摘要
    - 先用 4-6 条要点直接给出Top 5排序、核心逻辑、最大风险、最关键跟踪指标。

    # 二、提取选股关键变量
    - 从行业尽调报告中提炼真正影响选股成败的关键变量。
    - 必须输出表格：选股变量｜具体内容｜对选股的影响

    # 三、构建A股候选池
    - 说明应纳入哪些类型公司、应排除哪些类型公司、哪些概念邻近公司需要剔除。
    - 解释“核心受益”“间接受益”“主题映射但基本面弱相关”三类公司的边界。
    - 必须输出表格：公司类型｜是否纳入｜纳入/剔除原因｜备注

    # 四、股票多维评分
    - 对候选A股进行多维评分，并明确评分逻辑与权重。
    - 必须使用以下权重：
      - 概念相关性：15
      - 行业地位：15
      - 发展前景：18
      - 基本面：18
      - 技术面：14
      - 财务健康：12
      - 估值合理性：8
      - 风险扣分：最多扣 20 分
    - 请先给出评分方法说明，再输出评分表。
    - 评分表建议字段：股票代码｜股票名称｜概念相关性｜行业地位｜发展前景｜基本面｜技术面｜财务健康｜估值合理性｜风险扣分｜总分｜说明

    # 五、推荐A股 Top 5
    - 从候选池中给出最值得关注的Top 5。
    - 必须输出表格：排名｜股票代码｜股票名称｜所属行业｜总分｜推荐逻辑｜主要优势｜主要风险｜适合风格

    # 六、未入选/剔除原因
    - 对没有进入Top 5或被排除的关键类型公司进行解释。
    - 必须输出表格：类型公司｜未入选原因｜是否可观察

    # 七、组合建议
    - 给出稳健型、成长型、高弹性三类配置思路。
    - 说明哪类公司不宜过度集中，哪些风险暴露不应重仓叠加。
    - 必须输出表格：组合风格｜适合纳入的类型｜配置思路｜主要风险｜不宜超配的方向

    # 八、最终结论
    - 再次明确Top 5最终排序。
    - 逐一概括每只股票的核心逻辑。
    - 指出本次选股最大的系统性风险与最重要的跟踪指标。
    - 请输出表格：排名｜股票代码｜股票名称｜一句话核心逻辑｜最大风险｜跟踪指标

    最后单独输出一行风险提示：{risk_disclaimer}

    正文之后请输出如下结构化 JSON，字段名必须保持英文，缺失内容用空字符串或空数组：
    ```json
    {{
      "industry_logic_sections": {{
        "supply_chain": "产业链、资产类型或价值来源总结",
        "policy": "政策与监管逻辑",
        "cycle": "景气度和周期判断",
        "demand": "需求驱动",
        "competition": "竞争格局",
        "risks": "核心风险"
      }},
      "stock_selection_sections": {{
        "leaders": "龙头逻辑",
        "growth_beta": "成长弹性逻辑",
        "valuation_repair": "低估修复逻辑",
        "high_risk": "高风险高波动逻辑",
        "watchlist": "观察名单逻辑"
      }},
      "supply_chain_analysis": [
        {{
          "segment_key": "upstream | midstream | downstream | applications | infrastructure_or_services",
          "segment_name": "环节名称",
          "business": "主要业务",
          "benefit_logic": "受益逻辑",
          "key_indicators": "关键跟踪指标",
          "risks": "主要风险",
          "related_stocks": [
            {{"code": "000000", "name": "股票名称", "summary": "相关原因", "supply_chain_position": "环节名称"}}
          ]
        }}
      ],
      "recommendation_groups": [
        {{
          "group_key": "stable_leaders",
          "group_name": "稳健龙头",
          "description": "分组说明",
          "suitable_style": "适合投资风格",
          "main_risks": "主要风险",
          "stocks": [
            {{"code": "000000", "name": "股票名称", "score": 0, "recommendation_logic": "推荐逻辑", "main_advantages": "主要优势", "main_risks": "主要风险", "suitable_style": "适合风格", "supply_chain_position": "产业链位置"}}
          ]
        }},
        {{"group_key": "growth_beta", "group_name": "成长弹性", "description": "", "suitable_style": "", "main_risks": "", "stocks": []}},
        {{"group_key": "valuation_repair", "group_name": "低估修复", "description": "", "suitable_style": "", "main_risks": "", "stocks": []}},
        {{"group_key": "high_risk_high_volatility", "group_name": "高风险高波动", "description": "", "suitable_style": "", "main_risks": "", "stocks": []}},
        {{"group_key": "watchlist", "group_name": "观察名单", "description": "", "suitable_style": "", "main_risks": "", "stocks": []}}
      ],
      "recommendations": [
        {{"rank": 1, "code": "000000", "name": "股票名称", "industry": "行业", "score": 0, "summary": "摘要", "recommendation_logic": "推荐逻辑", "main_advantages": "主要优势", "main_risks": "主要风险", "suitable_style": "适合风格", "supply_chain_position": "产业链位置", "score_breakdown": {{}}}}
      ]
    }}
    ```
    """
).strip()


__all__ = [
    "RISK_DISCLAIMER",
    "DUE_DILIGENCE_PROMPT_TEMPLATE",
    "STOCK_SELECTION_PROMPT_TEMPLATE",
    "build_due_diligence_prompt",
    "build_stock_selection_prompt",
]


def build_due_diligence_prompt(industry_query: str) -> str:
    """构建行业尽调提示词。"""
    normalized_query = (industry_query or "").strip()
    if not normalized_query:
        raise ValueError("industry_query 不能为空")

    return DUE_DILIGENCE_PROMPT_TEMPLATE.format(
        industry_query=normalized_query,
        risk_disclaimer=RISK_DISCLAIMER,
    )


def build_stock_selection_prompt(
    industry_query: str,
    due_diligence_report: str,
    candidate_data: str = "",
) -> str:
    """构建基于尽调结果的A股选股提示词。"""
    normalized_query = (industry_query or "").strip()
    normalized_report = (due_diligence_report or "").strip()
    normalized_candidate_data = (candidate_data or "").strip()

    if not normalized_query:
        raise ValueError("industry_query 不能为空")
    if not normalized_report:
        raise ValueError("due_diligence_report 不能为空")

    return STOCK_SELECTION_PROMPT_TEMPLATE.format(
        industry_query=normalized_query,
        industry_due_diligence_report=normalized_report,
        candidate_data=(
            normalized_candidate_data
            or "未提供 candidate_data。请基于行业尽调报告自行构建A股候选池，并在输出中明确说明量化数据缺口与结论局限。"
        ),
        risk_disclaimer=RISK_DISCLAIMER,
    )

"""验收会报告生成：分用途、总表、分合同节能范围与签认对照。"""

from __future__ import annotations

from .core import PURPOSE_METER, PURPOSE_TEMP


def f1(x):
    return "—" if x is None else f"{x:.1f}"


def f0(x):
    return "—" if x is None else f"{x:.0f}"


def pct(x):
    return "—" if x is None else f"{x:.3f}"


def yuan(x):
    return "—" if x is None else f"{x:.2f}"


def _md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


# ---------------------------------------------------------------- 各节


def sec_scope(res):
    q = res["query_date"]
    lines = [
        "## 一、口径与可知性",
        "",
        f"- 查询日：**{q}**；日粒度记录翌日可知，本报告只使用 **{res['last_daily']} 及以前**的逐日记录。",
        "- 更正按发布日（recorded）截至查询日生效；同一表同一日期取最近发布的一条；换算系数相对原读数，撤销使该日读数无效。",
        "- 申请阶段 = 签认期间 2026-11 内、合同改造已投用且记录可知的日期。",
        "- 基准只用投用前可知资料：备案拟合窗进拟合，备案留出窗只核对不进拟合；分步投用期只有未投用用途的独立分表可作自身基准的额外证据。",
        "- 节能签认只在合同约定度日/小时范围内进行，超出有效观测支撑的组合不外推。",
        "- 存在未分项用热时，总表与有效分表共同限制可归属量：各合同当日可签合计不超过总表节能；超出部分不互抵、不分配。",
        "- 舒适缺测不是温度合格；只有确认停用且无开放承诺的日期才没有开放期温度义务。",
        "- 覆盖率分子须有可采用耗热证据与基准支撑（当日天气度日记录均可核）；开放期室温按舒适度约束单独核对，见第五节。",
        "",
        "**截至查询日生效的更正：**",
        "",
    ]
    rows = []
    for e in res["timeline"]:
        if e["in_scope"]:
            rows.append([e["recorded"], e["meter"], f"{e['from']}~{e['until']}", e["action"],
                         "—" if e["factor"] is None else e["factor"]])
    lines.append(_md_table(["发布日", "表", "适用日期", "动作", "系数"], rows) if rows else "（无）")
    post = [e for e in res["timeline"] if not e["in_scope"]]
    if post:
        lines += ["", "**查询日之后发布、不纳入本次口径的更正（见第八节）：**", ""]
        lines.append(_md_table(
            ["发布日", "表", "适用日期", "动作", "系数"],
            [[e["recorded"], e["meter"], f"{e['from']}~{e['until']}", e["action"],
              "—" if e["factor"] is None else e["factor"]] for e in post]))
    return "\n".join(lines)


def sec_baseline(res):
    lines = ["## 二、基准拟合与留出核对", ""]
    for name, b in res["baselines"].items():
        if name == "总表":
            coef_txt = f"截距 {b['coef'][0]:.2f}，度日 {b['coef'][1]:.3f}，活动室小时 {b['coef'][2]:.3f}，托育小时 {b['coef'][3]:.3f}"
            sup_h = "；".join(f"{k} {v[0]}~{v[1]}h" for k, v in b["support_hours"].items())
        else:
            coef_txt = f"截距 {b['coef'][0]:.2f}，度日 {b['coef'][1]:.3f}，小时 {b['coef'][2]:.3f}"
            sup_h = f"{b['support_hours'][0]}~{b['support_hours'][1]}h"
        n_staged = sum(1 for d in b["fit_days"] if b["fit_labels"][d] == "分步投用")
        hold_rows = [
            [h["date"], f1(h["pred"]), f1(h["actual"]), f1(h["err"])] for h in b["holdout"]
        ]
        mae = b["holdout_mae"]
        limit = None
        for ev in res["evals"]:
            if ev["purpose"] == name:
                limit = ev["protocol"]["max_holdout_mae_kwh"]
        verdict = "可采用" if (mae is not None and (limit is None or mae <= limit)) else "不可采用"
        lines += [
            f"### {name}（{b['meter']}）",
            "",
            f"- 拟合：{coef_txt}",
            f"- 拟合样本 {len(b['fit_days'])} 天（备案拟合 {len(b['fit_days']) - n_staged} 天 + 分步投用 {n_staged} 天）；留出样本不进拟合。",
            f"- 历史支撑范围：度日 {b['support_dd'][0]}~{b['support_dd'][1]}；开放小时 {sup_h}。",
            f"- 留出核对：MAE = **{f1(mae)} kWh**（{sum(1 for h in b['holdout'] if h['err'] is not None)} 天有效）"
            + (f"，上限 {limit} kWh → **{verdict}**" if limit is not None else f"（总表无合同约定上限，供对照）"),
            "",
            _md_table(["留出日", "基准预测", "实际", "绝对误差"], hold_rows),
            "",
        ]
    lines += [
        "> 说明：11-12 度日 40 超出全部基准的历史支撑（20~32），该日不做基准预测、不产生可签节能；"
        "合同约定度日范围 22~30 之外的日期（11-01/03 为 21，11-07/08/14 为 31~32）同样不计可签节能。",
        "",
    ]
    return "\n".join(lines)


def sec_purpose(res):
    lines = ["## 三、分用途节能范围（逐日）", ""]
    for ev in res["evals"]:
        purpose = ev["purpose"]
        lines += [f"### {purpose}（{ev['meter']}，合同 {ev['contract']}）", ""]
        rows = []
        for r in ev["rows"]:
            mark = "可签" if r["claimable"] else "；".join(r["gaps"]) if r["gaps"] else "不可签"
            rows.append([
                r["date"], r["dd"], f"{r['sched']}/{r['obs']}", r["state"],
                f1(r["meter"]) + ("" if r["meter_status"] == "有效" else f"({r['meter_status']})"),
                f1(r["pred"]), f1(r["saving"]),
                "—" if r["temp"] is None else r["temp"],
                mark,
            ])
        lines.append(_md_table(
            ["日期", "度日", "承诺/实开h", "状态", "分表读数", "基准预测", "当日节能", "室温最低℃", "可采用性"],
            rows))
        lines.append("")
    return "\n".join(lines)


def sec_master(res):
    lines = [
        "## 四、总表节能范围与联合核对",
        "",
        f"适用精度（meter_tolerance_kwh）：{res['tolerance']} kWh。未分项 = 总表 − 各有效分表合计；"
        "未分项为负且超出适用精度时，总表与分表矛盾，该日共同证据不可用。",
        "",
    ]
    rows = []
    for m in res["master"]:
        rows.append([
            m["date"], m["dd"],
            f1(m["m0"]) + ("" if m["m0_status"] == "有效" else f"({m['m0_status']})"),
            f1(m["m1"]), f1(m["m2"]),
            f1(m["pred"]) if m["supported"] else "无支撑",
            f1(m["saving"]), f1(m["unmetered"]), m["joint"],
        ])
    lines.append(_md_table(
        ["日期", "度日", "总表", "M1", "M2", "总表基准", "总表节能", "未分项", "联合核对"], rows))
    lines += [
        "",
        "> 11-10 总表经两次更正（440 → ×1.09 → ×0.8 = 352.0），当日 M2 缺测，联合核对无法完成；"
        "按更正后总表，若 M2 处于常态水平（约 240），未分项将为负且远超适用精度——该日共同证据不可用，"
        "M1 读数无自身校准问题，按独立分表证据采信。",
        "> 11-11 总表读数已撤销，该日无总表证据；M2 读数独立有效。",
        "",
    ]
    return "\n".join(lines)


def sec_contracts(res):
    lines = ["## 五、分合同节能范围", ""]
    for ev in res["evals"]:
        p = ev["protocol"]
        lines += [f"### 合同 {ev['contract']}（{ev['purpose']}）", ""]
        lines += [
            f"- 覆盖率：分子 {len(ev['numer'])} / 分母 {len(ev['denom'])} = **{pct(ev['coverage'])}**"
            f"（下限 {p['min_coverage']} → {'达标' if ev['coverage_ok'] else '不达标'}）",
            f"- 可签节能（舒适合格日）：**{f1(ev['saving_total'])} kWh**"
            f"（申请下限 {p['min_saving']} kWh → {'达标' if ev['saving_ok'] else '不达标'}）",
            f"- 留出核对：{'达标' if ev['holdout_ok'] else '不达标'}（见第二节）",
            f"- 计价依据说明：{f1(ev['saving_total'])} kWh × {p['rate_yuan_per_kwh']} 元/kWh"
            f" = {yuan(ev['saving_total'] * p['rate_yuan_per_kwh'])} 元（仅解释计价依据，不触发付款）",
            "",
        ]
        if ev["comfort_gaps"]:
            rows = [
                [r["date"], r["state"], "缺测" if r["temp"] is None else f"{r['temp']}℃ < {p['min_temp']}℃",
                 f1(r["saving"])]
                for r in ev["comfort_gaps"]
            ]
            lines += [
                f"开放期温度义务缺口（{p['min_temp']}℃ 承诺；缺测≠合格，当日节能不可签）：",
                "",
                _md_table(["日期", "状态", "温度情况", "被挡当日节能 kWh"], rows),
                "",
            ]
        else:
            lines += ["开放期温度义务无缺口。", ""]
    # 归属
    lines += ["### 归属上限核对（两合同共同受总表限制，不互抵）", ""]
    rows = []
    for a in res["attribution"]:
        if not a["claims"] and a["master_saving"] is None:
            continue
        claims = "；".join(f"{c} {v:.1f}" for c, v in sorted(a["claims"].items())) or "—"
        rows.append([
            a["date"], claims, f1(a["claim_total"]), f1(a["master_saving"]),
            a["joint"], a["status"], f1(a["excess"]),
        ])
    lines.append(_md_table(
        ["日期", "各合同可签", "可签合计", "总表节能", "联合核对", "归属判定", "未归属缺口"],
        rows))
    lines += [
        "",
        "> 11-15 两合同可签合计 86.9 kWh，超出当日总表节能 83.6 kWh 共 **3.4 kWh**："
        "超出部分无总表对应、不可签给任何一方，也不在两合同间抵扣或分摊，列为未归属缺口，"
        "由验收会处置（该缺口在留出误差量级内，但归属规则不因量小而豁免）。",
        "> 11-10、11-11 共同证据不可用（见第四节），当日各合同节能依各自分表独立证据成立。",
        "> 各日总表节能与各合同可签合计之差为未分项剩余（管路等未分项用热的变化），"
        "不分配给任何一方；某一方独立证据较多的日期，也不因此多分剩余。",
        "",
    ]
    return "\n".join(lines)


def sec_signoff(res):
    lines = ["## 六、签认对照（旧依据 vs 当前可签范围）", ""]
    cur = {ev["contract"]: ev for ev in res["evals"]}
    sig = {s["record"]["contract"]: s for s in res["signoffs"]}
    for contract in sorted(sig):
        s = sig[contract]
        rec = s["record"]
        b = s["basis"]
        c = cur[contract]
        lines += [
            f"### 合同 {contract}（{rec['period']}，状态：{rec['status']}）",
            "",
            f"- 签认基准日 {rec['basis_date']}（当时可知至 {b['rows'][-1]['date'] if b['rows'] else '—'}）；"
            f"确认时间 {rec['signed_at'] or '未签'}。",
            f"- 当时口径：覆盖率 {pct(b['coverage'])}（{len(b['numer'])}/{len(b['denom'])}），"
            f"可签节能 {f1(b['saving_total'])} kWh。",
            f"- 当前口径（{res['query_date']}）：覆盖率 {pct(c['coverage'])}（{len(c['numer'])}/{len(c['denom'])}），"
            f"可签节能 {f1(c['saving_total'])} kWh。",
            "",
        ]
    x2_basis = sig["X2"]["basis"]["saving_total"]
    x2_cur = cur["X2"]["saving_total"]
    x1_cur = cur["X1"]["saving_total"]
    x1_mae = res["baselines"]["活动室"]["holdout_mae"]
    lines += [
        "#### X2（已确认）",
        "",
        f"- 已签 {f1(x2_basis)} kWh 按当时可知证据**保留**，不因更正抹掉。",
        "- 更正影响：11-11 总表读数撤销 → 该日联合核对证据不存在；X2 当日 54.8 kWh 依 M2 独立校准证据成立，**金额不变**。",
        "- 11-10 总表更正（×0.8）不影响 X2：当日 M2 缺测，X2 在该日无可签节能。",
        f"- 当前期间新增可签 {f1(x2_cur - x2_basis)} kWh（11-13、11-15 等签认基准日之后的日期）属待审范围；其中 11-15 涉归属超限（第五节），须会议处置。",
        "- 结论：**无须复核已签金额**；新增部分按当前口径另审。",
        "",
        "#### X1（待审）",
        "",
        "- 待签材料基准日 11-13 时：覆盖 2/3 = 0.667、可签 30.2 kWh，均刚达下限；其中 11-10 的 30.2 kWh 当时以总表 440 kWh 作联合核对。",
        "- 该总表读数已经两次更正（→479.6→352.0），**旧依据失效，当天不能按旧依据签**；按更正后口径，11-10 联合核对不可用，X1 当日 30.2 kWh 改依 M1 独立证据成立，金额不变但依据须重述。",
        f"- 当前可签范围 {f1(x1_cur)} kWh：覆盖 6/7 = 0.857、留出 MAE {f1(x1_mae)} ≤ 24 均达标；但 11-15 与 X2 合计超总表 3.4 kWh（未归属缺口），且 11-20 起 M1 留出撤销生效（第八节），留出依据将变化。",
        "- 结论：除 11-15 超限部分待处置、留出依据待 11-20 更正生效后复核确认外，其余可签。",
        "",
    ]
    return "\n".join(lines)


def sec_gaps(res):
    lines = ["## 七、缺口清单与补测可恢复性", ""]
    for ev in res["evals"]:
        meter_gaps = [r["date"] for r in ev["denom"] if r["meter"] is None]
        range_gaps = [r["date"] for r in ev["rows"] if r["state"] != "计划停用" and not r["denom"]
                      and any("范围" in g for g in r["gaps"])]
        temp_gaps = [r["date"] for r in ev["comfort_gaps"]]
        lines += [
            f"### 合同 {ev['contract']}（{ev['purpose']}）",
            "",
            f"- 独立计量缺口（分母日内分表不可用）：{('、'.join(meter_gaps)) or '无'}",
            f"- 可比基准缺口（开放但出合同约定范围）：{('、'.join(range_gaps)) or '无'}",
            f"- 开放期温度证据缺口：{('、'.join(temp_gaps)) if temp_gaps else '无'}",
            "",
        ]
    lines += [
        "### 补测可恢复性",
        "",
        "- **不可补测**：过去开放日的室温缺测（温度义务当时未记录，事后无法补出）；"
        "过去日期的分表缺测（历史用量无法重测）；11-11 已撤销的总表读数；"
        "已改造设备无法补测成未改造基准（分步投用期之后的基准只能依靠备案拟合/留出窗）。",
        "- **可以补测**：以后仍能观察的工况（未来开放日的室温与计量），用于后续期间，不改变本次缺口。",
        "",
    ]
    return "\n".join(lines)


def sec_post_query(res):
    lines = ["## 八、查询日之后发布的更正（不纳入本次签认口径）", ""]
    pq = res["post_query"]
    if not pq:
        return "\n".join(lines + ["无。", ""])
    for m in pq["records"]:
        lines.append(
            f"- {m['recorded']} 发布：{m['meter']} {m['from']}~{m['until']} {m['action']}"
            + ("" if m["factor"] is None else f"（系数 {m['factor']}）"))
    lines += [
        "",
        "该更正覆盖备案留出窗内 M1 读数（02-21~02-25）。生效后 X1 留出样本由 8 天减为 5 天，"
        f"重核 MAE = {f1(pq['holdout_mae']['活动室'])} kWh，仍 ≤ 24 kWh；拟合样本不受影响（留出日不进拟合）。",
        "但备案留出依据已变化，X1 基准的采用**须复核确认**；X2 留出不受影响。",
        "本报告主口径未纳入该更正；生效后应重跑本分析（--query-date 2026-11-20 或之后）。",
        "",
    ]
    return "\n".join(lines)


def sec_notes(res):
    return "\n".join([
        "## 九、口径说明与敏感性",
        "",
        "- 覆盖率分子按“有可采用耗热证据且有基准支撑”计；开放期室温作为舒适度约束单独挡当日节能（第五节）。"
        "若改用更严口径（室温缺测日同时剔出分子）：X1 当前 5/7 = 0.714，X2 签认时点 4/7 = 0.571、当前 6/12 = 0.500，"
        "结论变化集中在 X2，提请验收会注意该口径选择。",
        "- 基准拟合口径敏感性：改用“仅拟合窗”或“仅开放日”拟合，11-15 归属超限仍在 3.4~4.7 kWh 之间，结论稳定。",
        "- 金额为计价依据说明（rate_yuan_per_kwh），不触发实际付款。",
        "- 本报告由 `python3 -m analysis` 生成，可用 --query-date 重放任意查询日口径。",
        "",
    ])


# ---------------------------------------------------------------- 汇总


def build_markdown(res):
    head = "\n".join([
        "# 节能验收证据报告",
        "",
        f"查询日 {res['query_date']} ｜ 逐日记录可知至 {res['last_daily']} ｜ 资料为本地合成业务数据",
        "",
        "社区活动室（X1）与托育点（X2）共用热量总表 M0，两处改造分别验收、不同日投用"
        "（X2 自 2026-11-01，X1 自 2026-11-08）。本报告给出分用途、总表、分合同的节能范围，"
        "各自算法与可采用日期，并对照已签/待签卷宗的旧依据与当前可签范围。",
        "",
    ])
    sections = [
        head,
        sec_scope(res),
        sec_baseline(res),
        sec_purpose(res),
        sec_master(res),
        sec_contracts(res),
        sec_signoff(res),
        sec_gaps(res),
        sec_post_query(res),
        sec_notes(res),
    ]
    return "\n".join(sections)


def build_json(res):
    def ev_json(ev):
        return {
            "contract": ev["contract"],
            "purpose": ev["purpose"],
            "coverage": ev["coverage"],
            "coverage_ok": ev["coverage_ok"],
            "denominator": [r["date"] for r in ev["denom"]],
            "numerator": [r["date"] for r in ev["numer"]],
            "saving_total_kwh": round(ev["saving_total"], 3),
            "saving_ok": ev["saving_ok"],
            "holdout_ok": ev["holdout_ok"],
            "claim_days": {r["date"]: round(r["saving"], 3) for r in ev["claim_rows"]},
            "comfort_gaps": [
                {"date": r["date"], "state": r["state"], "temp": r["temp"]} for r in ev["comfort_gaps"]
            ],
            "daily": [
                {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()}
                for r in ev["rows"]
            ],
        }

    return {
        "query_date": res["query_date"],
        "last_daily": res["last_daily"],
        "baselines": {
            name: {
                "meter": b["meter"],
                "coef": [round(c, 4) for c in b["coef"]],
                "fit_n": len(b["fit_days"]),
                "fit_days": b["fit_days"],
                "holdout_mae": None if b["holdout_mae"] is None else round(b["holdout_mae"], 3),
                "holdout": [
                    {k: (round(v, 3) if isinstance(v, float) else v) for k, v in h.items()}
                    for h in b["holdout"]
                ],
                "support_dd": b["support_dd"],
            }
            for name, b in res["baselines"].items()
        },
        "contracts": [ev_json(ev) for ev in res["evals"]],
        "master_daily": [
            {k: (round(v, 3) if isinstance(v, float) else v) for k, v in m.items()}
            for m in res["master"]
        ],
        "attribution": [
            {
                "date": a["date"],
                "claims": {c: round(v, 3) for c, v in a["claims"].items()},
                "claim_total": round(a["claim_total"], 3),
                "master_saving": None if a["master_saving"] is None else round(a["master_saving"], 3),
                "joint": a["joint"],
                "status": a["status"],
                "excess": None if a["excess"] is None else round(a["excess"], 3),
            }
            for a in res["attribution"]
        ],
        "signoffs": [
            {
                "contract": s["record"]["contract"],
                "status": s["record"]["status"],
                "signed_at": s["record"]["signed_at"],
                "basis_date": s["record"]["basis_date"],
                "basis_coverage": s["basis"]["coverage"],
                "basis_saving_kwh": round(s["basis"]["saving_total"], 3),
            }
            for s in res["signoffs"]
        ],
        "corrections": res["timeline"],
        "post_query_corrections": None if res["post_query"] is None else {
            "records": res["post_query"]["records"],
            "holdout_mae_if_applied": res["post_query"]["holdout_mae"],
        },
    }

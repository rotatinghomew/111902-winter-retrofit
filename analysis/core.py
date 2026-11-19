"""节能验收分析核心：口径、更正、基准、门槛、节能与归属。

口径要点（与 README 输入约定对应）：
- 日粒度记录翌日可知：查询日 Q 只使用 date <= Q-1 的 weather/activity/readings/calendar。
- 更正按 recorded <= Q 生效；同一 (meter, date) 取截至 Q 最近发布的一条；
  换算系数相对原读数；撤销使该日该表读数无效。
- 基准：分用途最小二乘 用量 ~ 1 + 采暖度日 + 实开小时；总表再加另一用途小时。
  X1(活动室) 拟合窗 = 备案拟合日 + 分步投用日（分步期未投用用途的独立分表可作自身基准证据）；
  X2(托育点) 拟合窗 = 备案拟合日（X2 先行投用，分步期读数已是改造后）。
  备案留出日只用于核对，绝不进入拟合。
- 覆盖率：分母 = 申请阶段内 改造已投用、承诺开放（非计划停用）、度日与承诺小时在合同约定内的日期；
  临时停用计入分母（缺口）；分子 = 其中有可采用耗热证据（本分表读数有效）的日期。
  室温作为舒适度约束单独核对：开放承诺日缺测即不合格，挡当日节能、不挡覆盖率。
- 归属：存在未分项用热时，当日各合同可签节能合计不超过总表节能（归属上限）；
  超出部分不互抵、不分配，列为未归属缺口。总表与有效分表在适用精度下矛盾
  （未分项为负且超出 meter_tolerance_kwh）或分表缺测无法完成联合核对时，
  该日共同证据不可用，独立分表按各自校准证据采信。
- 不外推：合同节能只在合同约定度日/小时范围内签认；总表基准只在拟合观测支撑范围内给出。
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

# ---------------------------------------------------------------- 基础工具


def load_source(path):
    src = json.loads(Path(path).read_text(encoding="utf-8"))
    assert src.get("synthetic"), "资料缺少 synthetic 标记"
    return src["tables"]


def day_shift(date, days):
    return (_dt.date.fromisoformat(date) + _dt.timedelta(days=days)).isoformat()


def ols(xs, ys):
    """最小二乘，xs 不含截距列；返回 [b0, b1, ...]。"""
    n = len(xs[0]) + 1
    X = [[1.0] + list(map(float, row)) for row in xs]
    Y = [float(v) for v in ys]
    A = [[sum(X[k][i] * X[k][j] for k in range(len(X))) for j in range(n)] for i in range(n)]
    b = [sum(X[k][i] * Y[k] for k in range(len(X))) for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(A[r][col]))
        A[col], A[piv] = A[piv], A[col]
        b[col], b[piv] = b[piv], b[col]
        for r in range(col + 1, n):
            f = A[r][col] / A[col][col]
            for j in range(col, n):
                A[r][j] -= f * A[col][j]
            b[r] -= f * b[col]
    coef = [0.0] * n
    for i in range(n - 1, -1, -1):
        coef[i] = (b[i] - sum(A[i][j] * coef[j] for j in range(i + 1, n))) / A[i][i]
    return coef


def predict(coef, feats):
    return coef[0] + sum(c * f for c, f in zip(coef[1:], feats))


# ---------------------------------------------------------------- 领域对象

PURPOSE_METER = {"活动室": "M1", "托育点": "M2"}
PURPOSE_HOURS = {"活动室": "activity_hours", "托育点": "nursery_hours"}
PURPOSE_TEMP = {"活动室": "activity_min_c", "托育点": "nursery_min_c"}


class Source:
    """来源资料 + 截至查询日的可知性口径。"""

    def __init__(self, tables, query_date):
        self.t = tables
        self.query_date = query_date
        self.last_daily = day_shift(query_date, -1)  # 日粒度记录翌日可知
        self.weather = {r["date"]: r for r in tables["weather"]}
        self.activity = {r["date"]: r for r in tables["activity"]}
        self.calendar = {(r["date"], r["purpose"]): r for r in tables["calendar"]}
        self.readings = {}
        for r in tables["readings"]:
            self.readings[(r["date"], r["meter"])] = r
        self.protocol = {r["contract"]: r for r in tables["protocol"]}
        self.dates = sorted(self.weather)

    # ---------------- 可知性

    def daily_knowable(self, date):
        return date <= self.last_daily

    def corrections(self, meter=None, date=None, effective=None):
        """更正记录。effective: 截至该日已发布（recorded <= effective）；None 表示不限。"""
        out = []
        for m in self.t["maintenance"]:
            if meter is not None and m["meter"] != meter:
                continue
            if date is not None and not (m["from"] <= date <= m["until"]):
                continue
            if effective is not None and m["recorded"] > effective:
                continue
            out.append(m)
        return out

    def correction_for(self, meter, date):
        """截至查询日最近发布的、覆盖 (meter, date) 的更正；无则 None。"""
        best = None
        for m in self.corrections(meter=meter, date=date, effective=self.query_date):
            if best is None or m["recorded"] > best["recorded"]:
                best = m
        return best

    def meter_value(self, meter, date):
        """应用截至查询日的更正后的读数。

        返回 (值, 状态)：状态 ∈ 有效 / 更正换算 / 撤销无效 / 缺测。
        """
        r = self.readings.get((date, meter))
        if r is None:
            return None, "缺测"
        c = self.correction_for(meter, date)
        if c is None:
            return float(r["reading"]), "有效"
        if c["action"] == "撤销":
            return None, "撤销无效"
        return float(r["reading"]) * c["factor"], "更正换算"

    def raw_reading(self, meter, date):
        r = self.readings.get((date, meter))
        return r["reading"] if r else None


# ---------------------------------------------------------------- 基准


def fit_baselines(src: Source):
    """分用途与总表基准。留出日只核对不拟合。"""
    fit_days = [d for d in src.dates if src.weather[d]["split"] == "拟合" and src.daily_knowable(d)]
    staged_days = [d for d in src.dates if src.weather[d]["split"] == "分步投用" and src.daily_knowable(d)]
    holdout_days = [d for d in src.dates if src.weather[d]["split"] == "留出" and src.daily_knowable(d)]

    out = {}
    for purpose, meter in PURPOSE_METER.items():
        hf = PURPOSE_HOURS[purpose]
        # 分步期只有未投用的用途可用独立分表作额外基准证据
        extra = []
        for d in staged_days:
            commissioned = any(
                p["purpose"] == purpose and p["effective"] <= d for p in src.protocol.values()
            )
            if not commissioned:
                extra.append(d)
        days, labels = [], {}
        for d in fit_days + extra:
            v, _ = src.meter_value(meter, d)
            if v is None:
                continue
            days.append(d)
            labels[d] = "拟合" if d in fit_days else "分步投用"
        coef = ols(
            [[src.weather[d]["degree_days"], src.activity[d][hf]] for d in days],
            [src.meter_value(meter, d)[0] for d in days],
        )
        out[purpose] = _baseline_result(src, meter, hf, coef, days, labels, holdout_days)

    # 总表：只用备案拟合窗（分步期总表已含一处改造效果，不能进未改造基准）
    days = [d for d in fit_days if src.meter_value("M0", d)[0] is not None]
    coef = ols(
        [[src.weather[d]["degree_days"], src.activity[d]["activity_hours"], src.activity[d]["nursery_hours"]]
         for d in days],
        [src.meter_value("M0", d)[0] for d in days],
    )
    out["总表"] = _baseline_result(src, "M0", None, coef, days, {d: "拟合" for d in days}, holdout_days)
    return out


def _baseline_result(src, meter, hf, coef, days, labels, holdout_days):
    def pred(d):
        if hf is None:
            feats = [src.weather[d]["degree_days"], src.activity[d]["activity_hours"], src.activity[d]["nursery_hours"]]
        else:
            feats = [src.weather[d]["degree_days"], src.activity[d][hf]]
        return predict(coef, feats)

    hold = []
    for d in holdout_days:
        v, _ = src.meter_value(meter, d)
        if v is None:
            hold.append({"date": d, "actual": None, "pred": None, "err": None})
            continue
        hold.append({"date": d, "actual": v, "pred": pred(d), "err": abs(pred(d) - v)})
    valid = [h for h in hold if h["err"] is not None]
    mae = sum(h["err"] for h in valid) / len(valid) if valid else None
    dds = [src.weather[d]["degree_days"] for d in days]
    res = {
        "meter": meter,
        "coef": coef,
        "fit_days": days,
        "fit_labels": labels,
        "holdout": hold,
        "holdout_mae": mae,
        "support_dd": [min(dds), max(dds)],
        "predict": pred,
    }
    if hf is not None:
        hs = [src.activity[d][hf] for d in days]
        res["support_hours"] = [min(hs), max(hs)]
    else:
        res["support_hours"] = {
            "活动室": [min(src.activity[d]["activity_hours"] for d in days), max(src.activity[d]["activity_hours"] for d in days)],
            "托育点": [min(src.activity[d]["nursery_hours"] for d in days), max(src.activity[d]["nursery_hours"] for d in days)],
        }
    return res


# ---------------------------------------------------------------- 合同评价


def evaluate_contract(src: Source, baselines, contract):
    """单合同在查询日口径下的逐日门槛、覆盖率、节能与舒适度。"""
    p = src.protocol[contract]
    purpose = p["purpose"]
    meter = PURPOSE_METER[purpose]
    hf = PURPOSE_HOURS[purpose]
    tf = PURPOSE_TEMP[purpose]
    base = baselines[purpose]
    lo_dd, hi_dd = p["degree_days_range"]
    lo_h, hi_h = p["hours_range"]

    rows = []
    for d in src.dates:
        if d < p["effective"] or not src.daily_knowable(d):
            continue
        cal = src.calendar[(d, purpose)]
        w = src.weather[d]
        act = src.activity[d]
        mv, mstatus = src.meter_value(meter, d)
        temp = act[tf]
        committed = cal["state"] != "计划停用"
        in_dd = lo_dd <= w["degree_days"] <= hi_dd
        in_h = lo_h <= cal["scheduled_hours"] <= hi_h
        denom = committed and in_dd and in_h
        temp_measured = temp is not None
        temp_ok = temp_measured and temp >= p["min_temp"]
        pred = base["predict"](d) if (denom and cal["state"] != "临时停用") else None
        saving = (pred - mv) if (pred is not None and mv is not None) else None
        claimable = bool(denom and cal["state"] != "临时停用" and mv is not None and temp_ok)
        gaps = []
        if not committed:
            gaps.append("计划停用")
        if committed and not in_dd:
            gaps.append("度日出约定范围")
        if committed and not in_h:
            gaps.append("承诺小时出约定范围")
        if cal["state"] == "临时停用":
            gaps.append("临时停用")
        if mv is None:
            gaps.append("分表缺测" if mstatus == "缺测" else "分表%s" % mstatus)
        if committed and not temp_measured:
            gaps.append("室温缺测")
        elif committed and not temp_ok:
            gaps.append("室温低于承诺")
        rows.append({
            "date": d, "state": cal["state"], "sched": cal["scheduled_hours"], "obs": cal["observed_hours"],
            "dd": w["degree_days"], "meter": mv, "meter_status": mstatus, "temp": temp,
            "denom": denom, "numerator": bool(denom and mv is not None),
            "temp_ok": temp_ok, "pred": pred, "saving": saving, "claimable": claimable,
            "gaps": gaps,
        })
    denom_rows = [r for r in rows if r["denom"]]
    num_rows = [r for r in denom_rows if r["numerator"]]
    claim_rows = [r for r in rows if r["claimable"]]
    coverage = (len(num_rows) / len(denom_rows)) if denom_rows else None
    total = sum(r["saving"] for r in claim_rows)
    comfort_gaps = [
        r for r in rows
        if r["state"] != "计划停用" and (r["temp"] is None or r["temp"] < p["min_temp"])
    ]
    return {
        "contract": contract, "purpose": purpose, "meter": meter, "protocol": p,
        "rows": rows, "denom": denom_rows, "numer": num_rows, "coverage": coverage,
        "claim_rows": claim_rows, "saving_total": total, "comfort_gaps": comfort_gaps,
        "coverage_ok": coverage is not None and coverage >= p["min_coverage"],
        "saving_ok": total >= p["min_saving"],
        "holdout_ok": baselines[purpose]["holdout_mae"] is not None
        and baselines[purpose]["holdout_mae"] <= p["max_holdout_mae_kwh"],
    }


# ---------------------------------------------------------------- 总表与归属


def evaluate_master(src: Source, baselines, tolerance):
    """总表逐日节能与联合核对状态。"""
    base = baselines["总表"]
    lo_dd, hi_dd = base["support_dd"]
    rows = []
    for d in src.dates:
        if not src.daily_knowable(d):
            continue
        if not any(p["effective"] <= d for p in src.protocol.values()):
            continue  # 首个改造投用前无节能口径
        w = src.weather[d]
        m0, s0 = src.meter_value("M0", d)
        m1, s1 = src.meter_value("M1", d)
        m2, s2 = src.meter_value("M2", d)
        supported = lo_dd <= w["degree_days"] <= hi_dd
        pred = base["predict"](d) if supported else None
        saving = (pred - m0) if (pred is not None and m0 is not None) else None
        # 联合核对：总表与有效分表合计差异
        if m0 is None:
            joint, unmetered = "总表不可用", None
        elif m1 is None or m2 is None:
            joint, unmetered = "分表缺测，联合核对不完整", None
        else:
            unmetered = m0 - m1 - m2
            if unmetered < 0 and abs(unmetered) > tolerance:
                joint = "矛盾（未分项为负且超差）"
            else:
                joint = "一致"
        rows.append({
            "date": d, "dd": w["degree_days"], "m0": m0, "m0_status": s0,
            "m1": m1, "m2": m2, "pred": pred, "saving": saving,
            "supported": supported, "joint": joint, "unmetered": unmetered,
        })
    return rows


def attribution(master_rows, evals):
    """归属上限核对：当日各合同可签节能合计 vs 总表节能。

    返回逐日归属表：可签合计、总表节能、是否超限、未归属缺口、联合核对状态。
    """
    claims = {}
    for ev in evals:
        for r in ev["claim_rows"]:
            claims.setdefault(r["date"], {})[ev["contract"]] = r["saving"]
    out = []
    for m in master_rows:
        d = m["date"]
        day_claims = claims.get(d, {})
        total = sum(day_claims.values())
        cap = m["saving"]
        if cap is None:
            status = "无总表节能口径"
            excess = None
        elif m["joint"] != "一致":
            status = "联合核对不可用，分表独立证据"
            excess = None
        elif total > cap + 1e-9:
            status = "归属超限"
            excess = total - cap
        else:
            status = "上限内"
            excess = None
        out.append({
            "date": d, "claims": day_claims, "claim_total": total,
            "master_saving": cap, "joint": m["joint"], "status": status, "excess": excess,
        })
    return out


# ---------------------------------------------------------------- 更正时间线


def correction_timeline(src: Source):
    """全部更正记录按发布时间排列，并标注是否纳入查询日口径。"""
    events = []
    for m in sorted(src.t["maintenance"], key=lambda r: (r["recorded"], r["meter"], r["from"])):
        events.append({
            "recorded": m["recorded"], "meter": m["meter"],
            "from": m["from"], "until": m["until"], "action": m["action"], "factor": m["factor"],
            "in_scope": m["recorded"] <= src.query_date,
        })
    return events


def run(path, query_date):
    """完整计算：返回报告所需的全部结果。"""
    src = Source(load_source(path), query_date)
    baselines = fit_baselines(src)
    tol = min(p["meter_tolerance_kwh"] for p in src.protocol.values())
    master = evaluate_master(src, baselines, tol)
    evals = [evaluate_contract(src, baselines, c) for c in sorted(src.protocol)]
    attrib = attribution(master, evals)

    # 签认对照：以各签认 basis_date 重建当时可知口径
    signoffs = []
    for s in src.t["signoffs"]:
        basis_src = Source(src.t, s["basis_date"])
        basis_base = fit_baselines(basis_src)
        basis_ev = evaluate_contract(basis_src, basis_base, s["contract"])
        basis_master = evaluate_master(basis_src, basis_base, tol)
        basis_attrib = attribution(basis_master, [basis_ev])
        signoffs.append({
            "record": s, "basis": basis_ev, "basis_master": basis_master, "basis_attrib": basis_attrib,
        })

    # 查询日之后发布的更正（不纳入当前口径，仅提示）
    pending = [m for m in src.t["maintenance"] if m["recorded"] > query_date]
    post_query = None
    if pending:
        later = min(m["recorded"] for m in pending)
        later_src = Source(src.t, later)
        later_base = fit_baselines(later_src)
        post_query = {
            "records": pending,
            "as_of": later,
            "holdout": {purpose: later_base[purpose]["holdout"] for purpose in PURPOSE_METER},
            "holdout_mae": {purpose: later_base[purpose]["holdout_mae"] for purpose in PURPOSE_METER},
        }

    return {
        "query_date": query_date,
        "last_daily": src.last_daily,
        "src": src,
        "baselines": baselines,
        "master": master,
        "evals": evals,
        "attribution": attrib,
        "signoffs": signoffs,
        "timeline": correction_timeline(src),
        "post_query": post_query,
        "tolerance": tol,
    }

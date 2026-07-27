"""训练建议引擎 — 把 16 项指标的判定转成"教练能用、运动员能练"的建议。

设计原则:
  - 只对"轻微/需改进"的指标给建议(达标的作为亮点表扬),避免信息过载。
  - 每条 = 问题(大白话说清哪不对) + 训练方法(具体怎么练)。
  - 按扣分严重度排序,教练一眼看到最该抓的。
  - 依据 Edriss 2024(几何指标)/Yue 2023(时序指标)+ 花游训练常识。

无 LLM 依赖:规则驱动,离线可跑、可解释、可复现。report 端点调 build_advice()。
"""
from __future__ import annotations

# 每个指标:问题描述 + 训练方法(针对"没做好"时)
_ADVICE = {
    # ── 视觉几何(Edriss 2024) ──
    "leg_deviation": ("腿没有绷直竖直,偏离垂直角度偏大",
                      "靠墙贴腿找垂直感;慢速举腿、在顶点保持 3–5 秒控制角度"),
    "knee_extension": ("膝盖没有完全绷直",
                       "坐姿压腿拉伸;举腿时刻意锁死膝关节 + 同时绷脚尖"),
    "shoulder_knee_alignment": ("从肩到膝没连成一条直线,核心塌了",
                                "核心收紧对镜找直线;平板支撑 + 空中直体控制"),
    "trunk_vertical": ("倒立/定型时躯干不够正直",
                       "靠墙倒立找正;强化核心避免弓背或折髋"),
    "leg_symmetry": ("左右两条腿不对称",
                     "对镜分腿训练;弱侧单独加练,追求两腿镜像一致"),
    "leg_height_index": ("腿举出水面的高度不够",
                         "髋屈肌柔韧 + 核心力量;陆上举腿高度专项"),
    "elbow": ("手臂造型/划水的肘部角度不规范",
              "对镜规范手臂线条;固定肘角做定位练习"),
    # ── 时序/动力学(Yue 2023 + IMU) ──
    "smoothness": ("动作有顿挫、不连贯,发力不平顺",
                   "慢速分解动作找连贯;消除动作之间的停顿与抖动"),
    "stability": ("定型/造型时晃动大,稳不住",
                  "静态保持训练(倒立、团身)3×30 秒;核心稳定性"),
    "movement_frequency": ("动作密度偏低,编排不够密",
                           "提高动作衔接速度;缩短无效过渡,增加有效动作"),
    "rotation_frequency": ("旋转速率不理想",
                           "分解旋转找轴心;控制旋转的启动与收速节奏"),
    "mean_pattern_duration": ("图形之间的节奏偏慢/拖沓",
                              "按音乐卡点练图形衔接;压缩过渡时间"),
    "last_hf_duration": ("收尾图形的时长控制欠佳",
                         "专门练结尾段的定格与收尾控制"),
    "explosive_power": ("爆发力不足,出水/起跳冲力弱",
                        "陆上爆发力训练(跳箱、药球);水中发力集中练"),
    "energy_index": ("整体运动量/体能投入偏低",
                     "提升有氧耐力与动作维持能力"),
    "motion_complexity": ("动作变化偏单一",
                          "丰富动作类型与过渡,增加编排层次"),
}

_ZONE_CN = {"clean": "达标", "minor": "轻微", "major": "需改进"}

# 指标英文名 → 中文标签(与前端 METRIC_EXPLAIN 保持一致)。
# 后端 report 只返回英文 name,这里自带一份避免脆弱的跨模块 import。
_LABELS = {
    "smoothness": "动作流畅度", "stability": "定型稳定度",
    "movement_frequency": "动作频率", "rotation_frequency": "旋转速率",
    "mean_pattern_duration": "图形平均时长", "last_hf_duration": "收尾图形时长",
    "explosive_power": "爆发力", "energy_index": "能量指数",
    "motion_complexity": "动作复杂度", "leg_deviation": "腿部垂直偏差",
    "leg_height_index": "举腿高度", "knee_extension": "膝伸展度",
    "shoulder_knee_alignment": "肩-膝对齐", "trunk_vertical": "躯干垂直度",
    "leg_symmetry": "双腿对称性", "elbow": "肘部角度",
}


def build_advice(metrics: list[dict], overall_score: float | None,
                 breakdown: dict | None = None) -> dict:
    """从指标列表生成结构化训练建议。

    Args:
        metrics: [{name, value, unit, zone, deduction}, ...]
        overall_score: 总分(0–10)或 None。
        breakdown: 4 维度分组(可选,用于总评措辞)。
    Returns:
        {
          "verdict": 一句话总评,
          "strengths": [达标亮点的中文标签...],
          "improvements": [{name, label, zone, value, unit, issue, drill, deduction}...按严重度],
          "top_priority": 最该抓的 1–2 条(name 列表),
        }
    """
    def label(n):
        return _LABELS.get(n, n)

    strengths, improvements = [], []
    for m in metrics:
        z = m.get("zone")
        n = m.get("name", "")
        if z == "clean":
            strengths.append(label(n))
        elif z in ("minor", "major") and n in _ADVICE:
            issue, drill = _ADVICE[n]
            improvements.append({
                "name": n, "label": label(n), "zone": z,
                "zone_cn": _ZONE_CN.get(z, z),
                "value": m.get("value"), "unit": m.get("unit", ""),
                "deduction": m.get("deduction", 0.0),
                "issue": issue, "drill": drill,
            })
    # 按扣分从大到小(major 在前)
    improvements.sort(key=lambda x: (x["zone"] != "major", -float(x.get("deduction") or 0)))
    top = [x["name"] for x in improvements[:2]]

    # 总评措辞
    if overall_score is None:
        verdict = "本次数据不足以给出综合评分(视觉入镜或 IMU 数据缺失),先补齐采集再复盘。"
    elif overall_score >= 8.5:
        verdict = f"整体优秀({overall_score:.1f}/10)。基础扎实,重点打磨细节即可再上一层。"
    elif overall_score >= 7:
        verdict = f"整体良好({overall_score:.1f}/10)。有明确的 {len(improvements)} 个提升点,针对性练能快速见效。"
    elif overall_score >= 5:
        verdict = f"整体中等({overall_score:.1f}/10)。先抓下面标红的重点项,逐个突破。"
    else:
        verdict = f"整体待提升({overall_score:.1f}/10)。建议从最基础的稳定性/腿型抓起,循序渐进。"

    return {
        "verdict": verdict,
        "strengths": strengths,
        "improvements": improvements,
        "top_priority": top,
    }

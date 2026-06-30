# Phase B 关键点标注规范（19 点含脚尖）

> 给关键点标注者。Phase A 标的是**框**(人在哪)；Phase B 标的是 **19 个关节点**
> (COCO-17 + 左右脚尖,绷脚可评)。预标注已由 v2 detector + MediaPipe 自动生成,
> 你**只需修正**,不用从零画。

## 19 个关键点
```
0 鼻   1/2 左右眼   3/4 左右耳   5/6 左右肩   7/8 左右肘   9/10 左右腕
11/12 左右髋   13/14 左右膝   15/16 左右踝   17/18 左右脚尖 ← Phase B 重点
```

## 准备（一次性）
```bash
# 1. 预标注(v2 detector 框 + MediaPipe 33点 → 19点初始标注)
python tools/preannotate_pose.py --raw data/raw_videos --interval 5 \
    --detector runs/detect/swimmer_det_v2/weights/best.pt
# 2. 把 data/training/phase_b/{images,labels} 上传 CVAT(关键点项目,19 点 skeleton)
# 3. 修正预标注 → 导出 YOLO pose
```

## 修正规则（最易错的几条）
| 规则 | 说明 |
|---|---|
| ⭐ **脚尖(17/18)是重点** | 绷脚时脚尖标在脚趾末端;预标注的脚尖常不准,重点修 |
| **倒立/水下** | 关节点标在**图像上看到的位置**(折射后的样子就是要评的对象);看不到的点 visibility=0 |
| **visibility** | 2=清晰可见 / 1=被遮挡但能估位置 / 0=完全看不到(坐标不重要) |
| **左右别标反** | 尤其倒立时容易左右颠倒——以运动员自身的左右为准 |
| 每人一套 19 点 | 完全被挡的运动员跳过(别猜位置硬标) |

## 训练 / 验证拆分（防泄漏,见 DEVLOG #33）
- val 用训练**没见过的 set/clip**(整段),不要随机拆相邻帧(会让 val OKS 虚高)
- 编辑 `data/training/phase_b/{train,val}.txt`(每行一个图片路径)

## 训练 + 评估
```bash
python tools/train_pose.py --data data/training/phase_b/swimmer_pose.yaml
python tools/eval_pose.py
```

## 标多少
- 首批 **~150 帧**(重点选脚尖出水/倒立/腿部造型的帧)→ 出 v1 pose 模型验证 OKS
- 脚尖准了之后,**绷脚角度才能进 FINA 评分**(当前 MediaPipe 通用脚尖仅 12% 准)

## 相关
- `tools/preannotate_pose.py` — 飞轮预标注(本流程第 1 步)
- `data/training/phase_b/swimmer_pose.yaml` — 19 点数据集定义
- DEVLOG #33 — 为什么必须自标自训

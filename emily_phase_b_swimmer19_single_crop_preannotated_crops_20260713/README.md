# Emily — Phase B 剩余骨架标注包（历史 19 点标准）

打包日期：20260713  
本批范围：41 张原始帧、53 位运动员。只保留裁剪范围内不含另一位已确认 swimmer，且本机姿态模型已有至少一个可靠可见关键点的 crop；每张图都可直接看到预标注。 每位运动员是一张独立 crop。

这个包**没有另起一套标准**。它逐字复用了 Tim 本机上已完成的 `swimmer` 19 点 skeleton：橙色 `swimmer`、COCO-17 加左右 `foot_index`。包内还带了那 53 张已完成 crop 的图片和 COCO 标注，作为唯一的标注样例。

## 导入（沿用旧 Phase B 流程）

1. 双击 `1-start-cvat.command`，打开本机 CVAT。
2. 新建 Project：`syncswim-phase-b-swimmer19`。
3. 在 Project 的 **Labels → Raw** 中，用 `cvat_skeleton_swimmer_19pt.json` 的完整内容替换编辑器，然后保存。它是历史文件的逐字副本；只会创建橙色的 `swimmer` 19 点 skeleton。**不要创建 `person`，不要增加或删除点。**
4. 在该 Project 新建 Task：`phase-b-swimmer19-crops`。上传 `phase_b_remaining_crop_images.zip` 作为图片数据。
5. 等任务准备完成后，在 Task 的 **Actions → Upload annotations**（有的版本写作 **Import annotations**）选择 **CVAT for images 1.1**，上传 `phase_b_remaining_crop_skeleton_seeds.xml`。这一步会预置 **53 个 `swimmer` skeleton**，每张 crop 一个。
6. 打开 Job 后确认共有 **53** 张图片，Objects 列表每张已有一个 `swimmer`。其中 **53** 张已有本机 YOLO pose 模型实际预测出的可见关键点（共 630 个）；模型未可靠预测的点保持空，不会用猜测坐标填充。双 `foot_index` 也保持空，因为 COCO pose 模型不预测该两点。文件名末尾 `_p0`、`_p1` 等是该原始帧中的第几个已确认 swimmer。
7. 打开 `reference_examples.jpg` 看已完成的真实样例；需要逐张查看原始标注时，可另建临时 task 导入 `reference_annotated_crops_images.zip` 与 `reference_annotated_crops_coco.zip`。

## 每张 crop 怎么标

1. 每张 crop 的 `swimmer` skeleton 已经预置。**不要新建、删除或复制 skeleton**；先核对模型已经落下的点，再修正它们并补空点。
2. 标完整 19 个点。左右以运动员自身左右为准。
3. 可清楚落点：**visible**（COCO `v=2`）。被水花、另一人或器材遮住、但关节位置可可靠判断：**occluded**（`v=1`）。看不清或无法可靠判断：保持未标（`v=0`），绝不按比例猜点。
4. 特别保留最后两个点：`left_foot_index`、`right_foot_index`。这正是旧 Phase B 标准相对 COCO-17 多出的两个点。

| 序号 | 关键点 |
|---:|---|
| 1 | `nose` |
| 2 | `left_eye` |
| 3 | `right_eye` |
| 4 | `left_ear` |
| 5 | `right_ear` |
| 6 | `left_shoulder` |
| 7 | `right_shoulder` |
| 8 | `left_elbow` |
| 9 | `right_elbow` |
| 10 | `left_wrist` |
| 11 | `right_wrist` |
| 12 | `left_hip` |
| 13 | `right_hip` |
| 14 | `left_knee` |
| 15 | `right_knee` |
| 16 | `left_ankle` |
| 17 | `right_ankle` |
| 18 | `left_foot_index` |
| 19 | `right_foot_index` |

## 交回

Task → **Actions → Export task dataset** → **COCO Keypoints 1.0** → 不勾 **Save images**。把下载文件命名为 `phase_b_swimmer19_crops_emily_YYYYMMDD.zip` 发回 Tim。

`crop_manifest.json` 记录每张 crop 对应的源帧、源 bbox 和裁切窗口，供 Tim 将结果复核或映射回原图；Emily 不需要修改它。

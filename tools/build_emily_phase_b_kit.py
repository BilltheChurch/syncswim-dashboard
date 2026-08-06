#!/usr/bin/env python3
"""Build the Phase B handoff using the established 19-point crop workflow.

This is deliberately based on the locally completed Phase B reference set:
``phase_b_crop_images.zip`` + ``phase_b_crop_coco.zip``.  Each approved
Phase A swimmer box becomes one image crop, with the original box centered at
two thirds of the crop size (one sixth padding on every side).  Emily labels
one ``swimmer`` skeleton with 19 points in each crop and exports COCO
Keypoints, exactly as in the completed reference set.

Usage:
    python3 tools/build_emily_phase_b_kit.py

Output:
    emily_phase_b_swimmer19_crops_YYYYMMDD.zip

Use ``--single-person-only`` to include only source frames with exactly one
confirmed Phase A swimmer. This is intentionally a source-frame filter: a
five-person frame is excluded even though it could be split into five crops.
Use ``--visible-preannotations-only`` to retain only one-swimmer crops where
the local pose model produced at least one reliable, visible keypoint.
Use ``--single-swimmer-crops-only`` to exclude a target crop whenever another
confirmed Phase A swimmer bounding box intersects that crop's pixels.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import shutil
import sys
import tempfile
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_IMAGES = ROOT / "data" / "training" / "phase_a" / "images"
DEFAULT_LABELS = ROOT / "data" / "training" / "phase_a" / "labels"
HISTORICAL_SKELETON = ROOT / "data" / "training" / "phase_a" / "cvat_skeleton_swimmer_19pt.json"
DEFAULT_REFERENCE_IMAGES = Path("/Users/billthechurch/Downloads/phase_b_crop_images.zip")
DEFAULT_REFERENCE_COCO = Path("/Users/billthechurch/Downloads/phase_b_crop_coco.zip")

SWIMMER_LABEL = "swimmer"
KEYPOINTS = (
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
    "left_foot_index",
    "right_foot_index",
)
SKELETON_EDGES = (
    (1, 2), (1, 3), (2, 4), (3, 5), (6, 7), (6, 8), (8, 10),
    (7, 9), (9, 11), (6, 12), (7, 13), (12, 13), (12, 14),
    (14, 16), (16, 18), (13, 15), (15, 17), (17, 19),
)
CROP_SCALE = 1.5
YOLO_POSE_KEYPOINT_COUNT = 17


@dataclass(frozen=True)
class Detection:
    source_image: str
    source_index: int
    cx: float
    cy: float
    width: float
    height: float


@dataclass(frozen=True)
class CropRecord:
    crop_image: str
    source_image: str
    source_annotation_index: int
    source_bbox_yolo: list[float]
    source_bbox_pixels: list[float]
    crop_window_pixels: list[int]
    swimmer_bbox_in_crop_pixels: list[float]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_by_stem(directory: Path, suffix: str) -> dict[str, Path]:
    if not directory.is_dir():
        raise ValueError(f"directory does not exist: {directory}")
    files = sorted(path for path in directory.iterdir() if path.suffix.lower() == suffix)
    if not files:
        raise ValueError(f"no {suffix} files found in: {directory}")
    by_stem = {path.stem: path for path in files}
    if len(by_stem) != len(files):
        raise ValueError(f"duplicate filename stems in: {directory}")
    return by_stem


def parse_detection_label(path: Path, source_image: str) -> list[Detection]:
    """Read a Phase A YOLO detection file without silently discarding rows."""
    detections: list[Detection] = []
    for line_number, raw_line in enumerate(path.read_text().splitlines(), start=1):
        fields = raw_line.split()
        if not fields:
            continue
        if len(fields) != 5:
            raise ValueError(f"{path}:{line_number} must have 5 YOLO detection fields")
        try:
            label_id = int(fields[0])
            cx, cy, width, height = (float(value) for value in fields[1:])
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number} contains a non-numeric YOLO value") from exc
        if label_id != 0:
            raise ValueError(f"{path}:{line_number} class must be 0 (swimmer), got {label_id}")
        if not (0 < width <= 1 and 0 < height <= 1):
            raise ValueError(f"{path}:{line_number} bbox size must be in (0, 1]")
        if not (width / 2 <= cx <= 1 - width / 2 and height / 2 <= cy <= 1 - height / 2):
            raise ValueError(f"{path}:{line_number} bbox must be wholly inside its image")
        detections.append(Detection(source_image, len(detections), cx, cy, width, height))
    return detections


def validate_historical_skeleton(path: Path) -> None:
    """Require the exact schema used by the locally completed Phase B set."""
    try:
        labels = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid historical skeleton JSON: {path}") from exc
    if not isinstance(labels, list) or len(labels) != 1:
        raise ValueError("historical skeleton JSON must have one top-level label")
    label = labels[0]
    if label.get("name") != SWIMMER_LABEL or label.get("color") != "#ff6037":
        raise ValueError("historical skeleton must be the orange `swimmer` label")
    if label.get("type") != "skeleton" or label.get("attributes") != []:
        raise ValueError("historical skeleton top-level shape is invalid")
    if [sublabel.get("name") for sublabel in label.get("sublabels", [])] != list(KEYPOINTS):
        raise ValueError("historical skeleton must use the exact 19-point swimmer order")
    if any(sublabel.get("type") != "points" or sublabel.get("attributes") != [] for sublabel in label["sublabels"]):
        raise ValueError("every historical swimmer keypoint must be a plain points sublabel")
    svg = label.get("svg")
    if not isinstance(svg, str):
        raise ValueError("historical skeleton is missing its SVG")
    if "data-label-id=" in svg or '"id"' in label:
        raise ValueError("historical Raw schema must bind skeleton points by name, not a fixed label ID")
    if svg.count("data-label-name=") != len(KEYPOINTS):
        raise ValueError("historical skeleton SVG must bind all 19 point names")
    for point_index, name in enumerate(KEYPOINTS, start=1):
        expected = f'data-element-id="{point_index}" data-node-id="{point_index}" data-label-name="{name}"'
        if expected not in svg:
            raise ValueError(f"historical skeleton SVG is missing point {point_index}: {name}")


def read_reference_coco(reference_images: Path, reference_coco: Path) -> tuple[dict, dict[int, bytes]]:
    """Validate and load the completed local crop annotation set for reference."""
    if not reference_images.is_file() or not reference_coco.is_file():
        raise ValueError("the completed local Phase B crop reference archives are required")
    with zipfile.ZipFile(reference_coco) as archive:
        member = "annotations/person_keypoints_default.json"
        if member not in archive.namelist():
            raise ValueError("reference COCO archive is missing annotations/person_keypoints_default.json")
        data = json.loads(archive.read(member))
    categories = data.get("categories", [])
    if len(categories) != 1:
        raise ValueError("reference COCO archive must have one swimmer category")
    category = categories[0]
    if category.get("name") != SWIMMER_LABEL or category.get("keypoints") != list(KEYPOINTS):
        raise ValueError("reference COCO category is not the established 19-point swimmer schema")
    if [tuple(edge) for edge in category.get("skeleton", [])] != list(SKELETON_EDGES):
        raise ValueError("reference COCO skeleton edges differ from the established Phase B schema")
    images = data.get("images", [])
    annotations = data.get("annotations", [])
    if len(images) != 53 or len(annotations) != 53:
        raise ValueError("reference set must contain its 53 completed crop annotations")
    if any(len(annotation.get("keypoints", [])) != len(KEYPOINTS) * 3 for annotation in annotations):
        raise ValueError("reference annotations must carry all 19 keypoint triples")
    if any(annotation.get("num_keypoints", 0) <= 0 for annotation in annotations):
        raise ValueError("reference annotations must contain completed keypoints")
    with zipfile.ZipFile(reference_images) as archive:
        image_bytes = {
            Path(member.filename).name: archive.read(member.filename)
            for member in archive.infolist()
            if not member.is_dir() and member.filename.lower().endswith(".jpg")
        }
    expected_names = {Path(image["file_name"]).name for image in images}
    if set(image_bytes) != expected_names:
        raise ValueError("reference crop image archive does not match its COCO annotations")
    return data, image_bytes


def make_crop_window(detection: Detection, image_width: int, image_height: int) -> tuple[int, int, int, int, list[float]]:
    """Return the historic 1.5x centered crop and original bbox coordinates inside it."""
    box_width = detection.width * image_width
    box_height = detection.height * image_height
    crop_width = math.ceil(box_width * CROP_SCALE)
    crop_height = math.ceil(box_height * CROP_SCALE)
    if crop_width > image_width or crop_height > image_height:
        raise ValueError(f"{detection.source_image}: source box is too large for a 1.5x Phase B crop")
    center_x = detection.cx * image_width
    center_y = detection.cy * image_height
    left = round(center_x - crop_width / 2)
    top = round(center_y - crop_height / 2)
    left = min(max(left, 0), image_width - crop_width)
    top = min(max(top, 0), image_height - crop_height)
    bbox_left = center_x - box_width / 2 - left
    bbox_top = center_y - box_height / 2 - top
    if not (0 <= bbox_left and 0 <= bbox_top and bbox_left + box_width <= crop_width and bbox_top + box_height <= crop_height):
        raise ValueError(f"{detection.source_image}: crop does not contain its source swimmer box")
    return left, top, crop_width, crop_height, [bbox_left, bbox_top, box_width, box_height]


def crop_contains_another_swimmer(
    record: CropRecord, source_detections: list[Detection], source_width: int, source_height: int,
) -> bool:
    """Check whether a different confirmed swimmer box overlaps the target crop.

    This is deliberately evaluated in source-image coordinates. It prevents a
    crop from being called "single swimmer" merely because we create one
    skeleton object for it while a second swimmer remains visible in the crop.
    """
    left, top, crop_width, crop_height = record.crop_window_pixels
    right, bottom = left + crop_width, top + crop_height
    for detection in source_detections:
        if detection.source_index == record.source_annotation_index:
            continue
        x1 = (detection.cx - detection.width / 2) * source_width
        y1 = (detection.cy - detection.height / 2) * source_height
        x2 = (detection.cx + detection.width / 2) * source_width
        y2 = (detection.cy + detection.height / 2) * source_height
        if max(left, x1) < min(right, x2) and max(top, y1) < min(bottom, y2):
            return True
    return False


def write_zip(source_dir: Path, output_path: Path, *, root_name: str | None = None) -> None:
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                relative = path.relative_to(source_dir).as_posix()
                archive.write(path, f"{root_name}/{relative}" if root_name else relative)


def write_image_subset_zip(images_dir: Path, image_names: list[str], output_path: Path) -> None:
    """Write exactly the selected crop images under the CVAT task's ``images/`` root."""
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for image_name in sorted(image_names):
            source = images_dir / image_name
            if not source.is_file():
                raise ValueError(f"selected crop image is missing: {source}")
            archive.write(source, f"images/{image_name}")


def build_reference_sheet(data: dict, image_bytes: dict[str, bytes], path: Path) -> None:
    """Make a viewable contact sheet from the real completed annotation examples."""
    images = {image["id"]: image for image in data["images"]}
    annotations = {annotation["image_id"]: annotation for annotation in data["annotations"]}
    columns, rows, tile_width, tile_height = 3, 4, 300, 250
    sheet = Image.new("RGB", (columns * tile_width, rows * tile_height), "#ffffff")
    for index, image_id in enumerate(sorted(images)[: columns * rows]):
        image_info = images[image_id]
        annotation = annotations[image_id]
        with Image.open(io.BytesIO(image_bytes[Path(image_info["file_name"]).name])) as source:
            source = source.convert("RGB")
            source.thumbnail((tile_width - 16, tile_height - 34), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (tile_width - 16, tile_height - 34), "#f4f4f4")
            offset_x = (canvas.width - source.width) // 2
            offset_y = (canvas.height - source.height) // 2
            canvas.paste(source, (offset_x, offset_y))
        draw = ImageDraw.Draw(canvas)
        scale_x = source.width / image_info["width"]
        scale_y = source.height / image_info["height"]
        points = annotation["keypoints"]
        for left_index, right_index in SKELETON_EDGES:
            left = points[(left_index - 1) * 3 : left_index * 3]
            right = points[(right_index - 1) * 3 : right_index * 3]
            if left[2] and right[2]:
                draw.line(
                    ((offset_x + left[0] * scale_x, offset_y + left[1] * scale_y),
                     (offset_x + right[0] * scale_x, offset_y + right[1] * scale_y)),
                    fill="#34d1bf", width=2,
                )
        for point_index in range(len(KEYPOINTS)):
            x, y, visibility = points[point_index * 3 : point_index * 3 + 3]
            if visibility:
                color = "#ff6037" if visibility == 2 else "#f6c945"
                px, py = offset_x + x * scale_x, offset_y + y * scale_y
                draw.ellipse((px - 3, py - 3, px + 3, py + 3), fill=color, outline="#111111")
        x = (index % columns) * tile_width
        y = (index // columns) * tile_height
        sheet.paste(canvas, (x + 8, y + 8))
        ImageDraw.Draw(sheet).text((x + 8, y + tile_height - 22), Path(image_info["file_name"]).stem, fill="#111111")
    sheet.save(path, quality=95, subsampling=0)


def validate_crop_archive(archive_path: Path, expected_names: list[str]) -> None:
    expected_members = {f"images/{name}" for name in expected_names}
    with zipfile.ZipFile(archive_path) as archive:
        members = {member for member in archive.namelist() if not member.endswith("/")}
        if members != expected_members:
            raise ValueError(f"crop archive structure mismatch; missing={sorted(expected_members - members)}, extra={sorted(members - expected_members)}")
        for name in expected_names:
            with Image.open(io.BytesIO(archive.read(f"images/{name}"))) as image:
                image.verify()


def is_reliable_model_point(
    keypoint: list[float], image_width: int, image_height: int, point_confidence: float,
) -> bool:
    x, y, confidence = keypoint
    return point_confidence <= confidence and 0 <= x < image_width and 0 <= y < image_height


def has_visible_model_pose(
    record: CropRecord, prediction: dict[str, Any], point_confidence: float,
) -> bool:
    """Return true only for a crop with at least one usable model keypoint."""
    keypoints = prediction["keypoints"]
    if keypoints is None:
        return False
    crop_width, crop_height = record.crop_window_pixels[2:]
    return any(
        is_reliable_model_point(keypoint, crop_width, crop_height, point_confidence)
        for keypoint in keypoints
    )


def filter_preannotation_report(
    report: dict[str, Any], selected_names: set[str], selection: str,
) -> dict[str, Any]:
    """Make the delivered report describe the selected task rather than inference leftovers."""
    per_crop = [row for row in report["per_crop"] if row["crop_image"] in selected_names]
    if len(per_crop) != len(selected_names):
        raise ValueError("preannotation report cannot be matched to the selected crop set")
    filtered = dict(report)
    filtered["source_inference_crops"] = report["crops"]
    filtered["selection"] = selection
    filtered["crops"] = len(per_crop)
    filtered["crops_with_model_detection"] = sum(row["detection_confidence"] is not None for row in per_crop)
    filtered["crops_with_visible_model_pose"] = sum(row["model_visible_coco17_points"] > 0 for row in per_crop)
    filtered["model_visible_coco17_points"] = sum(row["model_visible_coco17_points"] for row in per_crop)
    filtered["per_crop"] = per_crop
    return filtered


def generate_pose_predictions(crops_dir: Path, args: argparse.Namespace) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Run the local pose checkpoint and retain only real model keypoints.

    This is intentionally not a geometric fallback.  A point is pre-filled
    only when the local YOLO pose model emitted a coordinate with enough
    confidence.  The two swimmer-specific foot-index points remain empty,
    because the COCO checkpoint does not predict them.
    """
    if not args.pose_model.is_file():
        raise ValueError(f"local pose checkpoint does not exist: {args.pose_model}")
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise ValueError(
            "Ultralytics is required to build real Phase B preannotations; "
            "run this builder from the project's .venv"
        ) from exc

    crop_paths = sorted(crops_dir.glob("*.jpg"))
    if not crop_paths:
        raise ValueError("cannot generate pose preannotations without crop images")
    model = YOLO(str(args.pose_model))
    predictions: dict[str, dict[str, Any]] = {}
    for offset in range(0, len(crop_paths), args.pose_batch):
        batch_paths = crop_paths[offset : offset + args.pose_batch]
        results = model.predict(
            [str(path) for path in batch_paths],
            imgsz=args.pose_imgsz,
            conf=args.detection_confidence,
            max_det=1,
            batch=args.pose_batch,
            device=args.pose_device,
            verbose=False,
        )
        if len(results) != len(batch_paths):
            raise ValueError("pose model returned a result count that does not match the crop batch")
        for path, result in zip(batch_paths, results):
            prediction: dict[str, Any] = {
                "detection_confidence": None,
                "keypoints": None,
                "image_width": int(result.orig_shape[1]),
                "image_height": int(result.orig_shape[0]),
            }
            if result.boxes is not None and len(result.boxes) and result.keypoints is not None:
                keypoint_data = result.keypoints.data
                if keypoint_data is not None and len(keypoint_data):
                    keypoints = keypoint_data[0].cpu().numpy().tolist()
                    # 17 = stock COCO checkpoint; 19 = Phase B swimmer-19
                    # weights (DEVLOG #38) — feet get real pre-annotations.
                    if len(keypoints) not in (YOLO_POSE_KEYPOINT_COUNT, len(KEYPOINTS)) \
                            or any(len(row) < 3 for row in keypoints):
                        raise ValueError(
                            f"{path.name}: pose model returned "
                            f"{len(keypoints)} keypoints (expected 17 or 19)")
                    prediction["detection_confidence"] = float(result.boxes.conf[0].cpu().item())
                    prediction["keypoints"] = [
                        [float(x), float(y), float(confidence)]
                        for x, y, confidence in keypoints
                    ]
            predictions[path.name] = prediction

    detected = [value for value in predictions.values() if value["keypoints"] is not None]
    preannotated = [
        value for value in detected
        if any(
            is_reliable_model_point(
                keypoint, value["image_width"], value["image_height"], args.point_confidence,
            ) for keypoint in value["keypoints"]
        )
    ]
    visible_points = sum(
        1
        for value in detected
        for keypoint in value["keypoints"]
        if is_reliable_model_point(
            keypoint, value["image_width"], value["image_height"], args.point_confidence,
        )
    )
    if not detected:
        raise ValueError("local pose checkpoint did not produce any real preannotations")
    report = {
        "schema": "phase-b-swimmer19-model-preannotations/v1",
        "model": str(args.pose_model.resolve()),
        "detection_confidence_threshold": args.detection_confidence,
        "point_confidence_threshold": args.point_confidence,
        "image_size": args.pose_imgsz,
        "device": args.pose_device,
        "crops": len(crop_paths),
        "crops_with_model_detection": len(detected),
        "crops_with_visible_model_pose": len(preannotated),
        "model_visible_coco17_points": visible_points,
        "foot_index_points": (
            "pre-annotated by the Phase B swimmer-19 checkpoint"
            if any(v["keypoints"] is not None and len(v["keypoints"]) == len(KEYPOINTS)
                   for v in predictions.values())
            else "outside: local COCO pose checkpoint does not predict them"
        ),
        "per_crop": [
            {
                "crop_image": name,
                "detection_confidence": value["detection_confidence"],
                "model_visible_coco17_points": (
                    sum(
                        is_reliable_model_point(
                            keypoint, value["image_width"], value["image_height"], args.point_confidence,
                        )
                        for keypoint in value["keypoints"]
                    )
                    if value["keypoints"] is not None else 0
                ),
            }
            for name, value in sorted(predictions.items())
        ],
    }
    return predictions, report


def write_skeleton_seed_xml(
    records: list[CropRecord], predictions: dict[str, dict[str, Any]], point_confidence: float, path: Path,
) -> None:
    """Pre-create one 19-slot swimmer skeleton for every crop image.

    ``outside=1`` is CVAT's explicit representation of an unplaced skeleton
    element.  COCO-17 points with actual local-model coordinates are visible;
    all other points remain genuinely unannotated.  The XML follows CVAT for
    images 1.1.
    """
    root = ET.Element("annotations")
    ET.SubElement(root, "version").text = "1.1"
    for image_id, record in enumerate(sorted(records, key=lambda item: item.crop_image)):
        crop_width, crop_height = record.crop_window_pixels[2:]
        image = ET.SubElement(root, "image", {
            "id": str(image_id),
            "name": record.crop_image,
            "width": str(crop_width),
            "height": str(crop_height),
        })
        skeleton = ET.SubElement(image, "skeleton", {
            "label": SWIMMER_LABEL,
            "source": "file",
            "outside": "0",
        })
        placeholder = f"{crop_width / 2:.2f},{crop_height / 2:.2f}"
        prediction = predictions.get(record.crop_image)
        if prediction is None:
            raise ValueError(f"missing model prediction record for {record.crop_image}")
        model_points = prediction["keypoints"]
        for point_index, keypoint in enumerate(KEYPOINTS):
            attrs = {
                "label": keypoint,
                "source": "file",
                "outside": "1",
                "occluded": "0",
                "points": placeholder,
            }
            if model_points is not None and point_index < len(model_points):
                x, y, confidence = model_points[point_index]
                if is_reliable_model_point([x, y, confidence], crop_width, crop_height, point_confidence):
                    attrs["outside"] = "0"
                    attrs["points"] = f"{x:.2f},{y:.2f}"
            ET.SubElement(skeleton, "points", {
                **attrs,
            })
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def validate_skeleton_seed_xml(
    path: Path, records: list[CropRecord], predictions: dict[str, dict[str, Any]], point_confidence: float,
) -> None:
    """Prove every crop has one skeleton with only genuine model points shown."""
    root = ET.parse(path).getroot()
    if root.tag != "annotations" or root.findtext("version") != "1.1":
        raise ValueError("CVAT skeleton seed XML is not CVAT for images 1.1")
    images = root.findall("image")
    expected = {record.crop_image: record for record in records}
    if {image.get("name") for image in images} != set(expected):
        raise ValueError("CVAT skeleton seed XML image names do not match the crop archive")
    if len(images) != len(records):
        raise ValueError("CVAT skeleton seed XML does not cover every crop")
    for image in images:
        record = expected[image.attrib["name"]]
        crop_width, crop_height = record.crop_window_pixels[2:]
        if (int(image.attrib["width"]), int(image.attrib["height"])) != (crop_width, crop_height):
            raise ValueError(f"seed XML dimensions do not match {record.crop_image}")
        skeletons = image.findall("skeleton")
        if len(skeletons) != 1 or skeletons[0].get("label") != SWIMMER_LABEL:
            raise ValueError(f"seed XML must contain one swimmer skeleton for {record.crop_image}")
        points = skeletons[0].findall("points")
        if [point.get("label") for point in points] != list(KEYPOINTS):
            raise ValueError(f"seed XML point order is invalid for {record.crop_image}")
        prediction = predictions[record.crop_image]["keypoints"]
        expected_visible = set()
        if prediction is not None:
            expected_visible = {
                index
                for index, (x, y, confidence) in enumerate(prediction)
                if is_reliable_model_point([x, y, confidence], crop_width, crop_height, point_confidence)
            }
        for point_index, point in enumerate(points):
            is_visible = point.get("outside") == "0"
            if is_visible != (point_index in expected_visible):
                raise ValueError(f"seed XML visibility does not match model output for {record.crop_image}")
            if point.get("occluded") != "0":
                raise ValueError(f"seed XML must not invent occlusion for {record.crop_image}")


def readme_text(
    package_date: str,
    image_count: int,
    crop_count: int,
    preannotation_report: dict[str, Any],
    scope: str,
) -> str:
    point_rows = "\n".join(f"| {index} | `{name}` |" for index, name in enumerate(KEYPOINTS, start=1))
    return f"""# Emily — Phase B 剩余骨架标注包（历史 19 点标准）

打包日期：{package_date}  
本批范围：{image_count} 张原始帧、{crop_count} 位运动员。{scope} 每位运动员是一张独立 crop。

这个包**没有另起一套标准**。它逐字复用了 Tim 本机上已完成的 `swimmer` 19 点 skeleton：橙色 `swimmer`、COCO-17 加左右 `foot_index`。包内还带了那 53 张已完成 crop 的图片和 COCO 标注，作为唯一的标注样例。

## 导入（沿用旧 Phase B 流程）

1. 双击 `1-start-cvat.command`，打开本机 CVAT。
2. 新建 Project：`syncswim-phase-b-swimmer19`。
3. 在 Project 的 **Labels → Raw** 中，用 `cvat_skeleton_swimmer_19pt.json` 的完整内容替换编辑器，然后保存。它是历史文件的逐字副本；只会创建橙色的 `swimmer` 19 点 skeleton。**不要创建 `person`，不要增加或删除点。**
4. 在该 Project 新建 Task：`phase-b-swimmer19-crops`。上传 `phase_b_remaining_crop_images.zip` 作为图片数据。
5. 等任务准备完成后，在 Task 的 **Actions → Upload annotations**（有的版本写作 **Import annotations**）选择 **CVAT for images 1.1**，上传 `phase_b_remaining_crop_skeleton_seeds.xml`。这一步会预置 **{crop_count} 个 `swimmer` skeleton**，每张 crop 一个。
6. 打开 Job 后确认共有 **{crop_count}** 张图片，Objects 列表每张已有一个 `swimmer`。其中 **{preannotation_report['crops_with_visible_model_pose']}** 张已有本机 YOLO pose 模型实际预测出的可见关键点（共 {preannotation_report['model_visible_coco17_points']} 个）；模型未可靠预测的点保持空，不会用猜测坐标填充（若预标注模型是 19 点的 Phase B 权重，双 `foot_index` 也会有预标注；若是 COCO 17 点模型则保持空）。文件名末尾 `_p0`、`_p1` 等是该原始帧中的第几个已确认 swimmer。
7. 打开 `reference_examples.jpg` 看已完成的真实样例；需要逐张查看原始标注时，可另建临时 task 导入 `reference_annotated_crops_images.zip` 与 `reference_annotated_crops_coco.zip`。

## 每张 crop 怎么标

1. 每张 crop 的 `swimmer` skeleton 已经预置。**不要新建、删除或复制 skeleton**；先核对模型已经落下的点，再修正它们并补空点。
2. 标完整 19 个点。左右以运动员自身左右为准。
3. 可清楚落点：**visible**（COCO `v=2`）。被水花、另一人或器材遮住、但关节位置可可靠判断：**occluded**（`v=1`）。看不清或无法可靠判断：保持未标（`v=0`），绝不按比例猜点。
4. 特别保留最后两个点：`left_foot_index`、`right_foot_index`。这正是旧 Phase B 标准相对 COCO-17 多出的两个点。

| 序号 | 关键点 |
|---:|---|
{point_rows}

## 交回

Task → **Actions → Export task dataset** → **COCO Keypoints 1.0** → 不勾 **Save images**。把下载文件命名为 `phase_b_swimmer19_crops_emily_YYYYMMDD.zip` 发回 Tim。

`crop_manifest.json` 记录每张 crop 对应的源帧、源 bbox 和裁切窗口，供 Tim 将结果复核或映射回原图；Emily 不需要修改它。
"""


def build(args: argparse.Namespace) -> Path:
    validate_historical_skeleton(HISTORICAL_SKELETON)
    reference_coco, reference_image_bytes = read_reference_coco(args.reference_images, args.reference_coco)
    images_by_stem = find_by_stem(args.images, ".jpg")
    labels_by_stem = find_by_stem(args.labels, ".txt")
    if images_by_stem.keys() != labels_by_stem.keys():
        raise ValueError("Phase A image/label filename stems do not match")

    parsed = {
        stem: parse_detection_label(labels_by_stem[stem], images_by_stem[stem].name)
        for stem in sorted(images_by_stem)
    }
    included = {
        stem: detections
        for stem, detections in parsed.items()
        if not args.single_person_only or len(detections) == 1
    }
    crop_count = sum(len(detections) for detections in included.values())
    if crop_count == 0:
        scope = "single-person" if args.single_person_only else "source"
        raise ValueError(f"Phase A {scope} labels contain no swimmer boxes")

    selection_suffixes = []
    if args.single_person_only:
        selection_suffixes.append("single_person")
    if args.single_swimmer_crops_only:
        selection_suffixes.append("single_crop")
    if args.visible_preannotations_only:
        selection_suffixes.append("preannotated")
    selection_suffix = f"_{'_'.join(selection_suffixes)}" if selection_suffixes else ""
    package_name = f"emily_phase_b_swimmer19{selection_suffix}_crops_{args.package_date}"
    output_root = args.output.resolve()
    package_dir = output_root / package_name
    package_zip = output_root / f"{package_name}.zip"
    if package_dir.exists() or package_zip.exists():
        raise ValueError(f"output already exists: {package_dir} or {package_zip}")
    output_root.mkdir(parents=True, exist_ok=True)

    try:
        with tempfile.TemporaryDirectory(prefix="phase_b_swimmer19_") as temporary:
            staging = Path(temporary)
            crops_root = staging / "phase_b_remaining_crop_images"
            crops_dir = crops_root / "images"
            crops_dir.mkdir(parents=True)
            records: list[CropRecord] = []
            source_dimensions: dict[str, tuple[int, int]] = {}
            for stem in sorted(included):
                source_path = images_by_stem[stem]
                with Image.open(source_path) as source:
                    source = source.convert("RGB")
                    image_width, image_height = source.size
                    source_dimensions[source_path.name] = (image_width, image_height)
                    for detection in included[stem]:
                        left, top, crop_width, crop_height, crop_bbox = make_crop_window(
                            detection, image_width, image_height,
                        )
                        crop_name = f"{source_path.stem}_p{detection.source_index}.jpg"
                        source.crop((left, top, left + crop_width, top + crop_height)).save(
                            crops_dir / crop_name, quality=95, subsampling=0,
                        )
                        source_bbox = [
                            (detection.cx - detection.width / 2) * image_width,
                            (detection.cy - detection.height / 2) * image_height,
                            detection.width * image_width,
                            detection.height * image_height,
                        ]
                        records.append(CropRecord(
                            crop_image=crop_name,
                            source_image=source_path.name,
                            source_annotation_index=detection.source_index,
                            source_bbox_yolo=[detection.cx, detection.cy, detection.width, detection.height],
                            source_bbox_pixels=source_bbox,
                            crop_window_pixels=[left, top, crop_width, crop_height],
                            swimmer_bbox_in_crop_pixels=crop_bbox,
                        ))

            if args.single_swimmer_crops_only:
                records = [
                    record
                    for record in records
                    if not crop_contains_another_swimmer(
                        record,
                        parsed[Path(record.source_image).stem],
                        *source_dimensions[record.source_image],
                    )
                ]
                if not records:
                    raise ValueError("no crop remains after excluding overlapping swimmer detections")
            crop_names = [record.crop_image for record in records]
            if len(crop_names) != len(set(crop_names)):
                raise ValueError("generated crop image names are not unique")
            pose_input_dir = staging / "pose_input"
            pose_input_dir.mkdir()
            for crop_name in crop_names:
                shutil.copy2(crops_dir / crop_name, pose_input_dir / crop_name)
            predictions, preannotation_report = generate_pose_predictions(pose_input_dir, args)
            if args.visible_preannotations_only:
                records = [
                    record
                    for record in records
                    if has_visible_model_pose(record, predictions[record.crop_image], args.point_confidence)
                ]
                if not records:
                    raise ValueError("no crop has a reliable visible model pose for the requested selection")
                crop_names = [record.crop_image for record in records]
                preannotation_report = filter_preannotation_report(
                    preannotation_report,
                    set(crop_names),
                    "at_least_one_reliable_visible_local_model_keypoint",
                )
            crops_zip = staging / "phase_b_remaining_crop_images.zip"
            write_image_subset_zip(crops_dir, crop_names, crops_zip)
            validate_crop_archive(crops_zip, crop_names)
            seed_xml = staging / "phase_b_remaining_crop_skeleton_seeds.xml"
            write_skeleton_seed_xml(records, predictions, args.point_confidence, seed_xml)
            validate_skeleton_seed_xml(seed_xml, records, predictions, args.point_confidence)

            package_dir.mkdir()
            shutil.copy2(HISTORICAL_SKELETON, package_dir / HISTORICAL_SKELETON.name)
            shutil.copy2(crops_zip, package_dir / crops_zip.name)
            shutil.copy2(seed_xml, package_dir / seed_xml.name)
            (package_dir / "preannotation_report.json").write_text(
                json.dumps(preannotation_report, indent=2) + "\n",
            )
            shutil.copy2(args.reference_images, package_dir / "reference_annotated_crops_images.zip")
            shutil.copy2(args.reference_coco, package_dir / "reference_annotated_crops_coco.zip")
            (package_dir / "crop_manifest.json").write_text(
                json.dumps({
                    "schema": "phase-b-swimmer19-crops/v1",
                    "crop_scale": CROP_SCALE,
                    "original_bbox_fraction_of_crop": 2 / 3,
                    "source_frame_selection": "exactly_one_confirmed_swimmer" if args.single_person_only else "all_frames",
                    "crop_selection": (
                        "at_least_one_reliable_visible_local_model_keypoint"
                        if args.visible_preannotations_only else "all_generated_crops"
                    ),
                    "contains_no_other_confirmed_swimmer_bbox": args.single_swimmer_crops_only,
                    "records": [asdict(record) for record in records],
                }, indent=2) + "\n",
            )
            build_reference_sheet(reference_coco, reference_image_bytes, package_dir / "reference_examples.jpg")
            shutil.copy2(ROOT / "tools" / "start-cvat.command", package_dir / "1-start-cvat.command")
            (package_dir / "1-start-cvat.command").chmod(0o755)
            (package_dir / "2-open-instructions.command").write_text(
                "#!/bin/bash\nset -e\ncd \"$(dirname \"$0\")\"\nopen README.md\n",
            )
            (package_dir / "2-open-instructions.command").chmod(0o755)
            (package_dir / "README.md").write_text(
                readme_text(
                    args.package_date,
                    len({record.source_image for record in records}),
                    len(records),
                    preannotation_report,
                    (
                        "只保留裁剪范围内不含另一位已确认 swimmer，且本机姿态模型已有至少一个可靠可见关键点的 crop；"
                        "每张图都可直接看到预标注。"
                        if args.single_swimmer_crops_only and args.visible_preannotations_only
                        else (
                            "只保留本机姿态模型已有至少一个可靠可见关键点的单人 crop；"
                            "每张图都可直接看到预标注。"
                            if args.visible_preannotations_only
                            else (
                                "只包含原始帧中恰好有 1 位已确认 swimmer 的单人帧；多人帧完全排除。"
                                if args.single_person_only
                                else "包含所有原始帧中 Phase A 已确认的 swimmer。"
                            )
                        )
                    ),
                ),
            )
            manifest_lines = [
                f"{sha256(path)}  {path.name}"
                for path in sorted(package_dir.iterdir())
                if path.is_file() and path.name != "MANIFEST.sha256"
            ]
            (package_dir / "MANIFEST.sha256").write_text("\n".join(manifest_lines) + "\n")
            write_zip(package_dir, package_zip, root_name=package_name)
    except Exception:
        shutil.rmtree(package_dir, ignore_errors=True)
        package_zip.unlink(missing_ok=True)
        raise

    print("[done] historical-standard Phase B handoff kit created")
    print(f"  package: {package_zip}")
    print(f"  source frames: {len({record.source_image for record in records})}")
    print(f"  swimmer crops: {len(records)}")
    if args.single_person_only:
        print("  selection: source frames with exactly one confirmed swimmer")
    if args.single_swimmer_crops_only:
        print("  selection: crops without another confirmed swimmer bbox")
    if args.visible_preannotations_only:
        print("  selection: crops with at least one reliable visible local-model keypoint")
    print("  schema: orange swimmer skeleton, 19 points, COCO Keypoints export")
    return package_zip


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, default=DEFAULT_IMAGES)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--reference-images", type=Path, default=DEFAULT_REFERENCE_IMAGES)
    parser.add_argument("--reference-coco", type=Path, default=DEFAULT_REFERENCE_COCO)
    parser.add_argument("--pose-model", type=Path, default=ROOT / "yolov8s-pose.pt")
    parser.add_argument("--pose-device", default="cpu")
    parser.add_argument("--pose-batch", type=int, default=16)
    parser.add_argument("--pose-imgsz", type=int, default=640)
    parser.add_argument("--detection-confidence", type=float, default=0.10)
    parser.add_argument("--point-confidence", type=float, default=0.20)
    parser.add_argument(
        "--single-person-only",
        action="store_true",
        help="Exclude every source frame that does not contain exactly one confirmed swimmer",
    )
    parser.add_argument(
        "--visible-preannotations-only",
        action="store_true",
        help="Keep only crops where the local pose model produced at least one reliable visible keypoint",
    )
    parser.add_argument(
        "--single-swimmer-crops-only",
        action="store_true",
        help="Exclude a crop if another confirmed swimmer bounding box overlaps it",
    )
    parser.add_argument("--output", type=Path, default=ROOT)
    parser.add_argument("--date", dest="package_date", default=date.today().strftime("%Y%m%d"))
    args = parser.parse_args()
    if len(args.package_date) != 8 or not args.package_date.isdigit():
        parser.error("--date must be YYYYMMDD")
    if args.pose_batch < 1 or args.pose_imgsz < 32:
        parser.error("--pose-batch must be positive and --pose-imgsz must be at least 32")
    if not (0 <= args.detection_confidence <= 1 and 0 <= args.point_confidence <= 1):
        parser.error("pose confidence thresholds must be in [0, 1]")
    try:
        build(args)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

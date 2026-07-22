from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_AUDIO_DATASET_DIRS = (
    "converted_v1_toolmind_full",
    "converted_v1_nemotron_agentic_full",
    "converted_v1_nemotron_post_full",
)

MANIFEST_NAME = "audio_materialization_manifest.json"
TASKS_NAME = "audio_materialization_tasks.jsonl"
SHARD_GLOB = "audio_materialization_manifest_shard_*_of_*.json"


@dataclass(frozen=True)
class ManifestRecord:
    conversation_id: str
    turn_index: int
    audio_path: str
    dataset_name: str | None = None
    text: str | None = None
    language: str | None = None
    audio_source: str | None = None
    duration_ms: int | None = None
    sample_rate: int | None = None
    quality_flag: str | None = None
    turn_index_source: str = "manifest"
    source_file: str | None = None

    @classmethod
    def from_mapping(
        cls,
        data: dict[str, Any],
        *,
        fallback_turn_index: int | None = None,
        source_file: str | None = None,
        base_dir: str | Path | None = None,
        dataset_name: str | None = None,
    ) -> "ManifestRecord":
        flat = _flatten_mapping(data)
        conversation_id = _first_value(
            flat,
            "conversation_id",
            "dialogue_id",
            "dialog_id",
            "conversation_uuid",
            "uuid",
        )
        audio_path = _first_value(
            flat,
            "audio_path",
            "full_audio",
            "wav_path",
            "path",
            "output_path",
            "audio",
        )
        turn_index = _first_value(flat, "turn_index", "turn_id", "user_turn_index", "turn")
        turn_index_source = "manifest"
        if not conversation_id and audio_path:
            conversation_id = _conversation_id_from_audio_path(str(audio_path))
        if turn_index is None:
            parsed_turn_index = _turn_index_from_audio_path(str(audio_path)) if audio_path else None
            if parsed_turn_index is not None:
                turn_index = parsed_turn_index
                turn_index_source = "audio_path"
            elif fallback_turn_index is not None:
                turn_index = fallback_turn_index
                turn_index_source = "seed_order"
            else:
                raise ValueError("manifest record missing turn_index")
        if not conversation_id:
            raise ValueError("manifest record missing conversation_id")
        if not audio_path:
            raise ValueError("manifest record missing audio_path")
        if base_dir is not None:
            audio_path_obj = Path(str(audio_path))
            if not audio_path_obj.is_absolute():
                audio_path = str(Path(base_dir) / audio_path_obj)
        return cls(
            dataset_name=dataset_name,
            conversation_id=str(conversation_id),
            turn_index=int(turn_index),
            audio_path=str(audio_path),
            text=str(flat["text"]) if flat.get("text") is not None else None,
            language=str(flat["language"]) if flat.get("language") is not None else None,
            audio_source=str(flat["audio_source"]) if flat.get("audio_source") is not None else None,
            duration_ms=int(flat["duration_ms"]) if flat.get("duration_ms") is not None else None,
            sample_rate=int(flat["sample_rate"]) if flat.get("sample_rate") is not None else None,
            quality_flag=str(flat["quality_flag"]) if flat.get("quality_flag") is not None else None,
            turn_index_source=turn_index_source,
            source_file=source_file,
        )


class ManifestIndex:
    def __init__(self, records: Iterable[ManifestRecord]):
        self._records: dict[tuple[str | None, str, int], ManifestRecord] = {}
        for record in records:
            key = (record.dataset_name, record.conversation_id, record.turn_index)
            if key in self._records:
                raise ValueError(f"duplicate manifest key: {key}")
            self._records[key] = record

    def get(self, conversation_id: str, turn_index: int, dataset_name: str | None = None) -> ManifestRecord:
        key = (dataset_name, conversation_id, turn_index)
        if key not in self._records:
            raise KeyError(f"missing manifest record for {conversation_id} turn {turn_index}")
        return self._records[key]

    def records_for_conversation(self, conversation_id: str, dataset_name: str | None = None) -> list[ManifestRecord]:
        records = [
            r for (dataset, cid, _), r in self._records.items()
            if cid == conversation_id and dataset == dataset_name
        ]
        return sorted(records, key=lambda r: r.turn_index)

    def validate_audio_paths(self, manifest_root: str | Path | None = None) -> list[str]:
        root = Path(manifest_root) if manifest_root is not None else None
        missing: list[str] = []
        for record in self._records.values():
            path = Path(record.audio_path)
            if not path.is_absolute() and root is not None:
                path = root / path
            if not path.exists():
                missing.append(str(path))
        return missing

    def __len__(self) -> int:
        return len(self._records)

    def records(self) -> list[ManifestRecord]:
        return sorted(self._records.values(), key=lambda r: (r.dataset_name or "", r.conversation_id, r.turn_index))


@dataclass(frozen=True)
class ManifestSource:
    dataset_dir: Path
    manifest: Path | None
    shards: tuple[Path, ...]
    tasks: Path | None

    @property
    def dataset_name(self) -> str:
        return self.dataset_dir.name

    @property
    def selected_inputs(self) -> tuple[Path, ...]:
        candidates: list[Path] = []
        if self.manifest is not None:
            candidates.append(self.manifest)
        candidates.extend(self.shards)
        if self.tasks is not None:
            candidates.append(self.tasks)
        return tuple(candidates)


def _flatten_mapping(data: dict[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {}

    def visit(value: Any) -> None:
        if not isinstance(value, dict):
            return
        for key, item in value.items():
            flat.setdefault(str(key), item)
            if isinstance(item, dict):
                visit(item)

    visit(data)
    return flat


def _first_value(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _conversation_id_from_audio_path(audio_path: str) -> str | None:
    path = Path(audio_path)
    if path.parent.name:
        return path.parent.name
    return None


def _turn_index_from_audio_path(audio_path: str) -> int | None:
    match = re.search(r"(?:^|/)turn(\d+)[^/]*\.wav$", audio_path)
    if match:
        return int(match.group(1))
    match = re.search(r"\bturn(\d+)\b", Path(audio_path).name)
    if match:
        return int(match.group(1))
    return None


def iter_jsonl(path: str | Path) -> Iterable[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSONL") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no}: expected object")
            yield value


def _iter_json_records_from_value(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, list):
        for item in value:
            yield from _iter_json_records_from_value(item)
        return
    if not isinstance(value, dict):
        return

    if _looks_like_manifest_record(value):
        yield value
        return

    for key in ("records", "items", "data", "manifest", "tasks", "results"):
        child = value.get(key)
        if isinstance(child, (list, dict)):
            yield from _iter_json_records_from_value(child)


def _looks_like_manifest_record(value: dict[str, Any]) -> bool:
    flat = _flatten_mapping(value)
    has_audio = _first_value(flat, "audio_path", "full_audio", "wav_path", "path", "output_path", "audio") is not None
    if not has_audio:
        return False
    has_conversation = _first_value(flat, "conversation_id", "dialogue_id", "dialog_id", "conversation_uuid", "uuid") is not None
    has_turn = _first_value(flat, "turn_index", "turn_id", "user_turn_index", "turn") is not None
    if has_conversation and has_turn:
        return True
    audio_path = _first_value(flat, "audio_path", "full_audio", "wav_path", "path", "output_path", "audio")
    return bool(_conversation_id_from_audio_path(str(audio_path)) and _turn_index_from_audio_path(str(audio_path)) is not None)


def iter_json_records(path: str | Path) -> Iterable[dict[str, Any]]:
    path = Path(path)
    if path.suffix == ".jsonl":
        yield from iter_jsonl(path)
        return

    with path.open("r", encoding="utf-8") as f:
        value = json.load(f)
    yielded = False
    for item in _iter_json_records_from_value(value):
        yielded = True
        yield item
    if not yielded:
        raise ValueError(f"{path}: no manifest records found")


def load_manifest(
    path: str | Path,
    *,
    base_dir: str | Path | None = None,
) -> ManifestIndex:
    path = Path(path)
    if base_dir is None and path.suffix == ".json":
        base_dir = path.parent
    return ManifestIndex(
        ManifestRecord.from_mapping(item, source_file=str(path), base_dir=base_dir)
        for item in iter_json_records(path)
    )


def discover_manifest_sources(
    manifest_root: str | Path,
    *,
    dataset_dirs: Iterable[str] = DEFAULT_AUDIO_DATASET_DIRS,
) -> list[ManifestSource]:
    root = Path(manifest_root)
    sources: list[ManifestSource] = []
    for dataset_name in dataset_dirs:
        dataset_dir = root / dataset_name
        if not dataset_dir.exists():
            continue
        manifest = dataset_dir / MANIFEST_NAME
        tasks = dataset_dir / TASKS_NAME
        shards = tuple(sorted(dataset_dir.glob(SHARD_GLOB)))
        sources.append(
            ManifestSource(
                dataset_dir=dataset_dir,
                manifest=manifest if manifest.exists() else None,
                shards=shards,
                tasks=tasks if tasks.exists() else None,
            )
        )
    return sources


def load_manifest_root(
    manifest_root: str | Path,
    *,
    dataset_dirs: Iterable[str] = DEFAULT_AUDIO_DATASET_DIRS,
) -> ManifestIndex:
    records: list[ManifestRecord] = []
    sources = discover_manifest_sources(manifest_root, dataset_dirs=dataset_dirs)
    if not sources:
        raise FileNotFoundError(f"no known audio dataset directories under {manifest_root}")

    for source in sources:
        source_records: list[ManifestRecord] = []
        for path in source.selected_inputs:
            base_dir = source.dataset_dir
            try:
                for item in iter_json_records(path):
                    source_records.append(
                        ManifestRecord.from_mapping(
                            item,
                            source_file=str(path),
                            base_dir=base_dir,
                            dataset_name=source.dataset_name,
                        )
                    )
            except ValueError:
                continue
            if source_records:
                break
        records.extend(source_records)
    if not records:
        raise ValueError(f"no manifest records loaded from {manifest_root}")
    return ManifestIndex(records)

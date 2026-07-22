import json

from distillation_replay.manifest import ManifestIndex, ManifestRecord, load_manifest, load_manifest_root


def test_manifest_index_rejects_duplicate_keys():
    records = [
        ManifestRecord("dlg1", 0, "a.wav"),
        ManifestRecord("dlg1", 0, "b.wav"),
    ]

    try:
        ManifestIndex(records)
    except ValueError as exc:
        assert "duplicate manifest key" in str(exc)
    else:
        raise AssertionError("expected duplicate manifest key")


def test_load_manifest_jsonl(tmp_path):
    audio = tmp_path / "turn0.wav"
    audio.write_bytes(b"fake")
    path = tmp_path / "manifest.jsonl"
    path.write_text(
        json.dumps(
            {
                "conversation_id": "dlg1",
                "turn_index": 0,
                "audio_path": "turn0.wav",
                "sample_rate": 16000,
            }
        ) + "\n",
        encoding="utf-8",
    )

    manifest = load_manifest(path)

    assert manifest.get("dlg1", 0).sample_rate == 16000
    assert manifest.validate_audio_paths(tmp_path) == []


def test_load_manifest_root_falls_back_from_summary_manifest_to_tasks(tmp_path):
    dataset = tmp_path / "converted_v1_toolmind_full"
    audio = dataset / "audio" / "ToolMind" / "conv-a" / "turn0_abc.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"fake")
    (dataset / "audio_materialization_manifest.json").write_text(
        json.dumps({"dataset_root": str(dataset), "selected_audio_refs": 1}),
        encoding="utf-8",
    )
    (dataset / "audio_materialization_tasks.jsonl").write_text(
        json.dumps(
            {
                "audio": "audio/ToolMind/conv-a/turn0_abc.wav",
                "text": "hello",
                "language": "en",
            }
        ) + "\n",
        encoding="utf-8",
    )

    manifest = load_manifest_root(tmp_path, dataset_dirs=["converted_v1_toolmind_full"])
    record = manifest.get("conv-a", 0, dataset_name="converted_v1_toolmind_full")

    assert record.audio_path == str(audio)
    assert record.turn_index_source == "audio_path"
    assert record.text == "hello"
    assert record.language == "en"
    assert manifest.validate_audio_paths() == []


def test_load_manifest_root_keeps_dataset_name_in_key(tmp_path):
    for dataset_name in ("converted_v1_toolmind_full", "converted_v1_nemotron_post_full"):
        dataset = tmp_path / dataset_name
        audio = dataset / "audio" / "Shared" / "conv-same" / "turn0.wav"
        audio.parent.mkdir(parents=True)
        audio.write_bytes(b"fake")
        (dataset / "audio_materialization_tasks.jsonl").write_text(
            json.dumps({"audio": "audio/Shared/conv-same/turn0.wav", "text": dataset_name}) + "\n",
            encoding="utf-8",
        )

    manifest = load_manifest_root(
        tmp_path,
        dataset_dirs=["converted_v1_toolmind_full", "converted_v1_nemotron_post_full"],
    )

    assert len(manifest) == 2
    assert manifest.get("conv-same", 0, dataset_name="converted_v1_toolmind_full").text == "converted_v1_toolmind_full"
    assert manifest.get("conv-same", 0, dataset_name="converted_v1_nemotron_post_full").text == "converted_v1_nemotron_post_full"

from __future__ import annotations

import uuid

from app.services.checkpoints import JobCheckpoint, delete_checkpoint, load_checkpoint, save_checkpoint
from app.services.epub import Segment


def test_checkpoint_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.checkpoints.settings.upload_dir", tmp_path)
    job_id = uuid.uuid4()
    checkpoint = JobCheckpoint(
        stored_filename="book.epub",
        original_title="Atomic Habits",
        translated_title=None,
        batch_size=16,
        total_segments=1,
        total_batches=1,
        segments=[
            Segment(
                item_id="item-1",
                order_in_item=0,
                original_text="Hello",
                placeholder_map={},
                content_kind="body",
            )
        ],
        translated_texts=["Zdravo"],
    )

    save_checkpoint(job_id, checkpoint)
    loaded = load_checkpoint(job_id)

    assert loaded.stored_filename == checkpoint.stored_filename
    assert loaded.original_title == checkpoint.original_title
    assert loaded.translated_texts == checkpoint.translated_texts
    assert loaded.segments[0].placeholder_map == checkpoint.segments[0].placeholder_map

    delete_checkpoint(job_id)

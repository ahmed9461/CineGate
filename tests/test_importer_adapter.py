from types import SimpleNamespace

from telethon.tl.types import PeerChannel

from cinegate.domain.archive import MediaKind
from cinegate.importer.adapter import (
    forwarded_source_message_id,
    is_importable_message,
    telethon_message_to_archive,
)

SOURCE_ID = -1001234567890
OTHER_SOURCE_ID = -1009876543210


def fake_message(
    *,
    message_id: int = 10,
    photo=None,
    video=None,
    document=None,
    raw_text: str = "caption",
    fwd_from=None,
):
    return SimpleNamespace(
        id=message_id,
        photo=photo,
        video=video,
        document=document,
        raw_text=raw_text,
        fwd_from=fwd_from,
        forward=None,
    )


def test_adapter_maps_media_without_downloading() -> None:
    photo = telethon_message_to_archive(
        fake_message(photo=object())
    )
    video = telethon_message_to_archive(
        fake_message(video=object())
    )
    document = telethon_message_to_archive(
        fake_message(
            document=SimpleNamespace(mime_type="video/mp4"),
        )
    )
    other = telethon_message_to_archive(
        fake_message(
            document=SimpleNamespace(mime_type="application/pdf"),
        )
    )

    assert photo.media_kind is MediaKind.PHOTO
    assert video.media_kind is MediaKind.VIDEO
    assert document.media_kind is MediaKind.DOCUMENT
    assert other.media_kind is MediaKind.OTHER
    assert photo.caption == "caption"


def test_nonpositive_message_id_is_not_importable() -> None:
    assert is_importable_message(fake_message(message_id=1))
    assert not is_importable_message(fake_message(message_id=0))


def test_forward_metadata_recovers_source_channel_post_id() -> None:
    message = fake_message(
        message_id=500,
        fwd_from=SimpleNamespace(
            channel_post=42,
            from_id=PeerChannel(channel_id=1234567890),
        ),
    )

    assert forwarded_source_message_id(
        message,
        expected_source_channel_id=SOURCE_ID,
    ) == 42


def test_unrelated_archive_forward_is_ignored() -> None:
    message = fake_message(
        message_id=500,
        fwd_from=SimpleNamespace(
            channel_post=42,
            from_id=PeerChannel(channel_id=9876543210),
        ),
    )

    assert (
        forwarded_source_message_id(
            message,
            expected_source_channel_id=SOURCE_ID,
        )
        is None
    )


def test_forward_without_original_channel_post_is_ignored() -> None:
    message = fake_message(
        message_id=500,
        fwd_from=SimpleNamespace(
            channel_post=None,
            from_id=PeerChannel(channel_id=1234567890),
        ),
    )

    assert (
        forwarded_source_message_id(
            message,
            expected_source_channel_id=SOURCE_ID,
        )
        is None
    )

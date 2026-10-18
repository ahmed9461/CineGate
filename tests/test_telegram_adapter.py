from types import SimpleNamespace

from cinegate.bot.adapters import telegram_message_to_archive
from cinegate.domain.archive import MediaKind


def fake_message(
    *,
    photo=None,
    video=None,
    document=None,
    caption="caption",
):
    return SimpleNamespace(
        message_id=10,
        photo=photo,
        video=video,
        document=document,
        text=None,
        edit_date=None,
        caption=caption,
    )


def test_photo_maps_without_downloading_media() -> None:
    result = telegram_message_to_archive(fake_message(photo=[object()]))
    assert result.media_kind is MediaKind.PHOTO
    assert result.caption == "caption"


def test_video_maps_to_video() -> None:
    result = telegram_message_to_archive(fake_message(video=object()))
    assert result.media_kind is MediaKind.VIDEO


def test_video_document_maps_to_document() -> None:
    document = SimpleNamespace(mime_type="video/mp4")
    result = telegram_message_to_archive(fake_message(document=document))
    assert result.media_kind is MediaKind.DOCUMENT


def test_non_video_document_maps_to_other() -> None:
    document = SimpleNamespace(mime_type="application/pdf")
    result = telegram_message_to_archive(fake_message(document=document))
    assert result.media_kind is MediaKind.OTHER


def test_text_and_edit_version_are_preserved():
    from datetime import UTC, datetime

    message = fake_message(caption=None)
    message.text = "sequence interruption"
    message.edit_date = datetime(2026, 10, 15, tzinfo=UTC)
    result = telegram_message_to_archive(message)
    assert result.caption == message.text
    assert result.edited_at == message.edit_date

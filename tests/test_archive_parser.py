import pytest

from cinegate.domain.archive import ArchiveMessage, GroupStatus, MediaKind, ParserStyle
from cinegate.services.archive_parser import ArchiveParser


def photo(message_id: int, caption: str) -> ArchiveMessage:
    return ArchiveMessage(message_id, MediaKind.PHOTO, caption)


def video(message_id: int, caption: str) -> ArchiveMessage:
    return ArchiveMessage(message_id, MediaKind.VIDEO, caption)


def other(message_id: int, caption: str = "noise") -> ArchiveMessage:
    return ArchiveMessage(message_id, MediaKind.OTHER, caption)


def modern_poster(
    message_id: int = 100,
    *,
    title: str = "Irish Ashes",
    year: int = 2025,
) -> ArchiveMessage:
    return photo(
        message_id,
        (
            f"الفيلم: {title}\n"
            "التصنيف: اكشن #جريمة\n"
            "البلد: المملكة المتحدة\n"
            "اللغة: الإنجليزية\n"
            "الترجمة: العربية\n"
            f"السنة: {year}\n"
            "التقييم: 7/10\n"
            "القصة: قصة تجريبية"
        ),
    )


def test_modern_poster_with_multiple_qualities() -> None:
    parser = ArchiveParser()
    groups = parser.parse(
        [
            modern_poster(),
            video(101, "Irish Ashes 2025 #480p"),
            video(102, "Irish Ashes 2025 #720p"),
            video(103, "Irish Ashes 2025 #1080p"),
        ]
    )

    assert len(groups) == 1
    group = groups[0]
    assert group.status is GroupStatus.INDEXED
    assert group.parser_style is ParserStyle.MODERN
    assert group.display_title == "Irish Ashes"
    assert group.year == 2025
    assert [item.quality for item in group.qualities] == ["480p", "720p", "1080p"]


@pytest.mark.parametrize("label", ["فيلم", "فلم", "الفيلم", "الفلم"])
def test_legacy_title_label_variants(label: str) -> None:
    parser = ArchiveParser()
    groups = parser.parse(
        [
            photo(
                200,
                (
                    "#طلب_المتابعين\n"
                    f"{label}: The twon 2010\n"
                    "النوع: جريمة، اثارة، دراما\n"
                    "اللغة: الإنجليزية\n"
                    "القصة: قصة قديمة"
                ),
            ),
            video(
                201,
                "فلم: The twon 2010\nالجودة: 720p\n-@Shahedv_bot",
            ),
        ]
    )

    assert len(groups) == 1
    assert groups[0].status is GroupStatus.INDEXED
    assert groups[0].parser_style is ParserStyle.LEGACY
    assert groups[0].display_title == "The twon"
    assert groups[0].year == 2010
    assert groups[0].qualities[0].quality == "720p"


def test_legacy_does_not_require_follower_hashtag() -> None:
    parser = ArchiveParser()
    groups = parser.parse(
        [
            photo(
                210,
                "فلم: Godzilla 2014\nالنوع: اكشن\nاللغة: الإنجليزية\nالقصة: قصة",
            ),
            video(211, "فلم: Godzilla 2014\nالجودة: 720p\n@Shahedv_bot"),
        ]
    )
    assert groups[0].status is GroupStatus.INDEXED


def test_orphan_poster_is_not_indexed() -> None:
    group = ArchiveParser().parse([modern_poster()])[0]
    assert group.status is GroupStatus.ORPHAN
    assert not group.qualities


def test_quality_without_poster_is_ignored() -> None:
    assert ArchiveParser().parse([video(50, "Unknown 2025 #720p")]) == ()


def test_ampersand_and_word_do_not_break_grouping() -> None:
    group = ArchiveParser().parse(
        [
            modern_poster(title="Fast & Furious", year=2011),
            video(101, "Fast and Furious 2011 #720p"),
        ]
    )[0]
    assert group.status is GroupStatus.INDEXED
    assert group.normalized_title == "fast and furious"
    assert group.qualities[0].normalized_title == "fast and furious"


def test_colon_difference_does_not_break_grouping() -> None:
    group = ArchiveParser().parse(
        [
            modern_poster(title="Batman: Begins", year=2005),
            video(101, "Batman Begins 2005 #1080p"),
        ]
    )[0]
    assert group.status is GroupStatus.INDEXED


def test_cross_language_title_can_group_by_sequence() -> None:
    group = ArchiveParser().parse(
        [
            modern_poster(title="La sociedad de la nieve", year=2023),
            video(101, "Society of the Snow 2023 #720p"),
        ]
    )[0]
    assert group.status is GroupStatus.INDEXED
    assert group.qualities[0].quality == "720p"


def test_conflicting_year_is_not_blindly_accepted() -> None:
    group = ArchiveParser().parse(
        [
            modern_poster(title="Example Film", year=2025),
            video(101, "Example Film 2024 #720p"),
        ]
    )[0]
    assert group.status is GroupStatus.AMBIGUOUS
    assert not group.qualities
    assert any(item.startswith("ambiguous_quality:101:") for item in group.diagnostics)


def test_duplicate_quality_keeps_newest_message() -> None:
    group = ArchiveParser().parse(
        [
            modern_poster(),
            video(101, "Irish Ashes 2025 #720p"),
            video(102, "Irish Ashes 2025 #720p"),
        ]
    )[0]

    assert len(group.qualities) == 1
    assert group.qualities[0].message_id == 102
    assert "duplicate_quality_replaced:720p:101->102" in group.diagnostics


def test_new_poster_closes_previous_group() -> None:
    groups = ArchiveParser().parse(
        [
            modern_poster(100, title="First", year=2024),
            video(101, "First 2024 #720p"),
            modern_poster(200, title="Second", year=2025),
            video(201, "Second 2025 #1080p"),
        ]
    )
    assert [group.display_title for group in groups] == ["First", "Second"]
    assert all(group.status is GroupStatus.INDEXED for group in groups)


def test_one_noise_message_is_tolerated() -> None:
    group = ArchiveParser(max_noise_messages=1).parse(
        [
            modern_poster(),
            other(101),
            video(102, "Irish Ashes 2025 #720p"),
        ]
    )[0]
    assert group.status is GroupStatus.INDEXED


def test_excess_noise_closes_group_before_late_quality() -> None:
    groups = ArchiveParser(max_noise_messages=1).parse(
        [
            modern_poster(),
            other(101),
            other(102),
            video(103, "Irish Ashes 2025 #720p"),
        ]
    )
    assert len(groups) == 1
    assert groups[0].status is GroupStatus.ORPHAN


def test_repeated_parse_is_deterministic() -> None:
    messages = [
        modern_poster(),
        video(101, "Irish Ashes 2025 #480p"),
        video(102, "Irish Ashes 2025 #720p"),
    ]
    parser = ArchiveParser()
    assert parser.parse(messages) == parser.parse(messages)


def test_bulleted_modern_field_labels_are_supported() -> None:
    groups = ArchiveParser().parse(
        [
            photo(
                300,
                (
                    "-الفيلم: Bullet Style Movie\n"
                    "-التصنيف: دراما\n"
                    "-اللغة: الإنجليزية\n"
                    "-السنة: 2024\n"
                    "-القصة: قصة"
                ),
            ),
            video(301, "Bullet Style Movie 2024 #720p"),
        ]
    )

    assert len(groups) == 1
    assert groups[0].status is GroupStatus.INDEXED
    assert groups[0].display_title == "Bullet Style Movie"


def test_out_of_order_messages_are_rejected_instead_of_sorted_in_memory() -> None:
    parser = ArchiveParser()
    with pytest.raises(ValueError, match="ordered by ascending message_id"):
        parser.parse(
            [
                modern_poster(200, title="Later", year=2025),
                video(199, "Later 2025 #720p"),
            ]
        )


def test_legacy_alfilm_without_follower_hashtag_is_classified_legacy() -> None:
    group = ArchiveParser().parse(
        [
            photo(
                400,
                "الفيلم: Old Format 2018\nالنوع: دراما\nاللغة: الإنجليزية\nالقصة: قصة",
            ),
            video(401, "Old Format 2018 #720p"),
        ]
    )[0]

    assert group.status is GroupStatus.INDEXED
    assert group.parser_style is ParserStyle.LEGACY

from cinegate.db.base import Base
from cinegate.db.models import (
    AppSetting,
    MessageTemplate,
    Movie,
    MovieQuality,
    UserSearchSession,
)


def test_expected_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {
        "app_settings",
        "message_templates",
        "movie_qualities",
        "movies",
        "user_search_sessions",
    }


def test_model_classes_import() -> None:
    assert Movie.__tablename__ == "movies"
    assert MovieQuality.__tablename__ == "movie_qualities"
    assert AppSetting.__tablename__ == "app_settings"
    assert MessageTemplate.__tablename__ == "message_templates"
    assert UserSearchSession.__tablename__ == "user_search_sessions"

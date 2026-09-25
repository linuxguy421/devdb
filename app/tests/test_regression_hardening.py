import ast
from pathlib import Path

from sqlalchemy import BigInteger

from app.models import MediaItem
from app.services.tv_seasons import _season_summary_from_tmdb


ROOT = Path(__file__).resolve().parents[2]


def test_media_financial_columns_are_bigint():
    assert isinstance(MediaItem.__table__.c.budget.type, BigInteger)
    assert isinstance(MediaItem.__table__.c.revenue.type, BigInteger)


def test_tv_season_summary_normalizes_episode_count():
    summary = _season_summary_from_tmdb({
        "season_number": "1",
        "name": "Season 1",
        "episode_count": "9",
    })

    assert summary == {
        "season_number": 1,
        "name": "Season 1",
        "overview": None,
        "poster_path": None,
        "air_date": None,
        "episode_count": 9,
    }


def test_tv_season_summary_rejects_invalid_season_numbers():
    assert _season_summary_from_tmdb({"season_number": "not-a-number"}) is None
    assert _season_summary_from_tmdb({"season_number": -1}) is None


def test_migration_chain_has_one_head():
    revisions = {}
    versions_dir = ROOT / "alembic" / "versions"

    for path in versions_dir.glob("*.py"):
        tree = ast.parse(path.read_text())
        values = {}
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in {"revision", "down_revision"}
            ):
                values[node.targets[0].id] = ast.literal_eval(node.value)
        if "revision" in values:
            revisions[values["revision"]] = values.get("down_revision")

    referenced = {
        parent
        for parent in revisions.values()
        if isinstance(parent, str)
    }
    heads = set(revisions) - referenced

    assert heads == {"d8e5f0a1b2c3"}


def test_financial_migration_is_chained_from_dossier_migration():
    migration = ROOT / "alembic" / "versions" / "d8e5f0a1b2c3_widen_media_financial_metadata.py"
    text = migration.read_text()

    assert 'revision = "d8e5f0a1b2c3"' in text
    assert 'down_revision = "c7d4e91f2a63"' in text
    assert "ALTER COLUMN budget TYPE BIGINT" in text
    assert "ALTER COLUMN revenue TYPE BIGINT" in text

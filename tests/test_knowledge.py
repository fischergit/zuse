from zuse.knowledge import KnowledgeStore


def test_add_deduplicates_near_duplicates_and_tracks_uses(tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge.jsonl")

    first = store.add("preference", "Prefers communication in German.")
    duplicate = store.add("preference", "Prefers communication in German.")

    assert first is not None
    assert duplicate is None
    assert len(store.entries) == 1
    assert store.entries[0].uses == 1


def test_recall_prefers_matching_preferences_and_persists_use_count(tmp_path):
    path = tmp_path / "knowledge.jsonl"
    store = KnowledgeStore(path)
    store.add("preference", "Prefers communication in German.")
    store.add("fact", "Uses Docker on macOS.")

    hits = store.recall("communication German", k=2)

    assert [entry.text for entry in hits] == ["Prefers communication in German."]
    reloaded = KnowledgeStore(path)
    assert reloaded.entries[0].uses == 1


def test_invalid_kind_falls_back_to_fact(tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge.jsonl")

    entry = store.add("unknown", "Zuse runs in a terminal.")

    assert entry is not None
    assert entry.kind == "fact"

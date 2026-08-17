from backend import cache_metrics


def test_snapshot_omits_caches_with_no_activity() -> None:
    assert "Unused test cache" not in cache_metrics.snapshot()


def test_record_hit_and_miss_are_counted_per_cache() -> None:
    name = "Test cache A"
    cache_metrics.record_hit(name)
    cache_metrics.record_hit(name)
    cache_metrics.record_miss(name)

    result = cache_metrics.snapshot()[name]

    assert result == {"hits": 2, "misses": 1}


def test_different_caches_are_counted_independently() -> None:
    cache_metrics.record_hit("Test cache B")
    cache_metrics.record_miss("Test cache C")

    snapshot = cache_metrics.snapshot()

    assert snapshot["Test cache B"] == {"hits": 1, "misses": 0}
    assert snapshot["Test cache C"] == {"hits": 0, "misses": 1}

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_youtube_profile_card_requires_real_account_details() -> None:
    script = (ROOT / "frontend/youtube-account.js").read_text(encoding="utf-8")

    assert "const hasAccountDetails = Boolean(accountName || accountHandle);" in script
    assert (
        "profile.classList.toggle('hidden', !connected || !hasAccountDetails);"
        in script
    )
    assert "if (!connected || !hasAccountDetails)" in script
    assert "name.textContent = '';" in script
    assert "handle.textContent = '';" in script
    assert "handle.classList.add('hidden');" in script
    assert "const displayedName = accountName || accountHandle;" in script
    assert "handle.classList.toggle('hidden', !displayedHandle);" in script

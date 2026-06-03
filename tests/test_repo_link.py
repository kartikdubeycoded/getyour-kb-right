from app.models import Reel
from app.repo_link import find_repo


def test_finds_repo_in_caption():
    reel = Reel(url="x", caption="great tool: https://github.com/openai/whisper check it")
    assert find_repo(reel) == ("openai/whisper", "https://github.com/openai/whisper")


def test_finds_repo_across_fields_caption_wins_first():
    reel = Reel(url="x", transcript="see github.com/langchain-ai/langchain for more")
    assert find_repo(reel) == (
        "langchain-ai/langchain",
        "https://github.com/langchain-ai/langchain",
    )


def test_strips_trailing_punctuation_and_git_suffix():
    reel = Reel(url="x", visual="clone github.com/foo/bar.git.")
    assert find_repo(reel) == ("foo/bar", "https://github.com/foo/bar")


def test_ignores_non_repo_paths():
    reel = Reel(url="x", caption="visit github.com/topics/python for topics")
    assert find_repo(reel) is None


def test_returns_none_when_no_repo():
    reel = Reel(url="x", caption="just a cooking reel", transcript="add salt")
    assert find_repo(reel) is None

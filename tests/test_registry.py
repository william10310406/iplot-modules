import copy
import unicodedata
from datetime import UTC, datetime, timedelta

import pytest
import registry
from registry import (
    AT,
    DEFAULT_IGNORABLE,
    MAX_MODULES,
    MAX_NAMES,
    MAX_PER_DAY,
    DuplicateKey,
    Version,
    bump,
    check_name,
    invisible,
    key,
    limit_refusal,
    modules_size,
    nfc,
    owner_refusal,
    read_json_strict,
    record,
    version_for,
    write_json,
)
from say import SAY, Refusal, code

RA = 1
ME = 222
NOW = datetime(2026, 10, 21, 12, 0, 0, tzinfo=UTC)


def make_registry() -> dict:
    reg = {}
    for name in ("作業系統", "更新", "工作坊"):
        reg[key(name)] = {"name": name, "reserved": True}
    for name in ("開工", "開Terminal"):
        reg[key(name)] = {"name": name, "owner_id": RA, "owner": "research-assistant"}
    reg[key("整理桌面")] = {"name": "整理桌面", "owner_id": 111, "owner": "someone", "version": "0.0.1",
                          "notes": "", "issue": 5, "updated": "2026-10-01"}
    return reg


REG = make_registry()


def test_key_is_nfc_casefold():
    assert key("Foo") == key("FOO") == "foo"
    assert key(unicodedata.normalize("NFD", "ガイド")) == "ガイド"
    assert key("\uf901新") == "更新"


def test_first_upload_takes_the_name():
    reg = make_registry()
    assert owner_refusal("新東西", ME, reg) is None
    record(reg, "新東西", ME, "me", "0.0.1", "", 7, "2026-10-21")
    assert reg[key("新東西")] == {"name": "新東西", "owner_id": ME, "owner": "me", "version": "0.0.1",
                                 "notes": "", "issue": 7, "updated": "2026-10-21"}


def test_same_id_updates():
    reg = make_registry()
    assert owner_refusal("整理桌面", 111, reg) is None
    record(reg, "整理桌面", 111, "someone", "0.0.2", "n", 9, "2026-10-21")
    entry = reg[key("整理桌面")]
    assert entry["version"] == "0.0.2" and entry["owner_id"] == 111


def test_other_id_is_refused_without_at():
    refusal = owner_refusal("整理桌面", ME, REG)
    assert refusal.key == "taken"
    assert code("someone") in refusal.text and "@someone" not in refusal.text


@pytest.mark.parametrize("a, b", [("Foo", "FOO"),
                                  (unicodedata.normalize("NFC", "ガイド"), unicodedata.normalize("NFD", "ガイド")),
                                  ("更新", "\uf901新")])
def test_case_nfd_and_compat_ideograph_share_one_key(a, b):
    assert key(a) == key(b)


def test_nfd_and_compat_spellings_are_stored_as_nfc():
    assert nfc("\uf901新") == "更新"
    assert owner_refusal(nfc("\uf901新"), ME, REG).key == "reserved"
    reg = make_registry()
    nfd = unicodedata.normalize("NFD", "ガイド")
    record(reg, nfc(nfd), ME, "me", "0.0.1", "", 1, "2026-10-21")
    assert reg[key(nfd)]["name"] == unicodedata.normalize("NFC", "ガイド")


def test_case_only_difference_is_refused_for_the_owner():
    reg = make_registry()
    record(reg, "Foo", ME, "me", "0.0.1", "", 1, "2026-10-21")
    refusal = owner_refusal("foo", ME, reg)
    assert refusal.key == "case" and code("Foo") in refusal.text


def test_reserved_three_are_refused():
    for name in ("作業系統", "更新", "工作坊"):
        for uid in (ME, RA):
            assert owner_refusal(name, uid, REG).key == "reserved"


def test_seeded_name_is_refused_for_others():
    assert owner_refusal("開工", ME, REG).key == "taken"


def test_reserved_is_checked_before_owner():
    assert "owner_id" not in REG[key("更新")]
    assert owner_refusal("更新", ME, REG).key == "reserved"


def test_removed_is_refused_even_for_the_owner():
    reg = {key("舊的"): {"name": "舊的", "owner_id": 111, "removed": True}}
    assert owner_refusal("舊的", 111, reg).key == "removed"


def test_update_keeps_warning_and_unknown_fields():
    reg = make_registry()
    reg[key("整理桌面")]["warning"] = "小心"
    reg[key("整理桌面")]["審查"] = {"by": "ra", "ok": [1, 2]}
    record(reg, "整理桌面", 111, "someone", "0.0.2", "n", 9, "2026-10-21")
    assert reg[key("整理桌面")]["warning"] == "小心"
    assert reg[key("整理桌面")]["審查"] == {"by": "ra", "ok": [1, 2]}


def test_bot_writes_only_its_own_fields():
    reg = make_registry()
    reg[key("整理桌面")]["warning"] = "小心"
    before = copy.deepcopy(reg[key("整理桌面")])
    record(reg, "整理桌面", 111, "renamed", "0.0.2", "n", 9, "2026-10-21")
    after = reg[key("整理桌面")]
    changed = {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)}
    assert changed == {"owner", "version", "notes", "issue", "updated"}


@pytest.mark.parametrize("name, kind", [
    ("開工\u200b", "invisible"), ("開工\u202e", "invisible"), ("開工\ufe0f", "invisible"),
    ("開工\u3164", "invisible"), ("更\u00a0新", "invisible"), ("更新\u3000", "invisible"),
    ("更\u2800新", "invisible"), (" 開工", "invisible"), ("開\u0422erminal", "invisible"),
    ("開\uff34\uff45\uff52\uff4d\uff49\uff4e\uff41\uff4c", "similar"), ("更 新", "similar"), ("整理 桌面", "similar"),
    ("\uff23\uff2f\uff2e\uff34\uff25\uff38\uff34工具", None)])
def test_lookalikes_are_refused(name, kind):
    refusal = check_name(name, ME, REG)
    assert (refusal.key if refusal else None) == kind


def test_lookalikes_of_your_own_names_are_fine():
    assert check_name("整理 桌面", 111, REG) is None


def test_similar_names_the_other():
    refusal = check_name("更 新", ME, REG)
    assert isinstance(refusal, Refusal) and code("更新") in refusal.text


def test_unbumpable_current_version_is_bad_version(tmp_path):
    refusal = version_for({"version": "x"}, set(), tmp_path, "")
    assert isinstance(refusal, Refusal) and refusal.key == "bad_version"


def test_bad_name_is_refused():
    assert check_name("a/b", ME, REG).key == "bad_name"


def test_cyrillic_only_and_latin_only_names_are_fine():
    assert check_name("\u0422\u0435\u0441\u0442", ME, REG) is None
    assert check_name("Test", ME, REG) is None


def test_private_use_and_unassigned_are_refused():
    assert check_name("a\ue000", ME, REG).key == "invisible"
    assert check_name("a\u0378", ME, REG).key == "invisible"


def test_default_ignorable_table_covers_the_known_characters():
    for c in ("\u00ad\u034f\u061c\u115f\u1160\u17b4\u180e\u200b\u200d\u200f\u202a\u202e\u2060\u2066\u3164"
              "\ufe00\ufe0f\ufeff\uffa0\U0001d173\U000e0001\U000e0100"):
        assert invisible("a" + c), hex(ord(c))
    previous_end = -1
    for lo, hi in DEFAULT_IGNORABLE:
        assert lo <= hi <= 0x10FFFF
        assert lo > previous_end
        previous_end = hi


def test_read_json_strict_stops_on_duplicate_keys(tmp_path):
    path = tmp_path / "r.json"
    path.write_text('{"a": 1, "a": 2}', encoding="utf-8")
    with pytest.raises(DuplicateKey):
        read_json_strict(path)
    path.write_text("[1]", encoding="utf-8")
    with pytest.raises(ValueError):
        read_json_strict(path)
    data = {"z": "中文", "a": {"b": 1}}
    write_json(path, data)
    text = path.read_text(encoding="utf-8")
    assert read_json_strict(path) == data
    assert text.endswith("}\n") and not text.endswith("\n\n")
    assert "中文" in text and "\\u" not in text
    assert text.index('"z"') < text.index('"a"')


def changelog(tmp_path, text, raw=False):
    folder = tmp_path / "mod"
    folder.mkdir(exist_ok=True)
    (folder / "CHANGELOG.md").write_bytes(text if raw else text.encode("utf-8"))
    return folder


def test_no_changelog_bumps_the_last_segment(tmp_path):
    first = version_for(None, set(), tmp_path, "表單")
    assert first.version == "0.0.1" and first.notes == "表單"
    assert version_for({"version": "0.1.1"}, set(), tmp_path, "").version == "0.1.2"
    assert "模組裡沒有 CHANGELOG.md\uff1a版本自動往上加。" in first.remarks
    assert bump("0.1.1") == "0.1.2"


def test_changelog_version_must_be_newer(tmp_path):
    folder = changelog(tmp_path, "## [1.0.0]\n\nx\n")
    refusal = version_for({"version": "1.0.0"}, {"CHANGELOG.md"}, folder, "")
    assert refusal.key == "not_newer"
    folder = changelog(tmp_path, "## [1.0.1]\n\nx\n")
    result = version_for({"version": "1.0.0"}, {"CHANGELOG.md"}, folder, "")
    assert isinstance(result, Version) and result.version == "1.0.1"


def test_seed_without_version_counts_as_first(tmp_path):
    seed = {"name": "開工", "owner_id": RA, "owner": "x"}
    folder = changelog(tmp_path, "## [0.3.0]\n\nx\n")
    assert version_for(seed, {"CHANGELOG.md"}, folder, "").version == "0.3.0"
    assert version_for(seed, set(), tmp_path, "").version == "0.0.1"


def test_full_width_and_leading_zero_tricks_are_refused(tmp_path):
    folder = changelog(tmp_path, "## [\uff11.\uff10.\uff10]\n\nx\n")
    assert version_for(None, {"CHANGELOG.md"}, folder, "").key == "bad_version"
    folder = changelog(tmp_path, "## [1.01]\n\nx\n")
    assert version_for({"version": "1.1"}, {"CHANGELOG.md"}, folder, "").key == "not_newer"


def test_too_long_versions_are_refused(tmp_path):
    for v in ("1234567890.0", ".".join(["1"] * 11)):
        folder = changelog(tmp_path, f"## [{v}]\n\nx\n")
        assert version_for(None, {"CHANGELOG.md"}, folder, "").key == "bad_version"


@pytest.mark.parametrize("log", ["整理".encode("big5"), "沒有任何一節", "## [v1.0.0]"])
def test_unreadable_changelogs_use_the_latest_sentence(tmp_path, log):
    folder = changelog(tmp_path, log if isinstance(log, bytes) else log.encode(), raw=True)
    refusal = version_for(None, {"CHANGELOG.md"}, folder, "")
    assert isinstance(refusal, Refusal) and refusal.key == "changelog"
    assert SAY["changelog"].split("{")[0] in refusal.text


def test_notes_are_clipped_to_1000(tmp_path):
    folder = changelog(tmp_path, "## [1.0.0]\n\n" + "a" * 60_000_000)
    result = version_for(None, {"CHANGELOG.md"}, folder, "")
    assert len(result.notes) == 1000 and result.notes.endswith("…")
    assert [r for r in result.remarks if "1000" in r] == ["這一版改了什麼超過 1000 字\uff0c只留前 1000 字。"]


def test_changelog_wins_over_the_form_notes(tmp_path):
    folder = changelog(tmp_path, "## [1.0.0]\n\n來自 CHANGELOG\n\n## [0.9.0]\n\nold\n")
    result = version_for(None, {"CHANGELOG.md"}, folder, "表單")
    assert result.notes == "來自 CHANGELOG"
    assert "模組裡有 CHANGELOG.md\uff1a這一版改了什麼照它寫\uff0c表單那一格沒有用到。" in result.remarks


def test_lowercase_changelog_md_is_not_the_changelog(tmp_path):
    folder = changelog(tmp_path, "## [5.0.0]\n\nx\n")
    result = version_for(None, {"changelog.md"}, folder, "表單")
    assert result.version == "0.0.1" and result.notes == "表單"


def received_of(count, at, uid=ME):
    return {str(i): {"name": "x", "version": "1", "owner_id": uid, "at": at.strftime(AT)} for i in range(count)}


def test_eleventh_upload_in_24_hours_is_refused():
    received = received_of(MAX_PER_DAY, NOW - timedelta(hours=23, minutes=59))
    refusal = limit_refusal(ME, False, 1, REG, received, 0, NOW)
    assert refusal.key == "too_many_uploads" and "10 份" in refusal.text


def test_uploads_older_than_24_hours_do_not_count():
    received = received_of(MAX_PER_DAY, NOW - timedelta(hours=24))
    assert limit_refusal(ME, False, 1, REG, received, 0, NOW) is None
    received = received_of(MAX_PER_DAY, NOW - timedelta(days=3))
    assert limit_refusal(ME, False, 1, REG, received, 0, NOW) is None


def test_other_accounts_uploads_do_not_count():
    received = received_of(MAX_PER_DAY, NOW, uid=111)
    assert limit_refusal(ME, False, 1, REG, received, 0, NOW) is None


def test_twenty_first_name_is_refused_but_updates_pass():
    reg = {key(f"n{i}"): {"name": f"n{i}", "owner_id": ME, "owner": "me"} for i in range(MAX_NAMES)}
    refusal = limit_refusal(ME, True, 1, reg, {}, 0, NOW)
    assert refusal.key == "too_many_names" and "20 個" in refusal.text
    assert limit_refusal(ME, False, 1, reg, {}, 0, NOW) is None


def test_space_limit_blocks_new_names_only():
    used = MAX_MODULES - 10
    assert limit_refusal(ME, True, 11, REG, {}, used, NOW).key == "full"
    assert limit_refusal(ME, False, 11, REG, {}, used, NOW) is None
    assert limit_refusal(ME, True, 10, REG, {}, used, NOW) is None


def test_modules_size_counts_files_only(tmp_path):
    (tmp_path / "modules" / "a").mkdir(parents=True)
    (tmp_path / "modules" / "b").mkdir()
    (tmp_path / "modules" / "empty").mkdir()
    (tmp_path / "modules" / "a" / "x").write_bytes(b"abc")
    (tmp_path / "modules" / "b" / "y").write_bytes(b"12345")
    big = tmp_path / "big"
    big.write_bytes(b"0" * 10_000)
    (tmp_path / "modules" / "link").symlink_to(big)
    assert modules_size(tmp_path) == 8
    assert modules_size(tmp_path / "nowhere") == 0


def test_constants():
    assert registry.MAX_NOTES == 1000 and registry.MAX_MODULES == 800 * 1024 * 1024

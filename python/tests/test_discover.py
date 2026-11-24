"""Local agent discovery: finds candidates, exposes nothing until the user picks."""

import json

from elci import cli
from elci.discover import find_local_agents
from elci.home import Home


def fake_machine(tmp_path):
    home = tmp_path / "user"
    jarvy, devby = tmp_path / "Jarvy", tmp_path / "devbyarda"
    for folder, line in [(jarvy, "# Jarvy: private coordinator"), (devby, "# devbyarda content agent")]:
        folder.mkdir(parents=True)
        (folder / "CLAUDE.md").write_text(line + "\n\nmore", encoding="utf-8")
    (devby / ".claude" / "agents").mkdir(parents=True)
    (devby / ".claude" / "agents" / "editor.md").write_text(
        "---\nname: Video Editor\ndescription: cuts reels\n---\nbody", encoding="utf-8")
    (home / ".claude" / "agents").mkdir(parents=True)
    (home / ".claude" / "agents" / "researcher.md").write_text("no frontmatter", encoding="utf-8")
    (home / ".claude.json").write_text(json.dumps({"projects": {
        str(jarvy): {}, str(devby): {}, str(tmp_path / "gone"): {}}}), encoding="utf-8")
    return home, jarvy, devby


def test_finds_projects_and_subagents(tmp_path):
    home, jarvy, devby = fake_machine(tmp_path)
    found = {c.name: c for c in find_local_agents(home)}
    assert set(found) == {"jarvy", "devbyarda", "video-editor", "researcher"}
    assert found["jarvy"].description == "Jarvy: private coordinator"
    assert found["devbyarda"].kind == "claude-code-project"
    assert found["devbyarda"].mcp_command == f'cd "{devby}" && claude mcp add elci -e ELCI_AGENT=devbyarda -- elci-mcp'
    assert found["video-editor"].description == "cuts reels (in devbyarda)"


def test_nothing_on_a_fresh_machine(tmp_path):
    assert find_local_agents(tmp_path) == []


def test_init_shows_agents_and_exposes_only_the_picked_one(tmp_path, monkeypatch, capsys):
    home, jarvy, devby = fake_machine(tmp_path)
    monkeypatch.setattr(cli, "find_local_agents", lambda: find_local_agents(home))
    monkeypatch.setenv("ELCI_PASSPHRASE", "pw")
    order = [c.name for c in find_local_agents(home)]
    answers = iter([str(order.index("devbyarda") + 1), "", "collaboration, content"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    target = tmp_path / "elci-home"
    assert cli.main(["--home", str(target), "init", "--name", "Arda", "--domain", "arda.example"]) == 0
    out = capsys.readouterr().out
    assert "jarvy" in out and "Nothing is public until you pick it" in out
    card = Home(target).card()
    assert [a.name for a in card.agents] == ["devbyarda"]
    assert card.agents[0].topics == ("collaboration", "content")
    assert f'cd "{devby}" && claude mcp add elci -e ELCI_AGENT=devbyarda -- elci-mcp' in out


def test_add_and_remove_agents(tmp_path, monkeypatch):
    monkeypatch.setenv("ELCI_PASSPHRASE", "")
    h = tmp_path / "h"
    cli.main(["--home", str(h), "init", "--name", "A", "--domain", "a.example", "--agent", "one:scheduling"])
    assert cli.main(["--home", str(h), "add", "two:collaboration"]) == 0
    assert {a.name for a in Home(h).card().agents} == {"one", "two"}
    jti = next(d["jti"] for d in Home(h).delegations() if d["agent"] == "two")
    assert cli.main(["--home", str(h), "remove", "two"]) == 0
    card = Home(h).card()
    assert [a.name for a in card.agents] == ["one"] and jti in card.revoked

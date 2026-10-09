import os
import subprocess
import sys
from pathlib import Path

import pytest

from cli import main

ROOT = Path(__file__).resolve().parent.parent


def run_cli(capsys, *argv):
    """Lance la CLI en direct et retourne (code de sortie, sortie standard, erreurs)."""
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_default_scenario_shows_the_four_steps(capsys):
    code, out, _ = run_cli(capsys)

    print(out)
    assert code == 0
    for step in ("ÉTAPE 1/4", "ÉTAPE 2/4", "ÉTAPE 3/4", "ÉTAPE 4/4"):
        assert step in out
    assert "11 notifications sans fusion -> 5 émises (6 évitées)" in out
    assert "-> OK" in out


def test_single_change_shows_who_is_impacted_and_who_is_spared(capsys):
    code, out, _ = run_cli(capsys, "--change", "0", "w1", "horaire", "15h")

    assert code == 0
    assert "à notifier (3/5) : Alice, Bruno, Chloe" in out
    assert "épargnés (2) : David, Emma" in out
    assert "atelier impacté : Atelier Dégustation" in out  # la cascade est visible


def test_merging_is_visible_in_the_output(capsys):
    code, out, _ = run_cli(
        capsys,
        "--change", "0", "w1", "horaire", "15h",
        "--change", "5", "w1", "horaire", "16h",
        "--change", "12", "w1", "salle", "B",
    )

    assert code == 0
    assert "9 notifications sans fusion -> 3 émises (6 évitées)" in out
    assert "horaire → 16h, salle → B" in out


def test_priority_is_visible_in_the_send_order(capsys):
    _, out, _ = run_cli(capsys)

    order = out.split("ÉTAPE 3/4")[1].split("ÉTAPE 4/4")[0]
    assert order.index("ANNULATION") < order.index("CHANGEMENT_HORAIRE")


def test_rate_limit_options_are_applied(capsys):
    code, out, _ = run_cli(
        capsys, "--change", "0", "w1", "horaire", "15h", "--window", "0", "--limit", "1"
    )

    assert code == 0
    assert "limite 1 par 1s" in out
    assert "Maximum observé sur une fenêtre : 1 (limite 1)" in out


def test_list_shows_workshops_and_participants(capsys):
    code, out, _ = run_cli(capsys, "--list")

    assert code == 0
    assert "w1" in out and "Atelier Cuisine" in out and "Alice" in out


def test_help_describes_usage_and_exits_cleanly(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    assert exit_info.value.code == 0
    assert "Exemples" in capsys.readouterr().out


@pytest.mark.parametrize("argv, expected_message", [
    (["--change", "0", "inconnu", "horaire", "15h"], "atelier inconnu"),
    (["--change", "abc", "w1", "horaire", "15h"], "l'heure doit être un nombre"),
    (["--change", "-5", "w1", "horaire", "15h"], "ne peut pas être négative"),
    (["--change", "0", "w1", "horaire", "15h", "--window", "-5"], "window_seconds"),
    (["--change", "0", "w1", "horaire", "15h", "--limit", "0"], "max_per_period"),
    (["--data", "n_existe_pas.json"], "fichier introuvable"),
])
def test_invalid_input_gives_a_clear_error_and_exit_code_2(capsys, argv, expected_message):
    code, out, err = run_cli(capsys, *argv)

    assert code == 2
    assert expected_message in err
    assert out == ""  # rien d'affiché sur la sortie normale : pas de demi-résultat


def test_unknown_workshop_error_lists_the_valid_ones(capsys):
    _, _, err = run_cli(capsys, "--change", "0", "inconnu", "horaire", "15h")

    assert "w1" in err and "w4" in err


def test_script_is_really_executable_from_the_command_line():
    """Lance cli.py comme le ferait un utilisateur : un vrai processus Python séparé."""
    completed = subprocess.run(
        [sys.executable, "cli.py", "--change", "0", "w1", "horaire", "15h"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0
    assert "ÉTAPE 4/4" in completed.stdout
    assert completed.stderr == ""

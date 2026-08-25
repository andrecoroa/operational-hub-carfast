from scripts.conventional_migration_gate import command_manifest, fingerprint, run_gate


def test_manifest_is_secret_free_and_stable():
    manifest = command_manifest()
    rendered = str(manifest).lower()
    assert "password" not in rendered
    assert "database_url" not in rendered
    assert manifest["future_green_db"] == "dpg-da6d4d2jnfac73e2cl40-a"
    assert manifest["rollback_green_db"] == "dpg-da5dj0e417fc73f3uakg-a"
    assert len(fingerprint(manifest)) == 64


def test_three_common_runs_watchdog_ack_and_atomic_rollback_pass():
    result = run_gate()
    assert result["status"] == "NO_GO"
    assert result["synthetic_only"] is True
    assert result["real_window_authorized_by_output"] is False
    assert len(result["runs"]) == 3
    assert result["gates"]["7"]["status"] == "SYNTHETIC_PASS"
    assert any(gate["status"] == "PENDING" for gate in result["gates"].values())
    assert all(run["watchdog_rc"] == 0 for run in result["runs"])
    assert all(run["bundle_ack"] for run in result["runs"])

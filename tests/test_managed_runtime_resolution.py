"""Managed runtime helpers remain importable; site-wide rules live in scripts."""

import pytest


@pytest.mark.parametrize("helper", ["find_node_executable", "iter_hermes_node_dirs", "with_hermes_node_path"])
def test_managed_node_helpers_exist(helper):
    import hermes_constants

    assert callable(getattr(hermes_constants, helper))


def test_managed_uv_helpers_exist():
    """Legacy updater fixture still imports the retirement shim's public names."""
    from hermes_cli import managed_uv

    assert callable(managed_uv.resolve_uv)
    assert callable(managed_uv.ensure_uv)

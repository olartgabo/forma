"""SYNTHETIC checks of when design settings may follow measurement updates (#149)."""

import json
import sqlite3

from test_plans import stand_inputs

from forma_api.design_context import DesignContext, ResolvedDesignContext
from forma_api.projects import Project
from forma_api.settings_lineage import Revision, history, settings_for

PROJECT = "project-lineage"


def project(revision, stocks):
    return Project(id=PROJECT, goal="SYNTHETIC", revision_id=revision, stocks=stocks)


def context():
    _, _, _, parameters, process, profiles = stand_inputs(PROJECT)
    return ResolvedDesignContext.from_context(
        DesignContext(
            project_id=PROJECT,
            inventory_revision_id="inventory-a",
            parameters=parameters,
            process=process,
            joint_profiles=profiles,
            kerf_mm=2,
            edge_margin_mm=4,
        )
    )


def missing():
    return ResolvedDesignContext.missing(
        "No server-configured design context for this project and inventory revision."
    )


def resolver(entries):
    return lambda project_id, revision: entries.get(revision, missing())


def chain():
    stocks = stand_inputs(PROJECT)[0]
    return stocks, (
        Revision("inventory-b", stocks, None),
        Revision("inventory-a", stocks, None),
    )


def test_settings_carry_only_from_a_valid_unbroken_chain():
    stocks, revisions = chain()
    current = project("inventory-b", stocks)
    carried = settings_for(
        current, revisions, resolver({"inventory-a": context()}), missing()
    )
    assert carried.source_revision_id == "inventory-a"
    assert carried.covered == {s.id for s in stocks}
    assert carried.resolved.fingerprint != context().fingerprint
    # Evidence objects are the reviewed ones, unchanged.
    assert carried.resolved.process == context().process
    # An invalid earlier entry is never carried.
    invalid = ResolvedDesignContext.missing("Invalid.", code="invalid_reference")
    assert (
        settings_for(
            current, revisions, resolver({"inventory-a": invalid}), missing()
        ).covered
        is None
    )
    # The current revision must head the saved history.
    assert (
        settings_for(
            project("inventory-z", stocks),
            revisions,
            resolver({"inventory-a": context()}),
            missing(),
        ).covered
        is None
    )
    # The revision's own settings win, with no notes.
    own = settings_for(current, revisions, resolver({}), context())
    assert own.covered is None and own.notes == ()


def test_an_unreadable_receipt_stops_the_history(tmp_path):
    stocks, _ = chain()
    with sqlite3.connect(tmp_path / "db") as connection:
        connection.execute(
            "CREATE TABLE requests (owner, scope, key, digest, response)"
        )

        def add(response):
            connection.execute(
                "INSERT INTO requests VALUES ('alice', ?, 'k', 'd', ?)",
                (PROJECT + ":inventory", response),
            )

        add(
            json.dumps(
                {"project": project("inventory-a", stocks).model_dump(mode="json")}
            )
        )
        add("{corrupt")
        add(
            json.dumps(
                {"project": project("inventory-c", stocks).model_dump(mode="json")}
            )
        )
        revisions = history(connection, "alice", project("inventory-c", stocks))
    assert [r.revision_id for r in revisions] == ["inventory-c"]

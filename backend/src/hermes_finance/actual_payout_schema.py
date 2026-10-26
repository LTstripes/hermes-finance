"""Frozen 0065 rebuild inputs for #711. No released migration is edited."""

import hashlib
import re

from sqlalchemy import event

TABLES = (
    "expected_cash_flows",
    "applied_payout_reconciliations",
    "broker_money_occurrence_owners",
)
ECF_MATERIAL = (
    "reporting_month_id",
    "archived_from_period",
    "account_id",
    "instrument_id",
    "flow_type",
    "expected_date",
    "gross_amount_kopecks",
    "expected_tax_amount_kopecks",
    "expected_net_amount_kopecks",
    "currency",
    "source",
    "source_as_of_date",
    "forecast_version",
    "is_confirmed",
    "is_approximate",
)
LINK_COLUMNS = (
    "id",
    "applied_payout_id",
    "expected_cash_flow_id",
    "counting_decision",
    "created_at",
    "archived_from_period",
    "investment_cash_flow_id",
    "applied_payout_revision_id",
    "money_proof_request_id",
    "accepted_request_id",
    "supersedes_id",
    "provider_event_key",
)
LIVE = "archived_from_period IS NULL AND retired_request_id IS NULL"
LEGACY_INDEX = (
    "CREATE UNIQUE INDEX uq_applied_payout_reconciliations_active_manual_flow "
    "ON applied_payout_reconciliations (expected_cash_flow_id) WHERE archived_from_period IS NULL"
)
LINK_CHECK = """(
    investment_cash_flow_id IS NULL
    AND applied_payout_id IS NOT NULL AND expected_cash_flow_id IS NOT NULL
    AND counting_decision IN ('keep_both', 'count_manual', 'count_provider')
    AND applied_payout_revision_id IS NULL AND money_proof_request_id IS NULL
    AND accepted_request_id IS NULL AND supersedes_id IS NULL AND provider_event_key IS NULL
) OR (
    investment_cash_flow_id IS NOT NULL
    AND (applied_payout_id IS NOT NULL OR expected_cash_flow_id IS NOT NULL)
    AND counting_decision = 'count_actual'
    AND money_proof_request_id IS NOT NULL AND accepted_request_id IS NOT NULL
    AND archived_from_period IS NULL
    AND ((applied_payout_id IS NULL AND applied_payout_revision_id IS NULL
          AND provider_event_key IS NULL)
         OR (applied_payout_id IS NOT NULL AND applied_payout_revision_id IS NOT NULL
             AND provider_event_key IS NOT NULL AND length(provider_event_key) = 64))
    AND (supersedes_id IS NULL OR supersedes_id != id)
)"""


def _old_tables():
    return {
        "expected_cash_flows": EXPECTED_CASH_FLOWS_0065,
        "applied_payout_reconciliations": APPLIED_PAYOUT_RECONCILIATIONS_0065,
        "broker_money_occurrence_owners": BROKER_MONEY_OCCURRENCE_OWNERS_0065,
    }


def _new_tables():
    old = _old_tables()
    ecf = old[TABLES[0]].replace(
        "id INTEGER NOT NULL,", "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,", 1
    )
    ecf = ecf.replace(
        "PRIMARY KEY (id),",
        """payout_link_revision INTEGER NOT NULL DEFAULT 0,
        CONSTRAINT ck_expected_cash_flows_payout_link_revision
        CHECK (typeof(payout_link_revision) = 'integer' AND payout_link_revision >= 0),""",
    )
    owner = old[TABLES[2]].replace("role = 'coupon'", "role IN ('coupon', 'dividend')")
    link = (
        """CREATE TABLE applied_payout_reconciliations (
        id INTEGER NOT NULL PRIMARY KEY,
        applied_payout_id INTEGER REFERENCES applied_provider_payouts(id)
            ON DELETE RESTRICT ON UPDATE NO ACTION,
        expected_cash_flow_id INTEGER REFERENCES expected_cash_flows(id)
            ON DELETE RESTRICT ON UPDATE NO ACTION,
        counting_decision VARCHAR(16) NOT NULL,
        created_at DATETIME NOT NULL,
        archived_from_period VARCHAR(7),
        investment_cash_flow_id INTEGER REFERENCES investment_cash_flows(id)
            ON DELETE RESTRICT ON UPDATE NO ACTION,
        applied_payout_revision_id INTEGER REFERENCES applied_payout_revisions(id)
            ON DELETE RESTRICT ON UPDATE NO ACTION,
        money_proof_request_id VARCHAR(64) REFERENCES broker_month_applies(request_id)
            ON DELETE RESTRICT ON UPDATE NO ACTION,
        accepted_request_id VARCHAR(64) REFERENCES broker_month_applies(request_id)
            ON DELETE RESTRICT ON UPDATE NO ACTION,
        retired_request_id VARCHAR(64) REFERENCES broker_month_applies(request_id)
            ON DELETE RESTRICT ON UPDATE NO ACTION,
        supersedes_id INTEGER REFERENCES applied_payout_reconciliations(id)
            ON DELETE RESTRICT ON UPDATE NO ACTION,
        provider_event_key VARCHAR(64),
        CONSTRAINT ck_applied_payout_reconciliations_decision CHECK (%s)
    )"""
        % LINK_CHECK
    )
    return dict(zip(TABLES, (ecf, link, owner), strict=True))


def index_sql():
    prefix = "uq_applied_payout_reconciliations_"
    indices = (
        ("payout", "applied_payout_id", f"{LIVE} AND applied_payout_id IS NOT NULL"),
        (
            "active_manual_flow",
            "expected_cash_flow_id",
            f"{LIVE} AND expected_cash_flow_id IS NOT NULL",
        ),
        (
            "active_actual_flow",
            "investment_cash_flow_id",
            f"{LIVE} AND investment_cash_flow_id IS NOT NULL",
        ),
        (
            "active_provider_event",
            "provider_event_key",
            f"{LIVE} AND provider_event_key IS NOT NULL",
        ),
        ("successor", "supersedes_id", "supersedes_id IS NOT NULL"),
        (
            "legacy_payout",
            "applied_payout_id",
            "investment_cash_flow_id IS NULL AND retired_request_id IS NULL",
        ),
        (
            "receipt_actual",
            "accepted_request_id, investment_cash_flow_id",
            "accepted_request_id IS NOT NULL",
        ),
    )
    result = [
        f"CREATE UNIQUE INDEX {prefix}{suffix} ON applied_payout_reconciliations ({columns}) WHERE {where}"
        for suffix, columns, where in indices
    ]
    result.extend(
        f"CREATE INDEX ix_applied_payout_reconciliations_{column} ON applied_payout_reconciliations ({column})"
        for column in (
            "money_proof_request_id",
            "accepted_request_id",
            "retired_request_id",
            "applied_payout_revision_id",
        )
    )
    return result


def guard_sql():
    material = " OR ".join(f"OLD.{column} IS NOT NEW.{column}" for column in ECF_MATERIAL)
    immutable = " AND ".join(f"OLD.{column} IS NEW.{column}" for column in LINK_COLUMNS)
    receipt_target = " AND ".join(
        f"json_extract(t.value, '$.{column}') IS NEW.{column}"
        for column in (
            "investment_cash_flow_id",
            "applied_payout_id",
            "expected_cash_flow_id",
            "applied_payout_revision_id",
            "money_proof_request_id",
            "provider_event_key",
        )
    )
    accepted = f"""EXISTS (
        SELECT 1 FROM broker_month_applies r, json_each(r.projection_json, '$.targets') t
        WHERE r.request_id = NEW.accepted_request_id
        AND r.account_id = i.account_id AND r.reporting_month_id = i.reporting_month_id
        AND json_extract(r.projection_json, '$.contract_version') = 'broker_payout_reconciliation_v1'
        AND json_extract(r.projection_json, '$.operation') IN ('link', 'reaffirm')
        AND json_type(r.projection_json, '$.journal_revision') = 'integer'
        AND json_extract(r.projection_json, '$.journal_revision') > json_extract(m.projection_json, '$.journal_revision')
        AND {receipt_target}
        AND json_extract(t.value, '$.predecessor_id') IS NEW.supersedes_id
    )"""
    retirement = """EXISTS (
        SELECT 1 FROM broker_month_applies r, json_each(r.projection_json, '$.targets') t
        WHERE r.request_id = NEW.retired_request_id
        AND json_extract(r.projection_json, '$.contract_version') = 'broker_payout_reconciliation_v1'
        AND json_extract(r.projection_json, '$.operation') IN ('retire', 'link', 'reaffirm')
        AND json_type(r.projection_json, '$.journal_revision') = 'integer'
        AND ((OLD.investment_cash_flow_id IS NOT NULL AND EXISTS (
            SELECT 1 FROM investment_cash_flows i, broker_month_applies a
            WHERE i.id = OLD.investment_cash_flow_id AND a.request_id = OLD.accepted_request_id
            AND i.account_id = r.account_id AND i.reporting_month_id = r.reporting_month_id
            AND json_extract(r.projection_json, '$.base_request_id') = json_extract(a.projection_json, '$.base_request_id')
            AND json_extract(t.value, '$.investment_cash_flow_id') = OLD.investment_cash_flow_id
            AND ((json_extract(r.projection_json, '$.operation') = 'retire'
                  AND json_extract(t.value, '$.relation_id') = OLD.id)
                 OR (json_extract(r.projection_json, '$.operation') = 'reaffirm'
                     AND json_extract(t.value, '$.predecessor_id') = OLD.id
                     AND json_extract(t.value, '$.predecessor_retirement_request_id') IS NULL
                     AND json_extract(t.value, '$.applied_payout_id') IS OLD.applied_payout_id
                     AND json_extract(t.value, '$.expected_cash_flow_id') IS OLD.expected_cash_flow_id))
            AND json_extract(r.projection_json, '$.journal_revision') > json_extract(a.projection_json, '$.journal_revision')
        )) OR (OLD.investment_cash_flow_id IS NULL
            AND json_extract(r.projection_json, '$.operation') = 'link'
            AND json_extract(t.value, '$.predecessor_id') = OLD.id
            AND json_extract(t.value, '$.predecessor_retirement_request_id') IS NULL
            AND json_extract(t.value, '$.applied_payout_id') = OLD.applied_payout_id
            AND json_extract(t.value, '$.expected_cash_flow_id') = OLD.expected_cash_flow_id
            AND EXISTS (
                SELECT 1 FROM investment_cash_flows i, applied_provider_payouts p, expected_cash_flows e
                WHERE i.id = json_extract(t.value, '$.investment_cash_flow_id')
                AND p.id = OLD.applied_payout_id AND e.id = OLD.expected_cash_flow_id
                AND i.account_id = r.account_id AND i.reporting_month_id = r.reporting_month_id
                AND p.account_id = i.account_id AND e.account_id = i.account_id
                AND p.instrument_id = i.instrument_id AND e.instrument_id = i.instrument_id
                AND p.currency = i.currency AND e.currency = i.currency
                AND p.event_kind = i.flow_type AND e.flow_type = i.flow_type
            )
        ))
        AND NOT EXISTS (SELECT 1 FROM applied_payout_reconciliations s WHERE s.supersedes_id = OLD.id)
    )"""
    return {
        "payout_ecf_insert_revision": """BEFORE INSERT ON expected_cash_flows
            WHEN NEW.payout_link_revision IS NOT 0
            BEGIN SELECT RAISE(ABORT, 'payout_link_revision_must_start_at_zero'); END""",
        "payout_ecf_counter": f"""BEFORE UPDATE ON expected_cash_flows
            WHEN typeof(NEW.payout_link_revision) != 'integer'
            OR (({material}) AND NEW.payout_link_revision IS NOT OLD.payout_link_revision)
            OR (NOT ({material}) AND NOT (NEW.payout_link_revision = OLD.payout_link_revision
                OR (OLD.payout_link_revision < 9223372036854775807
                    AND NEW.payout_link_revision = OLD.payout_link_revision + 1)))
            BEGIN SELECT RAISE(ABORT, 'payout_link_revision_invalid'); END""",
        "payout_ecf_material": f"""AFTER UPDATE ON expected_cash_flows WHEN {material}
            BEGIN
                SELECT CASE WHEN OLD.payout_link_revision = 9223372036854775807
                    THEN RAISE(ABORT, 'payout_link_revision_overflow') END;
                UPDATE expected_cash_flows SET payout_link_revision = OLD.payout_link_revision + 1
                    WHERE id = NEW.id;
            END""",
        "payout_actual_insert": f"""BEFORE INSERT ON applied_payout_reconciliations
            WHEN NEW.investment_cash_flow_id IS NOT NULL BEGIN
                SELECT CASE WHEN NEW.retired_request_id IS NOT NULL OR NOT EXISTS (
                    SELECT 1 FROM investment_cash_flows i JOIN broker_month_applies m
                        ON m.request_id = NEW.money_proof_request_id
                    WHERE i.id = NEW.investment_cash_flow_id AND i.currency = 'RUB'
                    AND i.flow_type IN ('coupon', 'dividend')
                    AND i.account_id = m.account_id AND i.reporting_month_id = m.reporting_month_id
                    AND json_extract(m.projection_json, '$.contract_version') IN ('broker_money_v1', 'broker_money_v2')
                    AND json_extract(m.projection_json, '$.operation') IN ('accept', 'reaffirm')
                    AND json_type(m.projection_json, '$.journal_revision') = 'integer'
                    AND EXISTS (SELECT 1 FROM json_each(m.projection_json, '$.targets') mt
                        WHERE json_extract(mt.value, '$.target_id') = i.id
                        AND json_extract(mt.value, '$.role') = i.flow_type)
                    AND {accepted}
                    AND (NEW.applied_payout_id IS NULL OR EXISTS (
                        SELECT 1 FROM applied_provider_payouts a JOIN applied_payout_revisions v
                            ON v.applied_payout_id = a.id
                        WHERE a.id = NEW.applied_payout_id AND v.id = NEW.applied_payout_revision_id
                        AND a.account_id = i.account_id AND a.instrument_id = i.instrument_id
                        AND a.currency = i.currency AND a.event_kind = i.flow_type
                    ))
                    AND (NEW.expected_cash_flow_id IS NULL OR EXISTS (
                        SELECT 1 FROM expected_cash_flows e WHERE e.id = NEW.expected_cash_flow_id
                        AND e.account_id = i.account_id AND e.instrument_id = i.instrument_id
                        AND e.currency = i.currency AND e.flow_type = i.flow_type
                    ))
                    AND ((NEW.supersedes_id IS NULL AND NOT EXISTS (
                        SELECT 1 FROM applied_payout_reconciliations h
                        WHERE h.investment_cash_flow_id = NEW.investment_cash_flow_id
                    )) OR EXISTS (
                        SELECT 1 FROM applied_payout_reconciliations p
                        LEFT JOIN broker_month_applies a ON a.request_id = p.accepted_request_id
                        JOIN broker_month_applies r ON r.request_id = NEW.accepted_request_id
                        JOIN broker_month_applies d ON d.request_id = p.retired_request_id
                        JOIN json_each(r.projection_json, '$.targets') rt
                        WHERE p.id = NEW.supersedes_id
                        AND json_extract(rt.value, '$.predecessor_id') = p.id
                        AND json_extract(rt.value, '$.investment_cash_flow_id') = NEW.investment_cash_flow_id
                        AND p.applied_payout_id IS NEW.applied_payout_id
                        AND p.expected_cash_flow_id IS NEW.expected_cash_flow_id
                        AND NOT EXISTS (SELECT 1 FROM applied_payout_reconciliations s WHERE s.supersedes_id = p.id)
                        AND ((p.investment_cash_flow_id IS NULL
                              AND p.retired_request_id = r.request_id
                              AND json_extract(r.projection_json, '$.operation') = 'link'
                              AND json_extract(rt.value, '$.predecessor_retirement_request_id') IS NULL)
                             OR (p.investment_cash_flow_id = NEW.investment_cash_flow_id
                                 AND json_extract(r.projection_json, '$.operation') = 'reaffirm'
                                 AND json_extract(r.projection_json, '$.base_request_id') = json_extract(a.projection_json, '$.base_request_id')
                                 AND json_extract(r.projection_json, '$.journal_revision') > json_extract(a.projection_json, '$.journal_revision')
                                 AND ((p.retired_request_id = r.request_id
                                       AND json_extract(rt.value, '$.predecessor_retirement_request_id') IS NULL)
                                      OR (p.retired_request_id != r.request_id
                                          AND json_extract(rt.value, '$.predecessor_retirement_request_id') = d.request_id
                                          AND d.account_id = r.account_id AND d.reporting_month_id = r.reporting_month_id
                                          AND json_extract(d.projection_json, '$.contract_version') = 'broker_payout_reconciliation_v1'
                                          AND json_extract(d.projection_json, '$.operation') = 'retire'
                                          AND json_extract(d.projection_json, '$.base_request_id') = json_extract(a.projection_json, '$.base_request_id')
                                          AND json_type(d.projection_json, '$.journal_revision') = 'integer'
                                          AND json_extract(d.projection_json, '$.journal_revision') > json_extract(a.projection_json, '$.journal_revision')
                                          AND json_extract(d.projection_json, '$.journal_revision') < json_extract(r.projection_json, '$.journal_revision')
                                          AND EXISTS (SELECT 1 FROM json_each(d.projection_json, '$.targets') dt
                                              WHERE json_extract(dt.value, '$.relation_id') = p.id
                                              AND json_extract(dt.value, '$.investment_cash_flow_id') = p.investment_cash_flow_id)))))
                    ))
                ) THEN RAISE(ABORT, 'actual_payout_proof_scope_invalid') END;
            END""",
        "payout_actual_update": f"""BEFORE UPDATE ON applied_payout_reconciliations
            WHEN OLD.investment_cash_flow_id IS NOT NULL OR OLD.retired_request_id IS NOT NULL
                 OR NEW.investment_cash_flow_id IS NOT NULL OR NEW.retired_request_id IS NOT NULL
            BEGIN SELECT CASE WHEN NOT (
                OLD.retired_request_id IS NULL AND NEW.retired_request_id IS NOT NULL
                AND {immutable} AND {retirement}
            ) THEN RAISE(ABORT, 'actual_payout_history_is_immutable') END; END""",
        "payout_actual_delete": """BEFORE DELETE ON applied_payout_reconciliations
            WHEN OLD.investment_cash_flow_id IS NOT NULL OR OLD.retired_request_id IS NOT NULL
            BEGIN SELECT RAISE(ABORT, 'actual_payout_history_is_immutable'); END""",
    }


def install_sql_guards(connection):
    for name, sql in guard_sql().items():
        connection.exec_driver_sql(f"CREATE TRIGGER {name} {sql}")


def _signature(sql):
    """Compare complete DDL, ignoring only constraint order and SQL whitespace."""
    sql = " ".join(sql.replace('"', "").split())
    if not sql.startswith("CREATE TABLE "):
        return sql
    body = sql[sql.index("(") + 1 : sql.rindex(")")]
    parts, start, depth, quoted = [], 0, 0, False
    for n, char in enumerate(body):
        if char == "'":
            quoted = not quoted
        if not quoted:
            depth += (char == "(") - (char == ")")
            if char == "," and depth == 0:
                parts.append(body[start:n].strip())
                start = n + 1
    parts.append(body[start:].strip())
    return sorted(parts)


def _inventory(connection):
    return list(
        connection.exec_driver_sql(
            "SELECT type, name, tbl_name, sql FROM sqlite_schema "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).tuples()
    )


def _snapshot(connection, columns):
    result = {}
    for table, names in columns.items():
        # All old columns, not ORM fields. Multiplicity and NULL are retained.
        rows = connection.exec_driver_sql(
            f'SELECT {", ".join(chr(34) + c + chr(34) for c in names)} FROM "{table}"'
        )
        hashes = sorted(hashlib.sha256(repr(tuple(row)).encode()).digest() for row in rows)
        result[table] = (len(hashes), hashlib.sha256(b"".join(hashes)).hexdigest())
    return result


def _check_integrity(connection):
    if connection.exec_driver_sql("PRAGMA integrity_check").all() != [("ok",)]:
        raise RuntimeError("0066_integrity_check_failed")
    if connection.exec_driver_sql("PRAGMA foreign_key_check").all():
        raise RuntimeError("0066_foreign_key_check_failed")


def _checkpoint(_connection, _stage):
    """Fault-injection seam; production never skips a checkpoint or guard."""


def migrate(connection, *, upgrade):
    version = "0065_source_return_proofs" if upgrade else "0066_actual_payout_links"
    if connection.exec_driver_sql("SELECT version_num FROM alembic_version").all() != [(version,)]:
        raise RuntimeError("0066_exact_single_head_required")
    if connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 0:
        raise RuntimeError("0066_requires_reserved_migration_transaction")
    if not connection.connection.driver_connection.in_transaction:
        raise RuntimeError("0066_requires_reserved_migration_transaction")
    _check_integrity(connection)
    if not upgrade:
        for query in (
            "SELECT 1 FROM broker_month_applies WHERE json_extract(projection_json, '$.contract_version') IN ('broker_money_v2', 'broker_payout_reconciliation_v1', 'broker_payout_dependency_v1') LIMIT 1",
            "SELECT 1 FROM broker_money_occurrence_owners WHERE role = 'dividend' LIMIT 1",
            "SELECT 1 FROM applied_payout_reconciliations WHERE investment_cash_flow_id IS NOT NULL OR retired_request_id IS NOT NULL LIMIT 1",
            "SELECT 1 FROM expected_cash_flows WHERE payout_link_revision != 0 LIMIT 1",
        ):
            if connection.exec_driver_sql(query).first():
                raise RuntimeError("0066_cannot_downgrade_payout_history")
    inventory = _inventory(connection)
    expected = _old_tables() if upgrade else _new_tables()
    for table, sql in expected.items():
        actual = [(kind, name, ddl) for kind, name, owner, ddl in inventory if owner == table]
        expected_items = [("table", table, _signature(sql))]
        if upgrade and table == TABLES[1]:
            expected_items.append(
                (
                    "index",
                    "uq_applied_payout_reconciliations_active_manual_flow",
                    _signature(LEGACY_INDEX),
                )
            )
        if not upgrade:
            if table == TABLES[1]:
                for ddl in index_sql():
                    name = re.search(r"INDEX (\S+)", ddl)[1]
                    expected_items.append(("index", name, _signature(ddl)))
            for name, ddl in guard_sql().items():
                if f" ON {table}" in ddl:
                    expected_items.append(
                        ("trigger", name, _signature(f"CREATE TRIGGER {name} {ddl}"))
                    )
        observed = [(kind, name, _signature(ddl)) for kind, name, ddl in actual]
        if sorted(observed) != sorted(expected_items):
            raise RuntimeError(f"0066_schema_drift:{table}")
    # 0065's original two tables and all thirteen guards are mandatory inputs.
    proof_guards = {
        name: sql
        for kind, name, _, sql in inventory
        if kind == "trigger"
        and (name.startswith("return_proof_") or name.startswith("source_return_proof"))
    }
    if proof_guards != PROOF_GUARDS_0065:
        raise RuntimeError("0066_source_return_proof_schema_drift")
    proof_tables = {
        name: _signature(sql)
        for kind, name, _, sql in inventory
        if kind == "table" and name in PROOF_TABLES_0065
    }
    if proof_tables != {name: _signature(sql) for name, sql in PROOF_TABLES_0065.items()}:
        raise RuntimeError("0066_source_return_proof_schema_drift")
    columns = {
        name: [row[1] for row in connection.exec_driver_sql(f'PRAGMA table_info("{name}")')]
        for kind, name, _, _ in inventory
        if kind == "table" and name != "alembic_version"
    }
    if not upgrade:
        columns[TABLES[0]].remove("payout_link_revision")
        columns[TABLES[1]] = [
            "id",
            "applied_payout_id",
            "expected_cash_flow_id",
            "counting_decision",
            "created_at",
            "archived_from_period",
        ]
    before = _snapshot(connection, columns)
    sequence = dict(connection.exec_driver_sql("SELECT name, seq FROM sqlite_sequence").all())
    if not upgrade:
        # Cross-table guards must be removed inside the same rollbackable DDL
        # transaction before rebuilding their referenced parent.
        for name in guard_sql():
            connection.exec_driver_sql(f"DROP TRIGGER {name}")
    target = _new_tables() if upgrade else _old_tables()
    for table, sql in target.items():
        temporary = f"_0066_{table}"
        create = re.sub(
            r'CREATE TABLE "?' + table + r'"?', f'CREATE TABLE "{temporary}"', sql, count=1
        )
        connection.exec_driver_sql(create)
        names = ", ".join('"' + column + '"' for column in columns[table])
        connection.exec_driver_sql(
            f'INSERT INTO "{temporary}" ({names}) SELECT {names} FROM "{table}"'
        )
        connection.exec_driver_sql(f'DROP TABLE "{table}"')
        connection.exec_driver_sql(f'ALTER TABLE "{temporary}" RENAME TO "{table}"')
        _checkpoint(connection, table)
    if upgrade:
        for sql in index_sql():
            connection.exec_driver_sql(sql)
        install_sql_guards(connection)
    else:
        connection.exec_driver_sql(LEGACY_INDEX)
    if _snapshot(connection, columns) != before:
        raise RuntimeError("0066_old_values_changed")
    unchanged = [row for row in inventory if row[2] not in TABLES]
    if [row for row in _inventory(connection) if row[2] not in TABLES] != unchanged:
        raise RuntimeError("0066_unrelated_schema_changed")
    after_sequence = dict(connection.exec_driver_sql("SELECT name, seq FROM sqlite_sequence").all())
    if any(
        after_sequence.get(table) != seq for table, seq in sequence.items() if table != TABLES[0]
    ):
        raise RuntimeError("0066_existing_sequence_changed")
    if upgrade:
        maximum = connection.exec_driver_sql(
            "SELECT coalesce(max(id), 0) FROM expected_cash_flows"
        ).scalar_one()
        if after_sequence.get(TABLES[0], 0) < maximum:
            raise RuntimeError("0066_ecf_sequence_invalid")
    _check_integrity(connection)
    _checkpoint(connection, "before_commit")


def _after_create(_metadata, connection, **_kwargs):
    # create_all(checkfirst=True) can run again, or with a subset of metadata.
    # Do not replace an existing guard or install against an incomplete graph.
    inventory = _inventory(connection)
    tables = {name for kind, name, _, _ in inventory if kind == "table"}
    if not {
        *TABLES,
        "broker_month_applies",
        "investment_cash_flows",
        "applied_provider_payouts",
        "applied_payout_revisions",
    }.issubset(tables):
        return
    existing = {name: sql for kind, name, _, sql in inventory if kind == "trigger"}
    for name, sql in guard_sql().items():
        expected = f"CREATE TRIGGER {name} {sql}"
        if name in existing:
            if _signature(existing[name]) != _signature(expected):
                raise RuntimeError(f"0066_schema_drift:{name}")
        else:
            connection.exec_driver_sql(expected)


def install_hooks():
    from hermes_finance.persistence import Base

    if not event.contains(Base.metadata, "after_create", _after_create):
        event.listen(Base.metadata, "after_create", _after_create)


EXPECTED_CASH_FLOWS_0065 = "CREATE TABLE \"expected_cash_flows\" (\n\tid INTEGER NOT NULL, \n\treporting_month_id INTEGER, \n\taccount_id INTEGER NOT NULL, \n\tinstrument_id INTEGER NOT NULL, \n\tflow_type VARCHAR(16) NOT NULL, \n\texpected_date DATE NOT NULL, \n\tgross_amount_kopecks BIGINT NOT NULL, \n\texpected_tax_amount_kopecks BIGINT, \n\texpected_net_amount_kopecks BIGINT NOT NULL, \n\tcurrency VARCHAR(3) DEFAULT 'RUB' NOT NULL, \n\tsource VARCHAR(64) NOT NULL, \n\tsource_as_of_date DATE NOT NULL, \n\tforecast_version VARCHAR(32) NOT NULL, \n\tis_confirmed BOOLEAN DEFAULT 0 NOT NULL, \n\tis_approximate BOOLEAN DEFAULT 0 NOT NULL, \n\tnotes VARCHAR(2000), \n\tarchived_from_period VARCHAR(7), \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_expected_cash_flows_tax_nonnegative CHECK (expected_tax_amount_kopecks IS NULL OR expected_tax_amount_kopecks >= 0), \n\tCONSTRAINT ck_expected_cash_flows_gross_nonnegative CHECK (gross_amount_kopecks >= 0), \n\tCONSTRAINT ck_expected_cash_flows_net_nonnegative CHECK (expected_net_amount_kopecks >= 0), \n\tCONSTRAINT uq_expected_cash_flows_snapshot_event UNIQUE (reporting_month_id, account_id, instrument_id, flow_type, expected_date, forecast_version), \n\tCONSTRAINT ck_expected_cash_flows_flow_type CHECK (flow_type IN ('coupon', 'dividend', 'interest', 'redemption', 'other')), \n\tCONSTRAINT ck_expected_cash_flows_archive_scope CHECK ((reporting_month_id IS NULL AND archived_from_period IS NOT NULL) OR (reporting_month_id IS NOT NULL AND archived_from_period IS NULL)), \n\tFOREIGN KEY(reporting_month_id) REFERENCES reporting_months (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(instrument_id) REFERENCES instruments (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE RESTRICT\n)"

APPLIED_PAYOUT_RECONCILIATIONS_0065 = "CREATE TABLE \"applied_payout_reconciliations\" (\n\tid INTEGER NOT NULL, \n\tapplied_payout_id INTEGER NOT NULL, \n\texpected_cash_flow_id INTEGER NOT NULL, \n\tcounting_decision VARCHAR(16) NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tarchived_from_period VARCHAR(7), \n\tPRIMARY KEY (id), \n\tCONSTRAINT fk_applied_payout_reconciliations_applied_payout_id_applied_provider_payouts FOREIGN KEY(applied_payout_id) REFERENCES applied_provider_payouts (id) ON DELETE CASCADE, \n\tCONSTRAINT uq_applied_payout_reconciliations_payout UNIQUE (applied_payout_id), \n\tCONSTRAINT ck_applied_payout_reconciliations_decision CHECK (counting_decision IN ('keep_both', 'count_manual', 'count_provider')), \n\tCONSTRAINT fk_applied_payout_reconciliations_expected_cash_flow_id FOREIGN KEY(expected_cash_flow_id) REFERENCES expected_cash_flows (id) ON DELETE RESTRICT\n)"

BROKER_MONEY_OCCURRENCE_OWNERS_0065 = "CREATE TABLE broker_money_occurrence_owners (\n\tid INTEGER NOT NULL, \n\timport_id INTEGER NOT NULL, \n\tsection VARCHAR(16) NOT NULL, \n\tordinal INTEGER NOT NULL, \n\trow_fingerprint VARCHAR(64) NOT NULL, \n\trole VARCHAR(32) NOT NULL, \n\tinvestment_cash_flow_id INTEGER, \n\thistorical_owner_flow_id VARCHAR(64), \n\taccepted_request_id VARCHAR(64) NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_broker_money_occurrence UNIQUE (import_id, section, ordinal), \n\tCONSTRAINT ck_broker_money_occurrence CHECK (section = 'money' AND ordinal >= 0), \n\tCONSTRAINT ck_broker_money_fingerprint CHECK (length(row_fingerprint) = 64), \n\tCONSTRAINT ck_broker_money_target CHECK ((role = 'coupon' AND investment_cash_flow_id IS NOT NULL AND historical_owner_flow_id IS NULL) OR (role = 'account_funding' AND historical_owner_flow_id IS NOT NULL AND investment_cash_flow_id IS NULL)), \n\tFOREIGN KEY(import_id) REFERENCES mybroker_imports (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(investment_cash_flow_id) REFERENCES investment_cash_flows (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(historical_owner_flow_id) REFERENCES historical_owner_flows (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(accepted_request_id) REFERENCES broker_month_applies (request_id) ON DELETE RESTRICT\n)"


PROOF_GUARDS_0065 = {
    "return_proof_reporting_months_delete": "CREATE TRIGGER return_proof_reporting_months_delete AFTER DELETE ON reporting_months WHEN EXISTS (SELECT 1 FROM source_intake_originals) BEGIN INSERT INTO source_return_proof_dependencies(token) VALUES(lower(hex(randomblob(32)))); END",
    "return_proof_reporting_months_insert": "CREATE TRIGGER return_proof_reporting_months_insert AFTER INSERT ON reporting_months WHEN EXISTS (SELECT 1 FROM source_intake_originals) BEGIN INSERT INTO source_return_proof_dependencies(token) VALUES(lower(hex(randomblob(32)))); END",
    "return_proof_reporting_months_update": "CREATE TRIGGER return_proof_reporting_months_update AFTER UPDATE ON reporting_months WHEN EXISTS (SELECT 1 FROM source_intake_originals) AND (OLD.id IS NOT NEW.id OR OLD.year IS NOT NEW.year OR OLD.month IS NOT NEW.month OR OLD.period_start IS NOT NEW.period_start OR OLD.period_end IS NOT NEW.period_end OR OLD.snapshot_date IS NOT NEW.snapshot_date OR OLD.status IS NOT NEW.status OR OLD.source IS NOT NEW.source OR OLD.created_at IS NOT NEW.created_at OR OLD.updated_at IS NOT NEW.updated_at) BEGIN INSERT INTO source_return_proof_dependencies(token) VALUES(lower(hex(randomblob(32)))); END",
    "return_proof_security_reg_isin_mappings_delete": "CREATE TRIGGER return_proof_security_reg_isin_mappings_delete AFTER DELETE ON security_reg_isin_mappings WHEN EXISTS (SELECT 1 FROM source_intake_originals) BEGIN INSERT INTO source_return_proof_dependencies(token) VALUES(lower(hex(randomblob(32)))); END",
    "return_proof_security_reg_isin_mappings_insert": "CREATE TRIGGER return_proof_security_reg_isin_mappings_insert AFTER INSERT ON security_reg_isin_mappings WHEN EXISTS (SELECT 1 FROM source_intake_originals) BEGIN INSERT INTO source_return_proof_dependencies(token) VALUES(lower(hex(randomblob(32)))); END",
    "return_proof_security_reg_isin_mappings_update": "CREATE TRIGGER return_proof_security_reg_isin_mappings_update AFTER UPDATE ON security_reg_isin_mappings WHEN EXISTS (SELECT 1 FROM source_intake_originals) AND (OLD.id IS NOT NEW.id OR OLD.reg_number IS NOT NEW.reg_number OR OLD.isin IS NOT NEW.isin OR OLD.note IS NOT NEW.note OR OLD.created_at IS NOT NEW.created_at OR OLD.updated_at IS NOT NEW.updated_at) BEGIN INSERT INTO source_return_proof_dependencies(token) VALUES(lower(hex(randomblob(32)))); END",
    "return_proof_source_intake_money_classifications_delete": "CREATE TRIGGER return_proof_source_intake_money_classifications_delete AFTER DELETE ON source_intake_money_classifications WHEN EXISTS (SELECT 1 FROM source_intake_originals) BEGIN INSERT INTO source_return_proof_dependencies(token) VALUES(lower(hex(randomblob(32)))); END",
    "return_proof_source_intake_money_classifications_insert": "CREATE TRIGGER return_proof_source_intake_money_classifications_insert AFTER INSERT ON source_intake_money_classifications WHEN EXISTS (SELECT 1 FROM source_intake_originals) BEGIN INSERT INTO source_return_proof_dependencies(token) VALUES(lower(hex(randomblob(32)))); END",
    "return_proof_source_intake_money_classifications_update": "CREATE TRIGGER return_proof_source_intake_money_classifications_update AFTER UPDATE ON source_intake_money_classifications WHEN EXISTS (SELECT 1 FROM source_intake_originals) AND (OLD.id IS NOT NEW.id OR OLD.intake_id IS NOT NEW.intake_id OR OLD.observation_id IS NOT NEW.observation_id OR OLD.source_reference IS NOT NEW.source_reference OR OLD.date IS NOT NEW.date OR OLD.amount_kopecks IS NOT NEW.amount_kopecks OR OLD.currency IS NOT NEW.currency OR OLD.operation IS NOT NEW.operation OR OLD.narrative IS NOT NEW.narrative OR OLD.classification IS NOT NEW.classification OR OLD.origin IS NOT NEW.origin OR OLD.status IS NOT NEW.status OR OLD.created_at IS NOT NEW.created_at OR OLD.updated_at IS NOT NEW.updated_at OR OLD.security_reg_number IS NOT NEW.security_reg_number OR OLD.security_issuer IS NOT NEW.security_issuer OR OLD.instrument_id IS NOT NEW.instrument_id OR OLD.instrument_link_status IS NOT NEW.instrument_link_status) BEGIN INSERT INTO source_return_proof_dependencies(token) VALUES(lower(hex(randomblob(32)))); END",
    "source_return_proof_dependencies_no_delete": "CREATE TRIGGER source_return_proof_dependencies_no_delete BEFORE DELETE ON source_return_proof_dependencies BEGIN SELECT RAISE(ABORT, 'source return proof is append-only'); END",
    "source_return_proof_dependencies_no_update": "CREATE TRIGGER source_return_proof_dependencies_no_update BEFORE UPDATE ON source_return_proof_dependencies BEGIN SELECT RAISE(ABORT, 'source return proof is append-only'); END",
    "source_return_proofs_no_delete": "CREATE TRIGGER source_return_proofs_no_delete BEFORE DELETE ON source_return_proofs BEGIN SELECT RAISE(ABORT, 'source return proof is append-only'); END",
    "source_return_proofs_no_update": "CREATE TRIGGER source_return_proofs_no_update BEFORE UPDATE ON source_return_proofs BEGIN SELECT RAISE(ABORT, 'source return proof is append-only'); END",
}


PROOF_TABLES_0065 = {
    "source_return_proofs": "CREATE TABLE source_return_proofs (\n\tid INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, \n\tsource_account VARCHAR(256) NOT NULL, \n\tnative_account VARCHAR(256) NOT NULL, \n\trequest_id VARCHAR(64) NOT NULL, \n\trequest_fingerprint VARCHAR(64) NOT NULL, \n\tproof_version VARCHAR(32) NOT NULL, \n\tdependency_digest VARCHAR(64) NOT NULL, \n\tevidence_json TEXT NOT NULL, \n\tconfirmed_at DATETIME NOT NULL, \n\tCONSTRAINT ck_source_return_proof_version CHECK (proof_version = 'source_return_custody_v1'), \n\tCONSTRAINT ck_source_return_proof_dependency CHECK (length(dependency_digest) = 64), \n\tUNIQUE (request_id)\n)",
    "source_return_proof_dependencies": "CREATE TABLE source_return_proof_dependencies (\n\tseq INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, \n\ttoken VARCHAR(64) NOT NULL\n)",
}

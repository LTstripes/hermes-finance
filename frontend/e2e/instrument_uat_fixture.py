"""Synthetic read-only browser harness; production CLI isolation tested separately."""

import sys
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from hermes_finance import instrument_uat as uat
from hermes_finance import scratch_preflight as scratch
from hermes_finance.services.accounts import create_account


def main():
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "backend/tests"))
    from test_instrument_what_if_service import setup_stock
    from test_scratch_preflight_runtime import files, snapshot_binding, stamp_fixture
    from test_statement_import_mybroker import database

    with TemporaryDirectory(prefix="hermes-instrument-uat-synthetic-") as temporary:
        generator = database.__wrapped__(Path(temporary))
        writer = next(generator)
        setup_stock(writer)
        with writer.session_factory() as session:
            create_account(session, name="Synthetic empty account", account_type="iis")
        writer.engine.dispose()
        stamp_fixture(writer.database_path)
        binding = snapshot_binding(writer.database_path)
        before = files(writer.database_path)
        with ExitStack() as stack:
            stack.enter_context(scratch._hold_snapshot(writer.database_path))
            static, _ = uat.static_bundle(root / "frontend/dist", stack)
            reader = scratch._read_database(binding)
            try:
                app = uat.create_reader(
                    reader,
                    binding,
                    "a" * 64,
                    static,
                    lambda: scratch._check_snapshot(binding),
                )
                uvicorn.run(app, host="127.0.0.1", port=uat.PORT, access_log=False)
            finally:
                reader.engine.dispose()
                assert files(writer.database_path) == before
                generator.close()


if __name__ == "__main__":
    main()

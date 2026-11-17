"""Independent spending diary v1; no reporting-month facts are rewritten."""

import sqlalchemy as sa
from alembic import op

revision = "0069_spending_diary"
down_revision = "0068_owner_manual_gold_history"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        sa.text("""
CREATE TABLE spending_categories (
	id INTEGER NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	name_key VARCHAR(128) NOT NULL, 
	expense_type VARCHAR(32) NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (expense_type IN ('mandatory','comfortable','other')), 
	UNIQUE (name_key)
)

""")
    )
    op.execute(
        sa.text("""
CREATE TABLE spending_rules (
	id INTEGER NOT NULL, 
	scope VARCHAR(32) NOT NULL, 
	"key" TEXT NOT NULL, 
	action VARCHAR(32) NOT NULL, 
	category_id INTEGER, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_spending_rule UNIQUE (scope, "key"), 
	CHECK (scope IN ('merchant','bank_category')), 
	CHECK (action IN ('expense','refund','not_spending')), 
	FOREIGN KEY(category_id) REFERENCES spending_categories (id)
)

""")
    )
    op.execute(
        sa.text("""
CREATE TABLE spending_uploads (
	id INTEGER NOT NULL, 
	source VARCHAR(32) NOT NULL, 
	month VARCHAR(7) NOT NULL, 
	account TEXT NOT NULL, 
	filename TEXT NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	date_from DATE NOT NULL, 
	date_to DATE NOT NULL, 
	uploaded_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (source IN ('alfa_csv','manual_md')), 
	CHECK (date_to >= date_from)
)

""")
    )
    op.execute(
        sa.text("""
CREATE TABLE spending_operations (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, 
	upload_id INTEGER NOT NULL, 
	source VARCHAR(32) NOT NULL, 
	month VARCHAR(7) NOT NULL, 
	operation_date DATE, 
	transaction_date DATE, 
	amount_kopecks BIGINT NOT NULL, 
	direction VARCHAR(32) NOT NULL, 
	currency VARCHAR(8) NOT NULL, 
	status VARCHAR(64) NOT NULL, 
	category VARCHAR(128) NOT NULL, 
	description TEXT NOT NULL, 
	account TEXT NOT NULL, 
	card TEXT NOT NULL, 
	payment VARCHAR(16) NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	reason VARCHAR(64), 
	merchant_key TEXT NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	ordinal INTEGER NOT NULL, 
	raw_json TEXT NOT NULL, 
	decision VARCHAR(32), 
	decision_category_id INTEGER, 
	duplicate_of_id INTEGER, 
	needs_review BOOLEAN NOT NULL, 
	CONSTRAINT uq_spending_occurrence UNIQUE (source, month, fingerprint, ordinal), 
	CHECK (ordinal > 0 AND amount_kopecks != 0), 
	CHECK (source IN ('alfa_csv','manual_md')), 
	CHECK (decision IS NULL OR decision IN ('expense','refund','not_spending','duplicate','separate')), 
	FOREIGN KEY(upload_id) REFERENCES spending_uploads (id), 
	FOREIGN KEY(decision_category_id) REFERENCES spending_categories (id), 
	FOREIGN KEY(duplicate_of_id) REFERENCES spending_operations (id)
)

""")
    )
    op.execute(sa.text("CREATE INDEX ix_spending_operations_month ON spending_operations (month)"))
    op.execute(
        sa.text("""
CREATE TABLE spending_expense_links (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, 
	expense_entry_id INTEGER NOT NULL, 
	remember_recurring BOOLEAN NOT NULL, 
	merchant_keys_json TEXT NOT NULL, 
	active BOOLEAN NOT NULL, 
	UNIQUE (expense_entry_id), 
	FOREIGN KEY(expense_entry_id) REFERENCES expense_entries (id) ON DELETE CASCADE
)

""")
    )
    op.execute(
        sa.text("""
CREATE TABLE spending_link_operations (
	link_id INTEGER NOT NULL, 
	operation_id INTEGER NOT NULL, 
	PRIMARY KEY (link_id, operation_id), 
	FOREIGN KEY(link_id) REFERENCES spending_expense_links (id) ON DELETE CASCADE, 
	UNIQUE (operation_id), 
	FOREIGN KEY(operation_id) REFERENCES spending_operations (id)
)

""")
    )
    op.execute(
        sa.text("""
CREATE TABLE spending_reviews (
	id INTEGER NOT NULL, 
	month VARCHAR(7) NOT NULL, 
	reason VARCHAR(64) NOT NULL, 
	previous_json TEXT NOT NULL, 
	resolved BOOLEAN NOT NULL, 
	PRIMARY KEY (id)
)

""")
    )
    op.execute(sa.text("CREATE INDEX ix_spending_reviews_month ON spending_reviews (month)"))


def downgrade():
    if any(
        op.get_bind().execute(sa.text("SELECT 1 FROM " + table + " LIMIT 1")).first()
        for table in [
            "spending_categories",
            "spending_rules",
            "spending_uploads",
            "spending_operations",
            "spending_expense_links",
            "spending_link_operations",
            "spending_reviews",
        ]
    ):
        raise RuntimeError("cannot discard spending diary data")
    op.drop_table("spending_reviews")
    op.drop_table("spending_link_operations")
    op.drop_table("spending_expense_links")
    op.drop_table("spending_operations")
    op.drop_table("spending_uploads")
    op.drop_table("spending_rules")
    op.drop_table("spending_categories")

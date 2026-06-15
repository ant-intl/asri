# Manual migration to create the chatbot_prompt table for Django ORM compatibility.
# Migration 0026 only updated Django's state to make PromptTemplate point to the
# chatbot_prompt table (SeparateDatabaseAndState with only state_operations), but
# never actually created the table in the database. This migration creates it.
#
# The old chatbot_prompt_template table is preserved as-is, allowing both tables
# to coexist — matching the original design intent.

from django.db import migrations

# The table schema matches the PromptTemplate model definition with
# db_table='chatbot_prompt'. Index names match the state set by 0028's
# state_operations RenameIndex operations.

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS "chatbot_prompt" (
    "id" char(32) NOT NULL PRIMARY KEY,
    "tenant_id" varchar(64) NOT NULL,
    "name" varchar(100) NOT NULL,
    "description" text NOT NULL,
    "system_template" text NOT NULL,
    "user_template_mode" varchar(20) NOT NULL,
    "user_template" text NOT NULL,
    "layers" text NOT NULL,
    "extractor_config" text NOT NULL,
    "is_active" bool NOT NULL,
    "gmt_create" datetime NOT NULL,
    "gmt_modified" datetime NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS "uk_prompt_tenant_id_name" ON "chatbot_prompt" ("tenant_id", "name");
CREATE INDEX IF NOT EXISTS "chatbot_pro_name_83f4d7_idx" ON "chatbot_prompt" ("name");
CREATE INDEX IF NOT EXISTS "chatbot_pro_is_acti_d68786_idx" ON "chatbot_prompt" ("is_active");
"""

DROP_SQL = """
DROP TABLE IF EXISTS "chatbot_prompt";
"""


class Migration(migrations.Migration):

    dependencies = [
        ('apps', '0028_rename_chatbot_pro_name_a3c5c6_idx_chatbot_pro_name_83f4d7_idx_and_more'),
    ]

    operations = [
        migrations.RunSQL(CREATE_SQL, DROP_SQL),
    ]

"""Separate executable encrypted patches from display previews."""

from alembic import op

revision = "20261030_0055"
down_revision = "20261030_0054"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE public.remediations
          ADD COLUMN generation_status text NOT NULL DEFAULT 'legacy_unverified',
          ADD COLUMN generation_contract_version integer NULL,
          ADD COLUMN generation_failure jsonb NULL,
          ADD COLUMN patch_artifact_id uuid NULL,
          ADD COLUMN validated_at timestamptz NULL,
          ADD CONSTRAINT remediations_generation_status_check CHECK (generation_status IN ('pending','running','ready','failed','legacy_unverified')),
          ADD CONSTRAINT remediations_ready_artifact_check CHECK (generation_status <> 'ready' OR (patch_artifact_id IS NOT NULL AND validated_at IS NOT NULL));
        CREATE UNIQUE INDEX remediations_owner_finding_v2_key ON public.remediations(owner_id,finding_id) WHERE generation_contract_version = 2;
    """)
    op.execute("""
        ALTER TABLE private.review_agent_attempts ADD CONSTRAINT review_agent_attempts_owner_id_key UNIQUE (owner_id,id);
        CREATE TABLE private.remediation_patch_artifacts (
          id uuid PRIMARY KEY DEFAULT public.uuidv7(), owner_id uuid NOT NULL,
          remediation_id uuid NOT NULL, source_snapshot jsonb NOT NULL,
          ciphertext bytea NOT NULL, nonce bytea NOT NULL, key_version text NOT NULL,
          aad_version text NOT NULL, encryption_provider text NOT NULL, key_reference text NOT NULL,
          sha256 text NOT NULL, format_version integer NOT NULL DEFAULT 2,
          created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          CONSTRAINT patch_artifacts_owner_id_key UNIQUE(owner_id,id),
          CONSTRAINT patch_artifacts_owner_remediation_key UNIQUE(owner_id,remediation_id),
          FOREIGN KEY(owner_id,remediation_id) REFERENCES public.remediations(owner_id,id) ON DELETE CASCADE
        );
        CREATE TABLE private.remediation_generation_attempts (
          id uuid PRIMARY KEY DEFAULT public.uuidv7(), owner_id uuid NOT NULL,
          remediation_id uuid NOT NULL, review_attempt_id uuid NULL,
          submission_number integer NOT NULL, outcome text NOT NULL, diagnostics_json jsonb NULL,
          source_read_count integer NOT NULL DEFAULT 0, model_call_count integer NOT NULL DEFAULT 0,
          elapsed_ms integer NOT NULL DEFAULT 0, created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          CONSTRAINT generation_attempt_submission_key UNIQUE(owner_id,remediation_id,submission_number),
          CONSTRAINT generation_attempt_submission_check CHECK(submission_number BETWEEN 1 AND 3),
          FOREIGN KEY(owner_id,remediation_id) REFERENCES public.remediations(owner_id,id) ON DELETE CASCADE,
          FOREIGN KEY(owner_id,review_attempt_id) REFERENCES private.review_agent_attempts(owner_id,id) ON DELETE CASCADE
        );
    """)
    op.execute(
        "ALTER TABLE public.remediations ADD CONSTRAINT remediations_owner_patch_artifact_fkey FOREIGN KEY (owner_id,patch_artifact_id) REFERENCES private.remediation_patch_artifacts(owner_id,id)"
    )
    # The review worker connects as trace_internal, whose INSERT on remediations is
    # granted per column, so the new columns it sets at staging time need their own.
    op.execute(
        "GRANT INSERT (generation_status, generation_contract_version) "
        "ON public.remediations TO trace_internal"
    )
    for table in ("remediation_patch_artifacts", "remediation_generation_attempts"):
        op.execute(f"ALTER TABLE private.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE private.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_owner ON private.{table} USING (owner_id = public.trace_current_user_id()) WITH CHECK (owner_id = public.trace_current_user_id())"
        )
        op.execute(
            f"CREATE POLICY {table}_internal ON private.{table} TO trace_internal USING (true) WITH CHECK (true)"
        )
        op.execute(f"REVOKE ALL ON private.{table} FROM PUBLIC")
        op.execute(
            f"GRANT SELECT, INSERT ON private.{table} TO trace_app, trace_internal"
        )
    op.execute("""
        CREATE FUNCTION private.reject_patch_artifact_update() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'patch artifacts are immutable'; END $$;
        CREATE TRIGGER patch_artifact_immutable BEFORE UPDATE ON private.remediation_patch_artifacts FOR EACH ROW EXECUTE FUNCTION private.reject_patch_artifact_update();
        CREATE FUNCTION private.reject_ready_patch_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.generation_status = 'ready' AND (NEW.patch_artifact_id IS DISTINCT FROM OLD.patch_artifact_id OR NEW.proposed_diff IS DISTINCT FROM OLD.proposed_diff OR NEW.generation_status IS DISTINCT FROM OLD.generation_status) THEN
            RAISE EXCEPTION 'ready patch is immutable';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER remediation_ready_patch_immutable BEFORE UPDATE ON public.remediations FOR EACH ROW EXECUTE FUNCTION private.reject_ready_patch_change();
    """)


def downgrade():
    op.execute(
        "REVOKE INSERT (generation_status, generation_contract_version) "
        "ON public.remediations FROM trace_internal"
    )
    op.execute("DROP TRIGGER remediation_ready_patch_immutable ON public.remediations")
    op.execute("DROP FUNCTION private.reject_ready_patch_change()")
    op.execute(
        "DROP TRIGGER patch_artifact_immutable ON private.remediation_patch_artifacts"
    )
    op.execute("DROP FUNCTION private.reject_patch_artifact_update()")
    op.execute(
        "ALTER TABLE public.remediations DROP CONSTRAINT remediations_owner_patch_artifact_fkey"
    )
    op.execute("DROP TABLE private.remediation_generation_attempts")
    op.execute("DROP TABLE private.remediation_patch_artifacts")
    op.execute(
        "ALTER TABLE private.review_agent_attempts DROP CONSTRAINT review_agent_attempts_owner_id_key"
    )
    op.execute("DROP INDEX public.remediations_owner_finding_v2_key")
    op.execute(
        "ALTER TABLE public.remediations DROP CONSTRAINT remediations_ready_artifact_check, DROP CONSTRAINT remediations_generation_status_check, DROP COLUMN generation_status, DROP COLUMN generation_contract_version, DROP COLUMN generation_failure, DROP COLUMN patch_artifact_id, DROP COLUMN validated_at"
    )

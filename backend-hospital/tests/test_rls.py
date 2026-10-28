"""Row-level security (app/rls.py): the database keeps hospitals apart even
when a query forgets its hospital filter.

The policy tests need PostgreSQL (HOSPITAL_TEST_DATABASE_URL; CI runs them)
and run as the app role, like the rest of the suite there. The checks that
the model, app/rls.py and migration 0007 agree run everywhere.
"""

import importlib.util
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from conftest import APP_ROLE, postgres_url

from app import crypto, models, rls
from app.db import Base, platform_session, session_scope

pg_only = pytest.mark.skipif(not postgres_url(), reason="row-level security needs PostgreSQL")

A, B = "hospital-a", "hospital-b"
NOW = datetime(2026, 10, 27, 9, 0, tzinfo=timezone.utc)

POLICY_TABLES = [t for t, _ in rls.TENANT_TABLES] + list(rls.CHILD_TABLES)
#: The primary key of each policy table (to name the rows a query sees).
PK = {table: Base.metadata.tables[table].primary_key.columns.keys()[0] for table in POLICY_TABLES}


def _id(h, what, n):
    return f"{h[-1]}-{what}-{n}"


def build(table, h, n):
    """A row of ``table`` belonging to hospital ``h`` (its parents are the
    seeded rows, n=1); ``n`` keeps unique columns unique."""
    m = models
    staff, patient, record = _id(h, "staff", 1), _id(h, "patient", 1), _id(h, "record", 1)
    client = _id(h, "client", 1)
    rows = {
        "hospitals": lambda: m.Hospital(id=h if n == 1 else _id(h, "hospital", n), code=f"{h[-1]}{n}".upper(),
                                        name=f"Hospital {h} {n}"),
        "departments": lambda: m.Department(id=_id(h, "dept", n), hospital_id=h, kind="ward", name=f"Ward {n}"),
        "staff_users": lambda: m.StaffUser(id=_id(h, "staff", n), hospital_id=h, email=f"{n}@{h}.example",
                                           full_name="Dr Staff", role="doctor", password_hash="x"),
        "audit_events": lambda: m.AuditEvent(id=_id(h, "audit", n), hospital_id=h, action="test"),
        "doctor_profiles": lambda: m.DoctorProfile(user_id=_id(h, "staff", n), hospital_id=h),
        "patients": lambda: m.Patient(id=_id(h, "patient", n), hospital_id=h, mrn=f"MRN-{n}", full_name="Patient",
                                      sex="female"),
        "bookings": lambda: m.Booking(id=_id(h, "booking", n), hospital_id=h, external_id=_id(h, "ext", n),
                                      patient_dedan_id="DE000001", patient_name="Patient", visit_mode="video",
                                      scheduled_at=NOW, status="confirmed"),
        "patient_link_requests": lambda: m.PatientLinkRequest(id=_id(h, "link", n), hospital_id=h, patient_id=patient,
                                                              dedan_id="DE123456", method="card"),
        "visits": lambda: m.Visit(id=_id(h, "visit", n), hospital_id=h, patient_id=patient),
        "clinical_records": lambda: m.ClinicalRecord(id=_id(h, "record", n), hospital_id=h, patient_id=patient,
                                                     category="diagnosis", title="Malaria", occurred_at=NOW),
        "record_files": lambda: m.RecordFile(id=_id(h, "file", n), hospital_id=h, patient_id=patient,
                                             record_id=record, filename="a.pdf", content_type="application/pdf",
                                             size=1, sha256="0" * 64),
        "queue_days": lambda: m.QueueDay(id=_id(h, "queue", n), hospital_id=h, doctor_id=staff,
                                         day=date(2026, 10, 27) + timedelta(days=n)),
        "queue_entries": lambda: m.QueueEntry(id=_id(h, "entry", n), hospital_id=h, queue_id=_id(h, "queue", 1),
                                              ticket=n, patient_name="Patient"),
        "record_shares": lambda: m.RecordShare(id=_id(h, "share", n), hospital_id=h),
        "import_batches": lambda: m.ImportBatch(id=_id(h, "import", n), hospital_id=h, format="csv", plan="{}"),
        "onboarding_applications": lambda: m.OnboardingApplication(
            hospital_id=h if n == 1 else _id(h, "hospital", n), status="approved"),
        "onboarding_documents": lambda: m.OnboardingDocument(
            id=_id(h, "doc", n), hospital_id=h, kind=["moh_license", "owner_id"][n - 1], filename="a.pdf",
            content_type="application/pdf", size=1, sha256="0" * 64),
        "demo_bookings": lambda: m.DemoBooking(
            id=_id(h, "demo", n), hospital_id=h if n == 1 else _id(h, "hospital", n),
            slot_start=NOW + timedelta(hours=n, minutes=30 if h == A else 0),
            phone=f"+2519{1 if h == A else 2}000000{n}"),
        "prescription_dispenses": lambda: m.PrescriptionDispense(
            id=_id(h, "dispense", n), hospital_id=h, record_id=record, dedan_id="DE123456", pharmacy_name="Kenema",
            dispensed_at=NOW, status="open"),
        "patient_alerts": lambda: m.PatientAlert(id=_id(h, "alert", n), hospital_id=h, patient_id=patient, kind="allergy",
                                                 label="Penicillin"),
        "staff_sessions": lambda: m.StaffSession(id=_id(h, "session", n), token_hash=_id(h, "token", n),
                                                 user_id=staff, expires_at=NOW + timedelta(days=3650)),
        "shared_records": lambda: m.SharedRecord(id=_id(h, "shared", n), share_id=_id(h, "share", 1),
                                                 record_id="r", origin="Other", category="diagnosis", title="x",
                                                 occurred_at=NOW),
        # Version 1 is the hospital's active key (the encrypted columns above use it).
        "hospital_keys": lambda: m.HospitalKey(
            id=_id(h, "key", n), hospital_id=h, version=n, active=n == 1,
            wrapped_key=crypto.wrap(crypto.master_key(), os.urandom(32), h, n)),
        # The integration API (migration 0009).
        "integration_clients": lambda: m.IntegrationClient(
            id=_id(h, "client", n), hospital_id=h, client_id=_id(h, "client-id", n), name="Lab system",
            scopes="records.labs.write webhooks", mode="live", auth_method="client_secret", secret_hash="x",
            webhook_url="https://hooks.example.com/x", webhook_secret="whsec_x", created_by=staff),
        "integration_assertions": lambda: m.IntegrationAssertion(
            id=_id(h, "jti", n), hospital_id=h, client_pk=client, jti=f"jti-{n}", expires_at=NOW),
        "integration_requests": lambda: m.IntegrationRequest(
            id=_id(h, "request", n), hospital_id=h, client_pk=client, method="POST", path="/fhir", status=200,
            duration_ms=5, ip="203.0.113.1", at=NOW),
        "integration_resources": lambda: m.IntegrationResource(
            id=_id(h, "resource", n), hospital_id=h, client_pk=client, resource_type="Observation",
            resource_id=f"obs-{n}", content_hash="0" * 64, record_id=record),
        "integration_idempotency": lambda: m.IntegrationIdempotency(
            id=_id(h, "idem", n), hospital_id=h, client_pk=client, key=f"key-{n}", request_hash="0" * 64,
            status_code=200, response="{}"),
        "staff_recovery_codes": lambda: m.StaffRecoveryCode(
            id=_id(h, "recovery", n), hospital_id=h, user_id=staff, code_hash=f"{n}" * 64),
        "webhook_deliveries": lambda: m.WebhookDelivery(
            id=_id(h, "delivery", n), hospital_id=h, client_pk=client, event_id=f"evt-{n}",
            event_type="booking.created", body="{}", status="pending", attempts=0),
    }
    return rows[table]()


#: Insert order (parents first).
SEED_ORDER = ["hospitals", "hospital_keys", "departments", "staff_users", "staff_sessions", "audit_events", "doctor_profiles",
              "patients", "patient_alerts", "bookings", "patient_link_requests", "visits", "clinical_records",
              "record_files", "queue_days", "queue_entries", "record_shares", "shared_records", "import_batches",
              "onboarding_applications", "onboarding_documents", "demo_bookings", "prescription_dispenses",
              "integration_clients", "integration_assertions", "integration_requests", "integration_resources",
              "integration_idempotency", "webhook_deliveries", "staff_recovery_codes"]


#: A second row for the same hospital is not possible (or not a new hospital's).
ONE_PER_HOSPITAL = {"hospitals", "onboarding_applications", "demo_bookings", "doctor_profiles"}


def seed_id(table, h):
    return getattr(build(table, h, 1), PK[table])


@pytest.fixture
def two_hospitals(db):
    """One row of every policy table for each of two hospitals."""
    with platform_session() as session:
        for table in SEED_ORDER:
            for h in (A, B):
                session.add(build(table, h, 1))
                session.flush()


def visible(session, table):
    return set(session.scalars(text(f"SELECT {PK[table]} FROM {table}")))


def refused(exc) -> bool:
    if isinstance(exc, crypto.CryptoError):  # the encryption layer refused first: the parent is not visible
        return "is not visible" in str(exc)
    return "row-level security" in str(exc.orig)


# --- the model, app/rls.py and the migration agree (any database) --------------------------

def test_every_hospital_table_has_a_policy():
    tenant = {t for t, _ in rls.TENANT_TABLES}
    for name, table in Base.metadata.tables.items():
        if "hospital_id" in table.columns or name == "hospitals":
            assert name in tenant, f"{name} has hospital_id but no tenant policy"
        else:
            assert name in rls.CHILD_TABLES or name in rls.SHARED_TABLES, f"{name}: no policy and not shared"
    assert set(SEED_ORDER) == set(POLICY_TABLES)
    for table, (parent, fk) in rls.CHILD_TABLES.items():
        assert parent in tenant
        fks = {(f.parent.name, f.column.table.name) for f in Base.metadata.tables[table].foreign_keys}
        assert (fk, parent) in fks


def _migration(name="0007_row_level_security.py"):
    path = Path(__file__).resolve().parents[1] / "migrations" / "versions" / name
    spec = importlib.util.spec_from_file_location("rls_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_migration_installs_what_app_rls_describes():
    """0007 installed everything but the policies of hospital_keys, which 0008
    adds, and the integration API's tables and lookup, which 0009 adds."""
    migration, keys = _migration(), _migration("0008_encryption_at_rest.py")
    integrations = _migration("0009_integration_api.py")
    two_step = _migration("0010_two_step_verification.py")
    assert migration.TENANT_TABLES + keys.TENANT_TABLES + integrations.TENANT_TABLES + two_step.TENANT_TABLES         == rls.TENANT_TABLES
    assert migration.CHILD_TABLES == rls.CHILD_TABLES
    assert migration.SAME_HOSPITAL_REFERENCES + integrations.SAME_HOSPITAL_REFERENCES         + two_step.SAME_HOSPITAL_REFERENCES == rls.SAME_HOSPITAL_REFERENCES
    assert migration.FUNCTIONS + integrations.FUNCTIONS == rls.FUNCTIONS
    for later in (keys, integrations, two_step):
        assert later.PLATFORM_ROLE == rls.PLATFORM_ROLE and later.TENANT == rls.TENANT
    assert set(migration._parents()) | set(integrations.NEW_PARENTS) == set(rls.parents())
    assert sorted(migration.install_statements() + keys.policy_statements() + integrations.install_statements()
                  + two_step.install_statements()) == sorted(rls.install_statements())
    assert sorted(migration.drop_statements() + keys.drop_statements() + integrations.drop_statements()
                  + two_step.drop_statements()) == sorted(rls.drop_statements())


def test_every_reference_between_two_rows_of_a_hospital_is_a_composite_key():
    """Each foreign key from a hospital's table to another hospital-scoped
    table (not ``hospitals``) has its (hospital_id, x) twin, with the same
    ON DELETE."""
    declared = {(c, col): (p, d) for c, col, p, d in rls.SAME_HOSPITAL_REFERENCES}
    found = {}
    for name, table in Base.metadata.tables.items():
        if "hospital_id" not in table.columns:
            continue
        for fk in table.foreign_keys:
            parent = fk.column.table
            if parent.name != "hospitals" and "hospital_id" in parent.columns:
                found[(name, fk.parent.name)] = (parent.name, fk.ondelete)
    assert found == declared


# --- PostgreSQL ------------------------------------------------------------------------------

@pg_only
def test_the_app_connects_as_the_app_role(db):
    with session_scope(A) as session:
        user, superuser, bypass = session.execute(text(
            "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")).one()
        assert (user, superuser, bypass) == (APP_ROLE, False, False)
        # A member of the platform role, but without its rights until SET ROLE.
        inherit, can_set = session.execute(text(
            "SELECT m.inherit_option, m.set_option FROM pg_auth_members m "
            "WHERE m.roleid = CAST(:platform AS regrole) AND m.member = CAST(current_user AS regrole)"),
            {"platform": rls.PLATFORM_ROLE}).one()
        assert (inherit, can_set) == (False, True)
        assert session.scalar(text("SELECT rolcanlogin FROM pg_roles WHERE rolname = :r"),
                              {"r": rls.PLATFORM_ROLE}) is False


@pg_only
def test_every_policy_table_is_enabled_and_forced(db):
    with session_scope() as session:
        rows = dict((name, (enabled, forced)) for name, enabled, forced in session.execute(text(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'")))
        policies = set(session.execute(text("SELECT tablename, policyname, roles::text FROM pg_policies")))
    for table in POLICY_TABLES:
        assert rows[table] == (True, True), table
    assert policies == ({(t, rls.TENANT_POLICY, "{public}") for t in POLICY_TABLES}
                        | {(t, rls.PLATFORM_POLICY, "{%s}" % rls.PLATFORM_ROLE) for t in POLICY_TABLES})
    for table in rls.SHARED_TABLES:
        assert rows[table] == (False, False)


@pg_only
@pytest.mark.parametrize("table", POLICY_TABLES)
def test_tenant_sees_only_its_own_rows(two_hospitals, table):
    with session_scope(A) as session:
        assert visible(session, table) == {seed_id(table, A)}
        assert session.scalar(text(f"SELECT count(*) FROM {table} WHERE {PK[table]} = :id"),
                              {"id": seed_id(table, B)}) == 0
    with session_scope(B) as session:
        assert visible(session, table) == {seed_id(table, B)}


@pg_only
@pytest.mark.parametrize("table", POLICY_TABLES)
def test_tenant_cannot_insert_a_row_of_another_hospital(two_hospitals, table):
    # An encrypted child row whose parent is not visible is refused before the
    # database is asked (its hospital, hence its key, cannot be known).
    with pytest.raises((DBAPIError, crypto.CryptoError)) as caught:
        with session_scope(A) as session:
            session.add(build(table, B, 2))
            session.flush()
    assert refused(caught.value), caught.value
    if table in ONE_PER_HOSPITAL:
        return
    with session_scope(A) as session:  # the same row for its own hospital is accepted
        row = build(table, A, 2)
        session.add(row)
        session.flush()
        assert getattr(row, PK[table]) in visible(session, table)


@pg_only
@pytest.mark.parametrize("table", [t for t in POLICY_TABLES if t not in rls.APPEND_ONLY])
def test_tenant_cannot_change_or_delete_another_hospitals_rows(two_hospitals, table):
    pk = PK[table]
    with session_scope(A) as session:
        rights = rls.APP_RIGHTS.get(table, "DELETE, UPDATE")
        if "DELETE" in rights:  # data keys are never deleted (nor changed) by the app
            assert session.execute(text(f"DELETE FROM {table} WHERE {pk} = :id"),
                                   {"id": seed_id(table, B)}).rowcount == 0
        if "UPDATE" not in rights:
            return
        assert session.execute(text(f"UPDATE {table} SET {pk} = {pk} WHERE {pk} = :id"),
                               {"id": seed_id(table, B)}).rowcount == 0
    with platform_session() as session:
        assert seed_id(table, B) in visible(session, table)


@pg_only
def test_the_audit_log_is_append_only_and_per_hospital(two_hospitals):
    with session_scope(A) as session:  # its own hospital's entry: yes
        session.add(models.AuditEvent(hospital_id=A, action="test"))
    for statement in ("UPDATE audit_events SET action = 'x'", "DELETE FROM audit_events"):
        for scope in (lambda: session_scope(A), platform_session):
            with pytest.raises(DBAPIError) as caught:
                with scope() as session:
                    session.execute(text(statement))
            assert "permission denied" in str(caught.value.orig)
    with pytest.raises(DBAPIError) as caught:  # another hospital's: no
        with session_scope(A) as session:
            session.add(models.AuditEvent(hospital_id=B, action="forged"))
            session.flush()
    assert refused(caught.value)


@pg_only
def test_moving_a_row_to_another_hospital_is_refused(two_hospitals):
    with pytest.raises(DBAPIError) as caught:
        with session_scope(A) as session:
            session.execute(text("UPDATE patients SET hospital_id = :b WHERE id = :id"),
                            {"b": B, "id": seed_id("patients", A)})
    assert refused(caught.value)


@pg_only
@pytest.mark.parametrize("table", POLICY_TABLES)
def test_no_tenant_sees_nothing_and_writes_nothing(two_hospitals, table):
    with session_scope() as session:
        assert visible(session, table) == set()
    with pytest.raises((DBAPIError, crypto.CryptoError)) as caught:
        with session_scope() as session:
            session.add(build(table, A, 2))
            session.flush()
    assert refused(caught.value)


@pg_only
def test_a_raw_connection_without_the_app_settings_sees_nothing(two_hospitals):
    """Fails closed outside app.db too: a bare connection as the app role."""
    from app.db import database_url

    engine = create_engine(database_url())
    try:
        with engine.connect() as connection:
            for table in POLICY_TABLES:
                assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0, table
    finally:
        engine.dispose()


@pg_only
@pytest.mark.parametrize("tenant", ["", A])
def test_a_settable_flag_opens_nothing(two_hospitals, tenant):
    """No setting (GUC) is a way past the policies: setting flags as the app
    role, which any query could do, shows nothing more."""
    with session_scope(tenant) as session:
        for name, value in (("app.scope", "platform"), ("app.platform", "on"), ("app.bypass", "on")):
            session.execute(text("SELECT set_config(:n, :v, true)"), {"n": name, "v": value})
        expected = {seed_id("patients", A)} if tenant else set()
        assert visible(session, "patients") == expected
        assert visible(session, "hospitals") == ({A} if tenant else set())
    # row_security = off does not switch the policies off for the app role: it errors.
    with pytest.raises(DBAPIError):
        with session_scope(tenant) as session:
            session.execute(text("SELECT set_config('row_security', 'off', true)"))
            session.execute(text("SELECT count(*) FROM patients"))


@pg_only
def test_a_query_without_a_hospital_filter_still_sees_one_hospital(two_hospitals):
    with session_scope(A) as session:
        assert {p.hospital_id for p in session.scalars(select(models.Patient))} == {A}
        assert {s.hospital_id for s in session.scalars(select(models.StaffUser))} == {A}
        assert session.get(models.Patient, seed_id("patients", B)) is None


@pg_only
def test_platform_scope_sees_every_hospital(two_hospitals):
    with platform_session() as session:
        assert session.scalar(text("SELECT current_user")) == rls.PLATFORM_ROLE
        for table in POLICY_TABLES:
            assert visible(session, table) == {seed_id(table, A), seed_id(table, B)}, table


@pg_only
def test_platform_scope_only_where_used(two_hospitals):
    from app.db import database_url

    # One pooled connection for everything: nothing carries over between transactions.
    engine = create_engine(database_url(), pool_size=1, max_overflow=0)
    try:
        with Session(engine, info={"scope": "platform"}) as session:
            assert len(visible(session, "patients")) == 2
            session.commit()
            # A new transaction in the same session acts for Endod again ...
            assert session.scalar(text("SELECT current_user")) == rls.PLATFORM_ROLE
            session.commit()
        with Session(engine, info={"hospital_id": A}) as session:
            # ... but the next session on that connection is back to the app role.
            assert session.scalar(text("SELECT current_user")) == APP_ROLE
            assert visible(session, "patients") == {seed_id("patients", A)}
            session.commit()
        with Session(engine) as session:
            assert visible(session, "patients") == set()
            assert session.scalar(text("SELECT current_setting('app.hospital_id', true)")) in ("", None)
    finally:
        engine.dispose()


@pg_only
def test_a_staff_request_cannot_reach_another_hospital(client, two_hospitals):
    """Through the API: hospital A's admin, B's patient."""
    from conftest import make_staff, sign_in

    make_staff(A, "admin@a.example")
    headers = sign_in(client, "admin@a.example")
    assert client.get(f"/patients/{seed_id('patients', B)}", headers=headers).status_code == 404
    assert {p["id"] for p in client.get("/patients", headers=headers).json()["items"]} == {seed_id("patients", A)}


# --- composite foreign keys -------------------------------------------------------------------

@pg_only
@pytest.mark.parametrize("child,column,parent,on_delete", rls.SAME_HOSPITAL_REFERENCES)
def test_a_row_cannot_point_at_another_hospitals_row(two_hospitals, child, column, parent, on_delete):
    """Even acting for Endod (every row visible), hospital A's row cannot
    refer to hospital B's: the composite key refuses it."""
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError) as caught:
        with platform_session() as session:
            target = seed_id(parent, B)
            if child == "doctor_profiles":  # B's seeded doctor has a profile already
                session.add(build("staff_users", B, 3))
                session.flush()
                target = _id(B, "staff", 3)
            row = build(child, A, 1 if child in ONE_PER_HOSPITAL else 2)
            if child in ONE_PER_HOSPITAL:
                session.execute(text(f"DELETE FROM {child} WHERE {PK[child]} = :id"), {"id": getattr(row, PK[child])})
            setattr(row, column, target)
            session.add(row)
            session.flush()
    assert rls.fk_name(child, column) in str(caught.value.orig)


@pg_only
def test_deleting_a_parent_still_clears_or_cascades(two_hospitals):
    with platform_session() as session:
        session.execute(text("UPDATE patients SET department_id = :d WHERE id = :p"),
                        {"d": seed_id("departments", A), "p": seed_id("patients", A)})
        session.execute(text("DELETE FROM departments WHERE id = :d"), {"d": seed_id("departments", A)})
        assert session.execute(text("SELECT department_id, hospital_id FROM patients WHERE id = :p"),
                               {"p": seed_id("patients", A)}).one() == (None, A)
        session.execute(text("DELETE FROM patients WHERE id = :p"), {"p": seed_id("patients", A)})
        assert session.scalar(text("SELECT count(*) FROM clinical_records WHERE hospital_id = :h"), {"h": A}) == 0


# --- the narrow lookups --------------------------------------------------------------------------

@pg_only
def test_sign_in_lookups_name_only_a_hospital(two_hospitals):
    with session_scope() as session:
        assert rls.hospital_of_email(session, "1@hospital-b.example") == B
        assert rls.hospital_of_email(session, "nobody@example.com") is None
        assert rls.hospital_of_token(session, _id(A, "token", 1)) == A
        assert rls.hospital_of_token(session, "unknown") is None
        # The lookups did not open anything else up.
        assert visible(session, "staff_users") == set()
    with platform_session() as session:  # an inactive account, a revoked and an expired session
        session.execute(text("UPDATE staff_users SET active = false WHERE id = :u"), {"u": _id(B, "staff", 1)})
        session.execute(text("UPDATE staff_sessions SET revoked_at = now() WHERE id = :s"),
                        {"s": _id(A, "session", 1)})
        session.add(models.StaffSession(id="expired", token_hash="expired", user_id=_id(A, "staff", 1),
                                        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    with session_scope() as session:
        # A deactivated account is still found (its attempts are counted), but
        # its sessions are not.
        assert rls.hospital_of_email(session, "1@hospital-b.example") == B
        assert rls.hospital_of_token(session, _id(B, "token", 1)) is None
        assert rls.hospital_of_token(session, _id(A, "token", 1)) is None
        assert rls.hospital_of_token(session, "expired") is None


@pg_only
def test_the_lookups_are_pinned_and_not_public(db):
    with platform_session() as session:
        rows = session.execute(text(
            "SELECT p.proname, p.prosecdef, p.proconfig, pg_get_userbyid(p.proowner), "
            "COALESCE(bool_or(a.grantee = 0), false) FROM pg_proc p "
            "LEFT JOIN LATERAL aclexplode(p.proacl) a ON true "
            "WHERE p.pronamespace = 'public'::regnamespace GROUP BY 1, 2, 3, 4")).all()
    assert {r[0] for r in rows} == {name.split("(")[0] for name in rls.function_names()}
    for name, definer, config, owner, public in rows:
        assert definer and owner == rls.PLATFORM_ROLE and not public, name
        assert config == ["search_path=public, pg_temp"], name


@pg_only
def test_sign_up_needs_no_platform_transaction(client, db, monkeypatch):
    """The public sign-up runs as the new hospital only (codes through
    hospital_code_taken): no platform session on an unauthenticated path."""
    import importlib

    from app import db as dbmod

    opened = []
    real = dbmod.platform_session

    def watched():
        opened.append(1)
        return real()

    for module in ("app.db", "app.api.onboarding", "app.api.application", "app.auth", "app.onboarding", "app.rls"):
        mod = importlib.import_module(module)
        if hasattr(mod, "platform_session"):
            monkeypatch.setattr(mod, "platform_session", watched)
    body = {"hospital_name": "Tikur Anbessa", "admin_name": "Abebe", "admin_email": "a@ta.example",
            "password": "StaffPass123!x"}
    first = client.post("/onboarding", json=body)
    second = client.post("/onboarding", json={**body, "admin_email": "b@ta.example"})
    assert first.status_code == second.status_code == 201, (first.text, second.text)
    assert first.json()["hospital"]["code"] != second.json()["hospital"]["code"]
    assert opened == []


# --- roles: setup and refusal ---------------------------------------------------------------------

@pg_only
def test_the_app_role_cannot_change_the_schema_or_the_policies(db):
    for statement in ("ALTER TABLE patients DISABLE ROW LEVEL SECURITY",
                      "DROP POLICY tenant_isolation ON patients",
                      "CREATE TABLE sneaky (id int)"):
        with pytest.raises(DBAPIError):
            with session_scope(A) as session:
                session.execute(text(statement))


@pg_only
def test_the_api_and_worker_refuse_the_owner(db, monkeypatch):
    from fastapi.testclient import TestClient

    from app import db as dbmod
    from app.main import create_app

    dbmod.check_connection_role()  # the app role: fine
    monkeypatch.setenv("HOSPITAL_DATABASE_URL", postgres_url())  # the owner (a superuser here)
    dbmod.reset_engine()
    with pytest.raises(RuntimeError, match="superuser"):
        dbmod.check_connection_role()
    with pytest.raises(RuntimeError, match="superuser"):
        with TestClient(create_app()):
            pass


@pg_only
def test_migrations_fail_without_the_app_role(db):
    engine = create_engine(postgres_url())
    try:
        with pytest.raises(RuntimeError, match="does not exist"):
            with engine.begin() as connection:
                rls.set_up_app_role(connection, "hospital_app_missing", None, Base.metadata.tables)
    finally:
        engine.dispose()


@pg_only
def test_migrations_set_up_the_app_role_on_an_existing_database(db):
    """On a database that has the tables but not the role yet (production
    before this change): the role is created and granted, idempotently."""
    engine = create_engine(postgres_url())
    role = "hospital_app_check"
    password = "pa:ss%word'with\"quotes"

    def drop_role():
        with engine.begin() as connection:
            if connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).scalar():
                connection.exec_driver_sql(f"DROP OWNED BY {role}")
                connection.exec_driver_sql(f"DROP ROLE {role}")

    try:
        drop_role()
        with engine.begin() as connection:
            rls.set_up_app_role(connection, role, password, Base.metadata.tables)
            rls.set_up_app_role(connection, role, password, Base.metadata.tables)  # idempotent
            flags = connection.execute(text("SELECT rolsuper, rolbypassrls, rolcanlogin FROM pg_roles "
                                            "WHERE rolname = :r"), {"r": role}).one()
            assert tuple(flags) == (False, False, True)
            assert connection.execute(text("SELECT has_table_privilege(:r, 'patients', 'DELETE')"),
                                      {"r": role}).scalar()
            assert not connection.execute(text("SELECT has_table_privilege(:r, 'audit_events', 'DELETE')"),
                                          {"r": role}).scalar()
            assert connection.execute(text("SELECT has_function_privilege(:r, 'hospital_of_staff_email(text)', "
                                            "'EXECUTE')"), {"r": role}).scalar()
        check = create_engine(engine.url.set(username=role, password=password))
        try:
            with check.connect() as connection:
                assert connection.execute(text("SELECT count(*) FROM patients")).scalar() == 0
        finally:
            check.dispose()
    finally:
        drop_role()
        engine.dispose()


# --- the event outbox -------------------------------------------------------------------------------

@pg_only
def test_the_app_can_only_append_to_the_outbox_and_the_worker_publishes(two_hospitals):
    """Events (patient names, phones, clinical payloads of every hospital) are
    written in tenant transactions but read, marked and deleted only by the
    worker, as the platform role."""
    import fakeredis

    from app import eventbus

    with session_scope(A) as session:  # a staff transaction emits
        eventbus.emit(session, "test.event", {"hospital_id": A, "patient_name": "Abebe"})
    for statement in ("SELECT count(*) FROM outbox_events", "UPDATE outbox_events SET type = 'x'",
                      "DELETE FROM outbox_events"):
        for tenant in ("", A):
            with pytest.raises(DBAPIError) as caught:
                with session_scope(tenant) as session:
                    session.execute(text(statement))
            assert "permission denied" in str(caught.value.orig), statement
    bus = fakeredis.FakeRedis(decode_responses=True)
    assert eventbus.publish_pending(bus) == 1
    assert bus.xlen(eventbus.STREAM_OUT) == 1
    with platform_session() as session:
        assert session.scalar(text("SELECT count(*) FROM outbox_events WHERE published_at IS NULL")) == 0


# --- pooled connections -----------------------------------------------------------------------------

@pg_only
def test_a_session_level_role_or_setting_never_reaches_the_next_checkout(db):
    from app import db as dbmod

    dbmod.reset_engine()
    engine = dbmod.get_engine()
    with engine.connect() as connection:
        pid = connection.execute(text("SELECT pg_backend_pid()")).scalar()
        connection.exec_driver_sql(f"SET ROLE {rls.PLATFORM_ROLE}")  # session level, not LOCAL
        connection.execute(text("SELECT set_config('app.hospital_id', :h, false)"), {"h": B})
        connection.commit()
        assert connection.execute(text("SELECT current_user")).scalar() == rls.PLATFORM_ROLE
    with engine.connect() as connection:  # the same pooled connection, cleaned
        assert connection.execute(text("SELECT pg_backend_pid()")).scalar() == pid
        assert connection.execute(text("SELECT current_user")).scalar() == APP_ROLE
        assert connection.execute(text("SELECT current_setting('app.hospital_id', true)")).scalar() in ("", None)


# --- migration safety -------------------------------------------------------------------------------

def test_the_migration_checks_the_same_rows_as_app_rls():
    # 0009's tables are new (empty) when their composite keys are added: nothing to check there.
    new = {child for name in ("0009_integration_api.py", "0010_two_step_verification.py")
           for child, *_rest in _migration(name).SAME_HOSPITAL_REFERENCES}
    assert _migration().cross_hospital_queries() == [q for q in rls.cross_hospital_queries() if q[0] not in new]


@pg_only
def test_existing_cross_hospital_rows_stop_the_migration_with_their_ids(two_hospitals):
    engine = create_engine(postgres_url())  # the owner, as the migration runs
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.exec_driver_sql(f"ALTER TABLE clinical_records DROP CONSTRAINT "
                                       f"{rls.fk_name('clinical_records', 'patient_id')}")
            connection.execute(text("UPDATE clinical_records SET patient_id = :b WHERE id = :r"),
                               {"b": seed_id("patients", B), "r": seed_id("clinical_records", A)})
            with pytest.raises(RuntimeError) as caught:
                rls.check_same_hospital(connection)
            transaction.rollback()
    finally:
        engine.dispose()
    assert f"clinical_records.patient_id: {seed_id('clinical_records', A)}" in str(caught.value)


@pg_only
def test_the_app_password_is_stored_as_a_scram_verifier(db):
    engine = create_engine(postgres_url())
    try:
        with engine.connect() as connection:
            stored = connection.execute(text("SELECT rolpassword FROM pg_authid WHERE rolname = :r"),
                                        {"r": APP_ROLE}).scalar()
    finally:
        engine.dispose()
    assert stored.startswith("SCRAM-SHA-256$4096:")
    with pytest.raises(RuntimeError, match="ASCII"):
        rls.scram_verifier("pässword")


# --- encryption at rest -----------------------------------------------------------------------------

@pg_only
def test_data_keys_can_only_be_added_and_activated(two_hospitals):
    key = seed_id("hospital_keys", A)
    attempts = [(lambda: session_scope(A), "UPDATE hospital_keys SET wrapped_key = 'x' WHERE id = :id"),
                (lambda: session_scope(A), "UPDATE hospital_keys SET active = false WHERE id = :id"),
                (lambda: session_scope(A), "DELETE FROM hospital_keys WHERE id = :id"),
                (platform_session, "UPDATE hospital_keys SET wrapped_key = 'x' WHERE id = :id"),
                (platform_session, "UPDATE hospital_keys SET version = 9 WHERE id = :id"),
                (platform_session, "DELETE FROM hospital_keys WHERE id = :id")]
    for scope, statement in attempts:
        with pytest.raises(DBAPIError) as caught:
            with scope() as session:
                session.execute(text(statement), {"id": key})
        assert "permission denied" in str(caught.value.orig), statement
    with platform_session() as session:  # Endod activates a version (rotation)
        assert session.execute(text("UPDATE hospital_keys SET active = true WHERE id = :id"),
                               {"id": key}).rowcount == 1
    with session_scope(A) as session:  # the app adds a hospital's key
        session.add(build("hospital_keys", A, 2))


@pg_only
def test_the_downgrade_counts_ciphertext_that_row_level_security_hides(two_hospitals):
    """A login held by FORCE ROW LEVEL SECURITY sees no row; the downgrade
    counts as hospital_platform and still finds them (and refuses)."""
    migration = _migration("0008_encryption_at_rest.py")
    with platform_session() as session:
        session.execute(text("UPDATE record_files SET key_version = 1"))
    with session_scope() as session:
        connection = session.connection()
        assert connection.execute(text("SELECT count(*) FROM clinical_records")).scalar() == 0
        left = migration.encrypted_left(connection)
        assert "clinical_records.title: 2" in left and "record_files (files): 2" in left
        assert connection.execute(text("SELECT current_user")).scalar() == APP_ROLE  # role reset afterwards


@pg_only
def test_decrypt_existing_sees_the_api_still_connected(two_hospitals):
    from app import rekey
    from app.db import database_url, reset_engine

    reset_engine()  # this test's own pooled connections are gone
    rekey.require_services_stopped()
    other = create_engine(database_url(), connect_args={"application_name": "hospital-app"})
    try:
        with other.connect():
            with pytest.raises(rekey.ServiceRunning, match="hospital-app"):
                rekey.require_services_stopped()
    finally:
        other.dispose()

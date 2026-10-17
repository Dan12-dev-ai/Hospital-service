import pytest

from conftest import PASSWORD, make_hospital, make_staff, sign_in


class TestDepartments:
    def test_create_list_and_filter(self, client, admin):
        assert client.post("/departments", headers=admin,
                           json={"kind": "department", "name": "Internal Medicine", "name_am": "ሕክምና"}).status_code == 201
        assert client.post("/departments", headers=admin,
                           json={"kind": "ward", "name": "Ward B", "capacity": 40}).status_code == 201
        assert len(client.get("/departments", headers=admin).json()) == 2
        wards = client.get("/departments?kind=ward", headers=admin).json()
        assert [w["name"] for w in wards] == ["Ward B"] and wards[0]["capacity"] == 40

    @pytest.mark.parametrize("body", [
        {"kind": "galaxy", "name": "Space"},
        {"kind": "department", "name": "Cardiology", "capacity": 10},
        {"kind": "ward", "name": "W", "capacity": 5},
    ])
    def test_invalid_departments(self, client, admin, body):
        assert client.post("/departments", headers=admin, json=body).status_code in (400, 422)

    def test_duplicate_is_409_and_rename_works(self, client, admin):
        first = client.post("/departments", headers=admin, json={"kind": "clinic", "name": "OPD Central"}).json()
        assert client.post("/departments", headers=admin, json={"kind": "clinic", "name": "OPD Central"}).status_code == 409
        renamed = client.patch(f"/departments/{first['id']}", headers=admin, json={"name": "OPD Central Desk"})
        assert renamed.json()["name"] == "OPD Central Desk"
        hidden = client.patch(f"/departments/{first['id']}", headers=admin, json={"active": False})
        assert hidden.json()["active"] is False
        assert client.get("/departments", headers=admin).json() == []

    def test_only_admins_change_departments(self, client, hospital):
        make_staff(hospital, "doc@sph.example", role="doctor")
        doctor = sign_in(client, "doc@sph.example")
        assert client.post("/departments", headers=doctor, json={"kind": "clinic", "name": "X Desk"}).status_code == 403
        assert client.get("/departments", headers=doctor).status_code == 200


class TestStaff:
    def test_create_with_a_one_time_password(self, client, admin):
        resp = client.post("/staff", headers=admin, json={
            "email": "Hiwot@sph.example", "full_name": "Dr. Hiwot M. Gebre", "role": "doctor"})
        assert resp.status_code == 201
        body = resp.json()
        assert body["email"] == "hiwot@sph.example" and body["must_change_password"] is True
        headers = sign_in(client, "hiwot@sph.example", body["temporary_password"])
        assert client.get("/hospital", headers=headers).status_code == 403  # must change first

    @pytest.mark.parametrize("body", [
        {"email": "x@sph.example", "full_name": "X Y", "role": "janitor"},
        {"email": "not-an-email", "full_name": "X Y", "role": "nurse"},
        {"email": "x@sph.example", "full_name": "X Y", "role": "nurse", "department_id": "nope"},
    ])
    def test_invalid_staff(self, client, admin, body):
        assert client.post("/staff", headers=admin, json=body).status_code in (400, 422)

    def test_blank_optional_fields_mean_none(self, client, admin):
        resp = client.post("/staff", headers=admin, json={
            "email": "n@sph.example", "full_name": "  Nurse Almaz  ", "role": "nurse",
            "department_id": "", "phone": " ", "full_name_am": ""})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["full_name"] == "Nurse Almaz" and body["department_id"] is None and body["phone"] is None
        cleared = client.patch(f"/staff/{body['id']}", headers=admin, json={"department_id": ""})
        assert cleared.status_code == 200 and cleared.json()["department_id"] is None

    @pytest.mark.parametrize("path_body", [
        ("/staff", {"email": "b@sph.example", "full_name": "   ", "role": "nurse"}),
        ("/departments", {"kind": "clinic", "name": "  "}),
    ])
    def test_blank_names_are_refused(self, client, admin, path_body):
        path, body = path_body
        assert client.post(path, headers=admin, json=body).status_code == 422

    def test_blank_names_are_refused_on_update(self, client, admin):
        me = client.get("/auth/me", headers=admin).json()
        assert client.patch(f"/staff/{me['id']}", headers=admin, json={"full_name": " "}).status_code == 422
        assert client.patch("/hospital", headers=admin, json={"name": "  "}).status_code == 422

    def test_duplicate_email_is_409(self, client, admin):
        assert client.post("/staff", headers=admin, json={
            "email": "admin@sph.example", "full_name": "Again", "role": "nurse"}).status_code == 409

    def test_deactivating_ends_sessions(self, client, admin, hospital):
        nurse_id = make_staff(hospital, "nurse@sph.example", role="nurse")
        nurse = sign_in(client, "nurse@sph.example")
        assert client.patch(f"/staff/{nurse_id}", headers=admin, json={"active": False}).status_code == 200
        assert client.get("/auth/me", headers=nurse).status_code in (401, 403)

    def test_last_admin_cannot_be_removed(self, client, admin):
        me = client.get("/auth/me", headers=admin).json()
        assert client.patch(f"/staff/{me['id']}", headers=admin, json={"role": "nurse"}).status_code == 400
        assert client.patch(f"/staff/{me['id']}", headers=admin, json={"active": False}).status_code == 400

    def test_reset_password(self, client, admin, hospital):
        nurse_id = make_staff(hospital, "nurse@sph.example", role="nurse")
        old = sign_in(client, "nurse@sph.example")
        reset = client.post(f"/staff/{nurse_id}/reset-password", headers=admin).json()
        assert client.get("/auth/me", headers=old).status_code == 401
        new = sign_in(client, "nurse@sph.example", reset["temporary_password"])
        assert client.get("/auth/me", headers=new).json()["must_change_password"] is True

    def test_other_hospitals_staff_are_out_of_reach(self, client, admin):
        other = make_hospital(code="BLH", name="Black Lion")
        stranger = make_staff(other, "nurse@blh.example", role="nurse")
        assert client.patch(f"/staff/{stranger}", headers=admin, json={"role": "admin"}).status_code == 404
        assert client.post(f"/staff/{stranger}/reset-password", headers=admin).status_code == 404

    def test_non_admins_cannot_manage_staff(self, client, hospital):
        make_staff(hospital, "nurse@sph.example", role="nurse")
        nurse = sign_in(client, "nurse@sph.example")
        assert client.get("/staff", headers=nurse).status_code == 403


def test_hospital_settings(client, admin):
    resp = client.patch("/hospital", headers=admin, json={"name_am": "ቅዱስ ጳውሎስ", "timezone": "Africa/Addis_Ababa"})
    assert resp.status_code == 200 and resp.json()["name_am"] == "ቅዱስ ጳውሎስ"
    assert client.patch("/hospital", headers=admin, json={"timezone": "Mars/Base"}).status_code == 400


def test_errors_have_one_shape(client, admin):
    body = client.post("/departments", headers=admin, json={"kind": "ward"}).json()
    assert body["error_code"] == "VALIDATION_ERROR" and "name" in body["error"]


def test_unknown_paths_use_the_error_shape(client):
    body = client.get("/no-such-thing").json()
    assert body["error_code"] == "HTTP_404"


def test_bootstrap_cli(db, capsys):
    from app import cli

    assert cli.main(["bootstrap", "--code", "tkh", "--name", "Tikur Anbessa", "--admin-email", "Root@TKH.example",
                     "--admin-name", "Root"]) == 0
    printed = capsys.readouterr().out
    assert "TKH" in printed and "one-time password" in printed
    assert "root@tkh.example" in printed
    with pytest.raises(SystemExit):
        cli.bootstrap("TKH", "Again", None, "x@tkh.example", "Xy")
    with pytest.raises(SystemExit):
        cli.bootstrap("ABC", "Hospital", None, "not-an-email", "Admin")
    with pytest.raises(SystemExit):
        cli.bootstrap("ABC", "Hospital", None, "  ROOT@tkh.example ", "Admin")  # same email, other spelling


def test_migration_matches_the_models(tmp_path, monkeypatch):
    """`alembic upgrade head` builds exactly the tables the models describe."""
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext

    from app import db as dbmod
    from app.db import Base, get_engine

    monkeypatch.setenv("HOSPITAL_DATABASE_URL", f"sqlite:///{tmp_path / 'migrated.db'}")
    dbmod.reset_engine()
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(config, "head")
    with get_engine().connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    dbmod.reset_engine()
    assert diff == []

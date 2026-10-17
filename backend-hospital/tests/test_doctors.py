from conftest import make_hospital, make_staff, sign_in


def test_directory_profile_duty_and_load(client, admin, hospital):
    dept = client.post("/departments", headers=admin, json={"kind": "department", "name": "Internal Medicine"}).json()
    hiwot = make_staff(hospital, "hiwot@sph.example", role="doctor")
    make_staff(hospital, "abebe@sph.example", role="doctor")
    make_staff(hospital, "nurse@sph.example", role="nurse")
    client.patch(f"/staff/{hiwot}", headers=admin, json={"department_id": dept["id"]})

    profile = client.patch(f"/doctors/{hiwot}/profile", headers=admin, json={
        "license_number": "LIC-ETH-40812", "credentials": "MD, FACP", "specialty": "Gastroenterology",
        "rank": "senior-consultant", "extension": "4012", "daily_capacity": 4})
    assert profile.status_code == 200, profile.text
    assert profile.json()["department"]["name"] == "Internal Medicine"

    doctor = sign_in(client, "hiwot@sph.example")
    duty = client.patch(f"/doctors/{hiwot}/duty", headers=doctor,
                        json={"duty_status": "on-duty", "duty_location": "OPD Rm 204"}).json()
    assert duty["duty_status"] == "on-duty" and duty["duty_location"] == "OPD Rm 204"

    patient = client.post("/patients", headers=admin, json={"full_name": "Almaz Tefera", "sex": "female"}).json()
    client.patch(f"/patients/{patient['id']}", headers=admin, json={"attending_doctor_id": hiwot})

    listing = client.get("/doctors", headers=doctor).json()
    assert listing["counts"] == {"all": 2, "on-duty": 1, "in-consultation": 0, "on-call": 0, "off-duty": 1}
    by_id = {d["id"]: d for d in listing["items"]}
    assert by_id[hiwot]["load"] == {"patients": 1, "capacity": 4, "percent": 25}
    assert len(by_id) == 2  # nurses are not listed

    on_duty = client.get("/doctors", headers=doctor, params={"status": "on-duty"}).json()
    assert [d["id"] for d in on_duty["items"]] == [hiwot] and on_duty["counts"]["all"] == 2
    for q in ("lic-eth", "gastro", "internal", "hiwot"):
        assert [d["id"] for d in client.get("/doctors", headers=doctor, params={"q": q}).json()["items"]] == [hiwot], q
    assert client.get("/doctors", headers=doctor, params={"rank": "senior-consultant"}).json()["counts"]["all"] == 1


def test_off_duty_clears_the_location(client, admin, hospital):
    doc = make_staff(hospital, "doc@sph.example", role="doctor")
    client.patch(f"/doctors/{doc}/duty", headers=admin, json={"duty_status": "on-call", "duty_location": "OR-3"})
    off = client.patch(f"/doctors/{doc}/duty", headers=admin,
                       json={"duty_status": "off-duty", "duty_location": "OR-3"}).json()
    assert off["duty_location"] is None
    assert client.patch(f"/doctors/{doc}/duty", headers=admin, json={"duty_status": "napping"}).status_code == 400


def test_who_may_change_duty_and_profiles(client, hospital):
    one = make_staff(hospital, "one@sph.example", role="doctor")
    two = make_staff(hospital, "two@sph.example", role="doctor")
    make_staff(hospital, "desk@sph.example", role="reception")
    doctor = sign_in(client, "one@sph.example")
    desk = sign_in(client, "desk@sph.example")
    assert client.patch(f"/doctors/{two}/duty", headers=doctor, json={"duty_status": "on-duty"}).status_code == 403
    assert client.patch(f"/doctors/{one}/duty", headers=desk, json={"duty_status": "on-duty"}).status_code == 403
    assert client.patch(f"/doctors/{one}/profile", headers=doctor, json={"specialty": "X"}).status_code == 403


def test_licence_numbers_are_unique(client, admin, hospital):
    one = make_staff(hospital, "one@sph.example", role="doctor")
    two = make_staff(hospital, "two@sph.example", role="doctor")
    assert client.patch(f"/doctors/{one}/profile", headers=admin, json={"license_number": "LIC-1"}).status_code == 200
    assert client.patch(f"/doctors/{two}/profile", headers=admin, json={"license_number": "LIC-1"}).status_code == 409
    assert client.patch(f"/doctors/{two}/profile", headers=admin, json={"rank": "intern"}).status_code == 400


def test_other_hospitals_doctors_are_out_of_reach(client, admin):
    other = make_hospital(code="BLH", name="Black Lion")
    stranger = make_staff(other, "doc@blh.example", role="doctor")
    assert client.get(f"/doctors/{stranger}", headers=admin).status_code == 404
    assert client.patch(f"/doctors/{stranger}/duty", headers=admin, json={"duty_status": "on-duty"}).status_code == 404
    assert client.get("/doctors", headers=admin).json()["items"] == []


def test_phone_search_takes_local_formats(client, admin, hospital):
    doc = make_staff(hospital, "doc@sph.example", role="doctor")
    client.patch(f"/staff/{doc}", headers=admin, json={"phone": "0911 000 111"})
    for q in ("0911000111", "+251911000111", "0911 000"):
        assert [d["id"] for d in client.get("/doctors", headers=admin, params={"q": q}).json()["items"]] == [doc], q


def test_a_doctor_with_patients_keeps_the_doctor_role(client, admin, hospital):
    doc = make_staff(hospital, "doc@sph.example", role="doctor")
    patient = client.post("/patients", headers=admin, json={"full_name": "Almaz Tefera", "sex": "female"}).json()
    client.patch(f"/patients/{patient['id']}", headers=admin, json={"attending_doctor_id": doc})
    resp = client.patch(f"/staff/{doc}", headers=admin, json={"role": "pharmacist"})
    assert resp.status_code == 400 and "Assign them another doctor" in resp.json()["error"]
    client.patch(f"/patients/{patient['id']}", headers=admin, json={"status": "discharged"})
    assert client.patch(f"/staff/{doc}", headers=admin, json={"role": "pharmacist"}).status_code == 200


def test_deactivating_a_doctor_takes_them_off_duty(client, admin, hospital):
    doc = make_staff(hospital, "doc@sph.example", role="doctor")
    client.patch(f"/doctors/{doc}/duty", headers=admin, json={"duty_status": "on-duty", "duty_location": "ER"})
    client.patch(f"/staff/{doc}", headers=admin, json={"active": False})
    shown = client.get(f"/doctors/{doc}", headers=admin).json()
    assert shown["duty_status"] == "off-duty" and shown["duty_location"] is None


def test_outpatients_count_toward_load_only_on_the_day(client, admin, hospital):
    from datetime import timedelta

    from sqlalchemy import update

    from app.db import session_scope, utcnow
    from app.models import Patient

    doc = make_staff(hospital, "doc@sph.example", role="doctor")
    for name in ("Almaz Tefera", "Dawit Bekele"):
        p = client.post("/patients", headers=admin, json={"full_name": name, "sex": "female"}).json()
        client.patch(f"/patients/{p['id']}", headers=admin, json={"attending_doctor_id": doc})
    assert client.get(f"/doctors/{doc}", headers=admin).json()["load"]["patients"] == 2
    with session_scope() as session:
        session.execute(update(Patient).where(Patient.full_name == "Dawit Bekele")
                        .values(status_changed_at=utcnow() - timedelta(days=2)))
    assert client.get(f"/doctors/{doc}", headers=admin).json()["load"]["patients"] == 1

from ccauth.auth import (
    _parse_dt,
    _get_app_cred_id_and_secret,
    write_openrc_file,
    write_clouds_yaml,
)


def test_parse_dt_z_suffix():
    dt = _parse_dt("2020-01-01T00:00:00Z")
    assert dt.tzinfo is not None


def test_get_app_cred_id_and_secret_variants():
    a = {"id": "i", "secret": "s"}
    assert _get_app_cred_id_and_secret(a) == ("i", "s")
    b = {"application_credential_id": "i2", "application_credential_secret": "s2"}
    assert _get_app_cred_id_and_secret(b) == ("i2", "s2")


def test_write_openrc_and_clouds_yaml(tmp_path):
    app_cred = {"id": "id1", "application_credential_secret": "sec1", "name": "n"}
    openrc_path = tmp_path / "openrc.sh"
    write_openrc_file(app_cred, openrc_path, region_name="R", auth_url="https://k")
    content = openrc_path.read_text()
    assert "OS_APPLICATION_CREDENTIAL_ID" in content

    clouds_path = tmp_path / "clouds.yaml"
    write_clouds_yaml(app_cred, clouds_path, cloud_name="c1", region_name="R", auth_url="https://k")
    cy = clouds_path.read_text()
    assert "application_credential_secret" in cy

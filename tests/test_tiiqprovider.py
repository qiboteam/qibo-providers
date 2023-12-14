from pathlib import Path
import tarfile
from typing import Callable
from unittest.mock import patch, Mock

import pytest
from requests.exceptions import HTTPError

import tests.utils_test_tiiqprovider as utils

from qibo_tii_provider import tiiprovider
from qibo_tii_provider.config import MalformedResponseError, JobPostServerError

PKG = "qibo_tii_provider.tiiprovider"
LOCAL_URL = "http://localhost:8000/"
FAKE_QIBO_VERSION = "0.0.1"
FAKE_PID = "123"
ARCHIVE_NAME = "file.tar.gz"


@pytest.fixture(autouse=True)
def mock_qrccluster_ip():
    """Ensure that all the requests are made on localhost"""
    with patch(f"{PKG}.BASE_URL", LOCAL_URL) as _fixture:
        yield _fixture


@pytest.fixture(autouse=True)
def mock_qibo():
    """Ensure that all the requests are made on localhost"""
    with patch(f"{PKG}.qibo") as _mock_qibo:
        _mock_qibo.__version__ = FAKE_QIBO_VERSION
        _mock_qibo.result.load_result.side_effect = lambda x: x
        yield _mock_qibo


@pytest.fixture
def mock_request():
    """Returns a mocked get request"""
    with patch(f"{PKG}.requests") as _mock_request:
        yield _mock_request


@pytest.fixture
def archive_path(tmp_path):
    return tmp_path / ARCHIVE_NAME


@pytest.fixture
def mock_tempfile(archive_path):
    with patch(f"{PKG}.tempfile") as _mock_tempfile:
        _mock_tempfile.NamedTemporaryFile = utils.get_fake_tmp_file_class(archive_path)
        yield _mock_tempfile


def test_check_response_has_keys():
    """Check response body contains the keys"""
    keys = ["key1", "key2"]
    json_data = {"key1": 0, "key2": 1}
    status_code = 200
    mock_response = utils.MockedResponse(status_code, json_data)
    tiiprovider.check_response_has_keys(mock_response, keys)


def test_check_response_has_missing_keys():
    """Check response body contains the keys"""
    keys = ["key1", "key2"]
    json_data = {"key1": 0}
    status_code = 200
    mock_response = utils.MockedResponse(status_code, json_data)
    with pytest.raises(MalformedResponseError):
        tiiprovider.check_response_has_keys(mock_response, keys)


def _get_tii_client():
    return tiiprovider.TIIProvider("valid_token")


def _execute_check_client_server_qibo_versions(
    mock_request, local_qibo_version, remote_qibo_version
):
    mock_response = utils.MockedResponse(
        status_code=200, json_data={"qibo_version": remote_qibo_version}
    )
    mock_request.get.return_value = mock_response
    _get_tii_client()


def test_check_client_server_qibo_versions_with_version_match(mock_request: Mock):
    _execute_check_client_server_qibo_versions(
        mock_request, FAKE_QIBO_VERSION, FAKE_QIBO_VERSION
    )

    mock_request.get.assert_called_once_with(LOCAL_URL + "qibo_version/")


def test_check_client_server_qibo_versions_with_version_mismatch(mock_request):
    remote_qibo_version = "0.2.2"

    with pytest.raises(AssertionError):
        _execute_check_client_server_qibo_versions(
            mock_request, FAKE_QIBO_VERSION, remote_qibo_version
        )

    mock_request.get.assert_called_once_with(LOCAL_URL + "qibo_version/")


def test__post_circuit_with_invalid_token(mock_request: Mock):
    mock_get_response = utils.MockedResponse(
        status_code=200, json_data={"qibo_version": FAKE_QIBO_VERSION}
    )
    mock_request.get.return_value = mock_get_response

    # simulate 404 error due to invalid token
    mock_post_response = utils.MockedResponse(status_code=404)
    mock_request.post.return_value = mock_post_response

    client = _get_tii_client()
    with pytest.raises(HTTPError):
        client._post_circuit(utils.MockedCircuit())


def test__post_circuit_not_successful(mock_request: Mock):
    mock_get_response = utils.MockedResponse(
        status_code=200, json_data={"qibo_version": FAKE_QIBO_VERSION}
    )
    mock_request.get.return_value = mock_get_response

    # simulate 404 error due to invalid token
    json_data = {"pid": None, "message": "post job to queue failed"}
    mock_post_response = utils.MockedResponse(status_code=200, json_data=json_data)
    mock_request.post.return_value = mock_post_response

    client = _get_tii_client()
    with pytest.raises(JobPostServerError):
        client._post_circuit(utils.MockedCircuit())


def test__run_circuit_with_unsuccessful_post_to_queue(mock_request: Mock):
    mock_get_response = utils.MockedResponse(
        status_code=200, json_data={"qibo_version": FAKE_QIBO_VERSION}
    )
    mock_request.get.return_value = mock_get_response

    # simulate 404 error due to invalid token
    json_data = {"pid": None, "message": "post job to queue failed"}
    mock_post_response = utils.MockedResponse(status_code=200, json_data=json_data)
    mock_request.post.return_value = mock_post_response

    client = _get_tii_client()
    return_value = client.run_circuit(utils.MockedCircuit())

    assert return_value is None


def test_wait_for_response_to_get_request(mock_request: Mock):
    failed_attempts = 3
    url = "http://example.url"

    keep_waiting = utils.MockedResponse(
        status_code=200, json_data={"content": b"Job still in progress"}
    )
    job_done = utils.MockedResponse(status_code=200)

    mock_request.get.side_effect = [keep_waiting] * failed_attempts + [job_done]

    with patch(f"{PKG}.SECONDS_BETWEEN_CHECKS", 1e-4):
        tiiprovider.wait_for_response_to_get_request(url)

    assert mock_request.get.call_count == failed_attempts + 1


def test__write_stream_to_tmp_file_with_simple_text_stream(
    mock_tempfile: Mock, archive_path: Path
):
    """
    The test contains the following checks:

    - a new temporary file is created to a specific direction
    - the content of the temporary file contains equals the one given
    """
    stream = [b"line1\n", b"line2\n"]

    assert not archive_path.is_file()

    result_path = tiiprovider._write_stream_to_tmp_file(stream)

    assert result_path == archive_path
    assert result_path.is_file()
    assert result_path.read_bytes() == b"".join(stream)


def test__write_stream_to_tmp_file(mock_tempfile: Mock, archive_path: Path):
    """
    The test contains the following checks:

    - a new temporary file is created to a specific direction
    - the content of the temporary file contains equals the one given
    """
    stream, members, members_contents = utils.get_in_memory_fake_archive_stream(
        archive_path
    )

    assert not archive_path.is_file()

    result_path = tiiprovider._write_stream_to_tmp_file(stream)

    assert result_path == archive_path
    assert result_path.is_file()

    # load the archive in memory and check that the members and the contents
    # match with the expected ones
    with tarfile.open(result_path, "r:gz") as archive:
        result_members = sorted(archive.getnames())
        assert result_members == members
        for member, member_content in zip(members, members_contents):
            with archive.extractfile(member) as result_member:
                result_content = result_member.read()
            assert result_content == member_content


def test__extract_archive_to_folder_with_non_archive_input(tmp_path):
    file_path = tmp_path / "file.txt"
    file_path.write_text("test content")

    destination_folder = tmp_path / "destination_folder"
    destination_folder.mkdir()

    with pytest.raises(tarfile.ReadError):
        tiiprovider._extract_archive_to_folder(file_path, destination_folder)


def test__extract_archive_to_folder(tmp_path, archive_path):
    destination_folder = tmp_path / "destination_folder"
    destination_folder.mkdir()

    members, members_contents = utils.create_fake_archive(archive_path)

    tiiprovider._extract_archive_to_folder(archive_path, destination_folder)

    result_members = []
    result_members_contents = []
    for member_path in sorted(destination_folder.iterdir()):
        result_members.append(member_path.name)
        result_members_contents.append(member_path.read_bytes())

    assert result_members == members
    assert result_members_contents == members_contents


def test__save_and_unpack_stream_response_to_folder(
    mock_tempfile: Mock, archive_path: Path, tmp_path: Path
):
    destination_folder = tmp_path / "destination_folder"
    destination_folder.mkdir()

    stream, _, _ = utils.get_in_memory_fake_archive_stream(archive_path)

    assert not archive_path.is_file()

    tiiprovider._save_and_unpack_stream_response_to_folder(stream, destination_folder)

    # the archive should have been removed
    assert not archive_path.is_file()


def _get_request_side_effect(job_status: str = "success") -> Callable:
    """Return a callable mock for the get request function

    Job status parameter controls the response header of `get_result/{pid}`
    endpoint.

    :param job_status: the Job-Status header of the mocked response
    :type job_status: str

    :return: the get request side effect function
    :rtype: Callable
    """

    def _request_side_effect(url):
        if url == LOCAL_URL + "qibo_version/":
            return utils.MockedResponse(
                status_code=200, json_data={"qibo_version": FAKE_QIBO_VERSION}
            )
        if url == LOCAL_URL + f"get_result/{FAKE_PID}/":
            stream, _, _ = utils.get_in_memory_fake_archive_stream(archive_path)
            json_data = {
                "content": None,
                "iter_content": stream,
                "headers": {"Job-Status": job_status},
            }
            return utils.MockedResponse(status_code=200, json_data=json_data)

    return _request_side_effect


def _post_request_side_effect(url, json):
    if url == LOCAL_URL + "run_circuit/":
        json_data = {"pid": FAKE_PID, "message": "Success. Job posted"}
        return utils.MockedResponse(status_code=200, json_data=json_data)


@pytest.fixture
def mock_all_request_methods():
    with patch(f"{PKG}.requests") as _mock_request:
        _mock_request.get.side_effect = _get_request_side_effect()
        _mock_request.post.side_effect = _post_request_side_effect
        yield _mock_request


def _generic_test__get_results_fn(results_base_folder: Path):
    results_base_folder.mkdir()

    with patch(f"{PKG}.RESULTS_BASE_FOLDER", results_base_folder):
        client = _get_tii_client()
        client.pid = FAKE_PID
        return client._get_result()


def test__get_result(mock_qibo, mock_all_request_methods, mock_tempfile, tmp_path):
    results_base_folder = tmp_path / "results"
    expected_array_path = results_base_folder / FAKE_PID / "results.npy"

    result = _generic_test__get_results_fn(results_base_folder)

    mock_qibo.result.load_result.assert_called_once_with(expected_array_path)
    assert result == expected_array_path


def test__get_result_with_job_status_error(
    mock_qibo, mock_all_request_methods, mock_tempfile, tmp_path
):
    mock_all_request_methods.get.side_effect = _get_request_side_effect(
        job_status="error"
    )

    results_base_folder = tmp_path / "results"

    result = _generic_test__get_results_fn(results_base_folder)

    mock_qibo.result.load_result.assert_not_called()
    assert result is None


def test__run_circuit(mock_qibo, mock_all_request_methods, mock_tempfile, tmp_path):
    results_base_folder = tmp_path / "results"
    expected_array_path = results_base_folder / FAKE_PID / "results.npy"

    results_base_folder.mkdir()

    with patch(f"{PKG}.RESULTS_BASE_FOLDER", results_base_folder):
        client = _get_tii_client()
        client.pid = FAKE_PID
        result = client.run_circuit(utils.MockedCircuit())

    assert result == expected_array_path

import httpx2
import pytest

from superhumandoc_mcp.classify import classify_exception, classify_status
from superhumandoc_mcp.errors import FailureClass


@pytest.mark.parametrize(
    "exc",
    [httpx2.ConnectTimeout("x"), httpx2.ConnectError("x")],
)
def test_connect_phase_failures_never_reached_the_application(
    exc: Exception,
) -> None:
    assert classify_exception(exc) is FailureClass.REFUSED


@pytest.mark.parametrize(
    "exc",
    [httpx2.ReadTimeout("x"), httpx2.ReadError("x"),
     httpx2.RemoteProtocolError("x"), httpx2.WriteTimeout("x")],
)
def test_post_transmission_failures_leave_the_outcome_unknown(
    exc: Exception,
) -> None:
    assert classify_exception(exc) is FailureClass.TRANSMITTED_UNKNOWN


def test_429_is_refused_before_execution() -> None:
    assert classify_status(429) is FailureClass.REFUSED


@pytest.mark.parametrize("status", [500, 502, 503])
def test_server_errors_leave_the_outcome_unknown(status: int) -> None:
    """A 502 and a read timeout are the same epistemic situation."""
    assert classify_status(status) is FailureClass.TRANSMITTED_UNKNOWN


def test_504_is_an_answer_not_an_ambiguity() -> None:
    """A gateway timeout on this API means the request was too expensive as
    asked. Replaying it identically fails identically, so it is never retried
    here — reshaping it belongs to the tool that owns paging."""
    assert classify_status(504) is FailureClass.ANSWERED


@pytest.mark.parametrize("status", [400, 404, 409, 422])
def test_other_client_errors_are_answered_refusals(status: int) -> None:
    assert classify_status(status) is FailureClass.ANSWERED


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failures_are_their_own_class(status: int) -> None:
    assert classify_status(status) is FailureClass.AUTH


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirects_are_answered_and_never_followed(status: int) -> None:
    """The base URL is pinned. A redirect away from it means the pin is wrong,
    and following it quietly would defeat the pin."""
    assert classify_status(status) is FailureClass.ANSWERED


@pytest.mark.parametrize("status", [200, 201, 202, 204])
def test_success_is_not_a_failure_class(status: int) -> None:
    assert classify_status(status) is None

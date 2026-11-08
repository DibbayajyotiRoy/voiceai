"""Stubbed checks for control/handler.py: start, status, idle-stop rules."""

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import handler  # noqa: E402  (deploy/aws/control is on sys.path under pytest)


class FakeECS:
    def __init__(self, desired=0, tasks=()):
        self.desired = desired
        self.tasks = list(tasks)
        self.updates = []

    def describe_services(self, cluster, services):
        return {"services": [{"desiredCount": self.desired}]}

    def update_service(self, cluster, service, desiredCount):
        self.updates.append(desiredCount)
        self.desired = desiredCount

    def list_tasks(self, cluster, serviceName, desiredStatus):
        return {"taskArns": [t["taskArn"] for t in self.tasks]}

    def describe_tasks(self, cluster, tasks):
        return {"tasks": self.tasks}


def task(last="RUNNING", started=None):
    return {
        "taskArn": "arn:task",
        "lastStatus": last,
        "startedAt": started or datetime.now(UTC),
        "attachments": [
            {
                "type": "ElasticNetworkInterface",
                "details": [{"name": "networkInterfaceId", "value": "eni-1"}],
            }
        ],
    }


def install(monkeypatch, ecs, ip="203.0.113.7", health=True, idle=None, dns=None):
    monkeypatch.setattr(handler, "ecs", ecs)
    monkeypatch.setattr(
        handler,
        "ec2",
        SimpleNamespace(
            describe_network_interfaces=lambda NetworkInterfaceIds: {
                "NetworkInterfaces": [{"Association": {"PublicIp": ip}}]
            }
        ),
    )
    monkeypatch.setattr(handler, "_healthy", lambda: health)
    monkeypatch.setattr(handler, "_idle", lambda: idle)
    calls = [] if dns is None else dns
    monkeypatch.setattr(handler, "_ensure_dns", lambda ip: calls.append(ip))
    monkeypatch.setattr(handler, "_last_dns_ip", None)
    return calls


def test_start_sets_desired_one(monkeypatch):
    ecs = FakeECS(desired=0)
    install(monkeypatch, ecs)
    out = handler.start()
    assert ecs.updates == [1]
    assert out["state"] == "starting"  # no task yet


def test_start_idempotent_when_already_one(monkeypatch):
    ecs = FakeECS(desired=1)
    install(monkeypatch, ecs)
    handler.start()
    assert ecs.updates == []


def test_status_stopped_when_desired_zero(monkeypatch):
    install(monkeypatch, FakeECS(desired=0))
    assert handler.status() == {"state": "stopped", "url": None}


def test_status_starting_without_task(monkeypatch):
    install(monkeypatch, FakeECS(desired=1, tasks=[]))
    assert handler.status() == {"state": "starting", "url": None}


def test_status_ready_points_dns_and_returns_url(monkeypatch):
    dns = []
    install(monkeypatch, FakeECS(desired=1, tasks=[task()]), dns=dns)
    assert handler.status() == {"state": "ready", "url": "https://demo-api.dibbayajyoti.com"}
    assert dns == ["203.0.113.7"]


def test_status_starting_when_health_fails(monkeypatch):
    install(monkeypatch, FakeECS(desired=1, tasks=[task()]), health=False)
    assert handler.status() == {"state": "starting", "url": None}


def test_status_starting_while_pending(monkeypatch):
    install(monkeypatch, FakeECS(desired=1, tasks=[task(last="PENDING")]))
    assert handler.status()["state"] == "starting"


def test_sweep_stops_when_idle_and_no_active_calls(monkeypatch):
    ecs = FakeECS(desired=1, tasks=[task()])
    install(monkeypatch, ecs, idle={"idle_seconds": 1000, "active": 0})
    assert handler.sweep()["reason"] == "idle"
    assert ecs.updates == [0]


def test_sweep_does_not_stop_active_call_even_if_idle_large(monkeypatch):
    # Orchestrator rule: backend last_activity only updates on connect/disconnect.
    ecs = FakeECS(desired=1, tasks=[task()])
    install(monkeypatch, ecs, idle={"idle_seconds": 1000, "active": 1})
    assert handler.sweep()["action"] == "none"
    assert ecs.updates == []


def test_sweep_does_not_stop_under_idle_threshold(monkeypatch):
    ecs = FakeECS(desired=1, tasks=[task()])
    install(monkeypatch, ecs, idle={"idle_seconds": 600, "active": 0})
    handler.sweep()
    assert ecs.updates == []


def test_sweep_does_not_stop_when_idle_endpoint_unreachable(monkeypatch):
    ecs = FakeECS(desired=1, tasks=[task()])
    install(monkeypatch, ecs, idle=None)
    handler.sweep()
    assert ecs.updates == []


def test_sweep_stops_after_max_runtime_even_if_active(monkeypatch):
    old = datetime.now(UTC) - timedelta(minutes=61)
    ecs = FakeECS(desired=1, tasks=[task(started=old)])
    install(monkeypatch, ecs, idle={"idle_seconds": 0, "active": 1})
    assert handler.sweep()["reason"] == "max-runtime"
    assert ecs.updates == [0]


def test_sweep_noop_when_already_stopped(monkeypatch):
    ecs = FakeECS(desired=0)
    install(monkeypatch, ecs)
    assert handler.sweep()["reason"] == "stopped"
    assert ecs.updates == []

from __future__ import annotations

from gmail_cleanup import labels


class _FakeRequest:
    def __init__(self, response):
        self._response = response

    def execute(self):
        return self._response


class _FakeLabels:
    def __init__(self):
        self.update_calls: list[dict] = []
        self.delete_calls: list[dict] = []
        self.patch_calls: list[dict] = []

    def update(self, userId, id, body):
        self.update_calls.append({"userId": userId, "id": id, "body": body})
        return _FakeRequest({"id": id, "name": body.get("name")})

    def patch(self, userId, id, body):
        self.patch_calls.append({"userId": userId, "id": id, "body": body})
        return _FakeRequest({"id": id, "name": body.get("name")})

    def delete(self, userId, id):
        self.delete_calls.append({"userId": userId, "id": id})
        return _FakeRequest({})


class _FakeUsers:
    def __init__(self):
        self._labels = _FakeLabels()

    def labels(self):
        return self._labels


class _FakeService:
    def __init__(self):
        self._users = _FakeUsers()

    def users(self):
        return self._users


def test_update_label_calls_patch_with_new_name():
    service = _FakeService()
    result = labels.update_label(service, "Label_10", "amazon")
    calls = service._users._labels.patch_calls
    assert len(calls) == 1
    assert calls[0]["userId"] == "me"
    assert calls[0]["id"] == "Label_10"
    assert calls[0]["body"] == {"name": "amazon"}
    assert result == {"id": "Label_10", "name": "amazon"}


def test_delete_label_calls_delete_endpoint():
    service = _FakeService()
    labels.delete_label(service, "Label_25")
    calls = service._users._labels.delete_calls
    assert len(calls) == 1
    assert calls[0]["userId"] == "me"
    assert calls[0]["id"] == "Label_25"

"""Thin wrapper around the real Firestore client that mirrors the surface of
:class:`app.repositories.fake.FakeFirestore` so that the repositories layer
can stay agnostic.

We deliberately expose only what the application uses: ``collection``,
``transaction`` and a minimal ``run`` helper.  If you need more Firestore
features in future (e.g. cursor pagination) add them here.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, Iterator, Optional

from google.cloud import firestore
from google.cloud.firestore_v1 import Client as FirestoreClient
from google.cloud.firestore_v1.transaction import Transaction as RealTransaction


class _QueryBuilder:
    """Proxy over a Firestore ``Query`` so tests can use the same ``order_by``
    / ``limit`` chain as production."""

    def __init__(self, query):
        self._query = query

    def where(self, field: str, op: str, value: Any) -> "_QueryBuilder":
        self._query = self._query.where(field, op, value)
        return self

    def order_by(self, field: str, direction: Optional[str] = None) -> "_QueryBuilder":
        normalized = (direction or "ASCENDING").strip().upper()

        if normalized in {"DESC", "DESCENDING"}:
            firestore_direction = "DESCENDING"
        elif normalized in {"ASC", "ASCENDING"}:
            firestore_direction = "ASCENDING"
        else:
            raise ValueError(
                "Direction must be ASC, ASCENDING, DESC, or DESCENDING"
            )

        self._query = self._query.order_by(
            field,
            direction=firestore_direction,
        )
        return self

    def limit(self, count: int) -> "_QueryBuilder":
        self._query = self._query.limit(count)
        return self

    def stream(self) -> Iterator[Any]:
        return iter(self._query.stream())

    def get(self) -> Iterable[Any]:
        return list(self.stream())


class _Collection:
    def __init__(self, ref):
        self._ref = ref

    def document(self, doc_id: Optional[str] = None):
        return self._ref.document(doc_id) if doc_id else self._ref.document()

    def add(self, data: Dict[str, Any]):
        ts, ref = self._ref.add(data)
        return ref, ref.id

    def where(self, field: str, op: str, value: Any) -> _QueryBuilder:
        return _QueryBuilder(self._ref.where(field, op, value))

    def order_by(self, field: str, direction: Optional[str] = None) -> _QueryBuilder:
        # Route ordering through _QueryBuilder so application-friendly
        # values such as "DESC" are converted to Firestore constants.
        return _QueryBuilder(self._ref).order_by(field, direction)

    def limit(self, count: int) -> _QueryBuilder:
        return _QueryBuilder(self._ref.limit(count))

    def stream(self) -> Iterator[Any]:
        return iter(self._ref.stream())

    def get(self) -> Iterable[Any]:
        return list(self.stream())


class RealFirestoreAdapter:
    """Adapter that matches ``FakeFirestore``'s minimal surface."""

    def __init__(self, client: FirestoreClient):
        self._client = client

    @property
    def supports_transactions(self) -> bool:
        return True

    def collection(self, name: str) -> _Collection:
        return _Collection(self._client.collection(name))

    def transaction(self) -> RealTransaction:
        return self._client.transaction()

    def run_in_transaction(self, txn, fn: Callable[[RealTransaction], Any]) -> Any:
        # Newer google-cloud-firestore exposes a ``run`` helper on the client.
        if hasattr(self._client, "run_in_transaction"):
            return self._client.run_in_transaction(fn)
        # Fall back to ``transactional`` decorator pattern.  The repositories
        # pass an explicit transaction object, so we simply invoke ``fn``.
        return fn(txn)

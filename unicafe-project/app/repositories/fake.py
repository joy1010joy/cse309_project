"""In-memory fake of the small slice of Firestore the application uses.

The application talks to data through the :class:`Database` abstraction in
``app.repositories.base``.  In production the real ``firestore.Client`` is
wrapped; in tests we substitute this in-memory implementation so the entire
suite can run without network access.

Design notes:

* Documents are plain ``dict``s.
* ``Transaction`` uses a generous lock-based approach.  It is sufficient for
  serialising the inventory/order write path which is the only transactional
  flow we need.
* Queries support a subset of Firestore's operators: ``==``, ``!=``, ``<``,
  ``<=``, ``>``, ``>=``, ``in`` and a few convenience helpers.
"""
from __future__ import annotations

import threading
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


@dataclass
class _QueryOp:
    field: str
    op: str
    value: Any


@dataclass
class Query:
    """Result of ``collection.where(...)`` — iterable and chainable."""

    collection: "Collection"
    ops: List[_QueryOp] = field(default_factory=list)
    order_field: Optional[str] = None
    order_descending: bool = False
    limit_count: Optional[int] = None

    def where(self, field: str, op: str, value: Any) -> "Query":
        self.ops.append(_QueryOp(field=field, op=op, value=value))
        return self

    def order_by(self, field: str, direction: Optional[str] = None) -> "Query":
        self.order_field = field
        self.order_descending = (direction == "DESC")
        return self

    def limit(self, count: int) -> "Query":
        self.limit_count = count
        return self

    def stream(self) -> Iterable["DocumentSnapshot"]:
        results = list(self.collection._filter(self.ops))
        if self.order_field:
            results.sort(
                key=lambda doc: (doc.get().to_dict() or {}).get(self.order_field),
                reverse=self.order_descending,
            )
        if self.limit_count is not None:
            results = results[: self.limit_count]
        for doc in results:
            yield doc.get()

    def get(self) -> List["DocumentSnapshot"]:
        return list(self.stream())


class DocumentSnapshot:
    def __init__(self, collection: "Collection", doc_id: str, data: Dict[str, Any], exists: bool = True):
        self._collection = collection
        self.id = doc_id
        self._data = data
        self._exists = exists

    @property
    def exists(self) -> bool:
        return self._exists

    def to_dict(self) -> Dict[str, Any]:
        return deepcopy(self._data) if self._data else {}


class DocumentReference:
    def __init__(self, collection: "Collection", doc_id: str):
        self._collection = collection
        self.id = doc_id

    @property
    def parent(self) -> "Collection":
        return self._collection

    def get(self) -> DocumentSnapshot:
        data = self._collection._docs.get(self.id)
        return DocumentSnapshot(self._collection, self.id, data or {}, exists=data is not None)

    def set(self, data: Dict[str, Any], merge: bool = False) -> None:
        with self._collection._lock:
            current = self._collection._docs.get(self.id, {})
            if merge and current:
                merged = {**current, **data}
                self._collection._docs[self.id] = merged
            else:
                self._collection._docs[self.id] = deepcopy(data)

    def update(self, data: Dict[str, Any]) -> None:
        with self._collection._lock:
            current = self._collection._docs.get(self.id)
            if current is None:
                raise KeyError(f"document {self.id} not found")
            current.update(data)
            self._collection._docs[self.id] = current

    def delete(self) -> None:
        with self._collection._lock:
            self._collection._docs.pop(self.id, None)


class Collection:
    def __init__(self, name: str, parent: "FakeFirestore"):
        self.name = name
        self._parent = parent
        self._docs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._auto_id = 0

    def document(self, doc_id: Optional[str] = None) -> DocumentReference:
        if doc_id is None:
            doc_id = self._parent._next_id(self.name)
        return DocumentReference(self, doc_id)

    def add(self, data: Dict[str, Any]) -> Tuple[DocumentReference, str]:
        with self._lock:
            doc_id = self._parent._next_id(self.name)
            self._docs[doc_id] = deepcopy(data)
            return DocumentReference(self, doc_id), doc_id

    def where(self, field: str, op: str, value: Any) -> Query:
        return Query(self).where(field, op, value)

    def order_by(self, field: str, direction: Optional[str] = None) -> Query:
        return Query(self).order_by(field, direction)

    def limit(self, count: int) -> Query:
        return Query(self).limit(count)

    def stream(self) -> Iterable[DocumentSnapshot]:
        for doc in sorted(self._docs.items()):
            yield DocumentSnapshot(self, doc[0], doc[1])

    def get(self) -> List[DocumentSnapshot]:
        return list(self.stream())

    # internal
    def _filter(self, ops: List[_QueryOp]) -> List[DocumentReference]:
        results: List[DocumentReference] = []
        for doc_id, data in self._docs.items():
            if _matches(data, ops):
                results.append(DocumentReference(self, doc_id))
        return results


def _matches(doc: Dict[str, Any], ops: List[_QueryOp]) -> bool:
    for op in ops:
        value = doc.get(op.field)
        if not _compare(value, op.op, op.value):
            return False
    return True


def _compare(left: Any, op: str, right: Any) -> bool:
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    if op == "<":
        try:
            return left < right
        except TypeError:
            return False
    if op == "<=":
        try:
            return left <= right
        except TypeError:
            return False
    if op == ">":
        try:
            return left > right
        except TypeError:
            return False
    if op == ">=":
        try:
            return left >= right
        except TypeError:
            return False
    if op == "in":
        try:
            return left in right
        except TypeError:
            return False
    raise ValueError(f"unsupported operator {op!r}")


@dataclass
class Transaction:
    """Simplified transaction.  All operations execute under a global lock."""

    fake: "FakeFirestore"
    locks: List[threading.Lock] = field(default_factory=list)

    def get(self, ref: DocumentReference) -> DocumentSnapshot:
        return ref.get()

    def set(self, ref: DocumentReference, data: Dict[str, Any], merge: bool = False) -> None:
        ref.set(data, merge=merge)

    def update(self, ref: DocumentReference, data: Dict[str, Any]) -> None:
        ref.update(data)

    def delete(self, ref: DocumentReference) -> None:
        ref.delete()


class FakeFirestore:
    """A tiny in-memory drop-in for ``firestore.Client``."""

    def __init__(self) -> None:
        self._collections: Dict[str, Collection] = {}
        self._id_counter = 0
        self._global_lock = threading.Lock()
        self._prefix = "auto"

    @property
    def supports_transactions(self) -> bool:
        return True

    def _next_id(self, collection_name: str) -> str:
        with self._global_lock:
            self._id_counter += 1
            return f"{self._prefix}_{collection_name}_{self._id_counter:06d}"

    def collection(self, name: str) -> Collection:
        if name not in self._collections:
            self._collections[name] = Collection(name, self)
        return self._collections[name]

    def transaction(self) -> Transaction:
        return Transaction(self)

    def run_in_transaction(self, fn):
        """Run *fn(transaction)* under the global lock.

        The in-memory fake doesn't need real transactional semantics.
        We just create a :class:`Transaction`, call ``fn``, and return.
        """
        txn = Transaction(self)
        return fn(txn)

    # test helpers --------------------------------------------------

    def reset(self) -> None:
        self._collections.clear()
        self._id_counter = 0

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        return {name: deepcopy(coll._docs) for name, coll in self._collections.items()}

    def seed(self, name: str, docs: Dict[str, Dict[str, Any]]) -> None:
        coll = self.collection(name)
        with coll._lock:
            coll._docs.update(deepcopy(docs))
